"""Murphy — website analysis (Phase 1 of evaluation)."""

import sys

from browser_use import Agent
from browser_use.browser.session import BrowserSession
from browser_use.llm import ChatOpenAI
from murphy.models import WebsiteAnalysis
from murphy.prompts import build_analysis_prompt


async def analyze_website(
	url: str,
	llm: ChatOpenAI,
	category: str | None = None,
	goal: str | None = None,
	browser_session: BrowserSession | None = None,
) -> WebsiteAnalysis:
	"""Analyze a website to discover features and pages.

	When browser_session is None, creates a temporary agent (unauthenticated).
	When provided, reuses the session (authenticated).
	"""
	print(f'\n{"=" * 60}')
	print(f'Phase 1: Analyzing {url}')
	print(f'{"=" * 60}\n')

	is_authenticated = browser_session is not None
	task_prompt = build_analysis_prompt(url, category, goal, is_authenticated)

	agent_kwargs: dict = {
		'task': task_prompt,
		'llm': llm,
		'output_model_schema': WebsiteAnalysis,
		'max_actions_per_step': 3,
	}
	if browser_session is not None:
		agent_kwargs['browser_session'] = browser_session

	agent = Agent(**agent_kwargs)
	history = await agent.run(max_steps=30)

	result = history.final_result()
	if not result:
		if is_authenticated:
			raise RuntimeError('Analysis agent returned no result')
		print('ERROR: Analysis agent returned no result')
		sys.exit(1)

	analysis = WebsiteAnalysis.model_validate_json(result)
	print(f'\nAnalysis complete: {analysis.site_name} ({analysis.category})')
	print(f'  Pages found: {len(analysis.key_pages)}')
	print(f'  Features found: {len(analysis.features)}')
	print(f'  User flows: {len(analysis.identified_user_flows)}')
	return analysis
