"""Bounded read-only source and encoding handling."""
from dataclasses import dataclass
from pathlib import Path
import hashlib
import io
import struct
import zipfile
import zlib


class ParseError(ValueError):
    """Invalid input, unsupported container, or exceeded resource limit."""


@dataclass(frozen=True)
class Limits:
    input_bytes: int = 128 * 1024 * 1024
    expanded_bytes: int = 128 * 1024 * 1024
    object_chars: int = 32 * 1024 * 1024
    nesting: int = 64
    objects: int = 100_000
    token_chars: int = 1024 * 1024
    tokens: int = 10_000_000
    header_fields: int = 1024

    def __post_init__(self):
        from dataclasses import fields
        if any(type(getattr(self, f.name)) is not int or getattr(self, f.name) < 0 for f in fields(self)):
            raise ValueError('limits must be nonnegative integers')


def archive_payload(raw, archive, member, limit):
    # ZipExtFile limits its output to the advertised size. Validate the actual
    # compressed stream so a forged size cannot conceal unvalidated suffixes.
    with archive.open(member):
        pass  # Validate local header, filename, encryption and overlap rules.
    offset = member.header_offset
    if raw[offset:offset+4] != b'PK\x03\x04':
        raise ParseError('invalid ZIP local header')
    name_size, extra_size = struct.unpack_from('<HH', raw, offset+26)
    start = offset + 30 + name_size + extra_size
    end = start + member.compress_size
    if end > len(raw):
        raise ParseError('truncated ZIP payload')
    compressed = raw[start:end]
    if member.compress_type == zipfile.ZIP_STORED:
        data = compressed
    elif member.compress_type == zipfile.ZIP_DEFLATED:
        decoder = zlib.decompressobj(-zlib.MAX_WBITS)
        data = decoder.decompress(compressed, limit+1)
        if len(data) > limit:
            raise ParseError('expanded byte limit exceeded')
        if not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
            raise ParseError('invalid ZIP compressed stream boundary')
    else:
        raise ParseError('unsupported ZIP compression; use stored or deflate')
    if len(data) > limit:
        raise ParseError('expanded byte limit exceeded')
    if len(data) != member.file_size or zlib.crc32(data) & 0xffffffff != member.CRC:
        raise ParseError('ZIP payload size or CRC mismatch')
    return data


def read_source(path, limits):
    with Path(path).open('rb') as f:
        raw = f.read(limits.input_bytes + 1)
    if len(raw) > limits.input_bytes:
        raise ParseError('input byte limit exceeded')
    digest = hashlib.sha256(raw).hexdigest()
    member = None
    data = raw
    if raw.startswith(b'PK'):
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as z:
                members = [m for m in z.infolist() if not m.is_dir()]
                if len(members) != 1 or not members[0].filename.lower().endswith('.12da'):
                    raise ParseError('archive must contain exactly one .12da payload')
                m = members[0]
                if m.file_size > limits.expanded_bytes:
                    raise ParseError('expanded byte limit exceeded')
                member = m.filename
                data = archive_payload(raw, z, m, limits.expanded_bytes)
        except (zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError, zlib.error, struct.error) as e:
            raise ParseError(f'invalid ZIP: {e}') from e
    if len(data) > limits.expanded_bytes:
        raise ParseError('expanded byte limit exceeded')
    diagnostics = []
    try:
        if data.startswith((b'\xff\xfe', b'\xfe\xff')):
            encoding = 'utf-16'
        elif b'\x00' in data[:256]:
            # BOM-less Unicode selected from the ASCII command prefix.
            encoding = 'utf-16-le' if data[1:2] == b'\0' else 'utf-16-be'
            diagnostics.append('BOM-less UTF-16 detected')
        else:
            encoding = 'utf-8-sig'
        try:
            text = data.decode(encoding)
        except UnicodeDecodeError:
            if encoding != 'utf-8-sig':
                raise
            encoding = 'cp1252'
            text = data.decode(encoding)
            diagnostics.append('legacy cp1252 fallback; verify encoding')
    except UnicodeDecodeError as e:
        raise ParseError(f'invalid {encoding} encoding') from e
    return text, digest, hashlib.sha256(data).hexdigest(), member, encoding, diagnostics
