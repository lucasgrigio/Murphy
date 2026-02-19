"""Pydantic models for the Murphy evaluation pipeline."""

from typing import Literal

from pydantic import BaseModel


# ─── Shared types ─────────────────────────────────────────────────────────────

FeatureCategory = Literal[
	'navigation', 'search', 'forms', 'content_display',
	'filtering_sorting', 'media', 'authentication',
	'ecommerce', 'social', 'other'
]

TestPersona = Literal[
	'happy_path',        # standard user, expected flow
	'confused_novice',   # clicks wrong things, gets lost, misuses features
	'adversarial',       # tries to break things: XSS, injection, invalid inputs
	'edge_case',         # empty forms, special chars, long inputs, double-clicks
	'explorer',          # goes off the beaten path, tries unexpected combinations
	'impatient_user',    # clicks rapidly, doesn't wait for loads, skips steps
	'angry_user',        # rage-clicks, types frustration into fields, force-navigates
]


# ─── Phase 1: Analysis ─────────────────────────────────────────────────────────


class InteractiveElement(BaseModel):
	element_type: Literal[
		'link', 'button', 'text_input', 'search_box', 'dropdown',
		'checkbox', 'radio', 'form', 'tab', 'accordion',
		'modal_trigger', 'video_player', 'carousel', 'other'
	]
	label: str
	destination: str | None = None
	requires_auth: bool = False
	notes: str | None = None


class PageInfo(BaseModel):
	url: str
	title: str
	purpose: str
	page_type: Literal[
		'homepage', 'landing', 'product', 'listing', 'detail',
		'form', 'content', 'dashboard', 'auth', 'error', 'other'
	]
	interactive_elements: list[InteractiveElement]


class Feature(BaseModel):
	name: str
	category: FeatureCategory
	description: str
	page_url: str
	elements: list[str]
	testability: Literal['testable', 'partial', 'untestable']
	testability_reason: str | None = None
	importance: Literal['core', 'secondary', 'peripheral']


class WebsiteAnalysis(BaseModel):
	site_name: str
	category: str
	description: str
	key_pages: list[PageInfo]
	features: list[Feature]
	identified_user_flows: list[str]


# ─── Phase 2: Test Generation ──────────────────────────────────────────────────


class TestScenario(BaseModel):
	name: str
	description: str
	priority: Literal['critical', 'high', 'medium', 'low']
	feature_category: FeatureCategory
	target_feature: str
	test_persona: TestPersona
	steps_description: str
	success_criteria: str


class TestPlan(BaseModel):
	scenarios: list[TestScenario]


# ─── Phase 3: Results ──────────────────────────────────────────────────────────


class TestResult(BaseModel):
	scenario: TestScenario
	success: bool | None
	judgement: dict | None
	actions: list
	errors: list[str | None]
	duration: float
	failure_category: Literal['website_issue', 'test_limitation'] | None = None


class ReportSummary(BaseModel):
	total: int
	passed: int
	failed: int
	pass_rate: float
	website_issues: int = 0
	test_limitations: int = 0
	by_priority: dict[str, dict[str, int]]


class EvaluationReport(BaseModel):
	url: str
	timestamp: str
	analysis: WebsiteAnalysis
	results: list[TestResult]
	summary: ReportSummary
