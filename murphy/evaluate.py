"""
Murphy — Website Evaluation System

Analyzes a website, generates user journey tests, executes them, and reports results.

Supports two plan-generation paths:
1. **Feature-discovery** (default, no --goal): full site analysis → test generation
2. **Exploration-first** (--goal provided): explore agent → summarize → synthesize plan with quality checks

Usage:
    python -m murphy.evaluate https://www.prosus.com
    python -m murphy.evaluate https://stripe.com --category saas
    python -m murphy.evaluate https://example.com --model gpt-4o --max-tests 5
"""

import argparse
import asyncio
import re
import sys
import traceback
from pathlib import Path
from collections.abc import Callable
from typing import Any, Literal

from dotenv import load_dotenv

from browser_use import Agent
from browser_use.agent.views import AgentHistoryList
from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession
from browser_use.llm import ChatOpenAI, SystemMessage, UserMessage
from murphy.judge import murphy_judge
from murphy.models import (
	ReportSummary,
	ScenarioExecutionVerdict,
	TestPlan,
	TestResult,
	TestScenario,
	WebsiteAnalysis,
)
from murphy.report import write_full_report

load_dotenv()


# ─── Phase 1: Analyze ──────────────────────────────────────────────────────────


async def analyze_website(url: str, llm: ChatOpenAI, category: str | None = None, goal: str | None = None) -> WebsiteAnalysis:
	print(f'\n{"=" * 60}')
	print(f'Phase 1: Analyzing {url}')
	print(f'{"=" * 60}\n')

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
			f"- You should find at least 8-15 features for any non-trivial app. If you have fewer than 8, you haven't explored enough — go back and click more nav items.\n"
			f'- Name each feature as a user action: "Create AI agent", "Search tasks", "Upload document" — NOT "Navigation Links" or "Button group"\n'
			f"- A feature = one thing a user can accomplish. If it takes multiple steps, that's still one feature.\n"
			f'- For `elements`, write brief descriptions: "Create button on agents page", "Task name input" — NOT raw hrefs or DOM dumps\n'
			f'- For `page_url`, use the page where the feature is primarily accessed\n'
			f"- Skip generic navigation (header links, footer links, breadcrumbs) — those aren't features\n"
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
	url: str,
	analysis: WebsiteAnalysis,
	llm: ChatOpenAI,
	max_tests: int,
	goal: str | None = None,
) -> TestPlan:
	print(f'\n{"=" * 60}')
	print('Phase 2: Generating test scenarios')
	print(f'{"=" * 60}\n')

	# Build a features summary for the prompt
	features_by_testability: dict[str, list] = {'testable': [], 'partial': [], 'untestable': []}
	for f in analysis.features:
		features_by_testability[f.testability].append(f)

	testable_features = features_by_testability['testable'] + features_by_testability['partial']
	core_features = [f for f in testable_features if f.importance == 'core']
	secondary_features = [f for f in testable_features if f.importance == 'secondary']
	peripheral_features = [f for f in testable_features if f.importance == 'peripheral']

	goal_block = ''
	if goal:
		goal_block = f'\nIMPORTANT GOAL: The user specifically wants to test: {goal}. Prioritize generating scenarios that address this goal.\n'

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
			SystemMessage(
				content=(
					'You are a senior QA strategist who designs test suites that find real problems. '
					'Your job is NOT to verify happy paths — any junior can do that. '
					'Your job is to think like real users: confused, impatient, angry, adversarial, and exploratory. '
					'Each test should simulate a REALISTIC human behavior, not a robotic verification step. '
					'Real users misclick, rage-type, paste garbage, get lost, and do things nobody planned for.'
				)
			),
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


# ─── Exploration-first plan generation ────────────────────────────────────────


