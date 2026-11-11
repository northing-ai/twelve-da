import contextlib
from dataclasses import replace
import hashlib
import io
import json
import math
from pathlib import Path
import tempfile
import struct
import unittest
import zipfile
import zlib
from twelve_da import load, Limits, ParseError
from twelve_da.cli import main
from twelve_da.model import clean

FIXTURE = Path(__file__).parent/'fixtures/synthetic/complete.12da'


class ParserTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/'input.12da'

    def parse(self, text, **kwargs):
        self.path.write_text(text)
        return load(self.path, **kwargs)

    def test_complete_fixture(self):
        d = load(FIXTURE)
        self.assertEqual(d.coverage,'complete')
        self.assertEqual(len(d.objects),6)
        o = d.objects[0]
        self.assertEqual(o.settings['colour'],'blue')
        self.assertTrue(math.isnan(o.coordinates[2]))
        self.assertEqual(o.segments[0].radius,2)
        self.assertFalse(o.segments[0].major)
        self.assertEqual(d.models['Example'][3].value[0].value,'X')
        self.assertEqual(d.objects[-1].neighbours.tolist(),[0,0,2,1,0,0])
        self.assertEqual(d.objects[-1].nulling.tolist(),[1,2])
        self.assertEqual(d.objects[-1].construction.tolist(),[1,1])
        self.assertEqual(clean(o)['coordinates'][2],None)
        self.assertEqual(len({o.id for o in d.objects}),6)
        self.assertIs(d.get(o.id),o)

    def test_whitespace_comments_case_and_quotes(self):
        d = self.parse('MoDeL\n"}" STRING SUPER { name "{" data_2d { 1//comment\n2 } }')
        self.assertEqual(d.objects[0].model,'}')
        self.assertEqual(d.objects[0].name,'{')
        self.assertEqual(d.objects[0].coordinates[:2].tolist(),[1,2])

    def test_numbers_and_null(self):
        d = self.parse('null -7 string super { null_value -8 data_3d { +.5 1e2 -8 0x1p+2 -2.5E-1 -7 } }')
        a = d.objects[0].coordinates
        self.assertTrue(math.isnan(a[2]))
        self.assertEqual(a[3:].tolist(),[4,-.25,-7])

    def test_model_names_match_case_insensitively(self):
        d = self.parse('model {name M attributes {text A x}} model m string super { data_2d {0 0} }')
        self.assertEqual(list(d.models), ['M'])
        self.assertEqual(d.objects[0].model, 'M')
        self.assertEqual(d.objects[0].settings['model'], 'm')
        self.assertEqual(d.models['M'][0].value, 'x')

    def test_explicit_null_and_visibility(self):
        d = self.parse('string super { z null data_2d {0 0 1 1} vertex_visible_data {t f} segment_tinable_data {0} }')
        self.assertTrue(math.isnan(d.objects[0].coordinates[2]))
        self.assertEqual(d.objects[0].metadata['vertex_visible_data'], [True,False])
        self.assertEqual(d.objects[0].metadata['segment_tinable_data'], [False])
        self.assertEqual(d.coverage,'complete')

    def test_encodings_and_containers(self):
        text = 'string super { name "café" data_2d {1 2} }'
        expected = None
        for enc in ('utf-8','utf-16','utf-16-be','cp1252'):
            b = text.encode(enc)
            self.path.write_bytes(b)
            d = load(self.path)
            self.assertEqual(d.objects[0].name,'café')
            archive = self.path.with_suffix('.12daz')
            with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
                z.writestr('payload.12da',b)
            zipped = load(archive)
            self.assertEqual(zipped.objects[0].to_dict(),d.objects[0].to_dict())
            self.assertEqual(zipped.source_sha256,hashlib.sha256(archive.read_bytes()).hexdigest())
            self.assertEqual(zipped.payload_sha256,d.payload_sha256)
            self.assertEqual(zipped.archive_member,'payload.12da')
            if enc=='cp1252': self.assertIn('legacy',d.diagnostics[0])

    def test_partial_segments_and_fields(self):
        d = self.parse('string super { data_2d { 0 0 1 1 } geometry_data { spiral { type clothoid } } future { key value } points { arbitrary tokens } vertex_future_data { a b c } } string future { data { arbitrary tokens } }')
        self.assertEqual(d.coverage,'partial')
        self.assertEqual(d.objects[0].segments[0].kind,'spiral')
        self.assertEqual(len(d.objects[1].coordinates),0)
        self.assertEqual(len(d.objects[0].diagnostics),4)

    def test_closed_and_geometry_blocks(self):
        d = self.parse('string super { closed yes data_2d { 0 0 2 0 } geometry_data { arc { radius -2 major true } straight {} } }')
        self.assertEqual(len(d.objects[0].segments),2)
        self.assertTrue(d.objects[0].segments[0].major)
        d = self.parse('string super { data { 0 0 1 2 f 2 0 1 0 f } }')
        self.assertEqual(d.objects[0].segments[0].kind,'arc')

    def test_duplicate_attributes_are_preserved_and_partial(self):
        d = self.parse('string super { attributes { text A x text A y text a z } data_2d {0 0} }')
        self.assertEqual([a.value for a in d.objects[0].attributes],['x','y','z'])
        self.assertEqual(d.coverage,'partial')

    def test_unknown_nested_semantics_are_preserved_and_partial(self):
        d = self.parse('''model {name M attributes {
            group {name G attributes {text A a} future {x y}}
        }} string super {data_2d {0 0} attributes {
            group {name G attributes {text A a} future {x y}}
        } interval {chord_arc .1 unsupported_curve {a b}}
          vertex_annotate_data {properties {unsupported_curve {a b}}}
          input {future geometry} colours {future geometry}}''')
        obj = d.objects[0]
        self.assertEqual(d.coverage, 'partial')
        self.assertEqual(obj.attributes[0].metadata['future'], ['x', 'y'])
        self.assertEqual(d.models['M'][0].metadata['future'], ['x', 'y'])
        self.assertIn('unsupported attribute group field: future', obj.diagnostics)
        self.assertIn('unsupported property: interval/unsupported_curve', obj.diagnostics)
        self.assertEqual(obj.metadata['vertex_annotate_data'][0].extras['unsupported_curve'], ['a','b'])
        self.assertIn('unsupported field: input', obj.diagnostics)
        self.assertIn('unsupported field: colours', obj.diagnostics)
        self.assertEqual(obj.metadata['input'], ['future', 'geometry'])

    def test_known_nested_metadata_still_validates(self):
        valid = 'string super {data_2d {0 0} interval {chord_arc .1 distance 10}}'
        self.assertEqual(self.parse(valid).coverage, 'complete')
        d = self.parse('string super {data_2d {0 0} interval {chord_arc null distance null}}')
        self.assertEqual(d.coverage, 'complete')
        self.assertEqual(d.objects[0].metadata['interval'].values, {'chord_arc':None,'distance':None})
        for invalid in ('interval {chord_arc {x y}}', 'chainage {future geometry}',
                        'vertex_text_data {properties {x y}}'):
            with self.subTest(invalid=invalid), self.assertRaises(ParseError):
                self.parse('string super {data_2d {0 0} '+invalid+'}')

    def test_invalid_supported_input(self):
        invalid = ['string super {', 'string super { name "oops }', '}',
          'string super { data_2d {0} }', 'string super { data_3d {null 0 1} }',
          'string super { data_2d {0 0 4 0} radius_data {1} major_data {f} }',
          'string super { data_2d {0 0 1 1} geometry_data { arc { radius 0 major 0 } } }',
          'string super { data_2d {0 0} point_data {a b} }',
          'string super { data_2d {0 0} data_3d {0 0 0} }',
          'string super { data_2d {1e999 0} }',
          'string 3d { data {0 0 0 1 f 1} }',
          'string super {data_2d {0 0 1 1} radius_data {} major_data {}}',
          'string super {data_2d {0 0} vertex_visible_data {2}}',
          'tin {name a points {0 0 0 0 1 0 1 0 0} triangles {1 2 4}}',
          'tin {name a points {0 0 0 0 1 0 1 0 0} triangles {1 3 2}}',
          'tin {name a points {0 0 0 1 0 0 2 0 0} triangles {1 2 3}}',
          'string super { data_2d {0 0} } trailing',
          'null garbage', 'string super {data_2d {0 0} name a name b}']
        invalid.append('string super {data_2d {0 0} attributes {text x group {name y}}}')
        for text in invalid:
            with self.subTest(text=text),self.assertRaises(ParseError): self.parse(text)

    def test_tiny_valid_triangle_uses_exact_orientation(self):
        d = self.parse('tin {name tiny points {0 0 0 0 1e-200 0 1e-200 0 0} triangles {1 2 3}}')
        self.assertEqual(d.coverage, 'complete')

    def test_inherited_overrides_and_attribute_nulls(self):
        d = self.parse('colour blue string super {colour red data_2d {0 0} attributes {integer A null real B null text C null}} string super {data_2d {1 1}}')
        self.assertEqual([o.settings["colour"] for o in d.objects], ["red","blue"])
        self.assertEqual([a.value for a in d.objects[0].attributes], [None,None,"null"])

    def test_full_tin_topology_and_visibility_failures(self):
        text = FIXTURE.read_text()
        for bad in ('neighbours { 0 0 1 1 0 0 }','neighbours { 0 0 0 1 0 0 }','neighbours { 0 0 9 1 0 0 }'):
            with self.assertRaises(ParseError): self.parse(text.replace('neighbours { 0 0 2 1 0 0 }',bad))
        with self.assertRaises(ParseError): self.parse(text.replace('nulling { 1 2 }','nulling { 0 2 }'))
        with self.assertRaises(ParseError):
            self.parse(text.replace('neighbours { 0 0 2 1 0 0 }', 'neighbours {0 0 0 0 0 0}'))
        with self.assertRaises(ParseError):
            self.parse('tin {name repeated points {0 0 0 0 1 0 1 0 0} triangles {1 2 3 1 2 3}}')
        with self.assertRaises(ParseError):
            self.parse('tin {name nonmanifold points {0 0 0 0 1 0 1 0 0 2 0 0 3 0 0} triangles {1 2 3 1 2 4 1 2 5}}')

    def test_full_tin_shared_edges_match_neighbours(self):
        d = self.parse('''full_tin {name Full
            points {0 0 0 0 2 0 2 2 0 2 0 0 1 1 0}
            triangles {1 2 5 2 3 5 3 4 5 4 1 5}
            neighbours {0 2 4 0 3 1 0 4 2 0 1 3} nulling {1 2 2 1}
        }''')
        self.assertEqual(d.coverage, 'complete')
        self.assertEqual(d.objects[0].construction.tolist(), [1,1,1,1])

    def test_limits_configuration(self):
        for kwargs in ({'input_bytes':-1}, {'object_chars':1.5}, {'nesting':True}):
            with self.assertRaises(ValueError): Limits(**kwargs)

    def test_limits(self):
        text = 'string super { data_2d {0 0} }'
        for limits in (replace(Limits(), input_bytes=2),replace(Limits(),expanded_bytes=2),
                       replace(Limits(),objects=0),replace(Limits(),object_chars=10),
                       replace(Limits(),nesting=1),replace(Limits(),token_chars=3),replace(Limits(),tokens=2)):
            with self.assertRaises(ParseError): self.parse(text,limits=limits)
        with self.assertRaises(ParseError): self.parse('model { name a attributes {} }',limits=replace(Limits(),object_chars=10))

    def test_ambiguous_archive(self):
        p = self.path.with_suffix('.12daz')
        with zipfile.ZipFile(p,'w') as z:
            z.writestr('a.12da','');z.writestr('b.12da','')
        with self.assertRaises(ParseError): load(p)
        with zipfile.ZipFile(p,'w',zipfile.ZIP_DEFLATED) as z:
            z.writestr('a.12da','string super {data_2d {0 0}}')
        with self.assertRaises(ParseError): load(p,limits=replace(Limits(),expanded_bytes=2))
        p.write_bytes(b'PKbroken')
        with self.assertRaises(ParseError): load(p)

    def test_forged_zip_size_cannot_hide_decompressed_content(self):
        prefix = b'string super {data_2d {0 0}}\n'
        payload = prefix + b'invalid trailing content'
        p = self.path.with_suffix('.12daz')
        with zipfile.ZipFile(p, 'w', zipfile.ZIP_DEFLATED) as z:
            z.writestr('payload.12da', payload)
        raw = bytearray(p.read_bytes())
        central = raw.index(b'PK\x01\x02')
        for crc_offset, size_offset in ((14, 22), (central+16, central+24)):
            struct.pack_into('<I', raw, crc_offset, zlib.crc32(prefix))
            struct.pack_into('<I', raw, size_offset, len(prefix))
        p.write_bytes(raw)
        # Python's normal reader returns only the valid prefix for this forgery.
        with zipfile.ZipFile(p) as z:
            self.assertEqual(z.read('payload.12da'), prefix)
        with self.assertRaisesRegex(ParseError, 'size or CRC mismatch'):
            load(p)
        with self.assertRaisesRegex(ParseError, 'expanded byte limit'):
            load(p, limits=replace(Limits(), expanded_bytes=len(prefix)+1))

    def test_cli_atomic_output_and_status(self):
        d = load(FIXTURE)
        out = Path(self.tmp.name)/'object.json'
        with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(['get',str(FIXTURE),d.objects[0].id,'--output',str(out)]),0)
            self.assertEqual(json.loads(out.read_text())['object']['id'],d.objects[0].id)
            self.path.write_text('string super { data_2d {0 0} } broken')
            before = out.read_bytes()
            self.assertEqual(main(['get',str(self.path),'bad','--output',str(out)]),2)
            self.assertEqual(out.read_bytes(),before)
            self.assertEqual(main(['get',str(FIXTURE),'bad','--output',str(FIXTURE)]),2)
            self.path.write_text('string future { name x }')
            self.assertEqual(main(['inspect',str(self.path)]),3)
            self.assertEqual(main(['list',str(FIXTURE)]),0)

    def test_cli_rejects_existing_source_file_aliases(self):
        self.path.write_text('string super {data_2d {0 0}}')
        original = self.path.read_bytes()
        doc = load(self.path)
        hardlink = self.path.with_name('hardlink.12da')
        hardlink.hardlink_to(self.path)
        aliases = [hardlink]
        case_alias = self.path.with_name(self.path.name.upper())
        if case_alias.exists() and case_alias.samefile(self.path):
            aliases.append(case_alias)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            for alias in aliases:
                self.assertEqual(main(['get', str(self.path), doc.objects[0].id,
                                       '--output', str(alias)]), 2)
                self.assertEqual(self.path.read_bytes(), original)
                self.assertEqual(alias.read_bytes(), original)


if __name__=='__main__': unittest.main()
