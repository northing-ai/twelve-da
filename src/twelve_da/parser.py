"""12DA interpretation, independently implemented from the V15 specification."""
from array import array
import math
from .container import Limits, ParseError, read_source
from .grammar import Grammar, Block, Quoted, number
from .model import Attribute, Document, Object, Segment, SourceRef, Properties, TextGeometry, CircleGeometry, FlagValue, SuperTinDefinition, MAX_ISSUE_DETAILS
from .precision import ARC_DIAGNOSTIC, export_decimal_places, arc_rounding_bound, arc_exceeds_diameter


def pairs(block):
    items = block.items
    if len(items) % 2:
        raise ParseError(f'expected keyword/value pairs at {block.start}')
    result = {}
    for i in range(0, len(items), 2):
        key = items[i]
        if not isinstance(key, str):
            raise ParseError('expected keyword')
        key = key.lower()
        if key in result:
            raise ParseError(f'duplicate field {key}')
        value = items[i+1]
        result[key] = str(value) if isinstance(value, Quoted) else value
    return result


def attributes(block):
    if not isinstance(block, Block):
        raise ParseError('expected attributes block')
    result, i = [], 0
    while i < len(block.items):
        metadata = {}
        if not isinstance(block.items[i], str):
            raise ParseError('expected attribute type')
        kind = block.items[i].lower()
        if kind == 'group':
            if i+1 >= len(block.items) or not isinstance(block.items[i+1], Block):
                raise ParseError('invalid attribute group')
            group = pairs(block.items[i+1])
            name = group.get('name')
            value = attributes(group['attributes']) if 'attributes' in group else []
            metadata = {k: raw(v) for k, v in group.items() if k not in ('name', 'attributes')}
            i += 2
        else:
            if i+2 >= len(block.items):
                raise ParseError('invalid typed attribute')
            name, value = block.items[i+1:i+3]
            if not isinstance(value, str):
                raise ParseError('invalid attribute value')
            if kind in ('integer', 'real', 'uid'):
                is_null = not isinstance(value, Quoted) and value.lower() == 'null'
                value = None if is_null else number(value) if kind == 'real' else integer(value)
            i += 3
        if not isinstance(name, str) or not name.strip():
            raise ParseError('blank attribute name')
        result.append(Attribute(kind, str(name), str(value) if isinstance(value, Quoted) else value, metadata))
    return result


def integer(s):
    if isinstance(s, float):
        if not math.isfinite(s) or not s.is_integer() or abs(s) > 2**53:
            raise ParseError('invalid integer')
        return int(s)
    try:
        return int(s, 16 if str(s).lower().startswith(('0x', '-0x', '+0x')) else 10)
    except (ValueError, TypeError) as e:
        raise ParseError('invalid integer') from e


def flag(s):
    s = str(s).lower()
    if s == '1' or s.startswith(('t', 'y')):
        return True
    if s == '0' or s.startswith(('f', 'n')):
        return False
    raise ParseError('invalid boolean')


def numeric(value):
    if not isinstance(value, array):
        raise ParseError('expected numeric block')
    return value


def ints(value):
    try:
        return array('q', (integer(v) for v in numeric(value)))
    except OverflowError as e:
        raise ParseError('integer exceeds int64 storage') from e


def missing(v, null):
    return math.nan if math.isnan(v) or v == null else v


def raw(value):
    # Preserve metadata structure, case and ordering rather than guessing its meaning.
    if isinstance(value, Block):
        return [raw(v) for v in value.items]
    return str(value) if isinstance(value, Quoted) else value


ANNOTATION_NUMBERS = {'angle', 'offset', 'raise', 'slant', 'xfactor', 'x_factor',
                      'worldsize', 'papersize', 'screensize'}
ANNOTATION_TEXT = {'textstyle', 'justify', 'colour', 'text_colour'}
SYMBOL_NUMBERS = {'size', 'rotation', 'offset', 'raise'}
SYMBOL_TEXT = {'style', 'colour'}
LINE_KINDS = {'super', '2d', '3d', 'polyline'}


def scalar_real(value):
    if isinstance(value, str) and value.lower() == 'null':
        return None
    return number(value)