def _build_exploration_prompt(task: str, url: str) -> str:
	"""Discovery prompt for the explore agent."""
	return (
		f'You are exploring {url} to understand its UI for a specific task.\n\n'
		f'TASK: {task}\n\n'
		f'YOUR JOB:\n'
		f'1. Start from the home page.\n'
		f'2. Discover TWO candidate navigation routes to the page/feature relevant to the task.\n'
		f'3. Validate both routes — pick the most reliable one.\n'
		f'4. Execute the core happy-path flow ONCE end-to-end.\n'
		f'5. Capture concrete page URLs, control labels, and element types you interact with.\n\n'
		f'RULES:\n'
		f'- This is READ-ONLY exploration. Do NOT click "Delete" or confirm irreversible actions.\n'
		f'- Stay on the same domain as {url}.\n'
		f'- STOP once the core flow is confirmed — do not re-check or explore further.\n'
		f'- Note any alternative routes, form fields, buttons, dropdowns, and validation messages.\n'
	)


def _build_generation_prompt(task: str, url: str, exploration_context: str, max_scenarios: int) -> str:
	"""Synthesis prompt with persona requirements for generating a plan from exploration data."""
	return (
		f'Based on the following exploration of {url}, generate {max_scenarios} test scenarios.\n\n'
		f'TASK: {task}\n\n'
		f'EXPLORATION CONTEXT (observed UI evidence):\n{exploration_context}\n\n'
		f'REQUIREMENTS:\n'
		f'- Generate exactly {max_scenarios} scenarios (minimum 5 if max allows).\n'
		f'- Must include these personas: happy_path, confused_novice, adversarial, edge_case, explorer.\n'
		f'- At least one scenario must be happy_path with priority=critical.\n'
		f'- The happy_path scenario must describe the chosen route AND mention alternatives considered.\n'
		f'- steps_description must include at least 2-3 numbered steps with specific UI element references.\n'
		f'- success_criteria must reference observable UI signals (toasts, badges, list rows, confirmation messages).\n'
		f'- Do NOT fabricate URLs — only reference pages/paths observed in the exploration context.\n'
		f'- For non-happy-path tests: evaluate how the website HANDLES unexpected behavior.\n\n'
		f'PERSONA DISTRIBUTION:\n'
		f'- happy_path (~20%): Standard user completing the expected flow.\n'
		f'- confused_novice (~15%): Misclicks, wrong inputs, backtracking.\n'
		f'- adversarial (~15%): XSS payloads, SQL injection, probing /admin.\n'
		f'- edge_case (~15%): Empty inputs, special chars, long strings.\n'
		f'- explorer (~10%): Unusual navigation, unexpected feature combos.\n'
		f'- impatient_user (~15%): Rapid clicks, skipping steps.\n'
		f'- angry_user (~10%): Rage-clicks, profanity in inputs.\n'
	)


def _summarize_exploration_from_actions(actions: list[dict[str, Any]], url: str) -> str:
	"""Extract pages visited, clicks, and inputs from action history into a text summary."""
	lines: list[str] = []
	pages_seen: list[str] = []

	for i, action in enumerate(actions, 1):
		interacted = action.get('interacted_element')
		for key, val in action.items():
			if key == 'interacted_element':
				continue

			if key in ('navigate', 'go_to_url'):
				nav_url = val.get('url', '?') if isinstance(val, dict) else '?'
				lines.append(f'{i}. NAVIGATE → {nav_url}')
				if isinstance(val, dict) and val.get('url'):
					pages_seen.append(val['url'])

			elif key == 'click_element':
				el_desc = ''
				if interacted and isinstance(interacted, dict):
					tag = interacted.get('tag_name', '?')
					text = interacted.get('text', '')
					href = (
						interacted.get('attributes', {}).get('href', '') if isinstance(interacted.get('attributes'), dict) else ''
					)
					el_desc = f'<{tag}> "{text}"'
					if href:
						el_desc += f' → href="{href}"'
				else:
					idx = val.get('index', '?') if isinstance(val, dict) else '?'
					el_desc = f'element {idx}'
				lines.append(f'{i}. CLICK {el_desc}')

			elif key == 'input_text':
				text = val.get('text', '') if isinstance(val, dict) else ''
				lines.append(f'{i}. TYPE "{text[:50]}"')

			elif key == 'scroll':
				direction = 'down' if (isinstance(val, dict) and val.get('down', True)) else 'up'
				lines.append(f'{i}. SCROLL {direction}')

			elif key == 'done':
				lines.append(f'{i}. DONE')

	# Deduplicate pages
	unique_pages = list(dict.fromkeys(pages_seen))
	summary_parts = []
	if unique_pages:
		summary_parts.append('Pages visited:\n' + '\n'.join(f'  - {p}' for p in unique_pages))
	summary_parts.append('\nAction trace:\n' + '\n'.join(lines) if lines else '(no actions)')
	return '\n'.join(summary_parts)


