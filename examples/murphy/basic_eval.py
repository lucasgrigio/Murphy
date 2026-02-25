"""Basic murphy evaluation example.

Usage:
    uv run python examples/murphy/basic_eval.py https://example.com

Or use the CLI directly:
    uv run murphy --url https://example.com --no-auth --max-tests 3
"""

import sys

sys.argv = [
	'murphy',
	'--url',
	sys.argv[1] if len(sys.argv) > 1 else 'https://www.prosus.com',
	'--no-auth',
	'--max-tests',
	'3',
]

from murphy.cli import main

sys.exit(main())
