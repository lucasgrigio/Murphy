"""Murphy CLI — single command entry point.

Usage:
    murphy --url https://www.prosus.com                          # full run: detect auth → analyze → edit features → generate tests → edit tests → execute
    murphy --url https://work.toqan.ai --auth                    # skip detection, go straight to login wait
    murphy --url https://www.prosus.com --no-auth                # skip auth detection, treat as public
    murphy --url https://work.toqan.ai --features features.md    # skip analysis, load features from file
    murphy --url https://work.toqan.ai --plan plan.yaml          # skip analysis + generation, load test plan
    murphy --url https://work.toqan.ai --goal "check agent creation"
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from dotenv import load_dotenv

if TYPE_CHECKING:
	from browser_use.browser.session import BrowserSession
	from browser_use.llm import ChatOpenAI
	from murphy.models import TestPlan, TestResult, WebsiteAnalysis

load_dotenv()

# Persistent browser profile directory — stores cookies/session across runs so login is only needed once.
BROWSER_PROFILE_DIR = Path(__file__).parent / 'browser_profile'


def main() -> int:
	parser = argparse.ArgumentParser(
		prog='murphy',
		description='Murphy — AI-driven website evaluation',
	)
	parser.add_argument('--url', required=True, help='Target URL to evaluate')
	parser.add_argument('--goal', help="Free-text goal to bias test generation (e.g. 'check if agent creation works')")
	parser.add_argument('--auth', action='store_true', help='Skip auto-detection and go straight to manual login wait')
	parser.add_argument('--no-auth', action='store_true', help='Skip auth detection entirely, treat site as public')
	parser.add_argument('--features', help='Path to existing features markdown (skips analysis, goes to test generation)')
	parser.add_argument('--plan', help='Path to existing YAML test plan (skips analysis + test generation)')
	parser.add_argument('--max-tests', type=int, default=8, help='Max test scenarios (default: 8)')
	parser.add_argument('--model', default='gpt-4o', help='OpenAI model (default: gpt-4o)')
	parser.add_argument('--output-dir', default='./murphy/output', help='Output directory for reports')
	parser.add_argument('--category', help='Site category hint (ecommerce, saas, content, social)')
	parser.add_argument('--ui', action='store_true', help='Launch interactive web UI instead of running in terminal')
	parser.add_argument(
		'--no-highlights', action='store_true', help='Disable bounding boxes on interactive elements in the browser'
	)
	parser.add_argument('--max-steps', type=int, default=30, help='Max agent steps per exploration/execution phase (default: 30)')
	parser.add_argument(
		'--parallel', type=int, default=1, metavar='N',
		help='Number of tests to run concurrently (default: 1, sequential)',
	)
	args = parser.parse_args()

	try:
		asyncio.run(_async_main(args))
		return 0
	except KeyboardInterrupt:
		return 0
	except Exception as e:
		print(f'ERROR: {e}', file=sys.stderr)
		return 1


async def _async_main(args: argparse.Namespace) -> None:
	from browser_use.browser.profile import BrowserProfile
	from browser_use.browser.session import BrowserSession
	from browser_use.llm import ChatOpenAI
	from murphy.evaluate import (
		build_summary,
		execute_tests_with_session,
		explore_and_generate_plan,
		generate_tests,
	)
	from murphy.fixtures import ensure_dummy_fixture_files
	from murphy.models import WebsiteAnalysis
	from murphy.patches import apply as apply_patches
	from murphy.test_plan_io import load_test_plan, save_test_plan

	# Apply patches early (idempotent)
	apply_patches()

	# Ensure dummy fixture files exist for upload testing
	fixture_paths = ensure_dummy_fixture_files()

	llm = ChatOpenAI(model=args.model)
	output_dir = Path(args.output_dir)
	output_dir.mkdir(parents=True, exist_ok=True)

	browser_session: BrowserSession | None = None
	analysis: WebsiteAnalysis | None = None
	authenticated = False

	try:
		# ── Auth detection / login wait ──
		BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
		browser_session = BrowserSession(
			browser_profile=BrowserProfile(
				user_data_dir=BROWSER_PROFILE_DIR,
				keep_alive=True,
				dom_highlight_elements=not args.no_highlights,
			)
		)
		await browser_session.start()

		if args.auth:
			# --auth flag: skip detection, go straight to login wait
			await _wait_for_manual_login(browser_session, llm, args.url)
			authenticated = True
			print('Continuing with authenticated session...\n')
		elif not args.no_auth:
			# Auto-detect: navigate and let the LLM decide
			auth_required = await _detect_auth_required(browser_session, llm, args.url)
			if auth_required:
				await _wait_for_manual_login(browser_session, llm, args.url, already_navigated=True)
				authenticated = True
				print('Continuing with authenticated session...\n')

		# ── Plan generation ──
		use_exploration_first = bool(args.goal and not args.features and not args.plan)

		if args.plan:
			# Skip both analysis and test generation
			plan_path = Path(args.plan)
			assert plan_path.exists(), f'Plan file not found: {plan_path}'
			url, test_plan = load_test_plan(plan_path)
			if url != args.url:
				print(f'WARNING: Plan URL ({url}) differs from --url ({args.url}). Using --url.')
			print(f'Loaded {len(test_plan.scenarios)} scenarios from {plan_path}')
		elif use_exploration_first:
			# Exploration-first path: explore → summarize → synthesize plan
			test_plan = await explore_and_generate_plan(
				task=args.goal,
				url=args.url,
				llm=llm,
				session=browser_session,
				max_scenarios=args.max_tests,
				max_steps=args.max_steps,
			)

			# Save test plan to YAML
			plan_path = save_test_plan(args.url, test_plan, output_dir)
			print(f'\n  Test plan saved: {plan_path}')
			print('  Review and edit the file, then press Enter to continue.')
			print('  (Add, remove, or modify test scenarios as needed.)\n')

			loop = asyncio.get_event_loop()
			await loop.run_in_executor(None, lambda: input('  Press Enter to continue...  '))

			# Re-read in case user edited
			_, test_plan = load_test_plan(plan_path)
			print(f'  Using {len(test_plan.scenarios)} test scenarios.\n')
		else:
			if args.features:
				# Load features from existing file
				features_path = Path(args.features)
				assert features_path.exists(), f'Features file not found: {features_path}'
				analysis = _read_features_markdown(features_path)
				print(f'Loaded {len(analysis.features)} features from {features_path}')
			else:
				# Run analysis agent (feature-discovery path)
				analysis = await _analyze_with_session(args.url, llm, browser_session, goal=args.goal)

				# Save features markdown
				features_path = _write_features_markdown(analysis, output_dir)
				print(f'\n  Features saved: {features_path}')
				print('  Review and edit the file, then press Enter to continue.')
				print('  (Add, remove, or modify features as needed.)\n')

				loop = asyncio.get_event_loop()
				await loop.run_in_executor(None, lambda: input('  Press Enter to continue...  '))

				# Re-read in case user edited
				analysis = _read_features_markdown(features_path)
				print(f'  Using {len(analysis.features)} features for test generation.\n')

			# ── Phase 2: Generate tests ──
			test_plan = await generate_tests(args.url, analysis, llm, args.max_tests, goal=args.goal)

			# Save test plan to YAML
			plan_path = save_test_plan(args.url, test_plan, output_dir)
			print(f'\n  Test plan saved: {plan_path}')
			print('  Review and edit the file, then press Enter to continue.')
			print('  (Add, remove, or modify test scenarios as needed.)\n')

			loop = asyncio.get_event_loop()
			await loop.run_in_executor(None, lambda: input('  Press Enter to continue...  '))

			# Re-read in case user edited
			_, test_plan = load_test_plan(plan_path)
			print(f'  Using {len(test_plan.scenarios)} test scenarios.\n')

		# Ensure analysis exists for report writing (--goal and --plan paths skip feature discovery)
		if analysis is None:
			analysis = WebsiteAnalysis(
				site_name=args.url,
				category='unknown',
				description=args.goal or 'Loaded from plan file',
				key_pages=[],
				features=[],
				identified_user_flows=[],
			)

		# ── Phase 3: Execute ──
		def _on_test_complete(results: list['TestResult']) -> None:
			if analysis:
				_write_reports_and_print(args.url, analysis, results, output_dir)

		if not args.ui:
			results = await execute_tests_with_session(
				args.url,
				test_plan,
				llm,
				browser_session,
				goal=args.goal,
				fixture_paths=fixture_paths,
				max_steps=args.max_steps,
				save_callback=_on_test_complete,
				max_concurrent=args.parallel,
			)
			if analysis:
				_write_reports_and_print(args.url, analysis, results, output_dir)
			else:
				_print_results_summary(results)
			return

		# ── Server UI mode (--ui) ──
		from murphy.server import ServerState, start_server

		_browser_session = browser_session  # capture for closure

		async def _execute_fn(plan: TestPlan, state: 'ServerState') -> list[TestResult]:
			return await execute_tests_with_session(
				args.url,
				plan,
				llm,
				_browser_session,
				progress_state=state,
				goal=args.goal,
				fixture_paths=fixture_paths,
				max_steps=args.max_steps,
				save_callback=_on_test_complete,
			)

		state = ServerState(
			url=args.url,
			analysis=analysis,
			test_plan=test_plan,
			execute_fn=_execute_fn,
		)
		state.build_summary_fn = build_summary

		runner, port = await start_server(state)

		print('  Press Ctrl+C to stop the server.\n')
		try:
			while True:
				await asyncio.sleep(1)
				if state.done and state.results and not getattr(state, '_reports_written', False):
					if analysis:
						_write_reports_and_print(args.url, analysis, state.results, output_dir)
					else:
						_print_results_summary(state.results)
					state._reports_written = True  # type: ignore[attr-defined]
		except KeyboardInterrupt:
			pass
		finally:
			await runner.cleanup()

	finally:
		if browser_session:
			await browser_session.kill()


# ─── Auth helpers ─────────────────────────────────────────────────────────────


async def _detect_auth_required(browser_session: 'BrowserSession', llm: 'ChatOpenAI', url: str) -> bool:
	"""Navigate to URL and use a passive LLM call to detect if login is required."""
	print(f'\n{"=" * 60}')
	print(f'Checking if {url} requires login...')
	print(f'{"=" * 60}\n')

	await browser_session.navigate_to(url)
	await asyncio.sleep(2)  # let the page settle

	current_url, title, body = await _get_page_text(browser_session)
	is_content = await _llm_classify_page(llm, current_url, title, body, mode='auth_detect')
	auth_required = not is_content

	if auth_required:
		print('Login gate detected — authentication required.')
	else:
		print('Public/usable content detected — no login needed.')

	return auth_required


async def _get_page_text(browser_session: 'BrowserSession') -> tuple[str, str, str]:
	"""Read page title, URL, and truncated body text via CDP — completely passive, no side effects."""
	try:
		current_url = await browser_session.get_current_page_url()
	except Exception:
		current_url = ''

	cdp_session = await browser_session.get_or_create_cdp_session()
	try:
		result = await cdp_session.cdp_client.send.Runtime.evaluate(
			params={
				'expression': 'document.title + "\\n" + document.body.innerText.substring(0, 2000)',
				'returnByValue': True,
			},
			session_id=cdp_session.session_id,
		)
		text = result.get('result', {}).get('value', '') if result else ''
	except Exception:
		text = ''

	title = text.split('\n', 1)[0] if text else ''
	body = text.split('\n', 1)[1] if '\n' in text else ''
	return current_url, title, body


async def _llm_classify_page(llm: 'ChatOpenAI', url: str, title: str, body: str, *, mode: str = 'auth_detect') -> bool:
	"""Use a single LLM call (no agent) to classify page content.

	Returns True if the page looks like authenticated/usable content.
	Returns False if it looks like a login gate.
	"""
	from browser_use.llm.messages import UserMessage

	prompt = (
		f'You are classifying a web page. Current URL: {url}\nPage title: {title}\n\nPage text (first 2000 chars):\n{body}\n\n'
	)

	if mode == 'auth_detect':
		prompt += (
			'Question: Is this a login/sign-in page, welcome gate, or SSO redirect that blocks '
			'access to the main content? Or is this usable content (dashboard, app, articles, '
			'marketing site, product page, documentation)?\n\n'
			'Reply with exactly one word: LOGIN or CONTENT'
		)
	else:  # mode == "login_poll"
		prompt += (
			'Question: Has the user successfully logged in? Is this authenticated content '
			'(dashboard, app UI, user profile, main application) or is it still a login form, '
			'sign-in page, SSO flow, 2FA prompt, or pre-login screen?\n\n'
			'Reply with exactly one word: AUTHENTICATED or LOGIN'
		)

	response = await llm.ainvoke([UserMessage(content=prompt)])
	answer = response.completion.strip().upper() if isinstance(response.completion, str) else ''

	if mode == 'auth_detect':
		return 'CONTENT' in answer
	else:
		return 'AUTHENTICATED' in answer


async def _wait_for_manual_login(
	browser_session: 'BrowserSession',
	llm: 'ChatOpenAI',
	url: str,
	*,
	already_navigated: bool = False,
) -> None:
	"""Wait for the user to log in manually, then wait for explicit confirmation to proceed."""
	print(f'\n{"=" * 60}')
	print('Phase 0: Manual login')
	print(f'{"=" * 60}\n')

	if not already_navigated:
		await browser_session.navigate_to(url)

	print('>>> Log in manually in the browser window.')
	print(">>> When you're done, press Enter or type 'continue' to proceed.\n")

	# Block on user input — run in executor so asyncio loop isn't blocked
	loop = asyncio.get_event_loop()
	await loop.run_in_executor(None, lambda: input('  Press Enter to continue...  '))


async def _analyze_with_session(
	url: str,
	llm: 'ChatOpenAI',
	browser_session: 'BrowserSession',
	goal: str | None = None,
) -> 'WebsiteAnalysis':
	"""Phase 1 analysis reusing an authenticated browser session."""
	from browser_use import Agent
	from murphy.models import WebsiteAnalysis

	print(f'\n{"=" * 60}')
	print(f'Phase 1: Analyzing {url}')
	print(f'{"=" * 60}\n')

	goal_block = ''
	if goal:
		goal_block = (
			f'\nGOAL: Focus your exploration on: {goal}\n'
			f'- Still explore the full site, but pay extra attention to pages/features related to this goal.\n'
			f"- Mark features related to the goal as 'core' importance.\n\n"
		)

	agent = Agent(
		task=(
			f'You are already logged in to {url}. Discover what users can DO on this site.\n\n'
			f'{goal_block}'
			f'EXPLORATION (this is the most important part — be thorough):\n'
			f'- Look at the sidebar/top navigation and click EVERY major nav item (e.g. Dashboard, Agents, Tasks, Connectors, Reports, Admin, Profile, Conversations, Settings — whatever exists)\n'
			f'- Do NOT stop after 1-2 pages. You must visit every distinct section in the navigation.\n'
			f'- On each page, note what actions a user can perform (not just what elements exist)\n'
			f'- If you see a list/table, click an item to see the detail view\n'
			f'- Check user profile/settings pages too — those often have important features\n'
			f"- IMPORTANT: This is READ-ONLY exploration. Do NOT click 'Delete', 'Place Order', or any button that would permanently destroy data or cost money. You MAY click 'Create', 'Submit', 'Send', 'Save' to explore forms and creation flows — just don't confirm irreversible actions.\n"
			f'- IMPORTANT: Stay on the same domain as {url}. Do NOT follow links to external sites (e.g. social media, third-party docs, partner sites). If a link goes to a different domain, note the feature but do not navigate there.\n'
			f'- URL DISCIPLINE: Do NOT infer or guess deep-link URLs. Prefer clicking visible navigation controls to reach pages. For `page_url`, record only URLs you actually navigated to — never synthesize paths like "/spaces/agents/create" unless that exact URL appeared in the browser address bar.\n'
			f'- For each page, classify the page_type (homepage, landing, product, listing, detail, form, content, dashboard, auth, error, other)\n\n'
			f'FEATURE IDENTIFICATION:\n'
			f"- You should find at least 8-15 features for any non-trivial app. If you have fewer than 8, you haven't explored enough — go back and click more nav items.\n"
			f"- Name each feature as a user action: 'Create AI agent', 'Search tasks', 'Upload document' — NOT 'Navigation Links' or 'Button group'\n"
			f"- A feature = one thing a user can accomplish. If it takes multiple steps, that's still one feature.\n"
			f"- For `elements`, write brief descriptions: 'Create button on agents page', 'Task name input' — NOT raw hrefs or DOM dumps\n"
			f'- For `page_url`, use the page where the feature is primarily accessed\n'
			f"- Skip generic navigation (header links, footer links, breadcrumbs) — those aren't features\n"
			f'- Skip auth-related elements (login/logout buttons)\n'
			f'- Category: navigation, search, forms, content_display, filtering_sorting, media, authentication, ecommerce, social, other\n'
			f'- Assess testability: can an authenticated browser test this? (testable / partial / untestable). If not fully testable, explain why (third-party redirect, CAPTCHA, etc.)\n\n'
			f'IMPORTANCE:\n'
			f'- core: primary product functionality (the reason the site exists)\n'
			f'- secondary: useful but not the main purpose\n'
			f'- peripheral: only if truly notable (skip otherwise)\n\n'
			f'USER FLOWS:\n'
			f"- Identify 3-5 multi-step journeys: e.g. 'Create agent → configure settings → deploy'\n"
			f'- Each flow should describe a complete user goal, not a single click\n'
		),
		llm=llm,
		browser_session=browser_session,
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


# ─── Reporting helpers ────────────────────────────────────────────────────────


def _write_features_markdown(analysis: 'WebsiteAnalysis', output_dir: Path) -> Path:
	"""Write a clean markdown file listing all discovered features."""
	from urllib.parse import urlparse

	domain = urlparse(analysis.key_pages[0].url).netloc if analysis.key_pages else analysis.site_name
	slug = domain.replace('.', '_').replace(':', '_')
	path = output_dir / f'{slug}_features.md'

	lines: list[str] = []
	lines.append(f'# {analysis.site_name}')
	lines.append(f'**Category:** {analysis.category}  ')
	lines.append(f'**Description:** {analysis.description}\n')

	# ── Pages ──
	lines.append('## Pages discovered\n')
	lines.append('| Page | Type | Purpose |')
	lines.append('|------|------|---------|')
	for page in analysis.key_pages:
		lines.append(f'| [{page.title}]({page.url}) | `{page.page_type}` | {page.purpose} |')

	# ── Features by importance ──
	lines.append('\n## Features\n')
	for importance in ('core', 'secondary', 'peripheral'):
		features = [f for f in analysis.features if f.importance == importance]
		if not features:
			continue
		lines.append(f'### {importance.capitalize()}\n')
		for feat in features:
			testability_badge = {'testable': 'testable', 'partial': 'partial', 'untestable': 'untestable'}[feat.testability]
			lines.append(f'- **{feat.name}** (`{feat.category}`, {testability_badge})')
			lines.append(f'  {feat.description}')
			if feat.elements:
				lines.append(f'  Elements: {", ".join(feat.elements)}')
			if feat.testability_reason:
				lines.append(f'  _{feat.testability_reason}_')
			lines.append(f'  Page: {feat.page_url}\n')

	# ── User flows ──
	if analysis.identified_user_flows:
		lines.append('## Identified user flows\n')
		for flow in analysis.identified_user_flows:
			lines.append(f'1. {flow}')

	path.write_text('\n'.join(lines) + '\n')
	return path


def _read_features_markdown(path: Path) -> 'WebsiteAnalysis':
	"""Parse a features markdown file back into a WebsiteAnalysis."""
	import re

	from murphy.models import Feature, PageInfo, WebsiteAnalysis

	text = path.read_text()
	lines = text.split('\n')

	# ── Header ──
	site_name = ''
	category = ''
	description = ''
	for line in lines:
		if line.startswith('# ') and not line.startswith('## '):
			site_name = line[2:].strip()
		elif line.startswith('**Category:**'):
			category = line.replace('**Category:**', '').strip().rstrip('  ')
		elif line.startswith('**Description:**'):
			description = line.replace('**Description:**', '').strip()

	# ── Pages table ──
	key_pages: list[PageInfo] = []
	in_pages_table = False
	for line in lines:
		if line.startswith('## Pages discovered'):
			in_pages_table = True
			continue
		if in_pages_table and line.startswith('## '):
			break
		if in_pages_table and line.startswith('|') and not line.startswith('|---') and not line.startswith('| Page'):
			# | [Title](url) | `type` | Purpose |
			cells = [c.strip() for c in line.split('|')[1:-1]]
			if len(cells) >= 3:
				link_match = re.match(r'\[(.+?)\]\((.+?)\)', cells[0])
				title = link_match.group(1) if link_match else cells[0]
				url = link_match.group(2) if link_match else ''
				page_type = cells[1].strip('`').strip()
				purpose = cells[2]
				# Validate page_type, fall back to 'other'
				valid_types = (
					'homepage',
					'landing',
					'product',
					'listing',
					'detail',
					'form',
					'content',
					'dashboard',
					'auth',
					'error',
					'other',
				)
				if page_type not in valid_types:
					page_type = 'other'
				key_pages.append(
					PageInfo(
						url=url,
						title=title,
						purpose=purpose,
						page_type=page_type,
						interactive_elements=[],  # type: ignore[arg-type]
					)
				)

	# ── Features ──
	features: list[Feature] = []
	current_importance: str = 'core'
	i = 0
	while i < len(lines):
		line = lines[i]

		# Track importance sections
		if line.startswith('### Core'):
			current_importance = 'core'
		elif line.startswith('### Secondary'):
			current_importance = 'secondary'
		elif line.startswith('### Peripheral'):
			current_importance = 'peripheral'

		# Feature entry: - **Name** (`category`, testability)
		feat_match = re.match(r'^- \*\*(.+?)\*\* \(`(.+?)`,\s*(testable|partial|untestable)\)', line)
		if feat_match:
			name = feat_match.group(1)
			feat_category = feat_match.group(2)
			testability = feat_match.group(3)

			# Valid categories
			valid_cats = (
				'navigation',
				'search',
				'forms',
				'content_display',
				'filtering_sorting',
				'media',
				'authentication',
				'ecommerce',
				'social',
				'other',
			)
			if feat_category not in valid_cats:
				feat_category = 'other'

			feat_description = ''
			elements: list[str] = []
			testability_reason: str | None = None
			page_url = ''

			# Read continuation lines (indented with 2 spaces)
			j = i + 1
			while j < len(lines) and lines[j].startswith('  ') and not lines[j].startswith('- **'):
				cont = lines[j].strip()
				if cont.startswith('Elements:'):
					elements = [e.strip() for e in cont[len('Elements:') :].split(',')]
				elif cont.startswith('Page:'):
					page_url = cont[len('Page:') :].strip()
				elif cont.startswith('_') and cont.endswith('_'):
					testability_reason = cont.strip('_')
				elif cont and not feat_description:
					feat_description = cont
				j += 1

			features.append(
				Feature(
					name=name,
					category=feat_category,  # type: ignore[arg-type]
					description=feat_description,
					page_url=page_url,
					elements=elements,
					testability=testability,  # type: ignore[arg-type]
					testability_reason=testability_reason,
					importance=current_importance,  # type: ignore[arg-type]
				)
			)
			i = j
			continue

		i += 1

	# ── User flows ──
	user_flows: list[str] = []
	in_flows = False
	for line in lines:
		if line.startswith('## Identified user flows'):
			in_flows = True
			continue
		if in_flows and line.startswith('## '):
			break
		if in_flows and re.match(r'^\d+\.\s+', line):
			user_flows.append(re.sub(r'^\d+\.\s+', '', line).strip())

	return WebsiteAnalysis(
		site_name=site_name,
		category=category,
		description=description,
		key_pages=key_pages,
		features=features,
		identified_user_flows=user_flows,
	)


def _write_reports_and_print(
	url: str,
	analysis: 'WebsiteAnalysis',
	results: list['TestResult'],
	output_dir: Path,
) -> None:
	from murphy.evaluate import build_summary
	from murphy.report import write_full_report

	json_path, md_path = write_full_report(url, analysis, results, output_dir)
	summary = build_summary(results)

	print(f'\n{"=" * 60}')
	print('Evaluation Complete')
	print(f'{"=" * 60}')
	print(f'\n  Pass rate: {summary.pass_rate}% ({summary.passed}/{summary.total})')
	print(f'  JSON report: {json_path}')
	print(f'  Markdown report: {md_path}')


def _print_results_summary(results: list['TestResult']) -> None:
	from murphy.evaluate import build_summary

	summary = build_summary(results)
	print(f'\n{"=" * 60}')
	print('Evaluation Complete')
	print(f'{"=" * 60}')
	print(f'\n  Pass rate: {summary.pass_rate}% ({summary.passed}/{summary.total})')


if __name__ == '__main__':
	sys.exit(main())
