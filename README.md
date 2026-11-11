# twelve-da

Read-only Python library and CLI for supported 12d Archive text (`.12da`) and
single-payload ZIP (`.12daz`) files. Python 3.12 or later; standard library only
at runtime. Independently implemented from the published V15 format specification.

**0.4.0rc1 is an experimental community release candidate**, licensed under MIT. Native-software validation remains incomplete.
`complete` coverage describes implemented format interpretation, not engineering acceptance.

## Install and try

From the release artifact bundle, verify the wheel against `SHA256SUMS` before installing.
On macOS run `shasum -a 256 -c SHA256SUMS`; on Linux use `sha256sum -c SHA256SUMS`.
Run the command in the directory containing the listed artifacts.
A Python execution environment and access to the input file are required; an agent
with only web browsing cannot run the reader. Installation does not upload files.

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install --no-index --no-deps ./twelve_da-0.4.0rc1-py3-none-any.whl
.venv/bin/twelve-da inspect /path/to/input.12daz
.venv/bin/twelve-da list /path/to/input.12da
```

The CLI returns 0 when the primary has complete declared coverage and no
companion is rejected, 3 when the primary is partial or a companion is rejected,
and 2 for failure. A loaded partial companion alone does not force exit 3; always
check its diagnostics and the resolution report. The primary CLI output does not
include each accepted companion's full diagnostics: run `inspect` or `list` on
each companion as the primary input to review its coverage and diagnostics.
Treat 3 as a result requiring diagnostic review. Inspect/list avoid
coordinate arrays, but object summaries and diagnostics can still be large.
Use `get` with an ID returned by `list` to export one object's original data:

```sh
.venv/bin/twelve-da get /path/to/input.12da 'PAYLOAD_SHA256:1' --output object.json
```

Replace `PAYLOAD_SHA256:1` with the actual object ID. The library never writes its
input. `get` intentionally replaces an existing destination after successful
validation; use a new output filename to keep an existing export.

From the source checkout, the bundled synthetic example is
`tests/fixtures/synthetic/complete.12da` (six objects). See [contributing](CONTRIBUTING.md)
for build and test commands and [release notes](CHANGELOG.md).

## Scope and interpretation

No engineering validation, geometry repair, coordinate conversion, quantities,
writing back to 12d, or composite Super TIN calculation is provided. Units and CRS
are not inferred; missing Z stays missing. Check diagnostics before using geometry.
The CLI is strict; only the Python API supports opt-in zero-area inspection.
The parser has configurable input bounds, but callers processing untrusted files
must also impose process memory, CPU, wall-time and output limits.

## Python API

```python
from twelve_da import load, ParseError, Limits

try:
    document = load("input.12daz", limits=Limits())
    print(document.inspect())
    for obj in document.objects:
        print(obj.summary())
    if document.objects:
        obj = document.get(document.objects[0].id)
        data = obj.to_dict()  # JSON-safe coordinates, attributes and metadata
except ParseError as exc:
    print(exc)
