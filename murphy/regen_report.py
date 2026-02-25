"""Quick script to regenerate markdown from existing JSON report."""

from pathlib import Path

from murphy.models import EvaluationReport
from murphy.report import write_markdown_report

output_dir = Path('murphy/output')
json_data = (output_dir / 'evaluation_report.json').read_text()
report = EvaluationReport.model_validate_json(json_data)
md_path = write_markdown_report(report, output_dir)
print(f'Regenerated: {md_path}')
