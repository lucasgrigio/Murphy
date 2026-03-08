"""Tests for AI step private method used during rerun"""

from unittest.mock import AsyncMock, patch

import pytest

from browser_use.agent.service import Agent
from browser_use.agent.views import ActionResult
from browser_use.browser.session import BrowserSession
from tests.browser_use.conftest import create_mock_llm

MOCK_MARKDOWN = '# Test Page\nSome content here'
MOCK_STATS = {
	'original_html_chars': 200,
	'initial_markdown_chars': 100,
	'final_filtered_chars': 80,
	'filtered_chars_removed': 20,
}


@pytest.mark.timeout(30)
async def test_execute_ai_step_basic():
	"""Test that _execute_ai_step extracts content with AI"""

	async def custom_ainvoke(*args, **kwargs):
		from browser_use.llm.views import ChatInvokeCompletion

		return ChatInvokeCompletion(completion='Extracted: Test content from page', usage=None)

	mock_llm = AsyncMock()
	mock_llm.ainvoke.side_effect = custom_ainvoke
	mock_llm.model = 'mock-model'

	llm = create_mock_llm(actions=None)
	agent = Agent(task='Test task', llm=llm)

	with (
		patch('browser_use.dom.markdown_extractor.extract_clean_markdown', return_value=(MOCK_MARKDOWN, MOCK_STATS)),
		patch.object(BrowserSession, 'get_current_page_url', return_value='https://example.com/test'),
	):
		result = await agent._execute_ai_step(
			query='Extract the main heading',
			include_screenshot=False,
			extract_links=False,
			ai_step_llm=mock_llm,
		)

	assert isinstance(result, ActionResult)
	assert result.extracted_content is not None
	assert 'Extracted: Test content from page' in result.extracted_content
	assert result.long_term_memory is not None


@pytest.mark.timeout(30)
async def test_execute_ai_step_with_screenshot():
	"""Test that _execute_ai_step includes screenshot when requested"""

	async def custom_ainvoke(*args, **kwargs):
		from browser_use.llm.views import ChatInvokeCompletion

		messages = args[0] if args else []
		assert len(messages) >= 1, 'Should have at least one message'

		has_image = False
		for msg in messages:
			if hasattr(msg, 'content') and isinstance(msg.content, list):
				for part in msg.content:
					if hasattr(part, 'type') and part.type == 'image_url':
						has_image = True
						break

		assert has_image, 'Should include screenshot in message'
		return ChatInvokeCompletion(completion='Extracted content with screenshot analysis', usage=None)

	mock_llm = AsyncMock()
	mock_llm.ainvoke.side_effect = custom_ainvoke
	mock_llm.model = 'mock-model'

	llm = create_mock_llm(actions=None)
	agent = Agent(task='Test task', llm=llm)

	with (
		patch('browser_use.dom.markdown_extractor.extract_clean_markdown', return_value=(MOCK_MARKDOWN, MOCK_STATS)),
		patch.object(BrowserSession, 'get_current_page_url', return_value='https://example.com/test'),
		patch.object(BrowserSession, 'take_screenshot', return_value=b'fake-png-bytes'),
	):
		result = await agent._execute_ai_step(
			query='Analyze this page',
			include_screenshot=True,
			extract_links=False,
			ai_step_llm=mock_llm,
		)

	assert isinstance(result, ActionResult)
	assert result.extracted_content is not None
	assert 'Extracted content with screenshot analysis' in result.extracted_content


@pytest.mark.timeout(30)
async def test_execute_ai_step_error_handling():
	"""Test that _execute_ai_step handles errors gracefully"""
	mock_llm = AsyncMock()
	mock_llm.ainvoke.side_effect = Exception('LLM service unavailable')
	mock_llm.model = 'mock-model'

	llm = create_mock_llm(actions=None)
	agent = Agent(task='Test task', llm=llm)

	with (
		patch('browser_use.dom.markdown_extractor.extract_clean_markdown', return_value=(MOCK_MARKDOWN, MOCK_STATS)),
		patch.object(BrowserSession, 'get_current_page_url', return_value='https://example.com/test'),
	):
		result = await agent._execute_ai_step(
			query='Extract data',
			include_screenshot=False,
			ai_step_llm=mock_llm,
		)

	assert isinstance(result, ActionResult)
	assert result.error is not None
	assert 'AI step failed' in result.error
