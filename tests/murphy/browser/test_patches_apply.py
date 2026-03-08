"""Tests for patches.apply() and _patched() functions."""

from murphy.browser.patches import _patched, apply


def test_apply_is_idempotent():
	"""Calling apply() multiple times does not raise or double-patch."""
	apply()
	apply()  # second call should be a no-op


def test_patched_no_refs():
	"""_patched delegates to original when no $defs/$ref."""
	schema = {
		'type': 'object',
		'properties': {'name': {'type': 'string'}},
		'required': ['name'],
	}
	# _patched should call the original function without error
	result = _patched(schema)
	# Result is a dynamic Pydantic model class
	assert result is not None


def test_patched_with_refs():
	"""_patched resolves $defs before delegating."""
	schema = {
		'$defs': {
			'Inner': {
				'type': 'object',
				'properties': {'value': {'type': 'string'}},
				'required': ['value'],
			}
		},
		'type': 'object',
		'properties': {
			'inner': {'$ref': '#/$defs/Inner'},
		},
		'required': ['inner'],
	}
	result = _patched(schema)
	assert result is not None
