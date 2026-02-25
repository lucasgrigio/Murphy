"""
Murphy's own judge — evaluates agent success based on action trace, not self-report.

The key difference from browser_use's built-in judge: this treats the action trace
(navigations, clicks, form submissions, URLs visited) as primary evidence of task
completion, rather than demanding the agent explicitly report what it did.

Pre-processes raw action data into clean, human-readable evidence so the LLM judge
can't miss navigation proof buried in nested JSON.
"""

from typing import Literal

from pydantic import BaseModel

from browser_use.agent.views import AgentHistoryList
from browser_use.llm import ChatOpenAI, SystemMessage, UserMessage
from murphy.models import TestScenario

JUDGE_SYSTEM_PROMPT = """\
You are a QA judge evaluating whether a browser automation agent successfully completed a test scenario.

You judge success based on OBSERVABLE ACTIONS, not on what the agent said or reported.

## How to read the evidence

You will receive three evidence sections:

1. **Navigation Evidence** — a pre-extracted summary of every click, navigation, and form interaction the agent performed, plus the actual browser URLs reached. This is your PRIMARY evidence.
2. **Full Step Trace** — the complete step-by-step action log with results and errors.
3. **Agent's Final Response** — what the agent said at the end. This is supplementary only.

## Evaluation rules

- The action trace IS the verification. A click on a link with href="/about-us" followed by the browser URL changing to that path IS proof of successful navigation. No further "verification" is needed.
- If the Navigation Evidence shows the agent clicked the right elements and the browser reached the right URLs, that IS success.
- Real errors in the trace (timeouts, element not found, HTTP errors) weigh against success.
- An agent completing all required interactions with zero errors is strong evidence of success.
- The verdict should be TRUE if the actions and URLs match the success criteria, regardless of what the agent said or did not say in its final response.
- NEVER require the agent to "verify", "confirm", "report", or "provide evidence of" anything. The action trace is the evidence.

## Persona-specific evaluation

The test has a **Test Persona** that determines HOW you evaluate success:

- **happy_path**: Judge whether the expected flow completed successfully. Standard pass/fail.
- **confused_novice**: Judge whether the website HANDLED the confused behavior gracefully. A helpful error message, redirect, or gentle correction = PASS. A crash, blank page, or unhandled exception = FAIL. The user being confused is expected — the website's response is what matters.
- **adversarial**: Judge whether the website RESISTED the attack. Input sanitized or rejected = PASS. Script executed, debug info leaked, raw SQL error shown, or stack trace exposed = FAIL.
- **edge_case**: Judge whether the website handled unusual input without breaking. Validation error shown, input truncated, or graceful fallback = PASS. Unhandled exception, corrupted display, or crash = FAIL.
- **explorer**: Judge whether the website remained functional and navigable through the unusual path. Pages still load, no dead ends or infinite loops = PASS.
- **impatient_user**: Judge whether the website handled rapid/premature interactions without corruption. No duplicate submissions, no broken UI state, no data loss = PASS.
- **angry_user**: Judge whether the website absorbed hostile interaction gracefully. No crash from rage-clicks, profanity in inputs doesn't cause errors, rapid navigation doesn't break state = PASS.

CRITICAL: For non-happy-path personas, the test PASSES if the website handles the unexpected behavior gracefully, even if the "task" itself didn't complete normally. A confused novice test that results in a helpful error page is a PASS. An adversarial test where the injection is sanitized is a PASS.

## Failure classification

If verdict is FALSE, you MUST also classify the failure:
- **website_issue**: The agent executed the test (or got far enough) and observed the website behaving badly — empty page, broken UI, unhandled input, crash, error, missing validation, data corruption.
- **test_limitation**: The agent could NOT complete the test itself — couldn't find an element, ran out of steps, navigated to wrong page, test steps were ambiguous or impossible.

If verdict is TRUE, set failure_category to null.

## Evaluation dimensions

In addition to the verdict, provide three brief evaluation assessments:

1. **process_evaluation**: Assess the step-by-step process quality. Was the flow smooth or did the user encounter friction (extra clicks, unclear navigation, redundant confirmations)? Note any unnecessary steps or confusing transitions.
2. **logical_evaluation**: Assess UI/system logic consistency. Did the application behave logically? Were state changes consistent? Did buttons do what labels promised? Were error messages accurate?
3. **usability_evaluation**: Assess clarity, affordances, and user-friendliness. Were controls discoverable? Was feedback timely? Were labels clear? Would a real user understand what to do next at each step?

Keep each evaluation to 1-3 sentences grounded in the observed action trace.
"""

JUDGE_USER_TEMPLATE = """\
## Test Scenario
**Name:** {name}
**Test Persona:** {persona}
**Description:** {description}
**Steps:** {steps}
**Success Criteria:** {criteria}

## Navigation Evidence (pre-extracted)
{navigation_evidence}

## Pages Reached (actual browser URLs, in order)
{pages_reached}

## Full Step Trace
{step_trace}

## Errors
{errors}

## Agent's Final Response
{final_result}

---

## Validation rules
- Validate outcome state before returning a verdict (no inference from partial signals).
- Use visible UI signals only: toasts, badges, list rows, detail cards, confirmation messages.
- For create flows: confirm new entity appears with a recognizable identifier.
- For delete flows: confirm entity is absent from list/search.
- For edit flows: reopen and confirm updates persist.
- If evidence is ambiguous, return verdict=false.

Based on the Navigation Evidence and Pages Reached, did the agent successfully complete this test?
"""


