"""Whitespace-independent tokenizer and bounded recursive braced grammar."""
from array import array
from dataclasses import dataclass
import math
import re
from .container import ParseError
from .header import comment_field
from .precision import EXACT_COORDINATE, UNKNOWN_COORDINATE

SKIP = re.compile(r'\s+|//[^\r\n]*')
TOKEN = re.compile(r'[{}]|"[^"\\]*(?:\\.[^"\\]*)*"|(?:[^\s{}"/]+|/(?!/))+')
NUMBER = re.compile(r'[+-]?(?:0[xX][0-9a-fA-F]+(?:\.[0-9a-fA-F]*)?[pP][+-]?\d+|(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\Z')
NUMERIC = {
    'super': {'data_2d', 'data_3d', 'radius_data', 'major_data', 'data'},
    '2d': {'data'}, '3d': {'data'},
    'polyline': {'data'},
    'tin': {'points', 'triangles'},
    'full_tin': {'points', 'triangles', 'neighbours', 'nulling'},
}


def number(s):
    if not isinstance(s, str) or not NUMBER.fullmatch(s):
        raise ParseError(f'invalid number: {str(s)[:80]}')
    try:
        n = float.fromhex(s) if '0x' in s.lower() else float(s)
    except (ValueError, OverflowError) as e:
        raise ParseError('invalid numeric value') from e
    if not math.isfinite(n):
        raise ParseError('non-finite number')
    return n


@dataclass(slots=True)
class Block:
    items: list
    start: int
    end: int


class CoordinateArray(array):
    """Numeric storage with compact lexical precision for XY tokens only."""
    __slots__ = ('decimal_places',)

    def __new__(cls):
        return super().__new__(cls, 'd')

    def __init__(self):
        self.decimal_places = array('h')

    def note_xy_precision(self, token):
        token = token.lower()
        if '0x' in token:
            self.decimal_places.append(EXACT_COORDINATE)
            return
        if token == 'null':
            self.decimal_places.append(UNKNOWN_COORDINATE)
            return
        mantissa, _, exponent = token.partition('e')
        digits = exponent.lstrip('+-').lstrip('0')
        if len(digits) > 3:
            self.decimal_places.append(UNKNOWN_COORDINATE)
            return
        power = int(digits or '0') * (-1 if exponent.startswith('-') else 1)
        places = len(mantissa.partition('.')[2]) - power
        self.decimal_places.append(places if -308 <= places <= 323 else UNKNOWN_COORDINATE)


class Grammar:
    def __init__(self, text, limits):
        self.text, self.limits, self.pos = text, limits, 0
        self.cached = None
        self.object_start = 0
        self.in_object = False
        self.numeric_enabled = True
        self.object_kind = None
        self.token_count = 0
        self.collect_header = True
        self.header = []

    def peek(self):
        if self.cached is None:
            self.cached = self._next()
        return self.cached[0]

    def pop(self):
        self.peek()
        value = self.cached[0]
        self.cached = None
        if value is None:
            raise ParseError('unexpected end of input')
        return value

    def _next(self):
        while self.pos < len(self.text):
            skip = SKIP.match(self.text, self.pos)
            if skip:
                if self.collect_header and not self.in_object and self.text.startswith('//', self.pos):
                    record = comment_field(skip.group(), skip.start(), skip.end(), self.limits.token_chars)
                    if record is not None:
                        if len(self.header) >= self.limits.header_fields:
                            raise ParseError('header field limit exceeded')
                        if len(record.value) > self.limits.token_chars:
                            raise ParseError('header value character limit exceeded')
                        self.header.append(record)
                self.pos = skip.end()
                if self.in_object and self.pos - self.object_start > self.limits.object_chars:
                    raise ParseError('object character limit exceeded')
                continue
            m = TOKEN.match(self.text, self.pos, self.pos + self.limits.token_chars + 2)
            if not m:
                raise ParseError(f'invalid or unterminated token at character {self.pos}')
            self.pos = m.end()
            if self.in_object and self.pos - self.object_start > self.limits.object_chars:
                raise ParseError('object character limit exceeded')
            s = m.group()
            if s.isspace() or s.startswith('//'):
                continue
            self.token_count += 1
            if self.token_count > self.limits.tokens:
                raise ParseError('total token limit exceeded')
            if len(s) > self.limits.token_chars:
                raise ParseError('token character limit exceeded')
            if s.startswith('"'):
                s = re.sub(r'\\(["\\])', r'\1', s[1:-1])
                # Delimiters in quoted strings must never act as grammar tokens.
                return Quoted(s), m.start()
            return s, m.start()
        return None, self.pos

    def block(self, depth=1, numeric=False):
        if depth > self.limits.nesting:
            raise ParseError('nesting limit exceeded')
        if self.pop() != '{':
            raise ParseError('expected opening brace')
        start = self.pos - 1
        if numeric:
            coordinates = numeric in ('data_2d', 'data_3d', 'data') and self.object_kind in ('super', '2d', '3d', 'polyline')
            stride = 2 if numeric == 'data_2d' or self.object_kind == '2d' else 5 if numeric == 'data' and self.object_kind in ('super', 'polyline') else 3
            result = CoordinateArray() if coordinates else array('d')
            while self.peek() != '}':
                s = self.pop()
                if isinstance(s, Quoted):
                    raise ParseError('quoted number in geometry')
                if (numeric == 'major_data' or numeric == 'data' and self.object_kind in ('super', 'polyline') and len(result)%5 == 4) and s.lower() in ('f','t','false','true'):
                    result.append(float(s.lower().startswith('t')))
                else:
                    result.append(math.nan if s.lower() == 'null' else number(s))
                if coordinates and (len(result)-1) % stride < 2:
                    result.note_xy_precision(s)
            self.pop()
            return result
        items = []
        while self.peek() != '}':
            s = self.pop()
            if s == '{':
                raise ParseError('unlabelled opening brace')
            items.append(s)
            if self.peek() == '{':
                # Only immediate supported geometry keys use numeric storage.
                # Unknown object data stays structurally parsed, without guessing semantics.
                items.append(self.block(depth + 1, str(s).lower() if self.numeric_enabled and depth == 1 and str(s).lower() in NUMERIC.get(self.object_kind, set()) else False))
        self.pop()
        return Block(items, start, self.pos)


class Quoted(str):
    def __eq__(self, other):
        if other in ('{', '}') and not isinstance(other, Quoted):
            return False
        return super().__eq__(other)
    def __ne__(self, other):
        return not self.__eq__(other)
    __hash__ = str.__hash__
