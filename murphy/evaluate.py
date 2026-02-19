"""
Murphy — Website Evaluation System

Analyzes a website, generates user journey tests, executes them, and reports results.

Usage:
    python -m murphy.evaluate https://www.prosus.com
    python -m murphy.evaluate https://stripe.com --category saas
    python -m murphy.evaluate https://example.com --model gpt-4o --max-tests 5
"""

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv

from browser_use import Agent
from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession
from browser_use.llm import ChatOpenAI, SystemMessage, UserMessage

from murphy.models import (
	EvaluationReport,
	ReportSummary,
	TestPlan,
	TestResult,
	WebsiteAnalysis,
)
from murphy.judge import murphy_judge
from murphy.report import write_json_report, write_markdown_report

load_dotenv()


# ─── Phase 1: Analyze ──────────────────────────────────────────────────────────


async def analyze_website(url: str, llm: ChatOpenAI, category: str | None = None, goal: str | None = None) -> WebsiteAnalysis:
	print(f'\n{"="*60}')
	print(f'Phase 1: Analyzing {url}')
	print(f'{"="*60}\n')

	category_hint = f'\nCategory hint: {category}' if category else ''
	goal_block = ''
	if goal:
		goal_block = (
			f'\nGOAL: Focus your exploration on: {goal}\n'
			f'- Still explore the full site, but pay extra attention to pages/features related to this goal.\n'
			f'- Mark features related to the goal as "core" importance.\n\n'
		)

	agent = Agent(
		task=(
			f'Navigate to {url} and discover what users can DO on this site.{category_hint}\n\n'
			f'{goal_block}'
			f'EXPLORATION (this is the most important part — be thorough):\n'
			f'- Look at the sidebar/top navigation and click EVERY major nav item (e.g. Dashboard, Agents, Tasks, Connectors, Reports, Admin, Profile, Conversations, Settings — whatever exists)\n'
			f'- Do NOT stop after 1-2 pages. You must visit every distinct section in the navigation.\n'
			f'- On each page, note what actions a user can perform (not just what elements exist)\n'
			f'- If you see a list/table, click an item to see the detail view\n'
			f'- Check user profile/settings pages too — those often have important features\n'
			f'- IMPORTANT: This is READ-ONLY exploration. Do NOT click "Delete", "Place Order", or any button that would permanently destroy data or cost money. You MAY click "Create", "Submit", "Send", "Save" to explore forms and creation flows — just don\'t confirm irreversible actions.\n'
			f'- IMPORTANT: Stay on the same domain as {url}. Do NOT follow links to external sites (e.g. social media, third-party docs, partner sites). If a link goes to a different domain, note the feature but do not navigate there.\n'
			f'- For each page, classify the page_type (homepage, landing, product, listing, detail, form, content, dashboard, auth, error, other)\n\n'
			f'FEATURE IDENTIFICATION:\n'
			f'- You should find at least 8-15 features for any non-trivial app. If you have fewer than 8, you haven\'t explored enough — go back and click more nav items.\n'
			f'- Name each feature as a user action: "Create AI agent", "Search tasks", "Upload document" — NOT "Navigation Links" or "Button group"\n'
			f'- A feature = one thing a user can accomplish. If it takes multiple steps, that\'s still one feature.\n'
			f'- For `elements`, write brief descriptions: "Create button on agents page", "Task name input" — NOT raw hrefs or DOM dumps\n'
			f'- For `page_url`, use the page where the feature is primarily accessed\n'
			f'- Skip generic navigation (header links, footer links, breadcrumbs) — those aren\'t features\n'
			f'- Skip auth-related elements (login/logout buttons)\n'
			f'- Category: navigation, search, forms, content_display, filtering_sorting, media, authentication, ecommerce, social, other\n'
			f'- Assess testability: can an unauthenticated headless browser test this? (testable / partial / untestable). If not fully testable, explain why (requires login, third-party redirect, CAPTCHA, etc.)\n\n'
			f'IMPORTANCE:\n'
			f'- core: primary product functionality (the reason the site exists)\n'
			f'- secondary: useful but not the main purpose\n'
			f'- peripheral: only if truly notable (skip otherwise)\n\n'
			f'USER FLOWS:\n'
			f'- Identify 3-5 multi-step journeys: e.g. "Create agent → configure settings → deploy"\n'
			f'- Each flow should describe a complete user goal, not a single click\n'
		),
		llm=llm,
		output_model_schema=WebsiteAnalysis,
		max_actions_per_step=3,
	)
	history = await agent.run(max_steps=30)

	result = history.final_result()
	if not result:
		print('ERROR: Analysis agent returned no result')
		sys.exit(1)

	analysis = WebsiteAnalysis.model_validate_json(result)
	print(f'\nAnalysis complete: {analysis.site_name} ({analysis.category})')
	print(f'  Pages found: {len(analysis.key_pages)}')
	print(f'  Features found: {len(analysis.features)}')
	print(f'  User flows: {len(analysis.identified_user_flows)}')
	return analysis


