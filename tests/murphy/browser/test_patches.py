"""Tests for browser_use schema resolution monkey-patch."""

from murphy.browser.patches import _resolve_refs

# ─── _resolve_refs ────────────────────────────────────────────────────────────


def test_resolve_refs_no_refs():
	schema = {'type': 'object', 'properties': {'name': {'type': 'string'}}}
	result = _resolve_refs(schema)
	assert result == {'type': 'object', 'properties': {'name': {'type': 'string'}}}


def test_resolve_refs_simple_ref():
	schema = {
		'$defs': {
			'Address': {'type': 'object', 'properties': {'city': {'type': 'string'}}},
		},
		'type': 'object',
		'properties': {
			'address': {'$ref': '#/$defs/Address'},
		},
	}
	result = _resolve_refs(schema)
	assert '$defs' not in result
	assert '$ref' not in result['properties']['address']
	assert result['properties']['address']['type'] == 'object'
	assert result['properties']['address']['properties']['city'] == {'type': 'string'}


def test_resolve_refs_nested_ref():
	schema = {
		'$defs': {
			'Inner': {'type': 'string'},
			'Outer': {'type': 'object', 'properties': {'value': {'$ref': '#/$defs/Inner'}}},
		},
		'type': 'object',
		'properties': {
			'outer': {'$ref': '#/$defs/Outer'},
		},
	}
	result = _resolve_refs(schema)
	assert result['properties']['outer']['properties']['value']['type'] == 'string'


def test_resolve_refs_array_items():
	schema = {
		'$defs': {
			'Item': {'type': 'string'},
		},
		'type': 'array',
		'items': {'$ref': '#/$defs/Item'},
	}
	result = _resolve_refs(schema)
	assert result['items']['type'] == 'string'


def test_resolve_refs_list_input():
	schema = {
		'$defs': {'Val': {'type': 'number'}},
		'type': 'object',
		'properties': {
			'values': {'type': 'array', 'items': [{'$ref': '#/$defs/Val'}, {'type': 'string'}]},
		},
	}
	result = _resolve_refs(schema)
	items = result['properties']['values']['items']
	assert isinstance(items, list)
	assert items[0]['type'] == 'number'
	assert items[1]['type'] == 'string'


def test_resolve_refs_definitions_key():
	"""Also works with 'definitions' instead of '$defs'."""
	schema = {
		'definitions': {
			'Thing': {'type': 'integer'},
		},
		'properties': {
			'thing': {'$ref': '#/definitions/Thing'},
		},
	}
	result = _resolve_refs(schema)
	assert 'definitions' not in result
	assert result['properties']['thing']['type'] == 'integer'


def test_resolve_refs_preserves_extra_fields():
	"""Fields alongside $ref are merged into the resolved output."""
	schema = {
		'$defs': {
			'Base': {'type': 'object', 'properties': {'a': {'type': 'string'}}},
		},
		'properties': {
			'item': {'$ref': '#/$defs/Base', 'description': 'A base item'},
		},
	}
	result = _resolve_refs(schema)
	assert result['properties']['item']['description'] == 'A base item'
	assert result['properties']['item']['type'] == 'object'
