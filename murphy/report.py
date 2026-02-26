"""Report generation — JSON and Markdown output."""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from murphy.models import EvaluationReport, ExecutiveSummary, TestResult, WebsiteAnalysis


def copy_screenshots_to_output(report: EvaluationReport, output_dir: Path) -> None:
	"""Copy test screenshots to a stable output directory, organized by test.

	Idempotent: skips results whose screenshots already live inside the output dir
	(happens when save_callback invokes this incrementally after each test).
	"""
	screenshots_dir = output_dir / 'screenshots'
	screenshots_dir_resolved = screenshots_dir.resolve()
	for i, result in enumerate(report.results, 1):
		if not result.screenshot_paths:
			continue
		# Filter out None entries up front (screenshot_paths is list[str | None])
		valid_paths = [p for p in result.screenshot_paths if p]
		if not valid_paths:
			continue
		# Already copied on a previous incremental call — skip
		if all(
			str(Path(p).resolve()).startswith(str(screenshots_dir_resolved))
			for p in valid_paths
		):
			continue
		test_dir = screenshots_dir / f'test_{i:02d}_{_slugify(result.scenario.name)}'
		test_dir.mkdir(parents=True, exist_ok=True)
		for src_path_str in valid_paths:
			src = Path(src_path_str).resolve()
			dst = (test_dir / Path(src_path_str).name).resolve()
			if src.exists() and src != dst:
				shutil.copy2(src, dst)
		# Update paths to point to copied location
		result.screenshot_paths = [
			str(test_dir / Path(p).name)
			for p in valid_paths
			if Path(p).exists()
		]


def _slugify(name: str) -> str:
	"""Convert a test name to a filesystem-safe slug."""
	return name.lower().replace(' ', '_').replace("'", '')[:50]


def write_json_report(report: EvaluationReport, output_dir: Path) -> Path:
	path = output_dir / 'evaluation_report.json'
	path.write_text(report.model_dump_json(indent=2))
	return path


def write_full_report(
	url: str,
	analysis: WebsiteAnalysis,
	results: list[TestResult],
	output_dir: Path,
	executive_summary: ExecutiveSummary | None = None,
) -> tuple[Path, Path]:
	"""Copy screenshots + write JSON + write Markdown. Returns (json_path, md_path)."""
	from murphy.evaluate import build_summary

	summary = build_summary(results)
	report = EvaluationReport(
		url=url,
		timestamp=datetime.now(timezone.utc).isoformat(),
		analysis=analysis,
		results=results,
		summary=summary,
		executive_summary=executive_summary,
	)

	copy_screenshots_to_output(report, output_dir)
	json_path = write_json_report(report, output_dir)
	md_path = write_markdown_report(report, output_dir)
	return json_path, md_path


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


def _form_field_label(fill: dict) -> str:
	"""Build a human-readable label for a form field from available metadata."""
	# Try accessible name first
	if fill.get('field_name'):
		return fill['field_name']
	# aria-label
	if fill.get('aria_label'):
		return fill['aria_label']
	# placeholder text
	if fill.get('placeholder'):
		return fill['placeholder']
	# HTML name attribute
	if fill.get('name_attr'):
		return fill['name_attr']
	# Construct from tag + type: e.g. "<input type="email">"
	tag = fill.get('tag', '')
	type_attr = fill.get('type_attr', '')
	if tag:
		if type_attr:
			return f'<{tag} type="{type_attr}">'
		return f'<{tag}>'
	# Role-based fallback
	if fill.get('role'):
		return fill['role']
	# Last resort
	return f'element #{fill.get("index", "?")}'


