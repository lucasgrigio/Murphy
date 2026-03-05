"""
Test that clicking disabled elements returns a validation error instead of silently failing.

Verifies both `disabled` attribute and `aria-disabled="true"` are caught by the
watchdog's _click_element_node_impl safety check.
"""

import pytest

from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.browser.events import ClickElementEvent

DISABLED_BUTTONS_HTML = """
<!DOCTYPE html>
<html>
<head><title>Disabled Buttons Test</title></head>
<body>
	<form>
		<input type="text" id="name" placeholder="Enter name" />
		<button disabled id="submit-btn">Submit</button>
		<button aria-disabled="true" id="next-btn">Next</button>
		<button id="enabled-btn">Enabled Action</button>
	</form>
</body>
</html>
"""


@pytest.fixture
async def browser_session():
	session = BrowserSession(
		browser_profile=BrowserProfile(
			headless=True,
			user_data_dir=None,
			keep_alive=True,
		)
	)
	await session.start()
	yield session
	await session.kill()


@pytest.fixture
def page_url(httpserver):
	for _ in range(10):
		httpserver.expect_ordered_request('/disabled-test').respond_with_data(
			DISABLED_BUTTONS_HTML,
			content_type='text/html',
		)
	return httpserver.url_for('/disabled-test')


class TestDisabledButtons:
	async def test_click_disabled_button_returns_validation_error(self, browser_session, page_url):
		"""Clicking a button with disabled attribute should return a validation_error dict."""
		# Navigate to page
		await browser_session.navigate_to(page_url)

		# Get browser state to populate the DOM tree
		state = await browser_session.get_browser_state_summary(include_screenshot=False)
		assert state.dom_state is not None

		# Find the disabled button by walking the selector_map + the full DOM
		# The disabled button won't be in selector_map (filtered by serializer), so
		# we resolve it via CDP using JS to get the backendNodeId
		cdp_session = await browser_session.get_or_create_cdp_session()
		result = await cdp_session.cdp_client.send.Runtime.evaluate(
			params={
				'expression': 'document.getElementById("submit-btn")',
			},
			session_id=cdp_session.session_id,
		)
		object_id = result['result']['objectId']

		# Get the DOM node for this object
		dom_result = await cdp_session.cdp_client.send.DOM.describeNode(
			params={'objectId': object_id},
			session_id=cdp_session.session_id,
		)
		backend_node_id = dom_result['node']['backendNodeId']

		# Build a minimal EnhancedDOMTreeNode-like object for the disabled button
		from browser_use.dom.views import EnhancedDOMTreeNode, NodeType

		disabled_node = EnhancedDOMTreeNode(
			node_id=0,
			backend_node_id=backend_node_id,
			node_type=NodeType.ELEMENT_NODE,
			node_name='button',
			node_value='',
			attributes={'disabled': '', 'id': 'submit-btn'},
			is_scrollable=False,
			is_visible=True,
			absolute_position=None,
			target_id=cdp_session.target_id,
			frame_id=None,
			session_id=cdp_session.session_id,
			content_document=None,
			shadow_root_type=None,
			shadow_roots=None,
			parent_node=None,
			children_nodes=None,
			ax_node=None,
			snapshot_node=None,
		)

		# Dispatch ClickElementEvent directly
		event = browser_session.event_bus.dispatch(ClickElementEvent(node=disabled_node))
		await event
		click_result = await event.event_result(raise_if_any=True, raise_if_none=False)

		assert isinstance(click_result, dict), f'Expected dict result, got {type(click_result)}: {click_result}'
		assert 'validation_error' in click_result, f'Expected validation_error in result: {click_result}'
		assert 'disabled' in click_result['validation_error'].lower(), (
			f'Expected "disabled" in error message: {click_result["validation_error"]}'
		)

	async def test_click_aria_disabled_button_returns_validation_error(self, browser_session, page_url):
		"""Clicking a button with aria-disabled="true" should also return a validation_error dict."""
		await browser_session.navigate_to(page_url)
		await browser_session.get_browser_state_summary(include_screenshot=False)

		cdp_session = await browser_session.get_or_create_cdp_session()
		result = await cdp_session.cdp_client.send.Runtime.evaluate(
			params={'expression': 'document.getElementById("next-btn")'},
			session_id=cdp_session.session_id,
		)
		object_id = result['result']['objectId']

		dom_result = await cdp_session.cdp_client.send.DOM.describeNode(
			params={'objectId': object_id},
			session_id=cdp_session.session_id,
		)
		backend_node_id = dom_result['node']['backendNodeId']

		from browser_use.dom.views import EnhancedDOMTreeNode, NodeType

		aria_disabled_node = EnhancedDOMTreeNode(
			node_id=0,
			backend_node_id=backend_node_id,
			node_type=NodeType.ELEMENT_NODE,
			node_name='button',
			node_value='',
			attributes={'aria-disabled': 'true', 'id': 'next-btn'},
			is_scrollable=False,
			is_visible=True,
			absolute_position=None,
			target_id=cdp_session.target_id,
			frame_id=None,
			session_id=cdp_session.session_id,
			content_document=None,
			shadow_root_type=None,
			shadow_roots=None,
			parent_node=None,
			children_nodes=None,
			ax_node=None,
			snapshot_node=None,
		)

		event = browser_session.event_bus.dispatch(ClickElementEvent(node=aria_disabled_node))
		await event
		click_result = await event.event_result(raise_if_any=True, raise_if_none=False)

		assert isinstance(click_result, dict), f'Expected dict result, got {type(click_result)}: {click_result}'
		assert 'validation_error' in click_result, f'Expected validation_error in result: {click_result}'
		assert 'disabled' in click_result['validation_error'].lower(), (
			f'Expected "disabled" in error message: {click_result["validation_error"]}'
		)

	async def test_click_enabled_button_no_disabled_error(self, browser_session, page_url):
		"""Clicking an enabled button should NOT return a disabled validation error."""
		await browser_session.navigate_to(page_url)
		await browser_session.get_browser_state_summary(include_screenshot=False)

		cdp_session = await browser_session.get_or_create_cdp_session()
		result = await cdp_session.cdp_client.send.Runtime.evaluate(
			params={'expression': 'document.getElementById("enabled-btn")'},
			session_id=cdp_session.session_id,
		)
		object_id = result['result']['objectId']

		dom_result = await cdp_session.cdp_client.send.DOM.describeNode(
			params={'objectId': object_id},
			session_id=cdp_session.session_id,
		)
		backend_node_id = dom_result['node']['backendNodeId']

		from browser_use.dom.views import EnhancedDOMTreeNode, NodeType

		enabled_node = EnhancedDOMTreeNode(
			node_id=0,
			backend_node_id=backend_node_id,
			node_type=NodeType.ELEMENT_NODE,
			node_name='button',
			node_value='',
			attributes={'id': 'enabled-btn'},
			is_scrollable=False,
			is_visible=True,
			absolute_position=None,
			target_id=cdp_session.target_id,
			frame_id=None,
			session_id=cdp_session.session_id,
			content_document=None,
			shadow_root_type=None,
			shadow_roots=None,
			parent_node=None,
			children_nodes=None,
			ax_node=None,
			snapshot_node=None,
		)

		event = browser_session.event_bus.dispatch(ClickElementEvent(node=enabled_node))
		await event
		click_result = await event.event_result(raise_if_any=True, raise_if_none=False)

		# Should not be a validation error dict with 'disabled'
		if isinstance(click_result, dict) and 'validation_error' in click_result:
			assert 'disabled' not in click_result['validation_error'].lower(), (
				f'Enabled button should not trigger disabled validation error: {click_result}'
			)