```

`load` validates the entire input before returning. Invalid structure, invalid
supported geometry and resource breaches raise `ParseError`; filesystem failures
raise `OSError`. The library never exits the process. Unsupported content yields
`partial` coverage with document/object diagnostics. A failure returns no document.
Results are mutable Python data intended for read-only source inspection; mutation
of a returned object does not modify its source file.

Opt-in inspection is explicit: `load(path, inspection=True)` (or
`load_set(..., inspection=True)`) retains exactly zero-plan-area faces with three
distinct point references as structured `zero_plan_area` issues. Every other
validation still runs before returning. Default library and CLI calls remain
strict. Partial previews use separate source triangle exclusions; coordinates,
indices, neighbours and flags are never repaired. Inspection responses use
`inspection_version=1`; strict schema 3 remains compatible. See [inspection and dependency details](docs/inspection.md).

`Document` holds source SHA-256, payload SHA-256, archive member, encoding,
objects, models, diagnostics and ordered descriptive `HeaderField` records. Header
records retain key/value and decoded-character source range. Exporter/archive
comments are descriptive metadata. The one implemented interpretation exception
is a single valid `decimal_places` declaration used for the bounded arc uncertainty
rule below; comments never execute code or alter stored coordinates. `models` maps model names to ordered typed
attributes. Model identity follows case-insensitive matching and retains the
first spelling; each object's settings retain its source model spelling. Object
names and attribute case are preserved. Attributes are ordered `Attribute(kind,
name, value, metadata)` records; group values are nested attribute lists.
Unrecognised group fields remain in `metadata` and mark interpretation partial.
`uid` values are exact integer identifiers (including values beyond float64 precision),
with explicit partial coverage because identifier semantics are not interpreted.
Unknown scalar attribute types retain their declared kind and opaque value with
partial coverage. Duplicate attribute
names are preserved and explicitly mark interpretation partial.

`Object.coordinates` is a flat `array('d')` of float64 XYZ triples. Missing
Z values use NaN internally and JSON `null` at the API serialization boundary;
missing XY is invalid. No units or CRS are inferred. Triangle and neighbour
arrays use signed int64; all indices remain **one-based and local to each
surface**. Neighbour zero is the outer boundary. Triangle order is unchanged.
`nulling` preserves source codes 1 (hidden), 2 (visible). `construction` marks
full-TIN triangles touching source points 1–4, independently of visibility.
Visible-only TINs contain visible triangles and no implied construction points.

Segments retain their source kind, signed radius and major-arc flag. The active
segment count is vertex count minus one for open strings and vertex count for
closed superstrings and legacy polylines. An open superstring or polyline may retain an extra dormant segment
record for later closure. Unknown segment kinds are never turned into straights.
No length, area, alignment solving, coordinate conversion or geometry repair API
is provided. Object diagnostics must be checked before consuming geometry.

Text retains its exact string and anchor XYZ in `coordinates`, with presentation
fields in `text.properties`. Offsets, angles and text size are not applied to the
anchor. Circles retain centre XYZ and signed radius/interval in `circle`, without
polygon approximation. Negative radii remain signed and explicitly partial until
their direction semantics are established.

Common annotation, symbol, interval and culvert properties use
`Properties(values, extras)`: known fields have typed values, unknown fields remain
in `extras` with partial diagnostics. Pipe diameter arrays and per-element typed
attributes retain their source order. The undocumented `pipe_value` wrapper is
preserved as structured extension data with partial coverage. Scalar visibility
and tinability use `FlagValue(value, source)`: understood Boolean codes produce a
Boolean; null or unknown codes (including source code `2`) retain the source with
`value=None` and partial coverage. Conflicting annotation forms remain explicit;
pipe/culvert contradictions fail validation.

Object IDs are `<payload-sha256>:<one-based-object-ordinal>`. Duplicate and blank
names have separate IDs. IDs and decoded-character source ranges are identical
for an archive and its exact extracted payload; source SHA-256 identifies the
actual supplied container. Source ranges include an object's command through its
closing brace. They are not byte offsets. Unknown objects retain bounded source
ranges and names, without a retained syntax tree or round-trip writing promise.

## CLI and JSON contract (schema 3)

```sh
twelve-da inspect input.12daz
twelve-da list input.12da
twelve-da get input.12daz '<payload-sha256>:1' --output object.json
```

All commands scan and validate the whole input. `inspect` emits one JSON object
with parser/schema versions, source/payload hashes, member, encoding, coverage,
object count, type counts, model names, diagnostics, descriptive `header` records
and partial-object count.
`list` adds `objects`, an ordered list of summaries (ID, kind, name, model,
source range, coverage, vertex/triangle counts and diagnostics).

`get` requires an explicit output path. Its file contains `document` (inspection
metadata), `object` (all typed fields), and `model_attributes`. Its stdout is an
inspection object with the output path. Geometry is never sent to stdout.
Output is written to a temporary sibling and atomically replaced only after
validation and serialization succeed. Existing output remains intact on failure.
The input itself cannot be the output path, including case aliases, symlinks and
hard links to the same file. JSON contains no NaN/Infinity.

Exit statuses: **0** complete declared coverage, **3** partial primary coverage or rejected companions,
**2** error (including invalid geometry, unknown ID, filesystem or argument error).
Runtime errors emit a JSON `error` to stderr, with no success JSON or output
publication. Argument errors use argparse's standard text usage on stderr.
`complete` describes declared format interpretation only, not engineering acceptance.

## Coverage

| Content | Interpretation |
| --- | --- |
| Models, default/overridden colour/style/breakline/null | Preserved; model attributes supported |
| Typed integer/real/text attributes and nested groups | Preserved, case-sensitive, including null values |
| UID and other scalar attribute types | UID preserved as exact integer; opaque extra types retained with explicit partial coverage |
| Points | Single-vertex superstrings; no invented standalone point command |
| 2d/3d strings | Coordinates and constant/missing elevations |
| Superstrings | 2D/3D and superseded five-column data; closed flag |
| Straight/circular arcs | Radius/major arrays or geometry blocks; signed source parameters |
| Legacy polylines | Five-column XYZ/radius/major data, closed flag and dormant segment records |
| Text | Exact content, anchor and known presentation fields; unknown presentation fields partial |
| Circles | Exact centre, signed radius and interval; negative-radius direction unresolved |
| Vertex/segment metadata | Typed attributes, flags, annotations, symbols, pipe/culvert properties and intervals; unknown fields partial |
| Exporter/archive header | Bounded ordered descriptive comment metadata with source ranges |
| TIN/full TIN | Separate surfaces, vertices, triangles, neighbours, hidden/construction flags, colours |
| Alignment, drainage, meshes and other object types | Inventoried as unsupported; no interpreted geometry |
| Spiral/curve and other segment kinds | Explicit partial geometry; source kind retained |
| Unrecognised fields, fills and other semantics | Preserved metadata or bounded object reference, explicit partial coverage |

UTF-8 (with/without BOM), UTF-16 LE/BE (with BOM or ASCII-prefix detection),
and reported cp1252 fallback are supported. Decimal, exponent and hexadecimal
floating point numbers, quoted escaped quotes/backslashes, `//` comments, case
insensitive command keywords and arbitrary whitespace are supported. Metadata
retains source tokens where interpretation is not declared. Unsupported top-level
commands require a braced payload; a command with an unknown unbraced grammar
fails because it cannot safely be skipped.