def _render_test_detail(r: TestResult, index: int, lines: list[str]) -> None:
	"""Append detailed info for a single test result (pass or fail)."""
	m = _compute_metrics(r)
	passed = r.success

	lines.append(f'**Result:** {"Passed" if passed else "Failed"} in {r.duration:.0f}s')
	lines.append('')
	lines.append(f'**Metrics:** {_format_metrics_line(m)}')
	lines.append('')
	lines.append('**Path followed:**')
	lines.append(f'{_format_path(r)}')
	lines.append('')

	# ── Form fills ──
	if r.form_fills:
		lines += ['**Form data entered:**']
		for fill in r.form_fills:
			field_label = _form_field_label(fill)
			text = fill.get('text', '')
			preview = text[:80] + '...' if len(text) > 80 else text
			lines.append(f'- **{field_label}**: `{preview}`')
		lines.append('')

	# ── Screenshots ──
	if r.screenshot_paths:
		lines += ['**Screenshots:**']
		# Show first, last, and any mid-point screenshots
		total = len(r.screenshot_paths)
		key_indices = {0, total // 2, total - 1} if total > 3 else set(range(total))
		for idx in sorted(key_indices):
			path = r.screenshot_paths[idx]
			lines.append(f'- Step {idx + 1}/{total}: {Path(path).name}')
		if total > 3:
			lines.append(f'- _{total - len(key_indices)} more screenshots available in output directory_')
		lines.append('')

	# ── Validation evidence ──
	validation_evidence = getattr(r, 'validation_evidence', '') or ''
	if validation_evidence:
		lines += ['**Validation Performed:**', f'{validation_evidence}', '']
	else:
		lines += ['**Validation Performed:**', 'No explicit validation evidence recorded.', '']

	# ── Evaluation dimensions ──
	if r.process_evaluation:
		lines += ['**Process evaluation:**', f'{r.process_evaluation}', '']
	if r.logical_evaluation:
		lines += ['**Logical evaluation:**', f'{r.logical_evaluation}', '']
	if r.usability_evaluation:
		lines += ['**Usability evaluation:**', f'{r.usability_evaluation}', '']

	# ── Pages visited ──
	if r.pages_visited:
		lines += ['**Pages visited:**']
		for page_url in r.pages_visited:
			lines.append(f'- {page_url}')
		lines.append('')

	if not passed:
		failure_reason = r.reason or ''
		judge_reasoning = ''
		if r.judgement:
			if not failure_reason:
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
		f'| Pages Discovered | {", ".join(p.title for p in a.key_pages) or "None identified"} |',
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

	# ── Executive Summary ─────────────────────────────────────────────────────
	if report.executive_summary:
		es = report.executive_summary
		lines += [
			'## Executive Summary',
			'',
			f'{es.overall_assessment}',
			'',
			'### Key Findings',
			'',
		]
		for i, finding in enumerate(es.key_findings, 1):
			lines.append(f'{i}. {finding}')
		lines += [
			'',
			'### Recommended Actions',
			'',
		]
		for i, action in enumerate(es.recommended_actions, 1):
			lines.append(f'{i}. {action}')
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
			lines.append(f'| {f.name} | {f.category} | {f.importance} | {testability_icon} {f.testability} | {reason} |')
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
	"""Generate an actionable suggestion based on the failure context and persona."""
	judgement = result.judgement or {}
	failure_reason = judgement.get('failure_reason', '').lower()
	failure_reason_raw = judgement.get('failure_reason', '')
	reasoning = judgement.get('reasoning', '').lower()
	scenario = result.scenario
	persona = scenario.test_persona

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

	# Persona-specific suggestions for adversarial / edge_case / angry_user
	if persona in ('adversarial', 'edge_case', 'angry_user'):
		# Check if the site actually handled it fine but the test expected explicit feedback
		silent_handling_signals = [
			'no error', 'no explicit', 'no visible', 'no message', 'accepted',
			'no validation', 'did not show', 'without showing', 'no indication',
			'silently', 'no feedback',
		]
		if any(signal in failure_reason or signal in reasoning for signal in silent_handling_signals):
			return (
				f'The site accepted the {persona.replace("_", " ")} input without crashing or exposing errors, '
				f'which may actually be correct behavior (silent sanitization). '
				f'Consider whether the success criteria should treat silent handling as a pass. '
				f'Specific observation: {failure_reason_raw}'
			)
		# Site actually broke
		crash_signals = ['crash', 'exception', 'stack trace', 'debug', 'leaked', 'executed', 'injection']
		if any(signal in failure_reason or signal in reasoning for signal in crash_signals):
			return (
				f'The site did not handle {persona.replace("_", " ")} input safely. '
				f'Add input validation or sanitization for this input path. '
				f'Specific issue: {failure_reason_raw}'
			)

	# Agent got stuck / looping (common with confused_novice, impatient_user)
	if persona in ('confused_novice', 'impatient_user'):
		if result.duration > 200 or (len(result.actions) > 25):
			return (
				f'The agent ran {len(result.actions)} actions over {result.duration:.0f}s, suggesting it got stuck '
				f'in a loop. This is likely a test limitation — the "{persona.replace("_", " ")}" scenario '
				f'may need clearer exit conditions or a lower step limit. '
				f'Specific observation: {failure_reason_raw}'
			)

	# Verification / evidence issues
	if 'verify' in failure_reason or 'evidence' in failure_reason or 'confirm' in failure_reason:
		return (
			f'The actions were performed but the test could not confirm the expected outcome. '
			f'The success criteria may be too strict for what the site actually shows. '
			f'Specific observation: {failure_reason_raw}'
		)

	# Navigation failures
	if 'navigate' in failure_reason or 'load' in failure_reason or 'url' in failure_reason:
		return (
			f'A page failed to load or navigated to an unexpected URL. '
			f"Check that the target pages exist, aren't behind authentication, "
			f"and don't redirect unexpectedly. "
			f'Specific observation: {failure_reason_raw}'
		)

	# Element not found
	if 'element' in failure_reason or 'click' in failure_reason or 'not found' in failure_reason:
		return (
			f'An interactive element could not be found or clicked. '
			f'The page layout may have changed, or the element may load dynamically. '
			f'Specific observation: {failure_reason_raw}'
		)

	# Timeout
	if 'timeout' in failure_reason or 'time' in reasoning:
		return (
			f'The test took too long to complete. This could indicate slow page loads, '
			f'heavy JavaScript, or the agent getting stuck in a loop. '
			f'Specific observation: {failure_reason_raw}'
		)

	# Fallback with actual failure reason included
	if failure_reason_raw:
		return (
			f'The test failed during the "{persona.replace("_", " ")}" scenario. '
			f'Specific observation: {failure_reason_raw}'
		)

	return ''