def _scenario_quality_issues(task: str, scenario: TestScenario) -> list[str]:
	"""Per-scenario quality validation. Returns list of issue descriptions."""
	issues: list[str] = []
	task_lower = task.lower()
	task_words = set(re.findall(r'\w+', task_lower))

	# 1. Task alignment — scenario keywords should overlap with task
	scenario_text = f'{scenario.name} {scenario.description} {scenario.steps_description}'.lower()
	scenario_words = set(re.findall(r'\w+', scenario_text))
	overlap = task_words & scenario_words - {'the', 'a', 'an', 'to', 'is', 'and', 'or', 'in', 'on', 'for', 'of', 'with'}
	if len(overlap) < 1 and scenario.test_persona == 'happy_path':
		issues.append(f'Scenario "{scenario.name}" has no keyword overlap with task "{task}"')

	# 2. Step clarity — at least 2 numbered/dotted steps
	steps = scenario.steps_description
	step_lines = [line for line in steps.split('\n') if re.match(r'^\s*(\d+[\.\)]\s|[-•]\s)', line.strip())]
	if len(step_lines) < 2:
		issues.append(f'Scenario "{scenario.name}" has fewer than 2 explicit steps')

	# 3. Observable criteria — success criteria should reference UI signals
	criteria_lower = scenario.success_criteria.lower()
	ui_signals = [
		'visible',
		'appears',
		'displayed',
		'shows',
		'confirmation',
		'toast',
		'badge',
		'error',
		'message',
		'redirect',
		'page',
		'list',
		'row',
	]
	if not any(signal in criteria_lower for signal in ui_signals):
		issues.append(f'Scenario "{scenario.name}" success criteria lack observable UI signals')

	# 4. No fabricated URLs — reject patterns like "/spaces/" or bare http:// in steps
	if re.search(r'https?://(?!.*(?:' + re.escape(task.split()[0] if task.split() else '') + r'))', steps):
		# Only flag if URL doesn't look related to the task
		pass  # Relaxed — hard to validate without exploration data

	# 5. Generic phrases — flag vague phrasing outside confused_novice persona
	vague_patterns = ['click random', 'click any', 'click something']
	if scenario.test_persona != 'confused_novice':
		for pattern in vague_patterns:
			if pattern in steps.lower():
				issues.append(f'Scenario "{scenario.name}" uses vague "{pattern}" outside confused_novice persona')

	return issues


def _plan_quality_issues(task: str, plan: TestPlan) -> list[str]:
	"""Plan-level quality validation. Returns list of issue descriptions."""
	issues: list[str] = []

	# 1. Minimum scenarios
	if len(plan.scenarios) < 5:
		issues.append(f'Plan has only {len(plan.scenarios)} scenarios (minimum 5)')

	# 2. Required personas
	personas_present = {s.test_persona for s in plan.scenarios}
	required_personas = {'happy_path', 'confused_novice', 'adversarial', 'edge_case', 'explorer'}
	missing = required_personas - personas_present
	if missing:
		issues.append(f'Missing required personas: {", ".join(sorted(missing))}')

	# 3. Critical happy path
	has_critical_happy = any(s.test_persona == 'happy_path' and s.priority == 'critical' for s in plan.scenarios)
	if not has_critical_happy:
		issues.append('No happy_path scenario with priority=critical')

	# 4. Per-scenario quality
	for s in plan.scenarios:
		scenario_issues = _scenario_quality_issues(task, s)
		issues.extend(scenario_issues)

	# 5. Task relevance — max 33% can be unrelated by keyword overlap
	task_words = set(re.findall(r'\w+', task.lower())) - {
		'the',
		'a',
		'an',
		'to',
		'is',
		'and',
		'or',
		'in',
		'on',
		'for',
		'of',
		'with',
	}
	unrelated = 0
	for s in plan.scenarios:
		scenario_text = f'{s.name} {s.description}'.lower()
		scenario_words = set(re.findall(r'\w+', scenario_text))
		if not (task_words & scenario_words):
			unrelated += 1
	if plan.scenarios and unrelated / len(plan.scenarios) > 0.33:
		issues.append(f'{unrelated}/{len(plan.scenarios)} scenarios appear unrelated to task')

	return issues


