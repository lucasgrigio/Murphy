"""Tests for murphy fixture file generation."""

import tempfile
from pathlib import Path
from unittest.mock import patch

from murphy.fixtures import ensure_dummy_fixture_files


def test_ensure_dummy_fixture_files_creates_files():
	with tempfile.TemporaryDirectory() as tmpdir:
		fixtures_dir = Path(tmpdir) / 'fixtures'
		with (
			patch('murphy.fixtures.FIXTURES_DIR', fixtures_dir),
			patch('murphy.fixtures.DUMMY_FILE_PATH', fixtures_dir / 'dummy.txt'),
			patch('murphy.fixtures.DUMMY_CSV_PATH', fixtures_dir / 'dummy.csv'),
			patch('murphy.fixtures.DUMMY_PDF_PATH', fixtures_dir / 'dummy.pdf'),
			patch('murphy.fixtures.DUMMY_EXE_PATH', fixtures_dir / 'dummy.exe'),
			patch('murphy.fixtures.DUMMY_DOCX_PATH', fixtures_dir / 'dummy.docx'),
		):
			paths = ensure_dummy_fixture_files()
			assert len(paths) == 5
			for p in paths:
				assert p.exists()
				assert p.stat().st_size > 0


def test_ensure_dummy_fixture_files_idempotent():
	with tempfile.TemporaryDirectory() as tmpdir:
		fixtures_dir = Path(tmpdir) / 'fixtures'
		with (
			patch('murphy.fixtures.FIXTURES_DIR', fixtures_dir),
			patch('murphy.fixtures.DUMMY_FILE_PATH', fixtures_dir / 'dummy.txt'),
			patch('murphy.fixtures.DUMMY_CSV_PATH', fixtures_dir / 'dummy.csv'),
			patch('murphy.fixtures.DUMMY_PDF_PATH', fixtures_dir / 'dummy.pdf'),
			patch('murphy.fixtures.DUMMY_EXE_PATH', fixtures_dir / 'dummy.exe'),
			patch('murphy.fixtures.DUMMY_DOCX_PATH', fixtures_dir / 'dummy.docx'),
		):
			paths1 = ensure_dummy_fixture_files()
			paths2 = ensure_dummy_fixture_files()
			assert [p.name for p in paths1] == [p.name for p in paths2]
