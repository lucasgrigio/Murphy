"""Tests for murphy pydantic models."""

from murphy.models import JudgeVerdict, ScenarioExecutionVerdict, TestResult, TestScenario


def test_scenario_execution_verdict_defaults():
	v = ScenarioExecutionVerdict(success=True)
	assert v.success is True
	assert v.reason == ''
	assert v.process_evaluation == ''
	assert v.logical_evaluation == ''
	assert v.usability_evaluation == ''


def test_scenario_execution_verdict_with_fields():
	v = ScenarioExecutionVerdict(
		success=False,
		reason='Button not clickable',
		process_evaluation='Steps followed correctly',
		logical_evaluation='UI logic broken',
		usability_evaluation='Poor affordance on submit button',
	)
	assert v.success is False
	assert 'Button' in v.reason
	assert 'Steps' in v.process_evaluation


def _make_scenario() -> TestScenario:
	return TestScenario(
		name='Login flow',
		description='Test the login flow end-to-end',
		priority='high',
		feature_category='authentication',
		target_feature='Login form',
		test_persona='happy_path',
		steps_description='1. Open login page\n2. Enter credentials\n3. Click submit',
		success_criteria='User is logged in',
	)


def test_test_result_has_evaluation_fields():
	verdict = JudgeVerdict(
		reasoning='All steps completed successfully',
		verdict=True,
		failure_reason='',
		impossible_task=False,
		reached_captcha=False,
		failure_category=None,
	)
	r = TestResult(
		scenario=_make_scenario(),
		success=True,
		judgement=verdict,
		actions=[],
		errors=[],
		duration=1.5,
		reason='All steps completed',
		process_evaluation='Clean execution',
		logical_evaluation='Logic sound',
		usability_evaluation='Good UX',
		pages_visited=['https://example.com', 'https://example.com/login'],
	)
	assert r.success is True
	assert r.reason == 'All steps completed'
	assert len(r.pages_visited) == 2
	assert r.judgement is not None
	assert r.judgement.verdict is True
	assert r.judgement.reasoning == 'All steps completed successfully'