class JudgeVerdict(BaseModel):
	reasoning: str
	verdict: bool
	failure_reason: str
	impossible_task: bool
	reached_captcha: bool
	failure_category: Literal['website_issue', 'test_limitation'] | None
	process_evaluation: str = ''
	logical_evaluation: str = ''
	usability_evaluation: str = ''


def _extract_navigation_evidence(history: AgentHistoryList) -> str:
	"""Extract a clean, human-readable summary of navigation actions from the raw action trace.

	Pulls out clicked links (with hrefs), navigate actions, form submissions, typing,
	and other interactions — structured so the LLM judge can directly match against
	success criteria without parsing nested JSON.
	"""
	evidence_lines: list[str] = []
	actions = history.model_actions()

	for i, action in enumerate(actions, 1):
		# Each action dict has the action type as first key, plus 'interacted_element'
		interacted = action.get('interacted_element')

		# Extract action type (first key that isn't 'interacted_element')
		action_type = None
		action_params = None
		for key, val in action.items():
			if key != 'interacted_element':
				action_type = key
				action_params = val
				break

		if not action_type:
			continue

		if action_type == 'click_element':
			# Build description from interacted element
			if interacted and isinstance(interacted, dict):
				tag = interacted.get('tag_name', '?')
				text = interacted.get('text', '')
				href = interacted.get('attributes', {}).get('href', '') if isinstance(interacted.get('attributes'), dict) else ''

				if href:
					evidence_lines.append(f'{i}. CLICK: <{tag}> "{text}" → href="{href}"')
				elif text:
					evidence_lines.append(f'{i}. CLICK: <{tag}> "{text}"')
				else:
					index = action_params.get('index', '?') if isinstance(action_params, dict) else '?'
					evidence_lines.append(f'{i}. CLICK: <{tag}> (element {index})')
			else:
				index = action_params.get('index', '?') if isinstance(action_params, dict) else '?'
				evidence_lines.append(f'{i}. CLICK: element {index}')

		elif action_type == 'navigate':
			url = action_params.get('url', '?') if isinstance(action_params, dict) else '?'
			evidence_lines.append(f'{i}. NAVIGATE: → {url}')

		elif action_type == 'input_text':
			if isinstance(action_params, dict):
				text = action_params.get('text', '')
				evidence_lines.append(f'{i}. TYPE: "{text}"')

		elif action_type == 'search':
			if isinstance(action_params, dict):
				query = action_params.get('query', '')
				evidence_lines.append(f'{i}. SEARCH: "{query}"')

		elif action_type == 'scroll':
			direction = 'down' if (isinstance(action_params, dict) and action_params.get('down', True)) else 'up'
			evidence_lines.append(f'{i}. SCROLL: {direction}')

		elif action_type == 'done':
			text = action_params.get('text', '') if isinstance(action_params, dict) else ''
			success = action_params.get('success', True) if isinstance(action_params, dict) else True
			evidence_lines.append(f'{i}. DONE: success={success}')

		elif action_type in ('select_dropdown_option', 'get_dropdown_options'):
			if isinstance(action_params, dict):
				text = action_params.get('text', '')
				evidence_lines.append(f'{i}. {action_type.upper()}: "{text}"')

		elif action_type == 'switch_tab':
			evidence_lines.append(f'{i}. SWITCH TAB')

		else:
			evidence_lines.append(f'{i}. {action_type.upper()}')

	return '\n'.join(evidence_lines) if evidence_lines else '(no actions recorded)'


def _format_pages_reached(history: AgentHistoryList) -> str:
	"""Deduplicate and format the actual browser URLs visited, in order."""
	urls = history.urls()
	# Deduplicate while preserving order
	seen: set[str] = set()
	unique_urls: list[str] = []
	for url in urls:
		if url and url not in seen:
			seen.add(url)
			unique_urls.append(url)

	if not unique_urls:
		return '(no URLs recorded)'

	lines = [f'  {i}. {url}' for i, url in enumerate(unique_urls, 1)]
	return '\n'.join(lines)


async def murphy_judge(
	history: AgentHistoryList,
	scenario: TestScenario,
	llm: ChatOpenAI,
) -> dict:
	"""Evaluate agent success based on action trace, not self-report."""
	# Pre-processed evidence
	navigation_evidence = _extract_navigation_evidence(history)
	pages_reached = _format_pages_reached(history)

	# Full step trace from agent_steps() — already formatted for judge evaluation
	agent_steps = history.agent_steps()
	step_trace = '\n'.join(agent_steps) if agent_steps else '(no steps recorded)'

	# Errors
	errors = history.errors()
	errors_text = '\n'.join(f'  - Step {i + 1}: {e}' for i, e in enumerate(errors) if e) if any(errors) else '(none)'

	# Final result
	final_result = history.final_result() or '(no final response)'

	user_prompt = JUDGE_USER_TEMPLATE.format(
		name=scenario.name,
		persona=scenario.test_persona,
		description=scenario.description,
		steps=scenario.steps_description,
		criteria=scenario.success_criteria,
		navigation_evidence=navigation_evidence,
		pages_reached=pages_reached,
		step_trace=step_trace,
		errors=errors_text,
		final_result=final_result,
	)

	response = await llm.ainvoke(
		messages=[
			SystemMessage(content=JUDGE_SYSTEM_PROMPT),
			UserMessage(content=user_prompt),
		],
		output_format=JudgeVerdict,
	)

	verdict = response.completion
	assert isinstance(verdict, JudgeVerdict), f'Expected JudgeVerdict, got {type(verdict)}'

	return verdict.model_dump()