async def explore_and_generate_plan(
	task: str,
	url: str,
	llm: ChatOpenAI,
	session: BrowserSession,
	max_scenarios: int = 8,
	max_steps: int = 30,
) -> TestPlan:
	"""Exploration-first plan generation: explore → summarize → synthesize with quality checks."""
	from murphy.actions import register_domain_access_action, register_refresh_dom_action
	from murphy.session_utils import prepare_session_for_task

	print(f'\n{"=" * 60}')
	print('Exploration-first plan generation')
	print(f'  Task: {task}')
	print(f'  URL: {url}')
	print(f'{"=" * 60}\n')

	# Step 1: Prepare session
	await prepare_session_for_task(session, url, force_navigate=False)

	# Step 2: Run exploration agent
	print('Phase 1: Exploring UI...')
	explore_agent = Agent(
		task=_build_exploration_prompt(task, url),
		llm=llm,
		browser_session=session,
		use_judge=False,
		max_actions_per_step=3,
	)
	# Register custom actions on the explore agent's tools
	register_domain_access_action(explore_agent.tools, session)
	register_refresh_dom_action(explore_agent.tools, session)

	explore_steps = min(max_steps, 14)
	explore_history = await explore_agent.run(max_steps=explore_steps)

	# Step 3: Synthesize discovered context
	exploration_context = _summarize_exploration_from_actions(
		explore_history.model_actions(),
		url,
	)
	print(f'\n  Exploration complete. Summarized {len(explore_history.model_actions())} actions.\n')

	# Step 4: Generate plan with quality checks
	print('Phase 2: Synthesizing test plan...')
	synthesis_prompt = _build_generation_prompt(task, url, exploration_context, max_scenarios)

	max_retries = 2
	best_plan: TestPlan | None = None

	for attempt in range(max_retries + 1):
		retry_hint = ''
		if attempt > 0 and best_plan is not None:
			quality_issues = _plan_quality_issues(task, best_plan)
			if quality_issues:
				retry_hint = (
					'\n\nPREVIOUS ATTEMPT HAD QUALITY ISSUES — fix these:\n'
					+ '\n'.join(f'- {issue}' for issue in quality_issues)
					+ '\n'
				)
			else:
				break  # No issues, accept the plan

		response = await llm.ainvoke(
			messages=[
				SystemMessage(
					content=(
						'You are a QA strategist. Produce valid structured test plans from observed UI evidence. '
						'Every scenario must reference concrete UI elements observed during exploration.'
					)
				),
				UserMessage(content=synthesis_prompt + retry_hint),
			],
			output_format=TestPlan,
		)

		plan = response.completion
		assert isinstance(plan, TestPlan), f'Expected TestPlan, got {type(plan)}'

		# If empty, retry with explicit instruction
		if not plan.scenarios and attempt < max_retries:
			retry_hint = '\n\nYou returned an empty plan. Generate 5-8 scenarios with diverse personas.\n'
			continue

		best_plan = plan

		# Check quality on first attempt — retry if issues found
		if attempt == 0:
			quality_issues = _plan_quality_issues(task, plan)
			if not quality_issues:
				break
			print(f'  Quality issues found ({len(quality_issues)}), regenerating...')
		else:
			break

	assert best_plan is not None and best_plan.scenarios, 'Failed to generate any test scenarios'

	_log_plan_summary(best_plan)
	return best_plan


