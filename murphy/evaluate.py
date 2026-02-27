"""Murphy evaluate — backward-compatible re-exports.

All logic has been decomposed into focused modules:
- murphy.analysis — website analysis
- murphy.generation — test plan generation
- murphy.execution — test execution
- murphy.quality — plan/scenario validation
- murphy.summary — results classification and reporting
- murphy.prompts — all LLM prompt text
"""

import argparse
import asyncio
from pathlib import Path

from murphy.analysis import analyze_website
from murphy.execution import execute_tests, execute_tests_with_session
from murphy.generation import explore_and_generate_plan, generate_tests
from murphy.summary import build_summary, classify_failure, generate_executive_summary, write_reports_and_print


# Backward-compat wrapper: old signature was (url, llm, browser_session, goal=None)
# New analyze_website signature is (url, llm, category=None, goal=None, browser_session=None)
async def analyze_with_session(url, llm, browser_session, goal=None):
	"""Backward-compat alias for analyze_website with an existing session."""
	return await analyze_website(url, llm, browser_session=browser_session, goal=goal)


__all__ = [
	'analyze_website',
	'analyze_with_session',
	'build_summary',
	'classify_failure',
	'execute_tests',
	'execute_tests_with_session',
	'explore_and_generate_plan',
	'generate_executive_summary',
	'generate_tests',
]


# ─── Legacy main entry point ──────────────────────────────────────────────────


async def main():
	from browser_use.llm import ChatOpenAI
	from murphy.models import WebsiteAnalysis
	from murphy.test_plan_io import load_test_plan, save_test_plan

	parser = argparse.ArgumentParser(description='Murphy — AI-driven website evaluation')
	parser.add_argument('url', nargs='?', default='https://www.prosus.com', help='Website URL to evaluate')
	parser.add_argument('--category', help='Site category hint (ecommerce, saas, content, social)')
	parser.add_argument('--model', default='gpt-5-mini', help='OpenAI model for agent tasks (default: gpt-5-mini)')
	parser.add_argument('--judge-model', default='gpt-4o', help='OpenAI model for judging verdicts (default: gpt-4o)')
	parser.add_argument('--max-tests', type=int, default=8, help='Max test scenarios (default: 8)')
	parser.add_argument('--output-dir', default='./murphy/output', help='Output directory for reports')
	parser.add_argument('--goal', help='Free-text goal to bias test generation')
	parser.add_argument('--plan', help='Path to existing YAML test plan (skips analysis + test generation)')
	parser.add_argument('--no-ui', action='store_true', help='Skip interactive review UI, run all phases directly')
	args = parser.parse_args()

	llm = ChatOpenAI(model=args.model)
	output_dir = Path(args.output_dir)
	output_dir.mkdir(parents=True, exist_ok=True)

	if args.plan:
		plan_path = Path(args.plan)
		url, test_plan = load_test_plan(plan_path)
		if url != args.url:
			print(f'WARNING: Plan URL ({url}) differs from positional url ({args.url}). Using positional.')
		print(f'Loaded {len(test_plan.scenarios)} scenarios from {plan_path}')
		analysis = WebsiteAnalysis(
			site_name=args.url,
			category='unknown',
			description='Loaded from plan file',
			key_pages=[],
			features=[],
			identified_user_flows=[],
		)
	else:
		# Phase 1
		analysis = await analyze_website(args.url, llm, args.category)

		# Phase 2
		test_plan = await generate_tests(args.url, analysis, llm, args.max_tests, goal=args.goal)

		# Save test plan to YAML
		plan_path = save_test_plan(args.url, test_plan, output_dir)
		print(f'\n  Test plan saved: {plan_path}')

	def _on_test_complete(results: list) -> None:
		write_reports_and_print(args.url, analysis, results, output_dir)

	if args.no_ui:
		# Direct execution (original behavior)
		results = await execute_tests(args.url, test_plan, llm, save_callback=_on_test_complete)
		# Generate executive summary for the final report
		try:
			exec_summary = await generate_executive_summary(args.url, analysis, results, build_summary(results), llm)
		except Exception as e:
			print(f'  Warning: Could not generate executive summary: {e}')
			exec_summary = None
		write_reports_and_print(args.url, analysis, results, output_dir, executive_summary=exec_summary)
		return

	# Interactive UI mode — start server for test plan review
	from murphy.server import ServerState, start_server

	async def _execute_with_progress(plan, state: 'ServerState') -> list:
		"""Wrapper that updates server state as tests execute."""
		return await execute_tests(args.url, plan, llm, progress_state=state, save_callback=_on_test_complete)

	state = ServerState(
		url=args.url,
		analysis=analysis,
		test_plan=test_plan,
		execute_fn=_execute_with_progress,
	)
	state.build_summary_fn = build_summary

	runner, port = await start_server(state)

	print('  Press Ctrl+C to stop the server.\n')
	try:
		# Keep alive until Ctrl+C or execution completes and user is done
		while True:
			await asyncio.sleep(1)
			# After execution is done, write reports (once)
			if state.done and state.results and not getattr(state, '_reports_written', False):
				try:
					exec_summary = await generate_executive_summary(
						args.url, analysis, state.results, build_summary(state.results), llm
					)
				except Exception as e:
					print(f'  Warning: Could not generate executive summary: {e}')
					exec_summary = None
				write_reports_and_print(args.url, analysis, state.results, output_dir, executive_summary=exec_summary)
				state._reports_written = True  # type: ignore[attr-defined]
	except KeyboardInterrupt:
		pass
	finally:
		await runner.cleanup()


if __name__ == '__main__':
	asyncio.run(main())