# ─── Phase 2: Generate Tests ───────────────────────────────────────────────────


async def generate_tests(
	url: str, analysis: WebsiteAnalysis, llm: ChatOpenAI, max_tests: int, goal: str | None = None,
) -> TestPlan:
	print(f'\n{"="*60}')
	print(f'Phase 2: Generating test scenarios')
	print(f'{"="*60}\n')

	# Build a features summary for the prompt
	features_by_testability: dict[str, list] = {'testable': [], 'partial': [], 'untestable': []}
	for f in analysis.features:
		features_by_testability[f.testability].append(f)

	testable_features = features_by_testability['testable'] + features_by_testability['partial']
	core_features = [f for f in testable_features if f.importance == 'core']
	secondary_features = [f for f in testable_features if f.importance == 'secondary']
	peripheral_features = [f for f in testable_features if f.importance == 'peripheral']

	goal_block = ""
	if goal:
		goal_block = f"\nIMPORTANT GOAL: The user specifically wants to test: {goal}. Prioritize generating scenarios that address this goal.\n"

	prompt = f"""Based on this website analysis, generate {max_tests} test scenarios that target the discovered features.
{goal_block}
Website: {url}
Analysis:
{analysis.model_dump_json(indent=2)}

FEATURE-DRIVEN TEST ALLOCATION:
- ONLY generate tests for features with testability "testable" or "partial". SKIP "untestable" features entirely.
- Each test MUST reference a target_feature (matching a Feature.name from the analysis) and use a feature_category matching that feature's category.
- Priority derives from feature importance:
  - core features → critical or high priority
  - secondary features → medium priority
  - peripheral features → low priority
- At least 50% of the test budget ({max_tests // 2} or more tests) MUST target core features.
- At most 1 test per peripheral feature.

TESTABLE FEATURES AVAILABLE:
- Core ({len(core_features)}): {', '.join(f.name for f in core_features) or 'none'}
- Secondary ({len(secondary_features)}): {', '.join(f.name for f in secondary_features) or 'none'}
- Peripheral ({len(peripheral_features)}): {', '.join(f.name for f in peripheral_features) or 'none'}
- Untestable (SKIP): {', '.join(f.name for f in features_by_testability['untestable']) or 'none'}

MANDATORY PERSONA DISTRIBUTION (for {max_tests} tests):
Each test MUST have a test_persona field. Distribute across these personas:
- happy_path (~20%): Standard user, expected flow. A skilled user who knows exactly what they want.
- confused_novice (~15%): Simulate someone who doesn't read labels, clicks the wrong button, submits a form without filling it, navigates backward repeatedly, searches for something nonsensical, types a URL into a search box.
- adversarial (~15%): Try to break things: type "<script>alert(1)</script>" in search, enter SQL in form fields ("'; DROP TABLE users;--"), navigate to /admin or /api/debug, submit forms with only whitespace, paste HTML tags into text inputs.
- edge_case (~15%): Empty form submissions, extremely long inputs (500+ chars), special characters (emoji 🎉, RTL text مرحبا, null bytes, unicode snowman ☃), double-clicking buttons, using browser back during multi-step flows.
- explorer (~10%): Unexpected navigation patterns — visit pages in unusual order, use features in unintended combinations, click things that look decorative, try to use the site in ways the designer didn't intend.
- impatient_user (~15%): Click rapidly without waiting for pages to load, skip required steps in multi-step flows, try to submit forms immediately, navigate away mid-action, spam the search button.
- angry_user (~10%): Rage-clicks buttons multiple times, types frustration/profanity into form fields ("THIS IS BROKEN!!!"), force-navigates by typing URLs directly, hammers the back button.

PERSONA-SPECIFIC SUCCESS CRITERIA GUIDANCE:
- happy_path: "The agent completes the expected flow and arrives at the correct page/state"
- confused_novice: "The website gracefully handles the confused interaction — no crash, no blank page, shows a helpful error or redirects appropriately"
- adversarial: "The website does NOT execute injected scripts, does NOT expose debug info, shows an appropriate error or sanitizes the input"
- edge_case: "The website handles the edge case without crashing — shows a validation message, truncates gracefully, or ignores invalid input"
- explorer: "The website remains functional and navigable even through an unusual path"
- impatient_user: "The website handles rapid/premature interactions without corrupting state — no duplicate submissions, no broken UI, no data loss"
- angry_user: "The website absorbs the hostile interaction gracefully — no crash, no inappropriate response to profanity in inputs, no infinite loops from rapid clicks"

Each test should have:
- A clear name reflecting the persona behavior (e.g. "Novice submits empty search form" not "Test search functionality")
- What it verifies (description) — describe the REALISTIC USER BEHAVIOR being simulated
- Priority level (critical, high, medium, low)
- feature_category (navigation, search, forms, content_display, filtering_sorting, media, authentication, ecommerce, social, other)
- target_feature (the Feature.name this test exercises)
- test_persona (one of: happy_path, confused_novice, adversarial, edge_case, explorer, impatient_user, angry_user)
- Step-by-step instructions the browser agent should follow (steps_description) — write these AS IF the agent IS that persona. For a confused novice, the steps should include wrong clicks and backtracking. For adversarial, the steps should include actual attack payloads.
- Concrete success criteria the judge can verify (success_criteria) — for non-happy-path personas, evaluate HOW THE WEBSITE HANDLES the unexpected behavior, not whether the "task" succeeded.

IMPORTANT — Success criteria rules:
- Success criteria must ONLY reference observable actions: pages navigated to, elements clicked, forms submitted, text entered, and the website's response to those actions.
- Never require the agent to "report", "verify", "confirm", "provide evidence of", or "demonstrate" anything.
- For non-happy-path tests: a test PASSES if the website handles bad input gracefully (error message, redirect, sanitized display). A test FAILS if the website crashes, shows a blank page, displays an unhandled exception, or executes injected code.
- The judge evaluates success by matching the action trace and browser URLs against these criteria.

Make tests realistic — they should interact with the actual UI elements found in the analysis.
Do NOT generate tests that require authentication/login unless a login page was found.
"""

	response = await llm.ainvoke(
		messages=[
			SystemMessage(content=(
				'You are a senior QA strategist who designs test suites that find real problems. '
				'Your job is NOT to verify happy paths — any junior can do that. '
				'Your job is to think like real users: confused, impatient, angry, adversarial, and exploratory. '
				'Each test should simulate a REALISTIC human behavior, not a robotic verification step. '
				'Real users misclick, rage-type, paste garbage, get lost, and do things nobody planned for.'
			)),
			UserMessage(content=prompt),
		],
		output_format=TestPlan,
	)

	test_plan = response.completion
	assert isinstance(test_plan, TestPlan), f'Expected TestPlan, got {type(test_plan)}'

	print(f'Generated {len(test_plan.scenarios)} test scenarios:')
	for i, s in enumerate(test_plan.scenarios, 1):
		print(f'  {i}. [{s.priority.upper()}] [{s.test_persona}] {s.name} ({s.feature_category})')

	return test_plan


