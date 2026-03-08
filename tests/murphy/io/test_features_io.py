"""Tests for features markdown read/write roundtrips."""

import tempfile
from pathlib import Path

from murphy.io.features_io import read_features_markdown, write_features_markdown
from murphy.models import Feature, PageInfo, WebsiteAnalysis


def _make_analysis(**overrides) -> WebsiteAnalysis:
	defaults = dict(
		site_name='Acme Corp',
		category='saas',
		description='A project management tool',
		key_pages=[
			PageInfo(
				url='https://acme.com',
				title='Dashboard',
				purpose='Main dashboard',
				page_type='dashboard',
				interactive_elements=[],
			),
			PageInfo(
				url='https://acme.com/projects',
				title='Projects',
				purpose='Project listing',
				page_type='listing',
				interactive_elements=[],
			),
		],
		features=[
			Feature(
				name='Create Project',
				category='forms',
				description='Create a new project from the dashboard',
				page_url='https://acme.com/projects/new',
				elements=['New Project button', 'Project name input'],
				testability='testable',
				importance='core',
			),
			Feature(
				name='Search Projects',
				category='search',
				description='Search for projects by name',
				page_url='https://acme.com/projects',
				elements=['Search bar'],
				testability='testable',
				importance='secondary',
			),
			Feature(
				name='Export PDF',
				category='media',
				description='Export project as PDF',
				page_url='https://acme.com/projects/1',
				elements=['Export button'],
				testability='untestable',
				testability_reason='Requires file download verification',
				importance='peripheral',
			),
		],
		identified_user_flows=[
			'Create project -> Add tasks -> Assign members',
			'Search project -> Open details -> Export PDF',
		],
	)
	defaults.update(overrides)
	return WebsiteAnalysis.model_validate(defaults)


def test_write_and_read_roundtrip():
	analysis = _make_analysis()
	with tempfile.TemporaryDirectory() as tmpdir:
		path = write_features_markdown(analysis, Path(tmpdir))
		assert path.exists()

		loaded = read_features_markdown(path)
		assert loaded.site_name == analysis.site_name
		assert loaded.category == analysis.category
		assert loaded.description == analysis.description


def test_roundtrip_preserves_pages():
	analysis = _make_analysis()
	with tempfile.TemporaryDirectory() as tmpdir:
		path = write_features_markdown(analysis, Path(tmpdir))
		loaded = read_features_markdown(path)

		assert len(loaded.key_pages) == len(analysis.key_pages)
		for orig, loaded_page in zip(analysis.key_pages, loaded.key_pages):
			assert loaded_page.title == orig.title
			assert loaded_page.url == orig.url
			assert loaded_page.page_type == orig.page_type


def test_roundtrip_preserves_features():
	analysis = _make_analysis()
	with tempfile.TemporaryDirectory() as tmpdir:
		path = write_features_markdown(analysis, Path(tmpdir))
		loaded = read_features_markdown(path)

		assert len(loaded.features) == len(analysis.features)
		for orig, loaded_feat in zip(analysis.features, loaded.features):
			assert loaded_feat.name == orig.name
			assert loaded_feat.category == orig.category
			assert loaded_feat.testability == orig.testability
			assert loaded_feat.importance == orig.importance


def test_roundtrip_preserves_user_flows():
	analysis = _make_analysis()
	with tempfile.TemporaryDirectory() as tmpdir:
		path = write_features_markdown(analysis, Path(tmpdir))
		loaded = read_features_markdown(path)

		assert len(loaded.identified_user_flows) == len(analysis.identified_user_flows)


def test_roundtrip_preserves_testability_reason():
	analysis = _make_analysis()
	with tempfile.TemporaryDirectory() as tmpdir:
		path = write_features_markdown(analysis, Path(tmpdir))
		loaded = read_features_markdown(path)

		untestable = [f for f in loaded.features if f.testability == 'untestable']
		assert len(untestable) == 1
		assert untestable[0].testability_reason is not None
		assert 'download' in untestable[0].testability_reason.lower()


def test_filename_uses_domain_slug():
	analysis = _make_analysis()
	with tempfile.TemporaryDirectory() as tmpdir:
		path = write_features_markdown(analysis, Path(tmpdir))
		assert 'acme_com' in path.name


def test_write_with_no_features():
	analysis = _make_analysis(features=[])
	with tempfile.TemporaryDirectory() as tmpdir:
		path = write_features_markdown(analysis, Path(tmpdir))
		loaded = read_features_markdown(path)
		assert loaded.features == []


def test_write_with_no_user_flows():
	analysis = _make_analysis(identified_user_flows=[])
	with tempfile.TemporaryDirectory() as tmpdir:
		path = write_features_markdown(analysis, Path(tmpdir))
		loaded = read_features_markdown(path)
		assert loaded.identified_user_flows == []
