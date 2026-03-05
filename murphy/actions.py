"""Custom agent actions for Murphy evaluation scenarios."""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlparse

from browser_use.agent.views import ActionResult

if TYPE_CHECKING:
	from browser_use.browser.session import BrowserSession
	from browser_use.tools.service import Tools


def _domain_from_url(url: str) -> str:
	"""Extract domain from URL."""
	parsed = urlparse(url)
	return parsed.hostname or url


def register_domain_access_action(tools: 'Tools', session: 'BrowserSession') -> None:  # type: ignore[type-arg]
	"""Register an action that lets the agent request access to blocked domains."""

	@tools.action(
		description=('Request access to a domain not in the allowed list. Call when navigation is blocked. Pass the full URL.'),
	)
	async def request_domain_access(url: str) -> ActionResult:
		domain = _domain_from_url(url)
		answer = input(f'\n  Agent wants to visit: {domain}\n    URL: {url}\n    Allow? [y/N]: ')
		if answer.strip().lower() in ('y', 'yes'):
			domains = session.browser_profile.allowed_domains
			if domains is None:
				session.browser_profile.allowed_domains = [domain]
			elif isinstance(domains, set):
				domains.add(domain)
			else:
				domains.append(domain)
			return ActionResult(extracted_content=f'Granted -- {domain} now allowed. Navigate to {url}.')
		return ActionResult(
			extracted_content=f'Denied -- do not visit {domain}.',
			error=f'Navigation to {domain} denied.',
		)


def register_refresh_dom_action(tools: 'Tools', session: 'BrowserSession') -> None:  # type: ignore[type-arg]
	"""Register an action that forces a fresh DOM state read without page reload."""

	@tools.action(
		description=(
			'Read the current page state without a full DOM rebuild or page reload. '
			'Returns: current URL, page title, document.readyState, number of interactive elements, and visible text length. '
			'Use this to confirm: (1) navigation landed on the right URL, (2) page has finished loading (readyState=complete), '
			'(3) page is not empty (interactive_elements > 0). '
			'Call this AFTER any action that changes the page — navigate, form submit, button click, modal open/close — '
			'before attempting to read or interact with the updated content. '
			'NOTE: this does NOT return the full DOM or element list. '
			'To verify specific text or elements are present after a UI change, follow up with search_page or find_elements.'
		),
	)
	async def refresh_dom_state() -> ActionResult:
		try:
			cdp_session = await session.get_or_create_cdp_session()
			result = await cdp_session.cdp_client.send.Runtime.evaluate(
				params={
					'expression': """
(() => {
  const selectors = [
    'a[href]', 'button', 'input:not([type="hidden"])',
    'select', 'textarea', '[role="button"]', '[role="link"]',
    '[contenteditable="true"]'
  ];
  const interactiveCount = selectors
    .map((s) => document.querySelectorAll(s).length)
    .reduce((a, b) => a + b, 0);
  const textLength = (document.body?.innerText || '').trim().length;
  const readyState = document.readyState;
  const title = document.title || '';
  const url = location.href || '';
  return { interactiveCount, textLength, readyState, title, url };
})()
""",
					'returnByValue': True,
				},
				session_id=cdp_session.session_id,
			)
			value = (result or {}).get('result', {}).get('value', {}) or {}
			interactive_count = int(value.get('interactiveCount', 0) or 0)
			text_length = int(value.get('textLength', 0) or 0)
			ready_state = str(value.get('readyState', 'unknown'))
			title = str(value.get('title', ''))
			page_url = str(value.get('url', ''))
			summary = (
				f'DOM refreshed. url={page_url} title={title!r} readyState={ready_state} '
				f'interactive_elements={interactive_count} text_length={text_length}'
			)
			return ActionResult(extracted_content=summary)
		except Exception as exc:
			return ActionResult(
				extracted_content='DOM refresh failed.',
				error=f'{type(exc).__name__}: {exc}',
			)