# ─── Phase 3: Execute & Report ─────────────────────────────────────────────────


async def execute_tests(
	url: str, test_plan: TestPlan, llm: ChatOpenAI, progress_state: Any = None
) -> list[TestResult]:
	print(f'\n{"="*60}')
	print(f'Phase 3: Executing {len(test_plan.scenarios)} tests')
	print(f'{"="*60}\n')

	browser_session = BrowserSession(browser_profile=BrowserProfile(keep_alive=True))
	await browser_session.start()

	results: list[TestResult] = []

	try:
		for i, scenario in enumerate(test_plan.scenarios, 1):
			print(f'\n--- Test {i}/{len(test_plan.scenarios)}: {scenario.name} ---')
			if progress_state is not None:
				progress_state.current_test = i

			agent = Agent(
				task=(
					f'Test: {scenario.name}\n\n'
					f'Description: {scenario.description}\n\n'
					f'Steps:\n{scenario.steps_description}\n\n'
					f'Success criteria: {scenario.success_criteria}\n\n'
					f'IMPORTANT: Be direct and efficient. Do not wait unnecessarily. '
					f'Complete the test as fast as possible with minimal steps.\n\n'
					f'ADAPTATION RULES:\n'
					f'- If clicking a button returns a "disabled" error, do NOT retry the same click. Analyze why it is disabled — likely required fields need to be filled first, or a prerequisite step is missing.\n'
					f'- If search_page returns 0 results, the content does not exist on this page. Do NOT repeat the same search or scroll hoping it appears. Try alternative navigation or different search terms.\n'
					f'- If the expected UI element is not found after 2 attempts, the page structure differs from expectations. Report what you actually observe and complete the test with that information.\n'
					f'- Your step budget is limited. Never repeat a failed action more than once.'
				),
				llm=llm,
				browser_session=browser_session,
				use_judge=False,
				max_actions_per_step=3,
			)
			history = await agent.run(max_steps=15)

			judgement = await murphy_judge(history, scenario, llm)
			success = judgement['verdict']
			status = 'PASS' if success else 'FAIL'
			print(f'  Result: {status} ({history.total_duration_seconds():.1f}s)')

			test_result = TestResult(
				scenario=scenario,
				success=success,
				judgement=judgement,
				actions=history.model_actions(),
				errors=history.errors(),
				duration=history.total_duration_seconds(),
			)
			test_result.failure_category = classify_failure(test_result)
			results.append(test_result)

			# Navigate back to homepage between tests (direct CDP, no LLM needed)
			try:
				await browser_session.navigate_to(url)
			except Exception:
				pass

	finally:
		await browser_session.kill()

	return results