def property_record(value, numeric_keys, text_keys, obj, path):
    if not isinstance(value, Block):
        raise ParseError(f'expected properties block: {path}')
    result = Properties()
    for key, item in pairs(value).items():
        if key in numeric_keys:
            result.values[key] = scalar_real(item)
        elif key in text_keys:
            if not isinstance(item, str):
                raise ParseError(f'expected text property: {path}/{key}')
            result.values[key] = item
        else:
            result.extras[key] = raw(item)
            obj.diagnostics.append(f'unsupported property: {path}/{key}')
    if len({'worldsize', 'papersize', 'screensize'} & result.values.keys()) > 1:
        obj.diagnostics.append(f'multiple text size modes retained: {path}')
    return result


def property_list(value, numeric_keys, text_keys, obj, path):
    if not isinstance(value, Block) or len(value.items) % 2:
        raise ParseError(f'expected properties list: {path}')
    result = []
    for i in range(0, len(value.items), 2):
        if not isinstance(value.items[i], str) or value.items[i].lower() != 'properties':
            raise ParseError(f'expected properties record: {path}')
        result.append(property_record(value.items[i+1], numeric_keys, text_keys, obj, path))
    modes = {k for p in result for k in p.values if k in ('worldsize', 'papersize', 'screensize')}
    if len(modes) > 1:
        obj.diagnostics.append(f'mixed annotation size modes retained: {path}')
    return result


def positioned(obj, fields, null):
    circle = obj.kind == 'circle'
    keys = ('xcentre', 'ycentre', 'zcentre') if circle else ('x', 'y', 'z')
    x = number(fields.pop(keys[0], None))
    y = number(fields.pop(keys[1], None))
    z = scalar_real(fields.pop(keys[2], 'null'))
    obj.coordinates.extend((x, y, math.nan if z is None else missing(z, null)))
    if circle:
        radius = number(fields.pop('radius', None))
        if radius == 0:
            raise ParseError('circle radius must be nonzero')
        if radius < 0:
            obj.diagnostics.append('signed circle radius retained; direction semantics not interpreted')
        interval = scalar_real(fields.pop('interval', 'null'))
        obj.circle = CircleGeometry(radius, interval)
    else:
        value = fields.pop('text', None)
        if not isinstance(value, str):
            raise ParseError('text string requires text value')
        presentation = {k: fields.pop(k) for k in list(fields)
                        if k in ANNOTATION_NUMBERS | ANNOTATION_TEXT}
        block = Block([item for pair in presentation.items() for item in pair], 0, 0)
        obj.text = TextGeometry(value, property_record(block, ANNOTATION_NUMBERS,
                                                      ANNOTATION_TEXT, obj, 'text'))


