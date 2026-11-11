"""Invented geometry checks the declared-precision boundary, without private data."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from twelve_da import load, ParseError
from twelve_da.cli import main
from twelve_da.model import clean


class PrecisionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'synthetic.12da'

    def parse(self, body, header='// decimal_places 8\n'):
        self.path.write_text(header + body)
        return load(self.path)

    def arc(self, end='0.200000005', *, closed=False):
        return f'string super {{closed {int(closed)} data_2d {{0 0 {end} 0}} radius_data {{-0.1' + (' -0.1' if closed else '') + '} major_data {f' + (' f' if closed else '') + '}}'

    def test_small_decimal_rounding_is_partial_and_source_values_are_unchanged(self):
        body = self.arc()
        doc = self.parse(body)
        obj = doc.objects[0]
        self.assertEqual(doc.coverage, 'partial')
        self.assertEqual(clean(obj.coordinates), [0, 0, None, .200000005, 0, None])
        self.assertEqual(obj.segments[0].radius, -.1)
        self.assertFalse(obj.segments[0].major)
        self.assertIn('precision-limited arc segment 1', obj.diagnostics[0])
        self.assertIn('source parameters unchanged', obj.diagnostics[0])
        self.assertIn('1 segments in 1 objects', doc.inspect()['diagnostics'][0])
        self.assertEqual(self.path.read_text(), '// decimal_places 8\n' + body)

    def test_material_and_just_outside_rounding_discrepancies_still_fail(self):
        for end in ('.20000002', '.20001', '1', '0'):
            with self.subTest(end=end), self.assertRaisesRegex(ParseError, 'arc radius incompatible'):
                self.parse(self.arc(end))

    def test_missing_invalid_duplicate_or_coarse_declaration_does_not_relax(self):
        for header in ('', '// decimal_places 0\n', '// decimal_places -8\n',
                       '// decimal_places 16\n', '// decimal_places nan\n',
                       '// decimal_places 8.0\n', '// decimal_places 8\n// decimal_places 8\n',
                       '// decimal_places 8\n// decimal_places 7\n'):
            with self.subTest(header=header), self.assertRaises(ParseError):
                self.parse(self.arc(), header)

    def test_object_comment_is_not_a_precision_declaration(self):
        body = self.arc().replace('data_2d', '// decimal_places 8\ndata_2d')
        with self.assertRaises(ParseError): self.parse(body, '')

    def test_hex_xy_and_finer_lexical_precision_get_no_coarse_allowance(self):
        for coords in ('0x0p0 0x0p0 0x1.99999a4569303p-3 0x0p0',
                       '0.000000000000 0.000000000000 0.200000005000 0.000000000000'):
            with self.subTest(coords=coords), self.assertRaises(ParseError):
                self.parse(f'string super {{data_2d {{{coords}}} radius_data {{.1}} major_data {{f}}}}')

    def test_ordinary_valid_geometry_remains_complete(self):
        doc = self.parse(self.arc('0.2'))
        self.assertEqual(doc.coverage, 'complete')
        self.assertEqual(doc.diagnostics, [])
        self.assertEqual(doc.objects[0].diagnostics, [])

    def test_xy_precision_ignores_z_radius_and_flag_columns(self):
        bodies = [
            'string super {data_3d {0 0 1.123456789012 0.200000005 0 2.123456789012} radius_data {0.100000000000} major_data {f}}',
            'string super {data {0 0 1.123456789012 0.100000000000 f 0.200000005 0 2.123456789012 0 t}}',
            'string polyline {data {0 0 1.123456789012 0.100000000000 f 0.200000005 0 2.123456789012 0 t}}',
            'string super {data_2d {0 0 0.200000005 0} geometry_data {arc {radius .1 major t}}}',
        ]
        for body in bodies:
            with self.subTest(body=body):
                doc = self.parse(body)
                self.assertEqual(doc.coverage, 'partial')
                self.assertIn('precision-limited arc segment 1', doc.objects[0].diagnostics[0])

    def test_projected_coordinates_and_closed_wraparound(self):
        doc = self.parse('string super {closed 1 data_2d {123456.00000000 6543210.00000000 123456.200000005 6543210.00000000} radius_data {.1 -.1} major_data {f t}}')
        self.assertEqual(doc.coverage, 'partial')
        self.assertEqual(len(doc.objects[0].diagnostics), 2)
        self.assertIn('2 segments in 1 objects', doc.diagnostics[0])

    def test_relative_cap_rejects_coarse_or_float_ill_conditioned_geometry(self):
        for header, body in [
            ('// decimal_places 2\n', self.arc()),
            ('// decimal_places 8\n', 'string super {data_2d {0 0 .000000205 0} radius_data {.0000001} major_data {f}}'),
            ('// decimal_places 8\n', 'string super {data_2d {1000000000000 1000000000000 1000000000000.2001 1000000000000} radius_data {.1} major_data {f}}'),
        ]:
            with self.subTest(body=body), self.assertRaises(ParseError): self.parse(body, header)

    def test_small_diagonal_arc_uses_axis_quantization_without_moving_endpoints(self):
        doc = self.parse('string super {data_2d {0 0 .00989950 .00989950} radius_data {.007} major_data {f}}')
        self.assertEqual(doc.coverage, 'partial')
        self.assertEqual(clean(doc.objects[0].coordinates), [0, 0, None, .0098995, .0098995, None])
        with self.assertRaises(ParseError):
            self.parse('string super {data_2d {0 0 .00989952 .00989952} radius_data {.007} major_data {f}}')

    def test_other_axis_uncertainty_cannot_justify_impossible_chord(self):
        with self.assertRaises(ParseError):
            self.parse('string super {data_2d {0.000000000000 0 .200000000500 0} radius_data {.1} major_data {f}}')

    def test_exact_hex_axis_cannot_borrow_decimal_conversion_uncertainty(self):
        a, b = (1_000_000.0).hex(), (1_000_000.2000000001).hex()
        with self.assertRaises(ParseError):
            self.parse(f'string super {{data_2d {{{a} 0 {b} 0}} radius_data {{.1}} major_data {{f}}}}')

    def test_open_string_dormant_arc_is_preserved_without_validating_closure(self):
        doc = self.parse('string super {data_2d {0 0 .2 0 .4 0} radius_data {.1 0 .000000000001} major_data {f f t}}')
        self.assertEqual(doc.coverage, 'complete')
        self.assertFalse(doc.objects[0].settings['closed'])
        self.assertEqual(doc.objects[0].segments[-1].radius, .000000000001)
        self.assertTrue(doc.objects[0].segments[-1].major)

    def test_extreme_numeric_exponents_fail_closed_without_integer_conversion_errors(self):
        body = 'string super {data_2d {0e-' + '9'*5000 + ' 0 .200000005 0} radius_data {.1} major_data {f}}'
        with self.assertRaises(ParseError): self.parse(body)

    def test_leading_zero_exponents_do_not_leak_value_errors(self):
        for ending in ('', '8'):
            token = '0e' + '0'*5000 + ending
            with self.subTest(ending=ending):
                doc = self.parse(f'string super {{data_2d {{{token} 0 .2 0}} radius_data {{.1}} major_data {{f}}}}')
                self.assertEqual(doc.coverage, 'complete')
                self.assertEqual(doc.objects[0].coordinates[0], 0)

    def test_small_discrepancies_cannot_bypass_the_precision_policy(self):
        with self.assertRaises(ParseError): self.parse(self.arc('.200000000001'), '')
        with self.assertRaises(ParseError):
            self.parse('string super {data_2d {0x0p0 0x0p0 0x1.99999999a2656p-3 0x0p0} radius_data {.1} major_data {f}}')
        with self.assertRaises(ParseError):
            self.parse('string super {data_2d {0.000000000000000 0.000000000000000 .200000000001000 0.000000000000000} radius_data {.1} major_data {f}}')
        doc = self.parse(self.arc('.200000000001'))
        self.assertEqual(doc.coverage, 'partial')
        self.assertIn('precision-limited arc', doc.objects[0].diagnostics[0])

    def test_nonfinite_computed_chord_is_not_accepted(self):
        with self.assertRaises(ParseError):
            self.parse('string super {data_2d {-1e308 0 1e308 0} radius_data {1e308} major_data {f}}')

    def test_cli_get_publishes_partial_source_preserving_json(self):
        doc = self.parse(self.arc())
        before = self.path.read_bytes()
        target = self.path.with_suffix('.json')
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            status = main(['get', str(self.path), doc.objects[0].id, '--output', str(target)])
        self.assertEqual(status, 3)
        info = json.loads(stdout.getvalue())
        self.assertEqual(info['coverage'], 'partial')
        self.assertIn('precision-limited arcs', info['diagnostics'][0])
        self.assertEqual(json.loads(target.read_text())['object'], doc.objects[0].to_dict())
        self.assertEqual(self.path.read_bytes(), before)


if __name__ == '__main__': unittest.main()