def _log_plan_summary(plan: TestPlan) -> None:
	"""Print generated plan summary."""
	print(f'Generated {len(plan.scenarios)} test scenarios:')
	for i, s in enumerate(plan.scenarios, 1):
		print(f'  {i}. [{s.priority.upper()}] [{s.test_persona}] {s.name} ({s.feature_category})')


# ─── Enhanced execution prompt ────────────────────────────────────────────────


def _build_execution_prompt(global_task: str, scenario: TestScenario, start_url: str) -> str:
	"""Build execution prompt with validation rules."""
	return (
		f'Test: {scenario.name}\n\n'
		f'Global task context: {global_task}\n\n'
		f'Description: {scenario.description}\n\n'
		f'Steps:\n{scenario.steps_description}\n\n'
		f'Success criteria: {scenario.success_criteria}\n\n'
		f'IMPORTANT: You are already logged in. Be direct and efficient. '
		f'Complete the test as fast as possible with minimal steps.\n\n'
		f'ADAPTATION RULES:\n'
		f'- If clicking a button returns a "disabled" error, do NOT retry the same click. Analyze why it is disabled — likely required fields need to be filled first, or a prerequisite step is missing.\n'
		f'- If search_page returns 0 results, the content does not exist on this page. Do NOT repeat the same search or scroll hoping it appears. Try alternative navigation or different search terms.\n'
		f'- If the expected UI element is not found after 2 attempts, the page structure differs from expectations. Report what you actually observe and complete the test with that information.\n'
		f'- Your step budget is limited. Never repeat a failed action more than once.\n\n'
		f'VALIDATION RULES:\n'
		f'- Validate outcome state before returning success (no inference from partial signals).\n'
		f'- Use visible UI signals only: toasts, badges, list rows, detail cards, confirmation messages.\n'
		f'- For create flows: confirm new entity appears with a recognizable identifier.\n'
		f'- For delete flows: confirm entity is absent from list/search.\n'
		f'- For edit flows: reopen and confirm updates persist.\n'
		f'- If evidence is ambiguous, return success=false.\n'
	)


# ─── Structured output parsing ────────────────────────────────────────────────


def _parse_structured_output(
	history: AgentHistoryList, model_cls: type[ScenarioExecutionVerdict]
) -> ScenarioExecutionVerdict | None:
	"""Safely parse structured output from agent history."""
	result = history.final_result()
	if not result:
		return None
	try:
		return model_cls.model_validate_json(result)
	except Exception:
		# Try parsing as dict
		try:
			import json

			data = json.loads(result)
			return model_cls.model_validate(data)
		except Exception:
			return None


def _extract_form_fills(actions: list[dict[str, Any]]) -> list[dict]:
	"""Extract form fill actions with field info and typed text."""
	fills: list[dict] = []
	for action in actions:
		for key, val in action.items():
			if key in ('input_text', 'input') and isinstance(val, dict):
				fill: dict[str, Any] = {
					'text': val.get('text', ''),
					'index': val.get('index'),
				}
				# Include interacted element info if available
				el = action.get('interacted_element')
				if el and isinstance(el, dict):
					fill['field_name'] = el.get('ax_name', '')
					fill['tag'] = el.get('tag_name', '')
					fill['placeholder'] = el.get('placeholder', '')
				fills.append(fill)
	return fills


def _extract_pages_visited(actions: list[dict[str, Any]], start_url: str) -> list[str]:
	"""Extract unique pages visited from action history."""
	pages: list[str] = [start_url]
	for action in actions:
		for key, val in action.items():
			if key in ('navigate', 'go_to_url') and isinstance(val, dict):
				url = val.get('url', '')
				if url:
					pages.append(url)
	# Deduplicate preserving order
	seen: set[str] = set()
	unique: list[str] = []
	for p in pages:
		if p not in seen:
			seen.add(p)
			unique.append(p)
	return unique


# ─── Single-test execution helper ──────────────────────────────────────────────