def classify_failure(result: TestResult) -> Literal['website_issue', 'test_limitation'] | None:
	"""Classify a failed test as a website issue or a test limitation.

	Delegates to the judge LLM's failure_category field, which has full context
	about the agent's actions and the website's behavior.
	"""
	if result.success:
		return None
	judgement = result.judgement or {}
	return judgement.get('failure_category')


def build_summary(results: list[TestResult]) -> ReportSummary:
	passed = sum(1 for r in results if r.success is True)
	failed = sum(1 for r in results if r.success is not True)
	total = len(results)

	by_priority: dict[str, dict[str, int]] = {}
	for r in results:
		p = r.scenario.priority
		if p not in by_priority:
			by_priority[p] = {'passed': 0, 'failed': 0}
		if r.success is True:
			by_priority[p]['passed'] += 1
		else:
			by_priority[p]['failed'] += 1

	website_issues = sum(1 for r in results if r.failure_category == 'website_issue')
	test_limitations = sum(1 for r in results if r.failure_category == 'test_limitation')

	return ReportSummary(
		total=total,
		passed=passed,
		failed=failed,
		pass_rate=round(passed / total * 100, 1) if total > 0 else 0.0,
		website_issues=website_issues,
		test_limitations=test_limitations,
		by_priority=by_priority,
	)


# ─── Main ──────────────────────────────────────────────────────────────────────


