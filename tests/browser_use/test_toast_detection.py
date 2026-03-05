"""
Test that transient toast/notification elements are captured by the MutationObserver
and surfaced in BrowserStateSummary.toast_messages.

Usage:
	uv run pytest tests/browser_use/test_toast_detection.py -v -s
"""

import asyncio

import pytest
from pytest_httpserver import HTTPServer

from browser_use.browser import BrowserSession
from browser_use.browser.profile import BrowserProfile


@pytest.fixture(scope='session')
def http_server():
	server = HTTPServer()
	server.start()

	# Page that dynamically inserts toast notifications via JS
	server.expect_request('/toast-test').respond_with_data(
		"""
		<html>
		<head><title>Toast Detection Test</title></head>
		<body>
			<h1>Toast Detection Test</h1>
			<button id="trigger-alert" onclick="showToast('alert')">Show Alert Toast</button>
			<button id="trigger-live" onclick="showToast('live')">Show Live Toast</button>
			<button id="trigger-vanish" onclick="showToast('vanish')">Show Vanishing Toast</button>
			<div id="toast-container"></div>

			<script>
			function showToast(type) {
				var container = document.getElementById('toast-container');
				var toast = document.createElement('div');

				if (type === 'alert') {
					toast.setAttribute('role', 'alert');
					toast.textContent = 'Item deleted successfully';
				} else if (type === 'live') {
					toast.setAttribute('aria-live', 'assertive');
					toast.textContent = 'Connection restored';
				} else if (type === 'vanish') {
					toast.setAttribute('role', 'alert');
					toast.textContent = 'Temporary notification';
					// Remove after 500ms
					setTimeout(function() {
						if (toast.parentNode) toast.parentNode.removeChild(toast);
					}, 500);
				}

				container.appendChild(toast);
			}
			</script>
		</body>
		</html>
		""",
		content_type='text/html',
	)

	yield server
	server.stop()


@pytest.fixture(scope='session')
def base_url(http_server):
	return f'http://{http_server.host}:{http_server.port}'


async def _setup_session_and_navigate(base_url: str) -> BrowserSession:
	"""Create a fresh browser session and navigate to the toast test page."""
	session = BrowserSession(
		browser_profile=BrowserProfile(
			headless=True,
			user_data_dir=None,
			keep_alive=True,
		)
	)
	await session.start()

	from browser_use.tools.service import Tools

	tools = Tools()
	await tools.navigate(url=f'{base_url}/toast-test', new_tab=False, browser_session=session)
	await asyncio.sleep(0.5)

	# First state request injects the toast observer
	await session.get_browser_state_summary(include_screenshot=False)
	await asyncio.sleep(0.3)

	return session


async def _trigger_toast(session: BrowserSession, toast_type: str) -> None:
	"""Trigger a toast on the page via JS."""
	cdp_session = await session.get_or_create_cdp_session(focus=True)
	await cdp_session.cdp_client.send.Runtime.evaluate(
		params={'expression': f"showToast('{toast_type}')", 'returnByValue': True},
		session_id=cdp_session.session_id,
	)


class TestToastDetection:
	async def test_toast_role_alert_captured(self, base_url):
		"""Toast with role='alert' should be captured in toast_messages."""
		session = await _setup_session_and_navigate(base_url)
		try:
			await _trigger_toast(session, 'alert')
			await asyncio.sleep(0.3)

			state = await session.get_browser_state_summary(include_screenshot=False)
			assert 'Item deleted successfully' in state.toast_messages, (
				f'Expected "Item deleted successfully" in toast_messages, got: {state.toast_messages}'
			)
		finally:
			await session.kill()
			await session.event_bus.stop(clear=True, timeout=5)

	async def test_toast_aria_live_captured(self, base_url):
		"""Toast with aria-live='assertive' should be captured."""
		session = await _setup_session_and_navigate(base_url)
		try:
			await _trigger_toast(session, 'live')
			await asyncio.sleep(0.3)

			state = await session.get_browser_state_summary(include_screenshot=False)
			assert 'Connection restored' in state.toast_messages, (
				f'Expected "Connection restored" in toast_messages, got: {state.toast_messages}'
			)
		finally:
			await session.kill()
			await session.event_bus.stop(clear=True, timeout=5)

	async def test_toast_cleared_after_harvest(self, base_url):
		"""After harvesting, toast_messages should be empty on the next state read."""
		session = await _setup_session_and_navigate(base_url)
		try:
			await _trigger_toast(session, 'alert')
			await asyncio.sleep(0.3)

			# First harvest
			state1 = await session.get_browser_state_summary(include_screenshot=False)
			assert len(state1.toast_messages) > 0, 'First state should have toast messages'

			# Second state without triggering new toasts — should be empty
			state2 = await session.get_browser_state_summary(include_screenshot=False)
			assert len(state2.toast_messages) == 0, (
				f'Second state should have empty toast_messages after harvest, got: {state2.toast_messages}'
			)
		finally:
			await session.kill()
			await session.event_bus.stop(clear=True, timeout=5)

	async def test_toast_survives_disappearance(self, base_url):
		"""Toast that removes itself after 500ms should still be captured by the observer."""
		session = await _setup_session_and_navigate(base_url)
		try:
			await _trigger_toast(session, 'vanish')

			# Wait for the toast to appear AND disappear (it removes itself after 500ms)
			await asyncio.sleep(1.0)

			# The observer should have captured it even though it's gone from the DOM
			state = await session.get_browser_state_summary(include_screenshot=False)
			assert 'Temporary notification' in state.toast_messages, (
				f'Expected "Temporary notification" in toast_messages even after removal, got: {state.toast_messages}'
			)
		finally:
			await session.kill()
			await session.event_bus.stop(clear=True, timeout=5)
