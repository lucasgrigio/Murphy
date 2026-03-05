import logging

from browser_use.telemetry.views import BaseTelemetryEvent
from browser_use.utils import singleton

logger = logging.getLogger(__name__)


@singleton
class ProductTelemetry:
	"""
	Telemetry stub — no data is collected or sent.

	The upstream browser-use library shipped with PostHog telemetry that sent
	anonymous usage data to the browser-use project. Murphy does not use this;
	the PostHog integration has been removed entirely.
	"""

	_curr_user_id = None

	def __init__(self) -> None:
		self._posthog_client = None
		logger.debug('Telemetry disabled')

	def capture(self, event: BaseTelemetryEvent) -> None:
		pass

	def flush(self) -> None:
		pass

	@property
	def user_id(self) -> str:
		return 'DISABLED'
