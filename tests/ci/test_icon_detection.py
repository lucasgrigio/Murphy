"""
Test that icon-like elements (SVG, <i>, <img>) with aria-label are detected as interactive,
and that widened icon size bounds (8-64px) work correctly.

Usage:
	uv run pytest tests/ci/test_icon_detection.py -v -s
"""

import asyncio

import pytest
from pytest_httpserver import HTTPServer

from browser_use.browser import BrowserSession
from browser_use.browser.profile import BrowserProfile


@pytest.fixture(scope='module')
def http_server():
	server = HTTPServer()
	server.start()

	# Page with icon elements that should be detected as interactive
	server.expect_request('/icon-test').respond_with_data(
		"""
		<html>
		<head><title>Icon Detection Test</title></head>
		<body>
			<h1>Icon Detection Test</h1>

			<!-- SVG with aria-label: should be interactive -->
			<svg aria-label="Delete" width="24" height="24" viewBox="0 0 24 24">
				<path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12z"/>
			</svg>

			<!-- <i> tag with aria-label: should be interactive -->
			<i aria-label="Trash" class="fa fa-trash" style="display:inline-block;width:16px;height:16px;"></i>

			<!-- <img> with aria-label: should be interactive -->
			<img aria-label="Settings" src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7" width="20" height="20">

			<!-- 56px icon button: should be interactive with widened range -->
			<div role="button" style="width:56px;height:56px;cursor:pointer;" aria-label="Large Action">+</div>

			<!-- 8px micro icon with class: should be interactive with widened range -->
			<span class="micro-icon" role="button" style="display:inline-block;width:8px;height:8px;">x</span>

			<!-- <nav> with aria-label but 600px wide: should NOT be interactive (false positive guard) -->
			<nav aria-label="Main Navigation" style="width:600px;height:60px;">
				<a href="/home">Home</a>
			</nav>

			<!-- Plain div with no interactive signals: should NOT be interactive -->
			<div style="width:24px;height:24px;">decorative</div>
		</body>
		</html>
		""",
		content_type='text/html',
	)

	yield server
	server.stop()


@pytest.fixture(scope='module')
def base_url(http_server):
	return f'http://{http_server.host}:{http_server.port}'


@pytest.fixture(scope='module')
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
	await session.event_bus.stop(clear=True, timeout=5)


@pytest.fixture(scope='module')
async def icon_page_state(browser_session, base_url):
	"""Navigate to icon test page and return the browser state."""
	from browser_use.tools.service import Tools

	tools = Tools()
	await tools.navigate(url=f'{base_url}/icon-test', new_tab=False, browser_session=browser_session)
	await asyncio.sleep(0.5)

	state = await browser_session.get_browser_state_summary(
		include_screenshot=False,
		include_recent_events=False,
	)
	return state


def _find_element_by_attr(selector_map, attr_name, attr_value):
	"""Find an element in the selector map by attribute name and value."""
	for idx, el in selector_map.items():
		if el.attributes and el.attributes.get(attr_name) == attr_value:
			return idx, el
	return None, None


class TestIconDetection:
	async def test_svg_with_aria_label_detected(self, icon_page_state):
		"""SVG element with aria-label='Delete' should be in selector_map."""
		selector_map = icon_page_state.dom_state.selector_map
		idx, el = _find_element_by_attr(selector_map, 'aria-label', 'Delete')
		assert el is not None, (
			f'SVG with aria-label="Delete" not found in selector_map. '
			f'Elements: {[(i, e.tag_name, e.attributes) for i, e in selector_map.items()]}'
		)
		assert el.tag_name.lower() == 'svg'

	async def test_i_tag_with_aria_label_detected(self, icon_page_state):
		"""<i> tag with aria-label='Trash' should be in selector_map."""
		selector_map = icon_page_state.dom_state.selector_map
		idx, el = _find_element_by_attr(selector_map, 'aria-label', 'Trash')
		assert el is not None, (
			f'<i> with aria-label="Trash" not found in selector_map. '
			f'Elements: {[(i, e.tag_name, e.attributes) for i, e in selector_map.items()]}'
		)
		assert el.tag_name.lower() == 'i'

	async def test_img_with_aria_label_detected(self, icon_page_state):
		"""<img> with aria-label='Settings' should be in selector_map."""
		selector_map = icon_page_state.dom_state.selector_map
		idx, el = _find_element_by_attr(selector_map, 'aria-label', 'Settings')
		assert el is not None, (
			f'<img> with aria-label="Settings" not found in selector_map. '
			f'Elements: {[(i, e.tag_name, e.attributes) for i, e in selector_map.items()]}'
		)
		assert el.tag_name.lower() == 'img'

	async def test_56px_icon_button_detected(self, icon_page_state):
		"""56px div with role='button' should be in selector_map (widened 8-64px range)."""
		selector_map = icon_page_state.dom_state.selector_map
		idx, el = _find_element_by_attr(selector_map, 'aria-label', 'Large Action')
		assert el is not None, (
			f'56px button with aria-label="Large Action" not found in selector_map. '
			f'Elements: {[(i, e.tag_name, e.attributes) for i, e in selector_map.items()]}'
		)

	async def test_nav_with_aria_label_not_interactive(self, icon_page_state):
		"""<nav> with aria-label but 600px wide should NOT be in selector_map (no false positives)."""
		selector_map = icon_page_state.dom_state.selector_map
		idx, el = _find_element_by_attr(selector_map, 'aria-label', 'Main Navigation')
		# nav itself should not appear — only its child <a> link should
		assert el is None or el.tag_name.lower() != 'nav', (
			f'<nav> element should not be in selector_map as interactive. '
			f'Found: tag={el.tag_name if el else "N/A"}'
		)
