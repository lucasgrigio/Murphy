"""Tests for custom browser action helpers."""

from murphy.browser.actions import _domain_from_url

# ─── _domain_from_url ────────────────────────────────────────────────────────


def test_domain_from_url_standard():
	assert _domain_from_url('https://example.com/page') == 'example.com'


def test_domain_from_url_with_port():
	assert _domain_from_url('http://localhost:3000/api') == 'localhost'


def test_domain_from_url_subdomain():
	assert _domain_from_url('https://sub.domain.example.com/path') == 'sub.domain.example.com'


def test_domain_from_url_no_scheme():
	"""If no scheme, urlparse can't extract hostname — returns the input."""
	result = _domain_from_url('example.com')
	assert result == 'example.com'


def test_domain_from_url_ip():
	assert _domain_from_url('http://192.168.1.1:8080/test') == '192.168.1.1'
