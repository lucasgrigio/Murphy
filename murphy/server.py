"""Murphy — Interactive test review server.

Serves an HTML UI for reviewing generated tests before execution,
then shows results after execution completes.
"""

import asyncio
import html
import webbrowser
from typing import Any

from aiohttp import web

from murphy.models import ReportSummary, TestPlan, TestResult, WebsiteAnalysis
from murphy.report import _format_path, _suggest_fix

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
		text=_render_plan_html(state.url, state.analysis, state.test_plan),
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
		text=_render_results_html(state.url, state.analysis, state.results, state.summary),
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
	print(f'\n  Review tests at: {url}\n')
	webbrowser.open(url)

	return runner, port


# ─── HTML rendering ──────────────────────────────────────────────────────────

_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Open+Sans:wght@400;600;700&display=swap');
:root {
	--bg: #fdfffe; --surface: #ffffff; --border: #e5e7eb;
	--text: #333333; --text-muted: #6b7280; --accent: #333333;
	--green: #16a34a; --red: #dc2626; --orange: #d97706; --blue: #333333; --gray: #9ca3af;
	--hover-bg: #f9fafb;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: 'Open Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
	background: var(--bg); color: var(--text); line-height: 1.7; padding: 3rem 2rem; max-width: 960px; margin: 0 auto; }
h1 { font-family: Georgia, 'Times New Roman', serif; font-size: 2rem; font-weight: 400;
	margin-bottom: .25rem; color: var(--text); letter-spacing: -0.02em; }
h2 { font-family: Georgia, 'Times New Roman', serif; font-size: 1.3rem; font-weight: 400;
	margin: 2rem 0 1rem; color: var(--text); }
.subtitle { color: var(--text-muted); margin-bottom: 2rem; font-size: .9rem; letter-spacing: .02em;
	padding-bottom: 1.5rem; border-bottom: 1px solid var(--border); }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 2px;
	padding: 1rem 1.5rem; margin-bottom: .5rem; transition: box-shadow .15s; }
.card:hover { box-shadow: 0 1px 4px rgba(0,0,0,.06); }
.card-header { display: flex; align-items: center; gap: .75rem; cursor: pointer; user-select: none; }
.card-header .arrow { transition: transform .2s; font-size: .65rem; color: var(--text-muted); }
.card-header .arrow.open { transform: rotate(90deg); }
.card-body { display: none; margin-top: 1rem; padding-top: 1rem; border-top: 1px solid var(--border); }
.card-body.open { display: block; }
.badge { display: inline-block; padding: 3px 10px; border-radius: 2px; font-size: .65rem;
	font-weight: 700; text-transform: uppercase; letter-spacing: .08em; }
