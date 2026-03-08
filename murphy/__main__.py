"""Allow running as: python -m murphy --url <url>"""

import sys

from murphy.api.cli import main

sys.exit(main())
