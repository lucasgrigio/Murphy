"""Murphy — Interactive test review server.

Serves an HTML UI for reviewing generated tests before execution,
then shows results after execution completes.
"""

import asyncio
import logging
import webbrowser
from typing import Any

from aiohttp import web

from murphy.api.templates import render_plan_html, render_results_html
from murphy.models import ReportSummary, TestPlan, TestResult, WebsiteAnalysis

logger = logging.getLogger(__name__)

# ─── State shared between handlers ───────────────────────────────────────────


class ServerState:
	def __init__(
		self,
		url: str,
		analysis: WebsiteAnalysis,
		test_plan: TestPlan,
		execute_fn: Any,
	):
		self.url = url
		self.analysis = analysis
		self.test_plan = test_plan
		self.execute_fn = execute_fn  # async callable(test_plan) -> list[TestResult]

		self.running = False
		self.done = False
		self.current_test = 0
		self.total = len(test_plan.scenarios)
		self.results: list[TestResult] = []
		self.summary: ReportSummary | None = None
		self.build_summary_fn: Any = None  # set from evaluate.py


# ─── Handlers ─────────────────────────────────────────────────────────────────


async def handle_index(request: web.Request) -> web.Response:
	state: ServerState = request.app['state']
	if state.done:
		raise web.HTTPFound('/results')
	return web.Response(
		text=render_plan_html(state.url, state.analysis, state.test_plan),
		content_type='text/html',
	)


async def handle_run(request: web.Request) -> web.Response:
	state: ServerState = request.app['state']
	if state.running or state.done:
		return web.json_response({'status': 'already_running'})

	state.running = True

	async def _run() -> None:
		try:
			state.results = await state.execute_fn(state.test_plan, state)
			if state.build_summary_fn:
				state.summary = state.build_summary_fn(state.results)
		finally:
			state.done = True
			state.running = False

	asyncio.create_task(_run())
	return web.json_response({'status': 'started'})


async def handle_status(request: web.Request) -> web.Response:
	state: ServerState = request.app['state']
	current_name = ''
	if state.running and 0 < state.current_test <= len(state.test_plan.scenarios):
		current_name = state.test_plan.scenarios[state.current_test - 1].name
	return web.json_response(
		{
			'running': state.running,
			'done': state.done,
			'current_test': state.current_test,
			'current_test_name': current_name,
			'total': state.total,
		}
	)


async def handle_results(request: web.Request) -> web.Response:
	state: ServerState = request.app['state']
	if not state.done:
		raise web.HTTPFound('/')
	return web.Response(
		text=render_results_html(state.url, state.analysis, state.results, state.summary),
		content_type='text/html',
	)


# ─── Server lifecycle ────────────────────────────────────────────────────────


async def start_server(state: ServerState) -> tuple[web.AppRunner, int]:
	"""Start the aiohttp server on an OS-assigned port. Returns (runner, port)."""
	app = web.Application()
	app['state'] = state
	app.router.add_get('/', handle_index)
	app.router.add_post('/run', handle_run)
	app.router.add_get('/status', handle_status)
	app.router.add_get('/results', handle_results)

	runner = web.AppRunner(app)
	await runner.setup()
	site = web.TCPSite(runner, 'localhost', 0)
	await site.start()

	# Extract the actual port
	assert site._server is not None
	sockets = site._server.sockets  # type: ignore[attr-defined]
	assert sockets
	port: int = sockets[0].getsockname()[1]

	url = f'http://localhost:{port}'
	logger.info('\n  Review tests at: %s\n', url)
	webbrowser.open(url)

	return runner, port