async def main():
	parser = argparse.ArgumentParser(description='Murphy — AI-driven website evaluation')
	parser.add_argument('url', nargs='?', default='https://www.prosus.com', help='Website URL to evaluate')
	parser.add_argument('--category', help='Site category hint (ecommerce, saas, content, social)')
	parser.add_argument('--model', default='gpt-4o', help='OpenAI model (default: gpt-4o)')
	parser.add_argument('--max-tests', type=int, default=8, help='Max test scenarios (default: 8)')
	parser.add_argument('--output-dir', default='./murphy/output', help='Output directory for reports')
	parser.add_argument('--goal', help='Free-text goal to bias test generation')
	parser.add_argument('--plan', help='Path to existing YAML test plan (skips analysis + test generation)')
	parser.add_argument('--no-ui', action='store_true', help='Skip interactive review UI, run all phases directly')
	args = parser.parse_args()

	llm = ChatOpenAI(model=args.model)
	output_dir = Path(args.output_dir)
	output_dir.mkdir(parents=True, exist_ok=True)

	if args.plan:
		from murphy.test_plan_io import load_test_plan
		plan_path = Path(args.plan)
		url, test_plan = load_test_plan(plan_path)
		if url != args.url:
			print(f'WARNING: Plan URL ({url}) differs from positional url ({args.url}). Using positional.')
		print(f'Loaded {len(test_plan.scenarios)} scenarios from {plan_path}')
		analysis = WebsiteAnalysis(
			site_name=args.url, category='unknown', description='Loaded from plan file',
			key_pages=[], features=[], identified_user_flows=[],
		)
	else:
		# Phase 1
		analysis = await analyze_website(args.url, llm, args.category)

		# Phase 2
		test_plan = await generate_tests(args.url, analysis, llm, args.max_tests, goal=args.goal)

		# Save test plan to YAML
		from murphy.test_plan_io import save_test_plan
		plan_path = save_test_plan(args.url, test_plan, output_dir)
		print(f'\n  Test plan saved: {plan_path}')

	if args.no_ui:
		# Direct execution (original behavior)
		results = await execute_tests(args.url, test_plan, llm)
		_write_reports_and_print(args.url, analysis, results, output_dir)
		return

	# Interactive UI mode — start server for test plan review
	from murphy.server import ServerState, start_server

	async def _execute_with_progress(plan: TestPlan, state: 'ServerState') -> list[TestResult]:
		"""Wrapper that updates server state as tests execute."""
		return await execute_tests(args.url, plan, llm, progress_state=state)

	state = ServerState(
		url=args.url,
		analysis=analysis,
		test_plan=test_plan,
		execute_fn=_execute_with_progress,
	)
	state.build_summary_fn = build_summary

	runner, port = await start_server(state)

	print('  Press Ctrl+C to stop the server.\n')
	try:
		# Keep alive until Ctrl+C or execution completes and user is done
		while True:
			await asyncio.sleep(1)
			# After execution is done, write reports (once)
			if state.done and state.results and not getattr(state, '_reports_written', False):
				_write_reports_and_print(args.url, analysis, state.results, output_dir)
				state._reports_written = True  # type: ignore[attr-defined]
	except KeyboardInterrupt:
		pass
	finally:
		await runner.cleanup()


def _write_reports_and_print(
	url: str,
	analysis: WebsiteAnalysis,
	results: list[TestResult],
	output_dir: Path,
) -> None:
	summary = build_summary(results)
	report = EvaluationReport(
		url=url,
		timestamp=datetime.now(timezone.utc).isoformat(),
		analysis=analysis,
		results=results,
		summary=summary,
	)

	json_path = write_json_report(report, output_dir)
	md_path = write_markdown_report(report, output_dir)

	print(f'\n{"="*60}')
	print(f'Evaluation Complete')
	print(f'{"="*60}')
	print(f'\n  Pass rate: {summary.pass_rate}% ({summary.passed}/{summary.total})')
	print(f'  JSON report: {json_path}')
	print(f'  Markdown report: {md_path}')


if __name__ == '__main__':
	asyncio.run(main())