def read_metadata(obj, fields):
    n = len(obj.coordinates)//3
    ns = n if obj.settings.get('closed') else max(0, n-1)
    lines = obj.kind in LINE_KINDS
    scalar_arrays = {'point_data', 'vertex_uid_data', 'vertex_text_data', 'segment_text_data', 'colour_data'}
    flag_arrays = {'vertex_visible_data', 'segment_visible_data', 'vertex_tinable_data', 'segment_tinable_data'}
    flag_values = {key.replace('_data', '_value') for key in flag_arrays}
    attr_arrays = {'vertex_attribute_data', 'segment_attribute_data'}
    property_arrays = {'vertex_annotate_data', 'segment_annotate_data', 'symbol_data', 'culvert_data'}
    property_values = {'vertex_annotate_value', 'segment_annotate_value', 'symbol_value', 'culvert_value', 'pipe_value'}
    if lines and fields.keys() & {'diameter', 'diameter_value', 'diameter_data', 'pipe_value'} and fields.keys() & {'culvert_value', 'culvert_data'}:
        raise ParseError('pipe diameters and culvert dimensions are mutually exclusive')
    for key, value in fields.items():
        known, count = True, None
        if key in ('chainage', 'weight'):
            obj.metadata[key] = scalar_real(value)
        elif key in ('time_created', 'time_updated'):
            if not isinstance(value, str):
                raise ParseError(f'expected scalar metadata: {key}')
            obj.metadata[key] = value
        elif obj.kind in ('tin', 'full_tin') and key == 'colours':
            obj.metadata[key] = raw(value)
        elif lines and key in attr_arrays:
            if not isinstance(value, Block) or len(value.items) % 2:
                raise ParseError(f'expected per-element attributes: {key}')
            records = []
            for i in range(0, len(value.items), 2):
                if not isinstance(value.items[i], str) or value.items[i].lower() != 'attributes':
                    raise ParseError('invalid per-element attributes')
                records.append(attributes(value.items[i+1]))
            obj.metadata[key], count = records, len(records)
        elif lines and key in scalar_arrays | flag_arrays | {'diameter_data'}:
            if not isinstance(value, Block) or any(not isinstance(v, str) for v in value.items):
                raise ParseError(f'invalid scalar array: {key}')
            count = len(value.items)
            if key in flag_arrays:
                obj.metadata[key] = []
                for v in value.items:
                    if v.lower() == 'null':
                        obj.metadata[key].append(None)
                        obj.diagnostics.append(f'unresolved null flag: {key}')
                    else:
                        obj.metadata[key].append(flag(v))
            elif key == 'diameter_data':
                obj.metadata[key] = [scalar_real(v) for v in value.items]
            else:
                obj.metadata[key] = [str(v) for v in value.items]
        elif lines and key in flag_values:
            if not isinstance(value, str):
                raise ParseError(f'invalid scalar flag: {key}')
            if value.lower() == 'null':
                obj.metadata[key] = FlagValue(None, value)
                obj.diagnostics.append(f'unresolved null flag: {key}')
            elif value.lower() in ('0', '1') or value.lower().startswith(('t', 'y', 'f', 'n')):
                obj.metadata[key] = FlagValue(flag(value), value)
            else:
                obj.metadata[key] = FlagValue(None, value)
                obj.diagnostics.append(f'unsupported scalar flag value: {key}={value}')
        elif lines and key in ('vertex_text_value', 'segment_text_value', 'justify'):
            if not isinstance(value, str):
                raise ParseError(f'expected text metadata: {key}')
            obj.metadata[key] = value
        elif lines and key in ('diameter_value', 'diameter'):
            obj.metadata[key] = scalar_real(value)
        elif lines and key == 'interval':
            obj.metadata[key] = property_record(value, {'chord_arc', 'distance'}, set(), obj, key)
        elif lines and key in property_arrays | property_values:
            nums, words = ANNOTATION_NUMBERS, ANNOTATION_TEXT
            if key.startswith('symbol_'):
                nums, words = SYMBOL_NUMBERS, SYMBOL_TEXT
            elif key.startswith(('culvert_', 'pipe_')):
                nums, words = {'width', 'height', 'diameter'}, set()
            if key in property_arrays:
                result = property_list(value, nums, words, obj, key)
                obj.metadata[key], count = result, len(result)
            else:
                obj.metadata[key] = property_record(value, nums, words, obj, key)
                if key == 'pipe_value':
                    obj.diagnostics.append('extension metadata: pipe_value')
        else:
            known = False
            obj.metadata[key] = raw(value)
            obj.diagnostics.append(f'unsupported field: {key}')
            # V15: input is optional reconstruction history, not native faces.
            if obj.kind in ('tin', 'full_tin') and key != 'input':
                obj.preview_supported = False
        if known and lines and count is not None:
            vertex = key.startswith('vertex_') or key in ('point_data', 'symbol_data')
            if vertex and count != n:
                raise ParseError(f'{key} length does not match vertices')
            if not vertex and count not in (ns, n):
                raise ParseError(f'{key} length does not match segments')
    if not lines:
        return
    for prefix in ('vertex_annotate', 'segment_annotate', 'symbol', 'culvert', 'diameter',
                   'vertex_visible', 'segment_visible', 'vertex_tinable', 'segment_tinable',
                   'vertex_text', 'segment_text'):
        if prefix+'_value' in fields and prefix+'_data' in fields:
            obj.diagnostics.append(f'competing scalar and per-element settings retained: {prefix}')
    for prefix in ('vertex_annotate', 'segment_annotate'):
        records = list(obj.metadata.get(prefix+'_data', []))
        if prefix+'_value' in obj.metadata:
            records.append(obj.metadata[prefix+'_value'])
        modes = {key for record in records for key in record.values
                 if key in ('worldsize', 'papersize', 'screensize')}
        if len(modes) > 1:
            obj.diagnostics.append(f'mixed annotation size modes retained: {prefix}')