async def _execute_single_test(
	url: str,
	scenario: TestScenario,
	llm: ChatOpenAI,
	browser_session: BrowserSession,
	goal: str | None,
	fixture_paths: list[Path] | None,
	max_steps: int,
	index: int,
	total: int,
) -> TestResult:
	"""Execute one test scenario and return its TestResult.

	Shared by both sequential and parallel execution paths.
	"""
	from murphy.actions import register_domain_access_action, register_refresh_dom_action
	from murphy.session_utils import prepare_session_for_task

	print(f'\n--- Test {index}/{total}: {scenario.name} ---')

	try:
		# Stabilize session between tests
		await prepare_session_for_task(browser_session, url, force_navigate=False)

		task_prompt = (
			_build_execution_prompt(goal or '', scenario, url)
			if goal
			else (
				f'Test: {scenario.name}\n\n'
				f'Description: {scenario.description}\n\n'
				f'Steps:\n{scenario.steps_description}\n\n'
				f'Success criteria: {scenario.success_criteria}\n\n'
				f'IMPORTANT: You are already logged in. Be direct and efficient. '
				f'Complete the test as fast as possible with minimal steps.'
			)
		)

		file_paths_str = [str(p) for p in fixture_paths] if fixture_paths else []
		agent_kwargs: dict[str, Any] = {
			'task': task_prompt,
			'llm': llm,
			'browser_session': browser_session,
			'use_judge': False,
			'max_actions_per_step': 3,
		}
		if file_paths_str:
			agent_kwargs['available_file_paths'] = file_paths_str

		# Use structured output for the verdict
		agent_kwargs['output_model_schema'] = ScenarioExecutionVerdict

		agent = Agent(**agent_kwargs)
		# Register custom actions
		register_domain_access_action(agent.tools, browser_session)
		register_refresh_dom_action(agent.tools, browser_session)

		history = await agent.run(max_steps=max_steps)

		# Parse structured verdict from agent
		verdict = _parse_structured_output(history, ScenarioExecutionVerdict)

		# Also run murphy judge for authoritative pass/fail
		judgement = await murphy_judge(history, scenario, llm)

		# Merge: use judge verdict as authoritative, but overlay agent's evaluations
		success = judgement['verdict']
		status = 'PASS' if success else 'FAIL'
		print(f'  Result: {status} ({history.total_duration_seconds():.1f}s)')

		# Prefer verdict evaluations if available, fall back to judge's
		process_eval = (verdict.process_evaluation if verdict else '') or judgement.get('process_evaluation', '')
		logical_eval = (verdict.logical_evaluation if verdict else '') or judgement.get('logical_evaluation', '')
		usability_eval = (verdict.usability_evaluation if verdict else '') or judgement.get('usability_evaluation', '')
		reason = (verdict.reason if verdict else '') or judgement.get('failure_reason', '')

		all_actions = history.model_actions()
		test_result = TestResult(
			scenario=scenario,
			success=success,
			judgement=judgement,
			actions=all_actions,
			errors=history.errors(),
			duration=history.total_duration_seconds(),
			pages_visited=_extract_pages_visited(all_actions, url),
			screenshot_paths=[p for p in history.screenshot_paths() if p],
			form_fills=_extract_form_fills(all_actions),
			process_evaluation=process_eval,
			logical_evaluation=logical_eval,
			usability_evaluation=usability_eval,
			reason=reason,
		)
		test_result.failure_category = classify_failure(test_result)
	except Exception as exc:
		tb = traceback.format_exc()
		print(f'  CRASH: {type(exc).__name__}: {exc}')
		test_result = TestResult(
			scenario=scenario,
			success=False,
			judgement=None,
			actions=[],
			errors=[f'{type(exc).__name__}: {exc}', tb],
			duration=0.0,
			reason=f'Test crashed: {type(exc).__name__}: {exc}',
		)
		test_result.failure_category = 'test_limitation'

	return test_result


# ─── Session pool for parallel execution ──────────────────────────────────────


