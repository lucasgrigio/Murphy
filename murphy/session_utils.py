"""Session management helpers for stabilizing browser state between test runs."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
	from browser_use.browser.session import BrowserSession


async def ui_readiness_score(session: 'BrowserSession') -> tuple[int, int]:
	"""Return (interactive_count, text_length) from the current page."""
	cdp_session = await session.get_or_create_cdp_session()
	result = await cdp_session.cdp_client.send.Runtime.evaluate(
		params={
			'expression': """
(() => {
  const interactiveSelectors = [
    'a[href]', 'button', 'input:not([type="hidden"])',
    'select', 'textarea', '[role="button"]', '[role="link"]',
    '[contenteditable="true"]'
  ];
  const interactiveCount = interactiveSelectors
    .map((selector) => document.querySelectorAll(selector).length)
    .reduce((acc, count) => acc + count, 0);
  const textLength = (document.body?.innerText || '').trim().length;
  return { interactiveCount, textLength };
})()
""",
			'returnByValue': True,
		},
		session_id=cdp_session.session_id,
	)
	value = (result or {}).get('result', {}).get('value', {}) or {}
	interactive_count = int(value.get('interactiveCount', 0) or 0)
	text_length = int(value.get('textLength', 0) or 0)
	return interactive_count, text_length


async def wait_until_ui_ready(session: 'BrowserSession', url: str) -> bool:
	"""Adaptive polling with early exit — avoids long fixed sleeps."""
	poll_delays = [0.3, 0.6, 0.9, 1.2, 1.5]
	for delay in poll_delays:
		try:
			interactive_count, text_length = await ui_readiness_score(session)
			if interactive_count >= 3 or text_length >= 120:
				return True
		except Exception:
			pass
		# Force a fresh CDP round-trip
		try:
			cdp_session = await session.get_or_create_cdp_session()
			await cdp_session.cdp_client.send.Runtime.evaluate(
				params={'expression': 'document.readyState', 'returnByValue': True},
				session_id=cdp_session.session_id,
			)
		except Exception:
			pass
		await asyncio.sleep(delay)
	return False


async def enforce_single_tab(session: 'BrowserSession', url: str) -> None:
	"""Close extra tabs to prevent agent drift across duplicate tabs."""
	pages = await session.get_pages()
	if not pages:
		await session.navigate_to(url, new_tab=True)
		return

	# Keep the last page as the target — simplest heuristic
	target_page = pages[-1]
	for page in pages:
		if page is target_page:
			continue
		try:
			await session.close_page(page)
		except Exception:
			pass


async def prepare_session_for_task(
	session: 'BrowserSession',
	url: str,
	*,
	force_navigate: bool = False,
) -> bool:
	"""Stabilize session without unnecessary reloads.

	Preserves the current logged-in page if it is already interactive.
	If the CDP WebSocket is dead, kills and restarts the session first.
	"""
	# CDP recovery: if the websocket died, restart the session
	if not session.is_cdp_connected:
		try:
			await session.kill()
		except Exception:
			pass
		await session.start()
		force_navigate = True

	await enforce_single_tab(session, url)

	if not force_navigate:
		try:
			interactive_count, text_length = await ui_readiness_score(session)
			if interactive_count >= 3 or text_length >= 120:
				return True
		except Exception:
			pass

	try:
		await session.navigate_to(url)
	except Exception:
		return False

	await enforce_single_tab(session, url)
	return await wait_until_ui_ready(session, url)
