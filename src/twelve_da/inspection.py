"""Shared bounded agent/viewer inspection contract. No composite geometry output."""
from .model import clean, native_geometry_available, INSPECTION_VERSION
from .resolution import resolve


def inspection(supplied, *, rejected=(), include_geometry=False):
    report = resolve(supplied, rejected=rejected)
    documents = []
    for source in supplied:
        doc = source.document
        objects = []
        for obj in doc.objects:
            entry = obj.summary()
            entry['native_geometry_available'] = native_geometry_available(obj)
            if include_geometry and obj.preview_supported:
                entry['geometry'] = dict(coordinates=clean(obj.coordinates), triangles=clean(obj.triangles),
                                         nulling=clean(obj.nulling), construction=clean(obj.construction),
                                         excluded_triangles=clean(obj.preview_exclusions))
            objects.append(entry)
        documents.append(dict(file_id=source.file_id, version=source.version,
                              document=doc.inspect(), objects=objects))
    return dict(**report, inspection_version=INSPECTION_VERSION, documents=documents)