async def _create_session_pool(
	pool_size: int,
	original_session: BrowserSession,
	highlight_elements: bool = True,
) -> list[BrowserSession]:
	"""Create N independent browser sessions for parallel test execution.

	Slot 0 = the original session (already started, already authenticated).
	Slots 1..N-1 = new BrowserSession instances with their own BrowserProfile.
	Auth cookies are transferred from the original session via CDP.
	"""
	from browser_use.browser.profile import BrowserProfile

	if pool_size <= 1:
		return [original_session]

	sessions: list[BrowserSession] = [original_session]

	# Extract cookies from original session for auth transfer
	cookies: list[dict] = []
	try:
		cdp_session = await original_session.get_active_cdp_session()
		result = await cdp_session.cdp_client.send.Network.getAllCookies(
			session_id=cdp_session.session_id,
		)
		cookies = (result or {}).get('cookies', [])
	except Exception:
		pass

	for _ in range(1, pool_size):
		profile = BrowserProfile(
			keep_alive=True,
			dom_highlight_elements=highlight_elements,
		)
		session = BrowserSession(browser_profile=profile)
		await session.start()

		# Inject auth cookies if available
		if cookies:
			try:
				cdp_session = await session.get_active_cdp_session()
				await cdp_session.cdp_client.send.Network.setCookies(
					params={'cookies': cookies},
					session_id=cdp_session.session_id,
				)
			except Exception:
				pass

		sessions.append(session)

	return sessions


async def _cleanup_session_pool(sessions: list[BrowserSession], original_session: BrowserSession) -> None:
	"""Kill all pool sessions except the original."""
	for session in sessions:
		if session is original_session:
			continue
		try:
			await session.kill()
		except Exception:
			pass


# ─── Phase 3: Execute & Report ─────────────────────────────────────────────────


async def execute_tests(url: str, test_plan: TestPlan, llm: ChatOpenAI, progress_state: Any = None, save_callback: Callable[[list[TestResult]], None] | None = None) -> list[TestResult]:
	print(f'\n{"=" * 60}')
	print(f'Phase 3: Executing {len(test_plan.scenarios)} tests')
	print(f'{"=" * 60}\n')

	browser_session = BrowserSession(browser_profile=BrowserProfile(keep_alive=True))
	await browser_session.start()

	results: list[TestResult] = []

	try:
		for i, scenario in enumerate(test_plan.scenarios, 1):
			print(f'\n--- Test {i}/{len(test_plan.scenarios)}: {scenario.name} ---')
			if progress_state is not None:
				progress_state.current_test = i

			try:
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

				all_actions = history.model_actions()
				test_result = TestResult(
					scenario=scenario,
					success=success,
					judgement=judgement,
					actions=all_actions,
					errors=history.errors(),
					duration=history.total_duration_seconds(),
					pages_visited=_extract_pages_visited(all_actions, url),
					screenshot_paths=[p for p in history.screenshot_paths() if p],
					form_fills=_extract_form_fills(all_actions),
					process_evaluation=judgement.get('process_evaluation', ''),
					logical_evaluation=judgement.get('logical_evaluation', ''),
					usability_evaluation=judgement.get('usability_evaluation', ''),
					reason=judgement.get('failure_reason', ''),
				)
				test_result.failure_category = classify_failure(test_result)
			except Exception as exc:
				tb = traceback.format_exc()
				print(f'  CRASH: {type(exc).__name__}: {exc}')
				test_result = TestResult(
					scenario=scenario,
					success=False,
					judgement=None,
					actions=[],
					errors=[f'{type(exc).__name__}: {exc}', tb],
					duration=0.0,
					reason=f'Test crashed: {type(exc).__name__}: {exc}',
				)
				test_result.failure_category = 'test_limitation'

			results.append(test_result)

			if save_callback:
				try:
					save_callback(results)
				except Exception as e:
					print(f'  ⚠️  save_callback failed: {e}')

			# Navigate back to homepage between tests (direct CDP, no LLM needed)
			try:
				if not browser_session.is_cdp_connected:
					try:
						await browser_session.kill()
					except Exception:
						pass
					await browser_session.start()
				await browser_session.navigate_to(url)
			except Exception:
				pass

	finally:
		await browser_session.kill()

	return results


