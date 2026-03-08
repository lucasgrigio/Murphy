"""Quick script to regenerate markdown from existing JSON report."""

import logging
from pathlib import Path

from murphy.io.report import write_markdown_report
from murphy.models import EvaluationReport

logger = logging.getLogger(__name__)

output_dir = Path('murphy/output')
json_data = (output_dir / 'evaluation_report.json').read_text()
report = EvaluationReport.model_validate_json(json_data)
md_path = write_markdown_report(report, output_dir)
logger.info('Regenerated: %s', md_path)