Validation checks coordinate/array lengths, finite XY/TIN coordinates, arc radii
against endpoints, per-vertex/segment lengths, TIN index ranges, nonzero clockwise
triangle plan area, actual shared-edge incidence, duplicate-face/manifold-edge checks, neighbour
reciprocity, and full-TIN visibility
codes. It does not establish engineering correctness, non-overlap of every pair
of terrain triangles, or compatibility with untested export versions.

### Precision-limited source arcs

Decimal exports can round a near-semicircle's endpoints just beyond its diameter.
The arc/diameter predicate uses exact rational arithmetic on retained float64
values, without a broad relative epsilon. When it fails, the parser can retain
that source arc only if:

- There is exactly one leading `decimal_places` comment with a canonical integer
  value from 0 to 15. Missing, invalid or duplicate declarations do not qualify.
- Each decimal XY coordinate's uncertainty is half a last place at the **finer**
  of its own lexical precision and the declaration. Hexadecimal coordinates get
  no decimal uncertainty. Z, radius and flag precision never loosen XY checks.
- The two endpoint uncertainty rectangles permit a chord no longer than the
  retained diameter. Decimal float64 conversion error is bounded; the rectangle
  feasibility predicate is exact rational arithmetic. Hexadecimal coordinates
  receive neither decimal quantization nor decimal conversion uncertainty.
- Uncertainty on each axis is at most one millionth of the diameter. Coarse or
  numerically ill-conditioned geometry does not qualify for this rule.

Coordinates, signed radii and major flags are never moved, enlarged or snapped.
Every admitted segment receives a `precision-limited arc` diagnostic, and
`inspect` includes an aggregate segment/object count. The object/document is
**partial**, with CLI exit 3, even if all other interpretation is supported.
This describes export uncertainty, not proof of the native arc or engineering
validity. Zero-length/non-finite chords and discrepancies beyond this bound still
fail the entire input. This arc rule does not provide general geometry recovery.
The separate Python inspection mode described above admits only exactly zero
plan-area TIN faces with distinct source point references.
The declaration is used only for bounded validation uncertainty, never to set
geometry values or execute exporter comments. This candidate uses schema 3.

## Enforced default limits

Defaults for `Limits`:

| Resource | Limit |
| --- | --- |
| Original input | 128 MiB |
| Expanded payload | 128 MiB |
| Object/model block | 32 Mi decoded characters |
| Nesting | 64 brace levels |
| Objects and distinct models | 100,000 each |
| Individual token | 1 Mi characters |
| Total tokens | 10,000,000 |
| Descriptive header records | 1,024 (each value also bounded by token limit) |

Limits are configurable with `Limits`. Archives must contain exactly one
non-directory `.12da` member. Extra payloads, encrypted/unreadable/corrupt archives
and oversized members fail. Stored and deflate compression are supported; other
ZIP methods fail explicitly. Actual compressed-stream EOF, expanded size and CRC
are checked independently of the advertised member size. Archive members are read in memory, never extracted
by the library. Decompression reads are capped independently of ZIP metadata.
Coordinates use compact arrays; a temporary syntax tree is retained for only one
object at a time and geometry blocks directly populate numeric arrays.
These are bounded full parses, not streaming or random-access indexing.

## Validation and provenance

The test suite uses invented fixtures. It checks declared parsing, geometry,
resource boundaries, error handling and source/output protection. It does not
establish compatibility with every exporter/version or native engineering accuracy.
Native composite semantics and broader native-reference validation remain unverified.
See [third-party notices](THIRD_PARTY_NOTICES.md).

`twelve-da` is an independent project, not affiliated with or endorsed by
12d Solutions. The format specification is linked, not redistributed.