def interpret(kind, block, defaults, oid, coordinate_precision=None, *, inspection=False):
    obj = Object(oid, kind, '', defaults['model'], SourceRef(block.start, block.end))
    # Unsupported types have unconstrained inner grammars; retain bounded reference only.
    if kind not in ('super', '2d', '3d', 'polyline', 'text', 'circle', 'tin', 'full_tin', 'super_tin'):
        items = block.items
        for key in ('name', 'model'):
            for i, v in enumerate(items[:-1]):
                if isinstance(v, str) and v.lower() == key and isinstance(items[i+1], str):
                    setattr(obj, key, str(items[i+1])); break
        obj.diagnostics.append(f'unsupported object type: {kind}; geometry not interpreted')
        return obj
    fields = pairs(block)
    obj.name = fields.pop('name', '')
    if not isinstance(obj.name, str):
        raise ParseError('invalid object name')
    obj.settings = dict(defaults)
    for key in ('model', 'colour', 'style', 'breakline', 'null_value'):
        if key in fields:
            value = fields.pop(key)
            if not isinstance(value, str):
                raise ParseError(f'invalid {key} setting')
            obj.settings[key] = value
    obj.model = obj.settings['model']
    if not obj.model.strip():
        raise ParseError('blank model name')
    if obj.settings['breakline'].lower() not in ('point', 'line'):
        raise ParseError('invalid breakline type')
    null = obj.settings.get('null_value', obj.settings['null'])
    null = None if str(null).lower() == 'null' else number(null)
    if 'attributes' in fields:
        obj.attributes = attributes(fields.pop('attributes'))
    if kind == 'super_tin':
        if not obj.name.strip():
            raise ParseError('super TIN name is required')
        tins = fields.pop('tins', None)
        if not isinstance(tins, Block) or not tins.items or any(not isinstance(v, str) or not v.strip() for v in tins.items):
            raise ParseError('super TIN requires a nonempty list of component names')
        exact = fields.pop('exact', None)
        if exact is not None and (not isinstance(exact, str) or exact.lower() not in ('true', 'false')):
            raise ParseError('super TIN exact must be true or false')
        obj.super_tin = SuperTinDefinition([str(v) for v in tins.items], None if exact is None else exact.lower() == 'true')
        obj.diagnostics.append('super TIN composition unverified; definition only, not a complete usable surface')
    elif kind in ('tin', 'full_tin'):
        terrain(obj, fields, null, inspection=inspection)
    elif kind in ('text', 'circle'):
        positioned(obj, fields, null)
    else:
        string(obj, fields, null, coordinate_precision)
    read_metadata(obj, fields)
    if duplicate_attributes(obj.attributes) or (kind in LINE_KINDS and any(duplicate_attributes(v) for key, values in obj.metadata.items() if key in ('vertex_attribute_data', 'segment_attribute_data') for v in values)):
        obj.diagnostics.append('duplicate attribute names retained in source order')
        obj.preview_supported = False
    attr_diagnostics = attribute_diagnostics(obj.attributes)
    obj.diagnostics.extend(attr_diagnostics)
    if attr_diagnostics:
        obj.preview_supported = False
    if kind in LINE_KINDS:
        for key in ('vertex_attribute_data', 'segment_attribute_data'):
            for attrs in obj.metadata.get(key, []):
                obj.diagnostics.extend(attribute_diagnostics(attrs))
    return obj


def duplicate_attributes(attrs):
    names = [a.name for a in attrs]
    return len(names) != len(set(names)) or any(duplicate_attributes(a.value) for a in attrs if a.kind == 'group')


def attribute_diagnostics(attrs):
    diagnostics = []
    for attr in attrs:
        if attr.kind == 'uid':
            diagnostics.append('extension attribute type: uid; opaque identifier')
        elif attr.kind not in ('integer', 'real', 'text', 'group'):
            diagnostics.append(f'unsupported attribute type: {attr.kind}; opaque value retained')
        if attr.metadata:
            diagnostics.extend(f'unsupported attribute group field: {key}' for key in attr.metadata)
        if attr.kind == 'group':
            diagnostics.extend(attribute_diagnostics(attr.value))
    return diagnostics


def orientation(ax, ay, bx, by, cx, cy):
    left = (bx-ax)*(cy-ay)
    right = (by-ay)*(cx-ax)
    determinant = left-right
    if math.isfinite(determinant) and abs(determinant) > (abs(left)+abs(right))*1e-14:
        return determinant
    # Exact sign for collinear, near-collinear, underflow and overflow cases.
    from fractions import Fraction
    ax, ay, bx, by, cx, cy = map(Fraction, (ax, ay, bx, by, cx, cy))
    exact = (bx-ax)*(cy-ay)-(by-ay)*(cx-ax)
    return (exact > 0)-(exact < 0)


