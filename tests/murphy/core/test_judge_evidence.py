"""Tests for judge evidence extraction helpers (no LLM calls)."""

from unittest.mock import MagicMock

from murphy.core.judge import _extract_navigation_evidence, _format_pages_reached


def _mock_history(actions: list[dict], urls: list[str] | None = None) -> MagicMock:
	"""Build a mock AgentHistoryList with model_actions() and urls()."""
	h = MagicMock()
	h.model_actions.return_value = actions
	h.urls.return_value = urls or []
	return h


# ─── _extract_navigation_evidence ────────────────────────────────────────────


def test_extract_navigation_evidence_empty():
	h = _mock_history([])
	assert _extract_navigation_evidence(h) == '(no actions recorded)'


def test_extract_navigation_evidence_click_with_href():
	actions = [
		{
			'click_element': {'index': 1},
			'interacted_element': {
				'tag_name': 'a',
				'text': 'About Us',
				'attributes': {'href': '/about'},
			},
		}
	]
	result = _extract_navigation_evidence(_mock_history(actions))
	assert 'CLICK' in result
	assert 'About Us' in result
	assert '/about' in result


def test_extract_navigation_evidence_click_with_text_no_href():
	actions = [
		{
			'click_element': {'index': 2},
			'interacted_element': {'tag_name': 'button', 'text': 'Submit'},
		}
	]
	result = _extract_navigation_evidence(_mock_history(actions))
	assert 'CLICK' in result
	assert 'Submit' in result


def test_extract_navigation_evidence_click_no_text():
	actions = [
		{
			'click_element': {'index': 5},
			'interacted_element': {'tag_name': 'div', 'text': ''},
		}
	]
	result = _extract_navigation_evidence(_mock_history(actions))
	assert 'CLICK' in result
	assert 'element 5' in result


def test_extract_navigation_evidence_click_no_interacted_element():
	actions = [{'click_element': {'index': 3}}]
	result = _extract_navigation_evidence(_mock_history(actions))
	assert 'CLICK' in result
	assert 'element 3' in result


def test_extract_navigation_evidence_navigate():
	actions = [{'navigate': {'url': 'https://example.com/page'}}]
	result = _extract_navigation_evidence(_mock_history(actions))
	assert 'NAVIGATE' in result
	assert 'https://example.com/page' in result


def test_extract_navigation_evidence_input_text():
	actions = [{'input_text': {'text': 'hello world'}}]
	result = _extract_navigation_evidence(_mock_history(actions))
	assert 'TYPE' in result
	assert 'hello world' in result


def test_extract_navigation_evidence_search():
	actions = [{'search': {'query': 'python testing'}}]
	result = _extract_navigation_evidence(_mock_history(actions))
	assert 'SEARCH' in result
	assert 'python testing' in result


def test_extract_navigation_evidence_scroll_down():
	actions = [{'scroll': {'down': True}}]
	result = _extract_navigation_evidence(_mock_history(actions))
	assert 'SCROLL' in result
	assert 'down' in result


def test_extract_navigation_evidence_scroll_up():
	actions = [{'scroll': {'down': False}}]
	result = _extract_navigation_evidence(_mock_history(actions))
	assert 'SCROLL' in result
	assert 'up' in result


def test_extract_navigation_evidence_done():
	actions = [{'done': {'text': 'finished', 'success': True}}]
	result = _extract_navigation_evidence(_mock_history(actions))
	assert 'DONE' in result
	assert 'success=True' in result


def test_extract_navigation_evidence_dropdown():
	actions = [{'select_dropdown_option': {'text': 'Option A'}}]
	result = _extract_navigation_evidence(_mock_history(actions))
	assert 'SELECT_DROPDOWN_OPTION' in result
	assert 'Option A' in result


def test_extract_navigation_evidence_switch_tab():
	actions = [{'switch_tab': {}}]
	result = _extract_navigation_evidence(_mock_history(actions))
	assert 'SWITCH TAB' in result


def test_extract_navigation_evidence_unknown_action():
	actions = [{'some_new_action': {'param': 'value'}}]
	result = _extract_navigation_evidence(_mock_history(actions))
	assert 'SOME_NEW_ACTION' in result


def test_extract_navigation_evidence_multiple_actions():
	actions = [
		{'navigate': {'url': 'https://example.com'}},
		{'click_element': {'index': 1}, 'interacted_element': {'tag_name': 'a', 'text': 'Home', 'attributes': {}}},
		{'input_text': {'text': 'search query'}},
	]
	result = _extract_navigation_evidence(_mock_history(actions))
	lines = result.strip().split('\n')
	assert len(lines) == 3
	assert lines[0].startswith('1.')
	assert lines[1].startswith('2.')
	assert lines[2].startswith('3.')


def test_extract_navigation_evidence_skips_interacted_element_only():
	"""An action with only 'interacted_element' key and nothing else is skipped."""
	actions = [{'interacted_element': {'tag_name': 'div'}}]
	result = _extract_navigation_evidence(_mock_history(actions))
	assert result == '(no actions recorded)'


# ─── _format_pages_reached ───────────────────────────────────────────────────


def test_format_pages_reached_empty():
	h = _mock_history([], urls=[])
	assert _format_pages_reached(h) == '(no URLs recorded)'


def test_format_pages_reached_single():
	h = _mock_history([], urls=['https://example.com'])
	result = _format_pages_reached(h)
	assert 'https://example.com' in result
	assert '1.' in result


def test_format_pages_reached_deduplicates():
	h = _mock_history([], urls=['https://example.com', 'https://example.com', 'https://example.com/page'])
	result = _format_pages_reached(h)
	assert result.count('https://example.com/page') == 1
	lines = [line.strip() for line in result.strip().split('\n') if line.strip()]
	assert len(lines) == 2


def test_format_pages_reached_preserves_order():
	h = _mock_history([], urls=['https://c.com', 'https://a.com', 'https://b.com'])
	result = _format_pages_reached(h)
	lines = result.strip().split('\n')
	assert 'https://c.com' in lines[0]
	assert 'https://a.com' in lines[1]
	assert 'https://b.com' in lines[2]


def test_format_pages_reached_skips_empty_strings():
	h = _mock_history([], urls=['', 'https://example.com', ''])
	result = _format_pages_reached(h)
	lines = [line.strip() for line in result.strip().split('\n') if line.strip()]
	assert len(lines) == 1
