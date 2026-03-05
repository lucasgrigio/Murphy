import socketserver

import pytest
from pytest_httpserver import HTTPServer

from browser_use.browser import BrowserProfile, BrowserSession

# Fix for httpserver hanging on shutdown - prevent blocking on socket close
socketserver.ThreadingMixIn.block_on_close = False
socketserver.ThreadingMixIn.daemon_threads = True


class TestBrowserContext:
	"""Tests for browser context functionality using real browser instances."""

	@pytest.fixture(scope='session')
	def http_server(self):
		"""Create and provide a test HTTP server that serves static content."""
		server = HTTPServer()
		server.start()

		server.expect_request('/').respond_with_data(
			'<html><head><title>Test Home Page</title></head><body><h1>Test Home Page</h1><p>Welcome to the test site</p></body></html>',
			content_type='text/html',
		)

		yield server
		server.stop()

	@pytest.fixture(scope='session')
	def base_url(self, http_server):
		"""Return the base URL for the test HTTP server."""
		return f'http://{http_server.host}:{http_server.port}'

	@pytest.fixture(scope='module')
	async def browser_session(self):
		"""Create and provide a BrowserSession instance with security disabled."""
		browser_session = BrowserSession(
			browser_profile=BrowserProfile(
				headless=True,
				user_data_dir=None,
				keep_alive=True,
			)
		)
		await browser_session.start()
		yield browser_session
		await browser_session.kill()
		await browser_session.event_bus.stop(clear=True, timeout=5)

	def test_is_url_allowed(self):
		"""
		Test the _is_url_allowed method to verify that it correctly checks URLs against
		the allowed domains configuration.
		"""
		from bubus import EventBus

		from browser_use.browser.watchdogs.security_watchdog import SecurityWatchdog

		# Scenario 1: allowed_domains is None, any URL should be allowed.
		config1 = BrowserProfile(allowed_domains=None, headless=True, user_data_dir=None)
		context1 = BrowserSession(browser_profile=config1)
		event_bus1 = EventBus()
		watchdog1 = SecurityWatchdog(browser_session=context1, event_bus=event_bus1)
		assert watchdog1._is_url_allowed('http://anydomain.com') is True
		assert watchdog1._is_url_allowed('https://anotherdomain.org/path') is True

		# Scenario 2: allowed_domains is provided.
		allowed = ['https://example.com', 'http://example.com', 'http://*.mysite.org', 'https://*.mysite.org']
		config2 = BrowserProfile(allowed_domains=allowed, headless=True, user_data_dir=None)
		context2 = BrowserSession(browser_profile=config2)
		event_bus2 = EventBus()
		watchdog2 = SecurityWatchdog(browser_session=context2, event_bus=event_bus2)

		# URL exactly matching
		assert watchdog2._is_url_allowed('http://example.com') is True
		# URL with subdomain (should not be allowed)
		assert watchdog2._is_url_allowed('http://sub.example.com/path') is False
		# URL with subdomain for wildcard pattern (should be allowed)
		assert watchdog2._is_url_allowed('http://sub.mysite.org') is True
		# Bare domain does not match wildcard pattern (*.mysite.org requires a subdomain)
		assert watchdog2._is_url_allowed('https://mysite.org/page') is False
		# URL with port number, still allowed (port is stripped)
		assert watchdog2._is_url_allowed('http://example.com:8080') is True
		assert watchdog2._is_url_allowed('https://example.com:443') is True

		# Scenario 3: Malformed URL or empty domain
		assert watchdog2._is_url_allowed('notaurl') is False

	async def test_custom_action_with_no_arguments(self, browser_session, base_url):
		"""Test that custom actions with no arguments are handled correctly"""
		from browser_use.agent.views import ActionResult
		from browser_use.tools.registry.service import Registry

		# Create a registry
		registry = Registry()

		# Register a custom action with no arguments
		@registry.action('Some custom action with no args')
		def simple_action():
			return ActionResult(extracted_content='return some result')

		# Execute the action
		result = await registry.execute_action('simple_action', {})

		# Verify the result
		assert isinstance(result, ActionResult)
		assert result.extracted_content == 'return some result'

		# Test that the action model is created correctly
		action_model = registry.create_action_model()

		# The action should be in the model fields
		assert 'simple_action' in action_model.model_fields

		# Create an instance with the simple_action
		action_instance = action_model(simple_action={})  # type: ignore[call-arg]

		# Test that model_dump works correctly
		dumped = action_instance.model_dump(exclude_unset=True)
		assert 'simple_action' in dumped
		assert dumped['simple_action'] == {}

		# Test async version as well
		@registry.action('Async custom action with no args')
		async def async_simple_action():
			return ActionResult(extracted_content='async result')

		result = await registry.execute_action('async_simple_action', {})
		assert result.extracted_content == 'async result'

		# Test with special parameters but no regular arguments
		@registry.action('Action with only special params')
		async def special_params_only(browser_session):
			current_url = await browser_session.get_current_page_url()
			return ActionResult(extracted_content=f'Page URL: {current_url}')

		# Navigate to a known URL first so we can verify the action reads it
		from browser_use.browser.events import NavigateToUrlEvent

		event = browser_session.event_bus.dispatch(NavigateToUrlEvent(url=f'{base_url}/'))
		await event

		result = await registry.execute_action('special_params_only', {}, browser_session=browser_session)
		assert 'Page URL:' in result.extracted_content
		assert base_url in result.extracted_content
