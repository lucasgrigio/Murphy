"""Murphy REST API — HTTP interface for Toqan integration.

Exposes Murphy's evaluation pipeline as REST endpoints:
  POST /evaluate       — combined explore + plan generation (recommended for Toqan)
  POST /analyze        — website analysis (feature discovery)
  POST /generate-plan  — test plan generation from analysis
  POST /execute        — test execution from plan
  GET  /jobs/{job_id}  — job status polling
  GET  /health         — health check

Three modes per endpoint:
  - Synchronous (default): blocks until completion, returns 200 with result.
  - Async + webhook (webhook_url set): returns 202 + job_id, POSTs result to webhook.
  - Async + polling ("async": true): returns 202 + job_id, poll /jobs/{job_id} for result.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import traceback
from typing import Annotated, Any, Literal

import httpx
import uvicorn
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field
from uuid_extensions import uuid7str

from murphy.models import ReportSummary, TestPlan, TestResult, WebsiteAnalysis

load_dotenv()


def _parse_json_string(v: Any) -> Any:
	"""Accept both a dict/object and a JSON string, parsing the string if needed."""
	if isinstance(v, str):
		return json.loads(v)
	return v


logger = logging.getLogger('murphy.api')

# ─── Configuration ────────────────────────────────────────────────────────────

MURPHY_API_KEY = os.environ.get('MURPHY_API_KEY', '')
MURPHY_MAX_CONCURRENT_JOBS = int(os.environ.get('MURPHY_MAX_CONCURRENT_JOBS', '2'))

# Semaphore to limit concurrent browser jobs
_job_semaphore = asyncio.Semaphore(MURPHY_MAX_CONCURRENT_JOBS)

# ─── Job store ────────────────────────────────────────────────────────────────


class Job(BaseModel):
	id: str = Field(default_factory=uuid7str)
	status: Literal['running', 'completed', 'failed'] = 'running'
	result: Any = None
	error: str | None = None


_jobs: dict[str, Job] = {}

# ─── Auth dependency ──────────────────────────────────────────────────────────


async def _verify_api_key(request: Request) -> None:
	if not MURPHY_API_KEY:
		return  # no key configured = open access
	key = request.headers.get('X-API-Key', '')
	if key != MURPHY_API_KEY:
		raise HTTPException(status_code=401, detail='Invalid or missing API key')


# ─── Request / response models ────────────────────────────────────────────────


class AnalyzeRequest(BaseModel):
	model_config = ConfigDict(populate_by_name=True)

	url: str
	category: str | None = None
	goal: str | None = None
	model: str = 'gpt-5-mini'
	webhook_url: str | None = None
	async_mode: bool = Field(False, alias='async')


class GeneratePlanRequest(BaseModel):
	model_config = ConfigDict(populate_by_name=True)

	url: str
	analysis: Annotated[WebsiteAnalysis, BeforeValidator(_parse_json_string)]
	max_tests: int = 8
	goal: str | None = None
	model: str = 'gpt-5-mini'
	webhook_url: str | None = None
	async_mode: bool = Field(False, alias='async')


class ExecuteRequest(BaseModel):
	model_config = ConfigDict(populate_by_name=True)

	url: str
	test_plan: Annotated[TestPlan, BeforeValidator(_parse_json_string)] | None = None
	evaluate_job_id: str | None = None
	goal: str | None = None
	model: str = 'gpt-5-mini'
	judge_model: str = 'gpt-4o'
	max_steps: int = 15
	max_concurrent: int = 3
	webhook_url: str | None = None
	async_mode: bool = Field(False, alias='async')


class JobResponse(BaseModel):
	job_id: str
	status: str


class ExecuteResult(BaseModel):
	results: list[TestResult]
	summary: ReportSummary


class EvaluateRequest(BaseModel):
	model_config = ConfigDict(populate_by_name=True)

	url: str
	goal: str | None = None
	max_tests: int = 8
	model: str = 'gpt-5-mini'
	judge_model: str = 'gpt-4o'
	async_mode: bool = Field(False, alias='async')
	webhook_url: str | None = None


# ─── Webhook delivery ─────────────────────────────────────────────────────────


async def _deliver_webhook(webhook_url: str, payload: dict[str, Any]) -> None:
	"""POST job result to the webhook URL. Best-effort, no retries."""
	try:
		async with httpx.AsyncClient(timeout=30) as client:
			resp = await client.post(webhook_url, json=payload)
			logger.info(f'Webhook delivered to {webhook_url}: {resp.status_code}')
	except Exception as exc:
		logger.warning(f'Webhook delivery failed for {webhook_url}: {exc}')


# ─── Core logic (returns result dict or raises) ─────────────────────────────


async def _core_analyze(req: AnalyzeRequest) -> dict[str, Any]:
	"""Run website analysis. Returns serialized WebsiteAnalysis dict."""
	from browser_use.browser.profile import BrowserProfile
	from browser_use.browser.session import BrowserSession
	from browser_use.llm import ChatOpenAI
	from murphy.evaluate import analyze_with_session
	from murphy.patches import apply as apply_patches

	apply_patches()

	llm = ChatOpenAI(model=req.model)
	browser_session = BrowserSession(browser_profile=BrowserProfile(headless=True, keep_alive=False))
	await browser_session.start()

	try:
		analysis = await analyze_with_session(req.url, llm, browser_session, goal=req.goal)
		return analysis.model_dump()
	finally:
		await browser_session.kill()


async def _core_generate_plan(req: GeneratePlanRequest) -> dict[str, Any]:
	"""Generate test plan from analysis. Returns serialized TestPlan dict."""
	from browser_use.llm import ChatOpenAI
	from murphy.evaluate import generate_tests
	from murphy.patches import apply as apply_patches

	apply_patches()

	llm = ChatOpenAI(model=req.model)
	test_plan = await generate_tests(req.url, req.analysis, llm, req.max_tests, goal=req.goal)
	return test_plan.model_dump()


async def _core_execute(req: ExecuteRequest) -> dict[str, Any]:
	"""Execute tests from plan. Returns serialized ExecuteResult dict."""
	from browser_use.browser.profile import BrowserProfile
	from browser_use.browser.session import BrowserSession
	from browser_use.llm import ChatOpenAI
	from murphy.evaluate import build_summary, execute_tests_with_session
	from murphy.fixtures import ensure_dummy_fixture_files
	from murphy.patches import apply as apply_patches

	apply_patches()

	# Resolve test_plan: either from request body or from a completed evaluate job
	test_plan = req.test_plan
	if test_plan is None and req.evaluate_job_id:
		job = _jobs.get(req.evaluate_job_id.strip())
		if not job:
			raise ValueError(f'Evaluate job {req.evaluate_job_id} not found')
		if job.status != 'completed':
			raise ValueError(f'Evaluate job {req.evaluate_job_id} is not completed (status: {job.status})')
		test_plan = TestPlan.model_validate(job.result)
	if test_plan is None:
		raise ValueError('Either test_plan or evaluate_job_id must be provided')

	fixture_paths = ensure_dummy_fixture_files()
	llm = ChatOpenAI(model=req.model)
	judge_llm = ChatOpenAI(model=req.judge_model) if req.judge_model != req.model else None
	browser_session = BrowserSession(browser_profile=BrowserProfile(headless=True, keep_alive=False))
	await browser_session.start()

	try:
		results = await execute_tests_with_session(
			req.url,
			test_plan,
			llm,
			browser_session,
			goal=req.goal,
			fixture_paths=fixture_paths,
			max_steps=req.max_steps,
			max_concurrent=req.max_concurrent,
			judge_llm=judge_llm,
		)
		summary = build_summary(results)
		return ExecuteResult(results=results, summary=summary).model_dump()
	finally:
		await browser_session.kill()


async def _core_evaluate(req: EvaluateRequest) -> dict[str, Any]:
	"""Run exploration-first evaluation: explore site → generate test plan."""
	from browser_use.browser.profile import BrowserProfile
	from browser_use.browser.session import BrowserSession
	from browser_use.llm import ChatOpenAI
	from murphy.evaluate import explore_and_generate_plan
	from murphy.patches import apply as apply_patches

	apply_patches()

	task = req.goal or f'Evaluate the website at {req.url}'
	llm = ChatOpenAI(model=req.model)
	browser_session = BrowserSession(browser_profile=BrowserProfile(headless=True, keep_alive=False))
	await browser_session.start()

	try:
		test_plan = await explore_and_generate_plan(
			task=task,
			url=req.url,
			llm=llm,
			session=browser_session,
			max_scenarios=req.max_tests,
		)
		return test_plan.model_dump()
	finally:
		await browser_session.kill()


# ─── Background job wrapper (async mode with webhook) ───────────────────────


async def _run_job_async(
	job: Job,
	core_fn: Any,
	req: Any,
	webhook_url: str,
) -> None:
	"""Run core function as a background job, update job store, deliver webhook."""
	async with _job_semaphore:
		try:
			job.result = await core_fn(req)
			job.status = 'completed'
		except Exception as exc:
			tb = traceback.format_exc()
			logger.error(f'Job {job.id} failed: {exc}\n{tb}')
			job.status = 'failed'
			job.error = f'{type(exc).__name__}: {exc}'

	await _deliver_webhook(
		webhook_url,
		{
			'job_id': job.id,
			'status': job.status,
			'result': job.result,
			'error': job.error,
		},
	)


# ─── Background job wrapper (async mode without webhook) ─────────────────────


async def _run_job_no_webhook(
	job: Job,
	core_fn: Any,
	req: Any,
) -> None:
	"""Run core function as a background job, update job store. No webhook delivery."""
	async with _job_semaphore:
		try:
			job.result = await core_fn(req)
			job.status = 'completed'
		except Exception as exc:
			tb = traceback.format_exc()
			logger.error(f'Job {job.id} failed: {exc}\n{tb}')
			job.status = 'failed'
			job.error = f'{type(exc).__name__}: {exc}'


# ─── Sync mode helper ───────────────────────────────────────────────────────


async def _run_sync(core_fn: Any, req: Any) -> JSONResponse:
	"""Run core function synchronously (blocking), return 200 with result or 500 on error."""
	async with _job_semaphore:
		try:
			result = await core_fn(req)
			return JSONResponse(content={'status': 'completed', 'result': result}, status_code=200)
		except Exception as exc:
			tb = traceback.format_exc()
			logger.error(f'Sync request failed: {exc}\n{tb}')
			return JSONResponse(
				content={'status': 'failed', 'error': f'{type(exc).__name__}: {exc}'},
				status_code=500,
			)


# ─── Dispatch helper ─────────────────────────────────────────────────────────


async def _dispatch(core_fn: Any, req: Any) -> JSONResponse:
	"""Route request to sync, async+webhook, or async+poll mode."""
	if req.webhook_url:
		job = Job()
		_jobs[job.id] = job
		asyncio.create_task(_run_job_async(job, core_fn, req, req.webhook_url))
		return JSONResponse(
			content=JobResponse(job_id=job.id, status=job.status).model_dump(),
			status_code=202,
		)
	elif req.async_mode:
		job = Job()
		_jobs[job.id] = job
		asyncio.create_task(_run_job_no_webhook(job, core_fn, req))
		return JSONResponse(
			content=JobResponse(job_id=job.id, status=job.status).model_dump(),
			status_code=202,
		)
	else:
		return await _run_sync(core_fn, req)


# ─── FastAPI app ──────────────────────────────────────────────────────────────

app = FastAPI(
	title='Murphy API',
	description='AI-driven website evaluation — REST API for Toqan integration',
	version='0.1.0',
)


@app.get('/health')
async def health() -> dict[str, str]:
	return {'status': 'ok'}


@app.post('/analyze', dependencies=[Depends(_verify_api_key)])
async def analyze(req: AnalyzeRequest) -> JSONResponse:
	return await _dispatch(_core_analyze, req)


@app.post('/generate-plan', dependencies=[Depends(_verify_api_key)])
async def generate_plan(req: GeneratePlanRequest) -> JSONResponse:
	return await _dispatch(_core_generate_plan, req)


@app.post('/execute', dependencies=[Depends(_verify_api_key)])
async def execute(req: ExecuteRequest) -> JSONResponse:
	return await _dispatch(_core_execute, req)


@app.post('/evaluate', dependencies=[Depends(_verify_api_key)])
async def evaluate(req: EvaluateRequest) -> JSONResponse:
	return await _dispatch(_core_evaluate, req)


@app.get('/jobs/{job_id}', dependencies=[Depends(_verify_api_key)])
async def get_job(job_id: str, poll: int = 0) -> dict[str, Any]:
	"""Get job status. If poll>0, long-poll: block up to `poll` seconds waiting for completion."""
	job_id = job_id.strip()
	job = _jobs.get(job_id)
	if not job:
		raise HTTPException(status_code=404, detail='Job not found')

	if poll > 0 and job.status == 'running':
		wait = min(poll, 150)  # cap at 2.5 minutes
		elapsed = 0
		while elapsed < wait and job.status == 'running':
			await asyncio.sleep(5)
			elapsed += 5

	return job.model_dump()


# ─── Entrypoint ───────────────────────────────────────────────────────────────

# Default request timeout: 30 minutes. Covers long-running sync evaluations.
# Toqan's HTTPIntegration.Timeout is configured per-tool (up to 30 min for execute).
MURPHY_REQUEST_TIMEOUT = int(os.environ.get('MURPHY_REQUEST_TIMEOUT', '1800'))


def main() -> None:
	"""CLI entrypoint for `murphy-api` script."""
	host = os.environ.get('MURPHY_API_HOST', '0.0.0.0')
	port = int(os.environ.get('MURPHY_API_PORT', '8000'))
	uvicorn.run(
		'murphy.api:app',
		host=host,
		port=port,
		reload=False,
		timeout_keep_alive=MURPHY_REQUEST_TIMEOUT,
	)


if __name__ == '__main__':
	main()