def terrain(obj, f, null, *, inspection=False):
    if not obj.name.strip():
        raise ParseError('TIN name is required')
    obj.coordinates = numeric(f.pop('points', None))
    obj.triangles = ints(f.pop('triangles', None))
    if len(obj.coordinates)%3 or len(obj.triangles)%3 or not obj.coordinates or not obj.triangles:
        raise ParseError('invalid TIN array lengths')
    if any(not math.isfinite(v) for v in obj.coordinates):
        raise ParseError('null coordinate in TIN')
    np, nt = len(obj.coordinates)//3, len(obj.triangles)//3
    if any(v < 1 or v > np for v in obj.triangles):
        raise ParseError('TIN point reference out of range')
    faces, edges = set(), {}
    for i in range(0,len(obj.triangles),3):
        a,b,c = obj.triangles[i:i+3]
        if len({a,b,c}) != 3:
            raise ParseError('TIN triangle must reference three distinct points')
        face = tuple(sorted((a,b,c)))
        if face in faces:
            raise ParseError('duplicate TIN triangle')
        faces.add(face)
        for edge, (u,v) in enumerate(((a,b),(b,c),(c,a))):
            incidences = edges.setdefault(tuple(sorted((u,v))), [])
            incidences.append((i//3+1, edge, u, v))
            if len(incidences) > 2:
                raise ParseError('non-manifold TIN edge')
        ax,ay = obj.coordinates[3*(a-1):3*(a-1)+2]
        bx,by = obj.coordinates[3*(b-1):3*(b-1)+2]
        cx,cy = obj.coordinates[3*(c-1):3*(c-1)+2]
        sign = orientation(ax, ay, bx, by, cx, cy)
        if sign > 0 or sign == 0 and not inspection:
            raise ParseError('TIN triangle must have nonzero clockwise plan area')
        if sign == 0:
            obj.preview_exclusions.append(i//3+1)
    for incidences in edges.values():
        if len(incidences) == 2:
            first, second = incidences
            if first[2:] != second[2:][::-1]:
                raise ParseError('inconsistent TIN edge orientation')
    if obj.kind == 'full_tin':
        if np < 4:
            raise ParseError('full TIN needs four construction points')
        obj.neighbours = ints(f.pop('neighbours', None))
        codes = ints(f.pop('nulling', None))
        if len(obj.neighbours) != 3*nt or len(codes) != nt:
            raise ParseError('full TIN topology/visibility length mismatch')
        if any(v < 0 or v > nt for v in obj.neighbours) or any(v not in (1,2) for v in codes):
            raise ParseError('invalid full TIN neighbour or visibility')
        obj.nulling = array('B', codes)
        obj.construction = array('B', (any(v <= 4 for v in obj.triangles[i:i+3]) for i in range(0,3*nt,3)))
        for t in range(nt):
            tri = obj.triangles[3*t:3*t+3]
            for edge in range(3):
                nb = obj.neighbours[3*t+edge]
                incidences = edges[tuple(sorted((tri[edge],tri[(edge+1)%3])))]
                expected = next((entry[0] for entry in incidences if entry[0] != t+1), 0)
                if nb != expected:
                    raise ParseError('neighbour does not match edge incidence')
                if nb == 0:
                    if not (tri[edge] <= 4 and tri[(edge+1)%3] <= 4):
                        raise ParseError('outside edge must join construction points')
                    continue
                other = obj.triangles[3*(nb-1):3*nb]
                reverse = (tri[(edge+1)%3],tri[edge])
                matches = [j for j in range(3) if (other[j],other[(j+1)%3]) == reverse]
                if len(matches)!=1 or obj.neighbours[3*(nb-1)+matches[0]] != t+1:
                    raise ParseError('inconsistent neighbour topology')
    else:
        obj.nulling = array('B', [2])*nt
        obj.construction = array('B', [0])*nt
    if 'colours' in f:
        colour = f['colours']
        if (not isinstance(colour, Block) or len(colour.items) != nt
                or any(not isinstance(v, str) for v in colour.items)):
            raise ParseError('TIN colours length mismatch')
    # Recovery is published only after every structural/topology check passed.
    obj.preview_supported = True
    obj.geometry_issue_count = len(obj.preview_exclusions)
    obj.geometry_integrity = 'zero_area_faces' if obj.geometry_issue_count else 'valid'
    for triangle in obj.preview_exclusions:
        visible = obj.nulling[triangle-1] == 2
        obj.visible_geometry_issue_count += visible
        if len(obj.geometry_issues) < MAX_ISSUE_DETAILS:
            obj.geometry_issues.append(dict(code='zero_plan_area', severity='error', triangle=triangle,
                point_indices=list(obj.triangles[3*(triangle-1):3*triangle]), visible=visible,
                construction=bool(obj.construction[triangle-1])))


def string(obj, f, null, coordinate_precision=None):
    kind = obj.kind
    closed = flag(f.pop('closed', '0'))
    obj.settings['closed'] = closed
    keys = [k for k in ('data_2d','data_3d','data') if k in f]
    if len(keys)!=1:
        raise ParseError('string requires exactly one coordinate block')
    key = keys[0]
    if kind in ('2d','3d','polyline') and key != 'data':
        raise ParseError('legacy string requires data block')
    stride = 2 if key == 'data_2d' or kind == '2d' else 5 if key == 'data' and kind in ('super', 'polyline') else 3
    data = numeric(f.pop(key))
    if not data or len(data)%stride:
        raise ParseError('string coordinate length mismatch')
    zvalue = f.pop('z', 'null')
    z = math.nan if isinstance(zvalue, str) and zvalue.lower() == 'null' else missing(number(zvalue), null)
    radii, majors = [], []
    explicit_radii = 'radius_data' in f or stride == 5
    for i in range(0,len(data),stride):
        x,y = data[i:i+2]
        if not math.isfinite(x) or not math.isfinite(y):
            raise ParseError('missing plan coordinate')
        obj.coordinates.extend((x,y,z if stride==2 else missing(data[i+2],null)))
        if stride==5:
            radii.append(data[i+3]); majors.append(data[i+4])
    n = len(obj.coordinates)//3
    ns = n if closed else n-1
    if 'radius_data' in f:
        if stride==5:
            raise ParseError('conflicting segment representations')
        radii = numeric(f.pop('radius_data'))
        majors = numeric(f.pop('major_data', None))
    elif 'major_data' in f:
        raise ParseError('major data without radii')
    if explicit_radii:
        if len(radii) not in (ns,n) or len(majors)!=len(radii):
            raise ParseError('arc array length mismatch')
        obj.segments = [Segment('straight' if r==0 else 'arc', r, flag(integer(m))) for r,m in zip(radii,majors)]
    if 'geometry_data' in f:
        if radii:
            raise ParseError('conflicting segment representations')
        geometry = f.pop('geometry_data')
        if not isinstance(geometry, Block) or len(geometry.items)%2:
            raise ParseError('invalid segment geometry')
        for i in range(0,len(geometry.items),2):
            name,b = geometry.items[i:i+2]
            if not isinstance(name,str) or not isinstance(b,Block):
                raise ParseError('invalid segment block')
            name = name.lower()
            if name == 'straight':
                if b.items:
                    raise ParseError('unexpected straight parameters')
                obj.segments.append(Segment('straight'))
            elif name == 'arc':
                p = pairs(b)
                if set(p) != {'radius','major'}:
                    raise ParseError('invalid arc parameters')
                obj.segments.append(Segment('arc',number(p['radius']),flag(p['major'])))
            else:
                obj.segments.append(Segment(name))
                obj.diagnostics.append(f'unsupported segment: {name}; geometry incomplete')
        if len(obj.segments) not in (ns,n):
            raise ParseError('segment count mismatch')
    if not obj.segments:
        obj.segments = [Segment('straight') for _ in range(ns)]
    for i,s in enumerate(obj.segments):
        if s.kind == 'arc':
            if not math.isfinite(s.radius) or s.radius==0:
                raise ParseError('invalid arc radius')
            if i < ns:
                a,b = 3*i,3*((i+1)%n)
                chord = math.hypot(obj.coordinates[a]-obj.coordinates[b],obj.coordinates[a+1]-obj.coordinates[b+1])
                if chord == 0 or not math.isfinite(chord):
                    raise ParseError('arc radius incompatible with endpoints')
                if arc_exceeds_diameter(obj.coordinates, a, b, s.radius):
                    bound = arc_rounding_bound(data, coordinate_precision, a, b,
                                               obj.coordinates, s.radius)
                    if bound is None:
                        raise ParseError('arc radius incompatible with endpoints')
                    obj.diagnostics.append(f'{ARC_DIAGNOSTIC} segment {i+1}: endpoint/radius discrepancy '
                                           f'within decimal export rounding (bound {bound:.17g}); source parameters unchanged')


def load(path, *, limits=None, inspection=False):
    """Parse and validate all input before returning a Document; raises ParseError."""
    limits = limits or Limits()
    if type(inspection) is not bool:
        raise ValueError('inspection must be an explicit Boolean')
    text, sha, payload, member, encoding, diagnostics = read_source(path, limits)
    g = Grammar(text, limits)
    defaults = dict(model='data', colour='red', style='1', breakline='point', null='-999')
    objects, models, model_keys = [], {}, {}
    coordinate_precision, precision_resolved = None, False
    rounded_segments, rounded_objects = 0, 0

    def register_model(name, attrs=None):
        name = str(name)
        canonical = model_keys.setdefault(name.casefold(), name)
        if attrs is not None:
            models[canonical] = attrs
            if duplicate_attributes(attrs):
                diagnostics.append(f'duplicate model attribute names retained: {canonical}')
            diagnostics.extend(attribute_diagnostics(attrs))
        else:
            models.setdefault(canonical, [])
        if len(models) > limits.objects:
            raise ParseError('model count limit exceeded')
        return canonical

    while g.peek() is not None:
        if len(models) > limits.objects:
            raise ParseError('model count limit exceeded')
        start = g.cached[1]
        key = g.pop().lower()
        if key == 'model':
            g.collect_header = False
        if key in ('model','colour','style','breakline','null'):
            g.in_object, g.object_start = True, start
            g.numeric_enabled = False
            value = g.block() if g.peek() == '{' else g.pop()
            g.in_object = False
            if key=='model' and isinstance(value,Block):
                p = pairs(value)
                name = p.pop('name',None)
                attrs = attributes(p.pop('attributes')) if 'attributes' in p else []
                if p:
                    diagnostics.append('unsupported model fields')
                value = name
                if not isinstance(value, str) or not value.strip():
                    raise ParseError('invalid model name')
                register_model(value, attrs)
            if not isinstance(value,str) or value in ('{','}'):
                raise ParseError(f'invalid {key} setting')
            if key=='model':
                if not value.strip():
                    raise ParseError('blank model name')
                register_model(value)
            if key == 'null' and value.lower() != 'null':
                number(value)
            if key == 'breakline' and value.lower() not in ('point', 'line'):
                raise ParseError('invalid breakline type')
            defaults[key] = str(value)
            continue
        g.collect_header = False
        if not precision_resolved:
            coordinate_precision = export_decimal_places(g.header)
            precision_resolved = True
        kind = g.pop().lower() if key=='string' else key
        if g.peek() != '{':
            raise ParseError(f'unknown top-level command {key} without braced payload')
        if len(objects) >= limits.objects:
            raise ParseError('object count limit exceeded')
        g.in_object, g.object_start = True, start
        g.object_kind = kind
        g.numeric_enabled = kind in ('super', '2d', '3d', 'polyline', 'text', 'circle', 'tin', 'full_tin')
        block = g.block()
        g.in_object = False
        try:
            obj = interpret(kind, block, defaults, f'{payload}:{len(objects)+1}', coordinate_precision, inspection=inspection)
        except ParseError as e:
            raise ParseError(f'object {len(objects)+1} ({kind}) at characters {start}:{block.end}: {e}') from e
        obj.source.start = start
        objects.append(obj)
        count = sum(message.startswith(ARC_DIAGNOSTIC) for message in obj.diagnostics)
        rounded_segments += count
        rounded_objects += bool(count)
        obj.model = register_model(obj.model)
    if rounded_segments:
        diagnostics.append(f'{ARC_DIAGNOSTIC}s: {rounded_segments} segments in {rounded_objects} objects; '
                           'decimal export rounding allowance used; source geometry retained unchanged')
    return Document(sha,payload,member,encoding,objects,models,diagnostics,g.header)