.badge-critical { background: var(--red); color: #fff; }
.badge-high { background: var(--orange); color: #fff; }
.badge-medium { background: var(--text); color: #fff; }
.badge-low { background: var(--gray); color: #fff; }
.badge-pass { background: var(--green); color: #fff; }
.badge-fail-website { background: var(--red); color: #fff; }
.badge-fail-test { background: var(--orange); color: #fff; }
.test-name { font-weight: 600; flex: 1; font-size: .95rem; }
.detail { color: var(--text-muted); font-size: .875rem; margin-bottom: .6rem; line-height: 1.6; }
.detail strong { color: var(--text); font-weight: 600; }
.steps { background: #f3f4f6; border-radius: 2px; padding: .875rem 1.125rem; font-size: .825rem;
	white-space: pre-wrap; margin-top: .5rem; color: var(--text); line-height: 1.7; border: 1px solid var(--border); }
.btn { display: inline-block; background: var(--text); color: #fff; border: none; padding: .875rem 3.5rem;
	font-size: .9rem; font-weight: 600; border-radius: 2px; cursor: pointer; margin-top: 2rem;
	letter-spacing: .04em; text-transform: uppercase; transition: background .15s; }
.btn:hover { background: #1a1a1a; }
.btn:disabled { opacity: .4; cursor: not-allowed; }
.center { text-align: center; }
.progress-wrap { display: none; margin-top: 2rem; }
.progress-wrap.active { display: block; }
.progress-bar { height: 3px; background: var(--border); border-radius: 0; overflow: hidden; }
.progress-fill { height: 100%; background: var(--text); transition: width .3s; }
.progress-text { text-align: center; color: var(--text-muted); margin-top: .75rem; font-size: .85rem; }
.summary-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
	gap: 1rem; margin-bottom: 2rem; }
.summary-box { background: var(--surface); border: 1px solid var(--border); border-radius: 2px;
	padding: 1.25rem 1rem; text-align: center; }
.summary-box .num { font-family: Georgia, 'Times New Roman', serif; font-size: 2rem; font-weight: 400; }
.summary-box .label { font-size: .75rem; color: var(--text-muted); text-transform: uppercase;
	letter-spacing: .08em; margin-top: .25rem; }
.group-header { font-family: Georgia, 'Times New Roman', serif; font-size: 1.1rem; font-weight: 400;
	margin: 1.75rem 0 .75rem; display: flex; align-items: center; gap: .5rem;
	padding-bottom: .5rem; border-bottom: 1px solid var(--border); }
.actions-list { background: #f3f4f6; border: 1px solid var(--border); border-radius: 2px;
	padding: .5rem 0; margin-top: .5rem; }
.action-row { padding: .4rem 1rem; font-size: .825rem; line-height: 1.5; border-bottom: 1px solid #e9ebee; }
.action-row:last-child { border-bottom: none; }
.action-row:hover { background: #ebedf0; }
.action-type { color: var(--text); font-weight: 600; }
.action-element { color: #6d28d9; font-size: .8rem; }
.action-param { display: inline; margin-left: .35rem; color: var(--text-muted); font-size: .8rem; }
.action-key { color: var(--text); font-weight: 600; font-size: .75rem; }
.expand-link { color: var(--accent); cursor: pointer; font-size: .75rem; text-decoration: underline;
	margin-left: .25rem; }
.expand-link:hover { opacity: .7; }
.badge-persona { font-size: .6rem; letter-spacing: .06em; }
.badge-happy_path { background: #16a34a; color: #fff; }
.badge-confused_novice { background: #7c3aed; color: #fff; }
.badge-adversarial { background: #dc2626; color: #fff; }
.badge-edge_case { background: #d97706; color: #fff; }
.badge-explorer { background: #0891b2; color: #fff; }
.badge-impatient_user { background: #e11d48; color: #fff; }
.badge-angry_user { background: #9f1239; color: #fff; }
.persona-label { font-size: .7rem; color: var(--text-muted); text-transform: uppercase; letter-spacing: .06em; }
"""


def _e(s: str) -> str:
	"""HTML-escape."""
	return html.escape(str(s))


_expand_counter = [0]  # mutable counter for unique expand IDs


def _format_action_html(action: Any) -> str:
	"""Render a single action dict as a readable HTML row."""
	if not isinstance(action, dict):
		return f'<div class="action-row">{_e(str(action))}</div>'

	# Each action dict has one key like 'click', 'navigate', 'type', 'done', etc.
	for action_type, params in action.items():
		if action_type == 'interacted_element':
			continue
		icon = {
			'navigate': '&#x1f310;',  # globe
			'click': '&#x1f5b1;',  # mouse
			'type': '&#x2328;',  # keyboard
			'scroll': '&#x2195;',  # up-down arrow
			'done': '&#x2705;',  # checkmark
			'extract': '&#x1f4cb;',  # clipboard
			'wait': '&#x23f3;',  # hourglass
			'go_back': '&#x2b05;',  # left arrow
			'switch_tab': '&#x1f4c4;',  # page
			'search': '&#x1f50d;',  # magnifying glass
			'input_text': '&#x2328;',  # keyboard
			'select_option': '&#x2611;',  # checkbox
			'open_tab': '&#x2795;',  # plus
		}.get(action_type, '&#x2022;')  # bullet dot

		_expand_counter[0] += 1

		if isinstance(params, dict):
			parts = []
			for k, v in params.items():
				if k in ('interacted_element',) or v is None or v == '':
					continue
				val = str(v)
				if len(val) > 100:
					eid = f'exp-{_expand_counter[0]}-{k}'
					short = val[:100]
					parts.append(
						f'<span class="action-param"><span class="action-key">{_e(k)}:</span> '
						f'<span id="{eid}-short">{_e(short)}... '
						f'<a class="expand-link" onclick="toggleExp(\'{eid}\')">show more</a></span>'
						f'<span id="{eid}-full" style="display:none">{_e(val)} '
						f'<a class="expand-link" onclick="toggleExp(\'{eid}\')">show less</a></span>'
						f'</span>'
					)
				else:
					parts.append(f'<span class="action-param"><span class="action-key">{_e(k)}:</span> {_e(val)}</span>')
			detail = ''.join(parts) if parts else ''
		else:
			val = str(params)
			if len(val) > 100:
				eid = f'exp-{_expand_counter[0]}'
				short = val[:100]
				detail = (
					f'<span class="action-param">'
					f'<span id="{eid}-short">{_e(short)}... '
					f'<a class="expand-link" onclick="toggleExp(\'{eid}\')">show more</a></span>'
					f'<span id="{eid}-full" style="display:none">{_e(val)} '
					f'<a class="expand-link" onclick="toggleExp(\'{eid}\')">show less</a></span>'
					f'</span>'
				)
			else:
				detail = f'<span class="action-param">{_e(val)}</span>' if params else ''

		# Element context if present
		el = action.get('interacted_element')
		el_html = ''
		if el and isinstance(el, dict):
			tag = el.get('tag_name', '')
			name = el.get('ax_name', '').replace('\n', ' ').strip()
			if tag or name:
				el_html = f' <span class="action-element">{_e(tag)} &ldquo;{_e(name)}&rdquo;</span>'

		return f'<div class="action-row">{icon} <strong class="action-type">{_e(action_type)}</strong>{el_html}{" " + detail if detail else ""}</div>'

	return f'<div class="action-row">{_e(str(action))}</div>'


def _render_features_summary_html(analysis: WebsiteAnalysis) -> str:
	"""Render a features discovered summary section."""
	if not analysis.features:
		return ''

	# Group features by category
	by_category: dict[str, list] = {}
	for f in analysis.features:
		by_category.setdefault(f.category, []).append(f)

	html_parts = ['<h2>Features Discovered</h2>']
	for cat, features in by_category.items():
		html_parts.append(f'<div class="group-header">{_e(cat.replace("_", " ").title())} ({len(features)})</div>')
		for f in features:
			testability_color = {'testable': 'var(--green)', 'partial': 'var(--orange)', 'untestable': 'var(--gray)'}[
				f.testability
			]
			importance_label = f.importance.upper()
			html_parts.append(
				f'<div class="card" style="padding:.75rem 1.25rem">'
				f'<span style="font-weight:600;font-size:.9rem">{_e(f.name)}</span> '
				f'<span class="badge" style="background:{testability_color};font-size:.6rem">{_e(f.testability)}</span> '
				f'<span style="color:var(--text-muted);font-size:.75rem;margin-left:.5rem">{_e(importance_label)}</span>'
				f'<div class="detail" style="margin-top:.25rem;margin-bottom:0">{_e(f.description)}</div>'
				f'</div>'
			)

	return '\n'.join(html_parts)


_PERSONA_LABELS: dict[str, str] = {
	'happy_path': 'Happy Path',
	'confused_novice': 'Confused Novice',
	'adversarial': 'Adversarial',
	'edge_case': 'Edge Case',
	'explorer': 'Explorer',
	'impatient_user': 'Impatient User',
	'angry_user': 'Angry User',
}

_PERSONA_ORDER = list(_PERSONA_LABELS.keys())


def _render_plan_html(url: str, analysis: WebsiteAnalysis, test_plan: TestPlan) -> str:
	features_html = _render_features_summary_html(analysis)
	cards_html = ''

	# Group scenarios by test_persona
	groups: dict[str, list] = {}
	for i, s in enumerate(test_plan.scenarios):
		groups.setdefault(s.test_persona, []).append((i, s))

	for persona in _PERSONA_ORDER:
		items = groups.get(persona)
		if not items:
			continue
		label = _PERSONA_LABELS.get(persona, persona.replace('_', ' ').title())
		cards_html += f'<div class="group-header"><span class="badge badge-persona badge-{persona}">{_e(label)}</span> ({len(items)})</div>\n'
		for idx, s in items:
			cards_html += f"""<div class="card">
	<div class="card-header" onclick="toggle({idx})">
		<span class="arrow" id="arrow-{idx}">&#9654;</span>
		<span class="test-name">{_e(s.name)}</span>
		<span class="badge badge-{s.priority}">{_e(s.priority)}</span>
		<span class="badge badge-persona badge-{s.test_persona}">{_e(_PERSONA_LABELS.get(s.test_persona) or s.test_persona)}</span>
	</div>
	<div class="card-body" id="body-{idx}">
		<div class="detail"><strong>Target feature:</strong> {_e(s.target_feature)}</div>
		<div class="detail"><strong>Persona:</strong> {_e(_PERSONA_LABELS.get(s.test_persona) or s.test_persona)}</div>
		<div class="detail"><strong>Description:</strong> {_e(s.description)}</div>
		<div class="detail"><strong>Success criteria:</strong> {_e(s.success_criteria)}</div>
		<div class="steps">{_e(s.steps_description)}</div>
	</div>
</div>\n"""

	return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Murphy — Test Plan Review</title>
<style>{_CSS}</style></head><body>
<h1>Murphy — Test Plan Review</h1>
<div class="subtitle">{_e(analysis.site_name)} &middot; {_e(url)} &middot; {len(test_plan.scenarios)} tests</div>
{features_html}
<h2>Test Plan</h2>
{cards_html}
<div class="center">
	<button class="btn" id="run-btn" onclick="runTests()">Run Tests</button>
</div>
<div class="progress-wrap" id="progress">
	<div class="progress-bar"><div class="progress-fill" id="progress-fill" style="width:0%"></div></div>
	<div class="progress-text" id="progress-text">Starting...</div>
</div>
<script>
function toggle(i) {{
	var b = document.getElementById('body-'+i);
	var a = document.getElementById('arrow-'+i);
	b.classList.toggle('open');
	a.classList.toggle('open');
}}
function runTests() {{
	var btn = document.getElementById('run-btn');
	btn.disabled = true; btn.textContent = 'Running...';
	document.getElementById('progress').classList.add('active');
	fetch('/run', {{method:'POST'}}).then(function() {{ pollStatus(); }});
}}
function pollStatus() {{
	fetch('/status').then(r => r.json()).then(function(d) {{
		if (d.done) {{ window.location = '/results'; return; }}
		var pct = d.total > 0 ? Math.round(d.current_test / d.total * 100) : 0;
		document.getElementById('progress-fill').style.width = pct + '%';
		var txt = d.current_test_name
			? 'Running test ' + d.current_test + '/' + d.total + ': ' + d.current_test_name
			: 'Starting...';
		document.getElementById('progress-text').textContent = txt;
		setTimeout(pollStatus, 2000);
	}});
}}
</script></body></html>"""


def _render_results_html(
	url: str,
	analysis: WebsiteAnalysis,
	results: list[TestResult],
	summary: ReportSummary | None,
) -> str:
	_expand_counter[0] = 0  # reset for fresh render
	passed = sum(1 for r in results if r.success)
	total = len(results)
	rate = round(passed / total * 100, 1) if total else 0
	website_issues = sum(1 for r in results if r.failure_category == 'website_issue')
	test_limitations = sum(1 for r in results if r.failure_category == 'test_limitation')

	# Persona breakdown
	persona_stats: dict[str, dict[str, int]] = {}
	for r in results:
		p = r.scenario.test_persona
		if p not in persona_stats:
			persona_stats[p] = {'passed': 0, 'total': 0}
		persona_stats[p]['total'] += 1
		if r.success:
			persona_stats[p]['passed'] += 1

	persona_boxes = ''
	for persona in _PERSONA_ORDER:
		if persona not in persona_stats:
			continue
		ps = persona_stats[persona]
		label = _PERSONA_LABELS.get(persona, persona.replace('_', ' ').title())
		persona_boxes += (
			f'<div class="summary-box">'
			f'<div class="num">{ps["passed"]}/{ps["total"]}</div>'
			f'<div class="label"><span class="badge badge-persona badge-{persona}" style="font-size:.55rem">{_e(label)}</span></div>'
			f'</div>'
		)

	summary_html = f"""
<div class="summary-grid">
	<div class="summary-box"><div class="num">{total}</div><div class="label">Total</div></div>
	<div class="summary-box"><div class="num" style="color:var(--green)">{passed}</div><div class="label">Passed</div></div>
	<div class="summary-box"><div class="num" style="color:var(--red)">{website_issues}</div><div class="label">Website Issues</div></div>
	<div class="summary-box"><div class="num" style="color:var(--orange)">{test_limitations}</div><div class="label">Test Limitations</div></div>
	<div class="summary-box"><div class="num">{rate}%</div><div class="label">Pass Rate</div></div>
</div>
<h2>By Persona</h2>
<div class="summary-grid">
	{persona_boxes}
</div>"""

	# Group results: passed, website_issue, test_limitation
	sections = [
		('Passed', [r for r in results if r.success]),
		('Failed — Website Issue', [r for r in results if r.failure_category == 'website_issue']),
		('Failed — Test Limitation', [r for r in results if r.failure_category == 'test_limitation']),
	]

	cards_html = ''
	card_idx = 0
	for section_title, section_results in sections:
		if not section_results:
			continue
		cards_html += f'<div class="group-header">{section_title} ({len(section_results)})</div>\n'
		for r in section_results:
			# Determine badge
			if r.success:
				badge_cls = 'badge-pass'
				badge_text = 'PASS'
			elif r.failure_category == 'website_issue':
				badge_cls = 'badge-fail-website'
				badge_text = 'WEBSITE ISSUE'
			else:
				badge_cls = 'badge-fail-test'
				badge_text = 'TEST LIMITATION'

			# Build detail body
			body_parts = []
			body_parts.append(
				f'<div class="detail"><strong>Persona:</strong> <span class="badge badge-persona badge-{r.scenario.test_persona}">{_e(_PERSONA_LABELS.get(r.scenario.test_persona, r.scenario.test_persona))}</span></div>'
			)
			body_parts.append(f'<div class="detail"><strong>Target feature:</strong> {_e(r.scenario.target_feature)}</div>')
			body_parts.append(f'<div class="detail"><strong>Description:</strong> {_e(r.scenario.description)}</div>')
			body_parts.append(f'<div class="detail"><strong>Duration:</strong> {r.duration:.1f}s</div>')
			body_parts.append(f'<div class="detail"><strong>Path:</strong> {_e(_format_path(r))}</div>')

			# Evaluation dimensions
			if r.process_evaluation:
				body_parts.append(f'<div class="detail"><strong>Process evaluation:</strong> {_e(r.process_evaluation)}</div>')
			if r.logical_evaluation:
				body_parts.append(f'<div class="detail"><strong>Logical evaluation:</strong> {_e(r.logical_evaluation)}</div>')
			if r.usability_evaluation:
				body_parts.append(
					f'<div class="detail"><strong>Usability evaluation:</strong> {_e(r.usability_evaluation)}</div>'
				)

			# Pages visited
			if r.pages_visited:
				pages_html = ', '.join(_e(p) for p in r.pages_visited[:10])
				body_parts.append(f'<div class="detail"><strong>Pages visited:</strong> {pages_html}</div>')

			if r.judgement:
				reasoning = r.judgement.get('reasoning', '')
				if reasoning:
					body_parts.append(f'<div class="detail"><strong>Reasoning:</strong> {_e(reasoning)}</div>')
				failure_reason = r.reason or r.judgement.get('failure_reason', '')
				if failure_reason:
					body_parts.append(f'<div class="detail"><strong>Failure reason:</strong> {_e(failure_reason)}</div>')

			if not r.success:
				suggestion = _suggest_fix(r)
				if suggestion:
					body_parts.append(f'<div class="detail"><strong>Suggestion:</strong> {_e(suggestion)}</div>')

			# Actions trace
			if r.actions:
				action_rows = ''.join(_format_action_html(a) for a in r.actions[:30])
				body_parts.append(
					f'<div class="detail"><strong>Actions:</strong></div><div class="actions-list">{action_rows}</div>'
				)

			body_html = '\n'.join(body_parts)

			cards_html += f"""<div class="card">
	<div class="card-header" onclick="toggle({card_idx})">
		<span class="arrow" id="arrow-{card_idx}">&#9654;</span>
		<span class="test-name">{_e(r.scenario.name)}</span>
		<span class="badge badge-persona badge-{r.scenario.test_persona}">{_e(_PERSONA_LABELS.get(r.scenario.test_persona, r.scenario.test_persona))}</span>
		<span class="badge {badge_cls}">{badge_text}</span>
	</div>
	<div class="card-body" id="body-{card_idx}">
		{body_html}
	</div>
</div>\n"""
			card_idx += 1

	return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Murphy — Results</title>
<style>{_CSS}</style></head><body>
<h1>Murphy — Results</h1>
<div class="subtitle">{_e(analysis.site_name)} &middot; {_e(url)}</div>
{summary_html}
{cards_html}
<script>
function toggle(i) {{
	var b = document.getElementById('body-'+i);
	var a = document.getElementById('arrow-'+i);
	b.classList.toggle('open');
	a.classList.toggle('open');
}}
function toggleExp(id) {{
	var s = document.getElementById(id+'-short');
	var f = document.getElementById(id+'-full');
	if (s.style.display === 'none') {{ s.style.display = ''; f.style.display = 'none'; }}
	else {{ s.style.display = 'none'; f.style.display = ''; }}
}}
</script></body></html>"""
