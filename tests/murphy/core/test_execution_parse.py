"""Tests for _parse_structured_output with mocked AgentHistoryList."""

import json
from unittest.mock import MagicMock

from murphy.core.execution import _parse_structured_output
from murphy.models import ScenarioExecutionVerdict


def _mock_history(final_result: str | None) -> MagicMock:
	h = MagicMock()
	h.final_result.return_value = final_result
	return h


# ─── _parse_structured_output ────────────────────────────────────────────────


def test_parse_structured_output_none_result():
	h = _mock_history(None)
	assert _parse_structured_output(h, ScenarioExecutionVerdict) is None


def test_parse_structured_output_empty_string():
	h = _mock_history('')
	assert _parse_structured_output(h, ScenarioExecutionVerdict) is None


def test_parse_structured_output_valid_json():
	data = {
		'success': True,
		'reason': 'All steps completed',
		'process_evaluation': 'Smooth flow',
		'logical_evaluation': 'Consistent',
		'usability_evaluation': 'Clear',
		'validation_evidence': 'Results appeared',
	}
	h = _mock_history(json.dumps(data))
	result = _parse_structured_output(h, ScenarioExecutionVerdict)
	assert result is not None
	assert result.success is True
	assert result.reason == 'All steps completed'


def test_parse_structured_output_json_string_model_validate_json():
	"""model_validate_json path — valid JSON string."""
	data = {'success': False, 'reason': 'Failed'}
	h = _mock_history(json.dumps(data))
	result = _parse_structured_output(h, ScenarioExecutionVerdict)
	assert result is not None
	assert result.success is False


def test_parse_structured_output_invalid_json():
	h = _mock_history('not valid json at all')
	assert _parse_structured_output(h, ScenarioExecutionVerdict) is None


def test_parse_structured_output_partial_json():
	"""Valid JSON but not matching the model — might still work with defaults."""
	h = _mock_history('{"success": true}')
	result = _parse_structured_output(h, ScenarioExecutionVerdict)
	assert result is not None
	assert result.success is True
	assert result.reason == ''  # default


def test_parse_structured_output_minimal():
	"""Minimal valid JSON."""
	h = _mock_history('{"success": false}')
	result = _parse_structured_output(h, ScenarioExecutionVerdict)
	assert result is not None
	assert result.success is False
