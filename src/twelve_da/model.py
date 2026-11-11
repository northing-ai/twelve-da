"""Typed public objects. Coordinates are flat float64 arrays, stride three."""
from array import array
from dataclasses import dataclass, field
import math

VERSION = '0.4.0rc1'
SCHEMA_VERSION = '3'
# Viewer-only additions do not change historical strict CLI/toolkit schema 3.
INSPECTION_VERSION = '1'
MAX_ISSUE_DETAILS = 128


@dataclass(slots=True)
class Attribute:
    kind: str
    name: str
    value: object
    metadata: dict = field(default_factory=dict)


@dataclass(slots=True)
class SourceRef:
    start: int
    end: int
    # Character offsets in decoded member, not byte positions.


@dataclass(slots=True)
class HeaderField:
    key: str
    value: str
    source: SourceRef


@dataclass(slots=True)
class Properties:
    values: dict = field(default_factory=dict)
    extras: dict = field(default_factory=dict)


@dataclass(slots=True)
class FlagValue:
    value: bool | None
    source: str


@dataclass(slots=True)
class TextGeometry:
    value: str
    properties: Properties = field(default_factory=Properties)


@dataclass(slots=True)
class CircleGeometry:
    radius: float
    interval: float | None = None


@dataclass(slots=True)
class Segment:
    kind: str
    radius: float = 0.0
    major: bool = False


@dataclass(slots=True)
class SuperTinDefinition:
    component_names: list[str]
    exact: bool | None
    # Definition recognition is independent of composition/native validation.
    composition: str = 'unverified'


@dataclass(slots=True)
class Object:
    id: str
    kind: str
    name: str
    model: str
    source: SourceRef
    settings: dict = field(default_factory=dict)
    attributes: list = field(default_factory=list)
    coordinates: array = field(default_factory=lambda: array('d'))
    triangles: array = field(default_factory=lambda: array('q'))
    neighbours: array = field(default_factory=lambda: array('q'))
    nulling: array = field(default_factory=lambda: array('B'))
    construction: array = field(default_factory=lambda: array('B'))
    segments: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    diagnostics: list = field(default_factory=list)
    text: TextGeometry | None = None
    circle: CircleGeometry | None = None
    super_tin: SuperTinDefinition | None = None
    geometry_integrity: str = 'not_checked'
    preview_supported: bool = False
    geometry_issues: list = field(default_factory=list)
    geometry_issue_count: int = 0
    visible_geometry_issue_count: int = 0
    preview_exclusions: array = field(default_factory=lambda: array('q'))

    @property
    def coverage(self):
        return 'partial' if self.diagnostics or self.geometry_issue_count else 'complete'

    def summary(self):
        return dict(id=self.id, kind=self.kind, name=self.name, model=self.model,
                    source=clean(self.source), coverage=self.coverage,
                    vertices=len(self.coordinates)//3, triangles=len(self.triangles)//3,
                    diagnostics=self.diagnostics, super_tin=clean(self.super_tin),
                    geometry_integrity=self.geometry_integrity,
                    preview_status=preview_status(self), analysis_eligible=native_geometry_available(self),
                    geometry_issues=clean(self.geometry_issues), geometry_issue_count=self.geometry_issue_count,
                    visible_geometry_issue_count=self.visible_geometry_issue_count,
                    issue_details_truncated=self.geometry_issue_count > len(self.geometry_issues))

    def to_dict(self):
        return clean(self)


@dataclass(slots=True)
class Document:
    source_sha256: str
    payload_sha256: str
    archive_member: str | None
    encoding: str
    objects: list
    models: dict
    diagnostics: list
    header: list = field(default_factory=list)

    @property
    def coverage(self):
        return 'partial' if self.diagnostics or any(o.coverage == 'partial' for o in self.objects) else 'complete'

    def get(self, object_id):
        for obj in self.objects:
            if obj.id == object_id:
                return obj
        raise KeyError(object_id)

    def inspect(self):
        from collections import Counter
        return dict(parser_version=VERSION, schema_version=SCHEMA_VERSION,
                    source_sha256=self.source_sha256, payload_sha256=self.payload_sha256,
                    archive_member=self.archive_member, encoding=self.encoding,
                    coverage=self.coverage, object_count=len(self.objects),
                    types=dict(Counter(o.kind for o in self.objects)),
                    models=list(self.models), diagnostics=self.diagnostics,
                    header=clean(self.header),
                    partial_objects=sum(o.coverage == 'partial' for o in self.objects))


def clean(value):
    """JSON boundary maps missing elevations (internal NaN) to null."""
    from dataclasses import fields, is_dataclass
    if is_dataclass(value):
        return {f.name: clean(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, (array, list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def native_geometry_available(obj):
    return obj.preview_supported and obj.geometry_integrity == 'valid'


def preview_status(obj):
    if not obj.preview_supported:
        return 'unavailable'
    return 'partial' if obj.geometry_issue_count else 'complete'
