"""Explicit document-set dependency diagnosis; never constructs composite geometry."""
from dataclasses import dataclass
from collections import deque
from .container import ParseError
from .model import Document, clean, native_geometry_available


@dataclass(frozen=True)
class SuppliedDocument:
    file_id: str
    version: str
    document: Document


@dataclass(frozen=True)
class RejectedDocument:
    file_id: str
    version: str
    code: str
    message: str


@dataclass(frozen=True)
class ResolutionLimits:
    documents: int = 16
    objects: int = 100_000
    references: int = 100_000
    depth: int = 32

    def __post_init__(self):
        if any(type(v) is not int or v < 1 for v in (self.documents, self.objects, self.references, self.depth)):
            raise ValueError('resolution limits must be positive integers')


def failure_code(error):
    message = str(error).lower()
    if 'limit' in message:
        return 'resource_limit'
    if 'unsupported zip' in message or 'archive must contain' in message:
        return 'unsupported_container'
    return 'malformed_document'


def load_set(selections, *, limits=None, parse_limits=None, inspection=False):
    """Load each (file_id, immutable_version, local_path) atomically. Primary must pass.

    A rejected companion contributes no objects. Missing matches are then unknown,
    rather than falsely asserting absence from an unreadable document.
    """
    from .parser import load
    limits = limits or ResolutionLimits()
    if not 1 <= len(selections) <= limits.documents:
        raise ParseError('document set limit exceeded')
    supplied, rejected = [], []
    object_count = reference_count = 0
    for i, (file_id, version, path) in enumerate(selections):
        try:
            doc = load(path, limits=parse_limits, inspection=inspection)
            references = sum(len(o.super_tin.component_names) for o in doc.objects if o.super_tin)
            if object_count + len(doc.objects) > limits.objects or reference_count + references > limits.references:
                raise ParseError('combined document object/reference limit exceeded')
            supplied.append(SuppliedDocument(file_id, version, doc))
            object_count += len(doc.objects)
            reference_count += references
        except (ParseError, OSError) as error:
            if i == 0:
                raise
            rejected.append(RejectedDocument(file_id, version, failure_code(error) if isinstance(error, ParseError) else 'unavailable_document', str(error)))
    return supplied, rejected


def resolve(supplied, *, rejected=(), limits=None):
    """Preserve source ordering, combined-name ambiguity and exact source identity.

    Nested definitions remain inspectable but unsupported. Kahn's iterative graph
    pass diagnoses cyclic/transitively blocked dependencies without recursion.
    All composition profiles remain unverified pending native-reference evidence.
    """
    limits = limits or ResolutionLimits()
    if not 1 <= len(supplied) + len(rejected) <= limits.documents:
        raise ParseError('document set limit exceeded')
    identities = [(s.file_id, s.version) for s in (*supplied, *rejected)]
    if any(not a or not b for a, b in identities) or len({a for a, b in identities}) != len(identities):
        raise ParseError('unique exact file identities required')
    index, records, composites = {}, [], []
    count = edges = 0
    for source in supplied:
        doc = source.document
        count += len(doc.objects)
        if count > limits.objects:
            raise ParseError('resolution object limit exceeded')
        for obj in doc.objects:
            if obj.kind not in ('tin', 'full_tin', 'super_tin'):
                continue
            ref = dict(file_id=source.file_id, version=source.version, source_sha256=doc.source_sha256,
                       payload_sha256=doc.payload_sha256, object_id=obj.id, name=obj.name,
                       model=obj.model, kind=obj.kind, source=clean(obj.source))
            key = len(records)
            records.append((obj, ref))
            index.setdefault(obj.name.strip().casefold(), []).append(key)
            if obj.super_tin:
                edges += len(obj.super_tin.component_names)
                if edges > limits.references:
                    raise ParseError('resolution reference limit exceeded')
                composites.append(key)
    dependencies = {k: set() for k in composites}
    parents = {k: set() for k in composites}
    for key in composites:
        for name in records[key][0].super_tin.component_names:
            matches = index.get(name.strip().casefold(), [])
            if len(matches) == 1 and matches[0] in dependencies:
                dependencies[key].add(matches[0])
                parents[matches[0]].add(key)
    remaining = {k: len(v) for k, v in dependencies.items()}
    queue = deque(k for k, n in remaining.items() if not n)
    depth = {k: 1 for k in dependencies}
    while queue:
        child = queue.popleft()
        for parent in parents[child]:
            depth[parent] = max(depth[parent], depth[child] + 1)
            remaining[parent] -= 1
            if remaining[parent] == 0:
                queue.append(parent)
    reports = []
    candidate_count = 0
    for key in composites:
        obj, identity = records[key]
        components = []
        for ordinal, name in enumerate(obj.super_tin.component_names, 1):
            matches = index.get(name.strip().casefold(), [])
            candidate_count += len(matches)
            if candidate_count > limits.references:
                raise ParseError('resolution candidate output limit exceeded')
            candidates = [records[k][1] for k in matches]
            code, status = 'missing_component', 'missing'
            if len(matches) <= 1 and rejected:
                code, status = 'rejected_document_blocks_match', 'unknown'
            elif len(matches) > 1:
                code, status = 'ambiguous_name', 'ambiguous'
            elif len(matches) == 1:
                target, _ = records[matches[0]]
                if matches[0] == key:
                    code, status = 'self_reference', 'unsupported'
                elif target.super_tin:
                    code = 'cycle_or_transitive_cycle' if remaining[matches[0]] else 'depth_limit' if depth[matches[0]] >= limits.depth else 'unsupported_nesting'
                    status = 'unsupported'
                elif native_geometry_available(target):
                    code, status = 'native_geometry_available', 'available'
                elif target.preview_supported and target.geometry_integrity == 'zero_area_faces':
                    code, status = 'zero_plan_area', 'partial'
                else:
                    code, status = 'unsupported_geometry', 'unsupported'
            components.append(dict(ordinal=ordinal, name=name, status=status, code=code, candidates=candidates))
        reports.append(dict(identity=identity, definition=clean(obj.super_tin), components=components,
                            present_count=sum(bool(c['candidates']) for c in components),
                            available_count=sum(c['status'] == 'available' for c in components),
                            component_count=len(components), dependency_state='available' if all(c['status'] == 'available' for c in components) else 'incomplete',
                            composition='unverified', native_reference='unverified', usable_surface=False,
                            quantities=None, domain=None,
                            graph_diagnostics=['cycle_or_transitive_cycle'] if remaining[key] else ['depth_limit'] if depth[key] > limits.depth else []))
    return dict(schema_version='3', composites=reports, rejected_documents=clean(rejected),
                duplicate_names=[dict(normalized_name=n, candidates=[records[k][1] for k in keys]) for n, keys in index.items() if len(keys) > 1])
