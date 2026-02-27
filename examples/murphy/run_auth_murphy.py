"""Thin wrapper — equivalent to: murphy --url https://work.toqan.ai --auth"""

import sys

sys.argv = [
	'murphy',
	'--url',
	'https://work.toqan.ai',
	'--auth',
	'--max-tests',
	'8',
]

from murphy.cli import main

sys.exit(main())
