"""Specification-based invented fixtures, no copied upstream test data."""
import contextlib
from dataclasses import replace
import io
import json
import math
from pathlib import Path
import tempfile
import unittest
from twelve_da import load, Limits, ParseError, Properties, FlagValue
from twelve_da.cli import main


class CompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'example.12da'

    def parse(self, text, **kwargs):
        self.path.write_text(text, encoding='utf-8')
        return load(self.path, **kwargs)

    def test_text_retains_anchor_content_and_presentation(self):
        d = self.parse('''model Notes colour blue string text {
            name "" x 0x1.4p2 y -2 z null text "A \\\"quoted\\\" label\\\\path"
            angle 45 offset 1 raise 2 textstyle Arial slant .5 x_factor 1.25
            papersize .3 justify "middle-centre" text_colour green
        }''')
        obj = d.objects[0]
        self.assertEqual(d.coverage, 'complete')
        self.assertEqual(obj.coordinates[:2].tolist(), [5,-2])
        self.assertTrue(math.isnan(obj.coordinates[2]))
        self.assertEqual(obj.text.value, 'A "quoted" label\\path')
        self.assertEqual(obj.text.properties.values['x_factor'], 1.25)
        self.assertEqual(obj.text.properties.values['text_colour'], 'green')
        self.assertEqual(obj.settings['colour'], 'blue')
        self.assertEqual(obj.text.properties.values['raise'], 2)
        self.assertEqual(obj.coordinates[0], 5)  # Presentation offsets never move source anchors.

    def test_blank_text_and_null_sentinel(self):
        obj = self.parse('null -42 string text {x 1 y 2 z -42 text ""}').objects[0]
        self.assertEqual(obj.text.value, '')
        self.assertTrue(math.isnan(obj.coordinates[2]))

    def test_circle_is_exact_source_parameters(self):
        obj = self.parse('string circle {xcentre 1 ycentre 2 zcentre 3 radius 5 interval .1}').objects[0]
        self.assertEqual(obj.coordinates.tolist(), [1,2,3])
        self.assertEqual(obj.circle.radius, 5)
        self.assertEqual(obj.circle.interval, .1)
        self.assertEqual(obj.segments, [])
        self.assertEqual(len(obj.coordinates), 3)  # No tessellation.
        self.assertEqual(obj.coverage, 'complete')

    def test_signed_circle_radius_is_preserved_explicitly(self):
        obj = self.parse('string circle {xcentre 1 ycentre 2 radius -5}').objects[0]
        self.assertEqual(obj.circle.radius, -5)
        self.assertEqual(obj.coverage, 'partial')
        self.assertIn('signed circle radius', obj.diagnostics[0])

    def test_legacy_polyline_closed_and_dormant_segment(self):
        obj = self.parse('string polyline {closed 0 data {0 0 null -2 f 2 0 4 0 t}}').objects[0]
        self.assertEqual(len(obj.coordinates), 6)
        self.assertTrue(math.isnan(obj.coordinates[2]))
        self.assertEqual(len(obj.segments), 2)
        self.assertEqual(obj.segments[0].radius, -2)
        self.assertTrue(obj.segments[1].major)
        obj = self.parse('string polyline {closed true data {0 0 0 2 f 2 0 0 2 t}}').objects[0]
        self.assertTrue(obj.settings['closed'])
        self.assertEqual(len(obj.segments), 2)

    def test_invalid_new_geometry_fails(self):
        bad = ['string text {x 1 text hi}', 'string text {x null y 1 text hi}',
               'string text {x 1 y 1}', 'string text {x 1 y 1 text {bad value}}',
               'string circle {xcentre 1 ycentre 2 radius 0}',
               'string circle {xcentre 1 ycentre 2}',
               'string polyline {data {0 0 0 1}}',
               'string polyline {data {0 0 0 .1 f 2 0 0 0 f}}']
        for text in bad:
            with self.subTest(text=text), self.assertRaises(ParseError): self.parse(text)

    def test_structured_annotation_symbol_and_pipe(self):
        obj = self.parse('''string super {data_2d {0 0 1 1}
            vertex_annotate_value {angle 10 worldsize .4 textstyle Arial colour red}
            vertex_annotate_data {properties {worldsize .4} properties {worldsize .5}}
            symbol_data {properties {style A size 1 rotation 30} properties {style B size null}}
            diameter_value .2 diameter_data {.3 null} justify invert
            vertex_text_value Label segment_text_value "Segment label"
        }''').objects[0]
        self.assertEqual(obj.coverage, 'partial')
        self.assertIsInstance(obj.metadata['vertex_annotate_value'], Properties)
        self.assertEqual(obj.metadata['vertex_annotate_value'].values['angle'], 10)
        self.assertEqual(obj.metadata['symbol_data'][1].values['size'], None)
        self.assertEqual(obj.metadata['diameter_data'], [.3,None])
        self.assertEqual(obj.metadata['justify'], 'invert')
        self.assertTrue(any('competing scalar' in d for d in obj.diagnostics))
        obj = self.parse('''string super {data_2d {0 0 1 1}
            culvert_data {properties {width 1 height null}}}''').objects[0]
        self.assertEqual(obj.coverage, 'complete')
        self.assertEqual(obj.metadata['culvert_data'][0].values, {'width':1,'height':None})

    def test_contradictory_modes_cannot_be_complete(self):
        with self.assertRaises(ParseError):
            self.parse('string super {data_2d {0 0} diameter_value .2 culvert_value {width 1 height 2}}')
        obj = self.parse('''string super {data_2d {0 0}
            vertex_annotate_value {worldsize 1}
            vertex_annotate_data {properties {papersize 2}}}''').objects[0]
        self.assertEqual(obj.coverage, 'partial')
        self.assertTrue(any('mixed annotation' in d for d in obj.diagnostics))

    def test_unknown_nested_properties_are_never_complete(self):
        obj = self.parse('''string super {data_2d {0 0}
            symbol_value {style A future {key value}}
            pipe_value {diameter .4}
            vertex_annotate_value {worldsize 1 papersize 2}
        }''').objects[0]
        self.assertEqual(obj.coverage, 'partial')
        self.assertEqual(obj.metadata['symbol_value'].extras['future'], ['key','value'])
        self.assertEqual(obj.metadata['pipe_value'].values['diameter'], .4)
        self.assertTrue(any('multiple text size modes' in d for d in obj.diagnostics))

    def test_scalar_flags_keep_unresolved_codes_separate(self):
        obj = self.parse('''string super {data_2d {0 0}
            vertex_visible_value 2 segment_visible_value 0
            vertex_tinable_value null segment_tinable_value true
            vertex_visible_data {null}
        }''').objects[0]
        self.assertEqual(obj.metadata['vertex_visible_value'], FlagValue(None,'2'))
        self.assertEqual(obj.metadata['segment_visible_value'], FlagValue(False,'0'))
        self.assertEqual(obj.metadata['segment_tinable_value'], FlagValue(True,'true'))
        self.assertEqual(obj.metadata['vertex_visible_data'], [None])
        self.assertEqual(obj.coverage, 'partial')

    def test_metadata_lengths_and_known_value_types(self):
        bad = ['symbol_data {properties {size 1}}',
               'diameter_data {1 2 3}',
               'vertex_annotate_data {properties {worldsize 1}}',
               'culvert_value {width {x y}}',
               'vertex_annotate_value {worldsize nope}',
               'symbol_data {future {size 1}}']
        for metadata in bad:
            with self.subTest(metadata=metadata), self.assertRaises(ParseError):
                self.parse('string super {data_2d {0 0 1 1} '+metadata+'}')

    def test_line_specific_extension_names_on_other_objects_stay_partial(self):
        for prefix in ('string text {x 1 y 2 text X',
                       'string circle {xcentre 1 ycentre 2 radius 3',
                       'tin {name T points {0 0 0 0 1 0 1 0 0} triangles {1 2 3}'):
            for extension in ('vertex_annotate_value {future extension}',
                              'vertex_annotate_data {properties {future extension}}',
                              'vertex_attribute_data {attributes {text A a}}',
                              'segment_attribute_data {attributes {text A a}}'):
                with self.subTest(prefix=prefix, extension=extension):
                    obj = self.parse(prefix+' '+extension+'}').objects[0]
                    self.assertEqual(obj.coverage, 'partial')
                    self.assertTrue(obj.metadata)

    def test_uid_and_unknown_scalar_attributes(self):
        obj = self.parse('''string super {data_2d {0 0} attributes {
            uid ExternalID 18446744073709551617 uid Missing null
            future CaseSensitive "uninterpreted value"
            group {name G attributes {uid Nested 17}}
        }}''').objects[0]
        self.assertEqual(obj.attributes[0].value, 18446744073709551617)
        self.assertEqual(obj.attributes[1].value, None)
        self.assertEqual(obj.attributes[2].kind, 'future')
        self.assertEqual(obj.attributes[2].value, 'uninterpreted value')
        self.assertEqual(obj.coverage, 'partial')
        self.assertTrue(any('opaque identifier' in d for d in obj.diagnostics))
        with self.assertRaises(ParseError): self.parse('string super {data_2d {0 0} attributes {uid A nope}}')
        with self.assertRaises(ParseError): self.parse('string super {data_2d {0 0} attributes {integer A "null"}}')

    def test_header_metadata_is_descriptive_and_source_referenced(self):
        text = '''null null
// archive_version "15.1.test"
// application : Example Exporter
// output_example true
// null -999
model M
string super {data_3d {1 2 -999}}
// archive_version "not a header"
'''
        d = self.parse(text)
        self.assertEqual([h.key for h in d.header], ['archive_version','application','output_example','null'])
        self.assertEqual(d.header[0].value, '15.1.test')
        self.assertEqual(d.objects[0].coordinates[2], -999)  # Comment does not change null setting.
        self.assertEqual(text[d.header[0].source.start:d.header[0].source.end], '// archive_version "15.1.test"')
        self.assertEqual(d.inspect()['header'][1]['value'], 'Example Exporter')
        with self.assertRaises(ParseError): load(self.path, limits=replace(Limits(), header_fields=1))

    def test_header_count_and_value_size_caps(self):
        with self.assertRaises(ParseError): self.parse('// archive_version abc\n', limits=replace(Limits(), header_fields=0))
        with self.assertRaises(ParseError): self.parse('// application '+('x'*100), limits=replace(Limits(), token_chars=20))
        with self.assertRaises(ParseError):
            self.parse('// application x'+(' '*100000)+'y', limits=replace(Limits(), token_chars=20))

    def test_cli_schema_and_atomic_new_object_output(self):
        doc = self.parse('// archive_version X\nstring circle {xcentre 1 ycentre 2 radius 3}')
        target = Path(self.temp.name)/'circle.json'
        with contextlib.redirect_stdout(io.StringIO()):
            status = main(['get',str(self.path),doc.objects[0].id,'--output',str(target)])
        self.assertEqual(status, 0)
        result = json.loads(target.read_text())
        self.assertEqual(result['document']['schema_version'], '3')
        self.assertEqual(result['document']['header'][0]['value'], 'X')
        self.assertEqual(result['object']['circle']['radius'], 3)


if __name__ == '__main__': unittest.main()
