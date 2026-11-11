"""Exporter comments, never commands or geometry defaults.

A unique decimal precision declaration can bound explicit partial arc diagnostics;
it never changes source coordinates or curve parameters.
"""
import re
from .model import HeaderField, SourceRef
from .container import ParseError

PREFIX = re.compile(r'\s*([a-zA-Z_][a-zA-Z_0-9]*)(?:\s+|:)', re.ASCII)
KEYS = {'archive_version', 'decimal_places', 'null', 'null_keyword', 'do_null',
        'dereference', 'project', 'model_attributes_mode', 'ouput_rgb_colours'}


def comment_field(comment, start, end, max_chars):
    match = PREFIX.match(comment, 2)
    if not match:
        return None
    key = match.group(1)
    if len(key) > max_chars:
        raise ParseError('header key character limit exceeded')
    key = key.lower()
    if key not in KEYS and not key.startswith(('application', 'manufacturer', 'export_', 'output_')):
        return None
    if len(comment) - match.end() > max_chars:
        raise ParseError('header value character limit exceeded')
    value = comment[match.end():].strip()
    if value.startswith(':'):
        value = value[1:].lstrip()
    if len(value) >= 2 and value[0] == value[-1] == '"':
        value = re.sub(r'\\(["\\])', r'\1', value[1:-1])
    return HeaderField(key, value, SourceRef(start, end))