async def execute_tests_with_session(
	url: str,
	test_plan: TestPlan,
	llm: ChatOpenAI,
	browser_session: BrowserSession,
	progress_state: Any = None,
	goal: str | None = None,
	fixture_paths: list[Path] | None = None,
	max_steps: int = 15,
	save_callback: Callable[[list[TestResult]], None] | None = None,
	max_concurrent: int = 1,
) -> list[TestResult]:
	"""Phase 3 execution reusing an existing browser session.

	Uses BOTH structured agent verdict (ScenarioExecutionVerdict) AND murphy judge.
	When max_concurrent > 1, runs tests in parallel using a session pool.
	"""
	total = len(test_plan.scenarios)
	mode = 'parallel' if max_concurrent > 1 else 'sequential'
	print(f'\n{"=" * 60}')
	print(f'Phase 3: Executing {total} tests ({mode}, max_concurrent={max_concurrent})')
	print(f'{"=" * 60}\n')

	if max_concurrent <= 1:
		# ── Sequential path (unchanged behavior) ──
		results: list[TestResult] = []
		for i, scenario in enumerate(test_plan.scenarios, 1):
			if progress_state is not None:
				progress_state.current_test = i

			test_result = await _execute_single_test(
				url=url,
				scenario=scenario,
				llm=llm,
				browser_session=browser_session,
				goal=goal,
				fixture_paths=fixture_paths,
				max_steps=max_steps,
				index=i,
				total=total,
			)
			results.append(test_result)

			if save_callback:
				try:
					save_callback(results)
				except Exception as e:
					print(f'  ⚠️  save_callback failed: {e}')

		return results

	# ── Parallel path ──
	highlight = browser_session.browser_profile.dom_highlight_elements if browser_session.browser_profile else True
	sessions = await _create_session_pool(
		pool_size=max_concurrent,
		original_session=browser_session,
		highlight_elements=highlight,
	)

	try:
		results_slots: list[TestResult | None] = [None] * total
		report_lock = asyncio.Lock()
		sem = asyncio.Semaphore(max_concurrent)

		async def _run_one(index_0: int, scenario: TestScenario) -> None:
			async with sem:
				session = sessions[index_0 % len(sessions)]
				if progress_state is not None:
					progress_state.current_test = index_0 + 1

				result = await _execute_single_test(
					url=url,
					scenario=scenario,
					llm=llm,
					browser_session=session,
					goal=goal,
					fixture_paths=fixture_paths,
					max_steps=max_steps,
					index=index_0 + 1,
					total=total,
				)
				results_slots[index_0] = result

				if save_callback:
					async with report_lock:
						completed = [r for r in results_slots if r is not None]
						try:
							save_callback(completed)
						except Exception as e:
							print(f'  ⚠️  save_callback failed: {e}')

		async with asyncio.TaskGroup() as tg:
			for i, scenario in enumerate(test_plan.scenarios):
				tg.create_task(_run_one(i, scenario))

		# Return results in plan order
		return [r for r in results_slots if r is not None]

	finally:
		await _cleanup_session_pool(sessions, browser_session)


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
			site_name=args.url,
			category='unknown',
			description='Loaded from plan file',
			key_pages=[],
			features=[],
			identified_user_flows=[],
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

	def _on_test_complete(results: list[TestResult]) -> None:
		_write_reports_and_print(args.url, analysis, results, output_dir)

	if args.no_ui:
		# Direct execution (original behavior)
		results = await execute_tests(args.url, test_plan, llm, save_callback=_on_test_complete)
		_write_reports_and_print(args.url, analysis, results, output_dir)
		return

	# Interactive UI mode — start server for test plan review
	from murphy.server import ServerState, start_server

	async def _execute_with_progress(plan: TestPlan, state: 'ServerState') -> list[TestResult]:
		"""Wrapper that updates server state as tests execute."""
		return await execute_tests(args.url, plan, llm, progress_state=state, save_callback=_on_test_complete)

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
	json_path, md_path = write_full_report(url, analysis, results, output_dir)
	summary = build_summary(results)

	print(f'\n{"=" * 60}')
	print('Evaluation Complete')
	print(f'{"=" * 60}')
	print(f'\n  Pass rate: {summary.pass_rate}% ({summary.passed}/{summary.total})')
	print(f'  JSON report: {json_path}')
	print(f'  Markdown report: {md_path}')


if __name__ == '__main__':
	asyncio.run(main())
