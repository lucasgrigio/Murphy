import asyncio
import sys

from dotenv import load_dotenv

from browser_use import Agent
from browser_use.llm import ChatOpenAI

load_dotenv()

DEFAULT_URL = 'https://www.prosus.com'


async def main():
	url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL
	agent = Agent(
		task=f'Analyze the website {url} and summarize its content',
		llm=ChatOpenAI(model='gpt-4o'),
	)
	result = await agent.run()
	print(result)


asyncio.run(main())
