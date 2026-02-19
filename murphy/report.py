"""Report generation — JSON and Markdown output."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from murphy.models import EvaluationReport, TestResult


def write_json_report(report: EvaluationReport, output_dir: Path) -> Path:
	path = output_dir / 'evaluation_report.json'
	path.write_text(report.model_dump_json(indent=2))
	return path


# ─── Action metrics ──────────────────────────────────────────────────────────


@dataclass
class ActionMetrics:
	clicks: int = 0
	navigations: int = 0
	text_inputs: int = 0
	scrolls: int = 0
	pages_visited: list[str] = field(default_factory=list)
	total_actions: int = 0

	@property
	def unique_pages(self) -> int:
		return len(set(self.pages_visited))


def _compute_metrics(result: TestResult) -> ActionMetrics:
	"""Count clicks, navigations, text inputs, scrolls, and pages visited."""
	m = ActionMetrics()
	for action in result.actions:
		if not isinstance(action, dict):
			continue
		m.total_actions += 1
		if 'click' in action:
			m.clicks += 1
		if 'navigate' in action:
			m.navigations += 1
			url = action['navigate'].get('url', '')
			if url:
				m.pages_visited.append(url)
		if 'input_text' in action:
			m.text_inputs += 1
		if 'scroll' in action:
			m.scrolls += 1
		if 'go_to_url' in action:
			m.navigations += 1
			url = action['go_to_url'].get('url', '')
			if url:
				m.pages_visited.append(url)
	return m


def _format_path(result: TestResult) -> str:
	"""Extract a concise user-readable path from the actions list.

	e.g. "Homepage → click 'About us' → click 'Ecosystems' → Portfolio"
	"""
	steps: list[str] = []
	for action in result.actions:
		if not isinstance(action, dict):
			continue
		if 'navigate' in action or 'go_to_url' in action:
			nav = action.get('navigate') or action.get('go_to_url') or {}
			url = nav.get('url', '')
			label = url.rstrip('/').split('/')[-1] or 'Homepage'
			steps.append(f'navigate → {label}')
		elif 'click' in action:
			el = action.get('interacted_element')
			if el and isinstance(el, dict):
				name = el.get('ax_name', '')
				name = name.replace('Link to', '').replace('page', '').replace('\n', ' ').strip()
				if name:
					steps.append(f'click "{name}"')
		elif 'input_text' in action:
			text = action['input_text'].get('text', '')
			preview = text[:20] + '...' if len(text) > 20 else text
			steps.append(f'type "{preview}"')
		elif 'scroll' in action:
			direction = action['scroll'].get('direction', 'down')
			steps.append(f'scroll {direction}')
	return ' → '.join(steps) if steps else 'No path recorded'


def _format_metrics_line(m: ActionMetrics) -> str:
	"""Single-line summary of action metrics."""
	parts = []
	if m.clicks:
		parts.append(f'{m.clicks} click{"s" if m.clicks != 1 else ""}')
	if m.navigations:
		parts.append(f'{m.navigations} navigation{"s" if m.navigations != 1 else ""}')
	if m.text_inputs:
		parts.append(f'{m.text_inputs} text input{"s" if m.text_inputs != 1 else ""}')
	if m.scrolls:
		parts.append(f'{m.scrolls} scroll{"s" if m.scrolls != 1 else ""}')
	if m.unique_pages:
		parts.append(f'{m.unique_pages} unique page{"s" if m.unique_pages != 1 else ""}')
	return ', '.join(parts) if parts else 'No actions recorded'


def _render_test_detail(r: TestResult, index: int, lines: list[str]) -> None:
	"""Append detailed info for a single test result (pass or fail)."""
	m = _compute_metrics(r)
	passed = r.success

	lines.append(f'**Result:** {"Passed" if passed else "Failed"} in {r.duration:.0f}s')
	lines.append('')
	lines.append(f'**Metrics:** {_format_metrics_line(m)}')
	lines.append('')
	lines.append(f'**Path followed:**')
	lines.append(f'{_format_path(r)}')
	lines.append('')

	if not passed:
		failure_reason = ''
		judge_reasoning = ''
		if r.judgement:
			failure_reason = r.judgement.get('failure_reason', '')
			judge_reasoning = r.judgement.get('reasoning', '')

		if failure_reason:
			lines += [
				'**Why it failed:**',
				f'{failure_reason}',
				'',
			]

		if judge_reasoning and judge_reasoning != failure_reason:
			lines += [
				'**Details:**',
				f'{judge_reasoning}',
				'',
			]

		suggestion = _suggest_fix(r)
		if suggestion:
			lines += [
				'**Suggested fix:**',
				f'{suggestion}',
				'',
			]


def write_markdown_report(report: EvaluationReport, output_dir: Path) -> Path:
	path = output_dir / 'evaluation_report.md'
	s = report.summary
	a = report.analysis

	lines = [
		f'# Evaluation Report: {a.site_name}',
		'',
		f'> **{a.description}**',
		'',
		'| | |',
		'|---|---|',
		f'| URL | {report.url} |',
		f'| Category | {a.category} |',
		f'| Date | {report.timestamp[:10]} |',
		f'| Pages Discovered | {", ".join(p.title for p in a.key_pages)} |',
		'',
		'---',
		'',
		'## Results at a Glance',
		'',
	]

	# Partition results
	website_issues = [r for r in report.results if r.failure_category == 'website_issue']
	test_limitations = [r for r in report.results if r.failure_category == 'test_limitation']
	passed_tests = [r for r in report.results if r.success]

	# Scorecard
	rate_str = f'{s.pass_rate}%'
	lines += [
		f'**{s.passed}/{s.total} tests passed ({rate_str})**',
		f'- Website Issues: {s.website_issues}',
		f'- Test Limitations: {s.test_limitations}',
		'',
		'| Test | Persona | Priority | Result | Category | Duration |',
		'|------|---------|----------|--------|----------|----------|',
	]
	for r in report.results:
		persona_label = r.scenario.test_persona.replace('_', ' ').title()
		if r.success:
			emoji = '\u2705'
			result_str = 'Passed'
			category_str = ''
		elif r.failure_category == 'website_issue':
			emoji = '\U0001f534'
			result_str = 'Failed'
			category_str = 'Website Issue'
		else:
			emoji = '\u26a0\ufe0f'
			result_str = 'Failed'
			category_str = 'Test Limitation'
		lines.append(
			f'| {emoji} {r.scenario.name} | {persona_label} | {r.scenario.priority} | '
			f'{result_str} | {category_str} | {r.duration:.0f}s |'
		)

	# Per-priority breakdown if there are multiple priorities
	priorities_present = list(s.by_priority.keys())
	if len(priorities_present) > 1:
		lines += [
			'',
			'### By Priority',
			'',
			'| Priority | Passed | Failed |',
			'|----------|--------|--------|',
		]
		for priority in ['critical', 'high', 'medium', 'low']:
			if priority in s.by_priority:
				d = s.by_priority[priority]
				lines.append(f'| {priority.capitalize()} | {d["passed"]} | {d["failed"]} |')

	# Per-persona breakdown
	persona_stats: dict[str, dict[str, int]] = {}
	for r in report.results:
		p = r.scenario.test_persona
		if p not in persona_stats:
			persona_stats[p] = {'passed': 0, 'failed': 0}
		if r.success:
			persona_stats[p]['passed'] += 1
		else:
			persona_stats[p]['failed'] += 1

	if len(persona_stats) > 1:
		lines += [
			'',
			'### By Persona',
			'',
			'| Persona | Passed | Failed |',
			'|---------|--------|--------|',
		]
		for persona in ['happy_path', 'confused_novice', 'adversarial', 'edge_case', 'explorer', 'impatient_user', 'angry_user']:
			if persona in persona_stats:
				d = persona_stats[persona]
				label = persona.replace('_', ' ').title()
				lines.append(f'| {label} | {d["passed"]} | {d["failed"]} |')

	lines += ['', '---', '']

	# ── Website Issues section ────────────────────────────────────────────────
	if website_issues:
		lines += ['## Website Issues', '']
		for i, r in enumerate(website_issues, 1):
			persona_label = r.scenario.test_persona.replace('_', ' ').title()
			lines += [
				f'### {i}. \U0001f534 {r.scenario.name}',
				'',
				f'**Persona:** {persona_label}',
				'',
				f'**What was tested:** {r.scenario.description}',
				'',
			]
			_render_test_detail(r, i, lines)
			lines += ['---', '']

	# ── Test Limitations section ──────────────────────────────────────────────
	if test_limitations:
		lines += ['## Test Limitations', '']
		for i, r in enumerate(test_limitations, 1):
			persona_label = r.scenario.test_persona.replace('_', ' ').title()
			lines += [
				f'### {i}. \u26a0\ufe0f {r.scenario.name}',
				'',
				f'**Persona:** {persona_label}',
				'',
				f'**What was tested:** {r.scenario.description}',
				'',
			]
			_render_test_detail(r, i, lines)
			lines += ['---', '']

	# ── Passed Tests section ──────────────────────────────────────────────────
	if passed_tests:
		lines += ['## Passed Tests', '']
		for i, r in enumerate(passed_tests, 1):
			persona_label = r.scenario.test_persona.replace('_', ' ').title()
			lines += [
				f'### {i}. \u2705 {r.scenario.name}',
				'',
				f'**Persona:** {persona_label}',
				'',
				f'**What was tested:** {r.scenario.description}',
				'',
			]
			_render_test_detail(r, i, lines)
			lines += ['---', '']

	# Features discovered
	if a.features:
		lines += [
			'## Features Discovered',
			'',
			'| Feature | Category | Importance | Testability | Reason |',
			'|---------|----------|------------|-------------|--------|',
		]
		for f in a.features:
			testability_icon = {'testable': '\u2705', 'partial': '\u26a0\ufe0f', 'untestable': '\u26d4'}[f.testability]
			reason = f.testability_reason or ''
			lines.append(
				f'| {f.name} | {f.category} | {f.importance} | '
				f'{testability_icon} {f.testability} | {reason} |'
			)
		lines.append('')

	# User flows discovered (context)
	if a.identified_user_flows:
		lines += [
			'## User Flows Discovered',
			'',
			'These are the user journeys identified on the website:',
			'',
		]
		for flow in a.identified_user_flows:
			lines.append(f'- {flow}')
		lines.append('')

	path.write_text('\n'.join(lines))
	return path


def _suggest_fix(result: TestResult) -> str:
	"""Generate an actionable suggestion based on the failure context."""
	judgement = result.judgement or {}
	failure_reason = judgement.get('failure_reason', '').lower()
	reasoning = judgement.get('reasoning', '').lower()
	scenario = result.scenario

	# Captcha blocked
	if judgement.get('reached_captcha'):
		return (
			'The test was blocked by a CAPTCHA. This is expected for automated testing. '
			'Consider whitelisting the test environment or using a CAPTCHA-solving service.'
		)

	# Impossible task
	if judgement.get('impossible_task'):
		return (
			'This test scenario may not be possible on the current version of the website. '
			'Review whether the feature being tested actually exists and is accessible.'
		)

	# Verification / evidence issues
	if 'verify' in failure_reason or 'evidence' in failure_reason or 'confirm' in failure_reason:
		return (
			'The actions were performed but the test could not confirm the expected outcome. '
			'This often means the page loaded correctly but the success criteria were too strict '
			'or the page content didn\'t explicitly match what was expected. '
			'Try making the success criteria more specific (e.g., "page title contains X") '
			'or check if the page content has changed.'
		)

	# Navigation failures
	if 'navigate' in failure_reason or 'load' in failure_reason or 'url' in failure_reason:
		return (
			'A page failed to load or navigated to an unexpected URL. '
			'Check that the target pages exist, aren\'t behind authentication, '
			'and don\'t redirect unexpectedly.'
		)

	# Element not found
	if 'element' in failure_reason or 'click' in failure_reason or 'not found' in failure_reason:
		return (
			'An interactive element could not be found or clicked. '
			'The page layout may have changed, or the element may load dynamically. '
			'Check if the element is visible without scrolling and isn\'t behind a popup or overlay.'
		)

	# Timeout
	if 'timeout' in failure_reason or 'time' in reasoning:
		return (
			'The test took too long to complete. This could indicate slow page loads, '
			'heavy JavaScript, or the agent getting stuck in a loop. '
			'Check page performance and ensure key content loads within a few seconds.'
		)

	# Generic fallback
	if failure_reason:
		return (
			'Review the failure reason above. If the website content has changed recently, '
			'the test expectations may need updating. Re-running the evaluation can also help '
			'rule out transient issues.'
		)

	return ''
