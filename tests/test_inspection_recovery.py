"""Synthetic recovery policy regressions."""
from array import array
from pathlib import Path
import tempfile
import unittest
from twelve_da import load, load_set, ParseError, SuppliedDocument, resolve
from twelve_da.inspection import inspection
from twelve_da.model import MAX_ISSUE_DETAILS

ZERO = 'tin {name Defective points {0 0 0 1 1 0 2 2 0} triangles {1 2 3}}'
VALID = 'tin {name Valid points {0 0 0 0 1 0 1 0 0} triangles {1 2 3}}'
FULL = '''full_tin {name Full
 points {0 0 0 0 2 0 2 2 0 2 0 0 0 1 0}
 triangles {1 2 5 2 3 5 3 4 5 4 1 5}
 neighbours {0 2 4 0 3 1 0 4 2 0 1 3} nulling {1 2 2 1}}'''


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'input.12da'

    def parse(self, text, **kwargs):
        self.path.write_text(text)
        return load(self.path, **kwargs)

    def test_strict_default_and_explicit_inspection(self):
        with self.assertRaises(ParseError): self.parse(ZERO)
        doc = self.parse(VALID+ZERO, inspection=True)
        good, bad = doc.objects
        self.assertEqual(good.summary()['preview_status'], 'complete')
        self.assertEqual(bad.summary()['preview_status'], 'partial')
        self.assertEqual(bad.summary()['geometry_integrity'], 'zero_area_faces')
        self.assertFalse(bad.summary()['analysis_eligible'])
        self.assertEqual(bad.geometry_issues, [dict(code='zero_plan_area', severity='error', triangle=1,
            point_indices=[1,2,3], visible=True, construction=False)])
        self.assertEqual(bad.coordinates, array('d', [0,0,0,1,1,0,2,2,0]))
        self.assertEqual(bad.triangles.tolist(), [1,2,3])
        self.assertEqual(bad.preview_exclusions.tolist(), [1])
        self.assertEqual(doc.coverage, 'partial')
        with self.assertRaises(ParseError): load_set([('id','id',self.path)])
        self.assertEqual(len(load_set([('id','id',self.path)], inspection=True)[0][0].document.objects), 2)

    def test_no_epsilon_and_repeated_indices_or_other_failures_are_not_recovered(self):
        tiny = 'tin {name Tiny points {0 0 0 0 1e-200 0 1e-200 0 0} triangles {1 2 3}}'
        self.assertEqual(self.parse(tiny, inspection=True).objects[0].geometry_integrity, 'valid')
        for text in (ZERO.replace('1 2 3}', '1 2 1}'), ZERO.replace('1 2 3}', '1 2 4}'),
                     VALID.replace('1 2 3}', '1 3 2}'), VALID.replace('1 2 3}', '1 2 3 1 2 3}'),
                     FULL.replace('0 2 4', '0 3 4'), ZERO+'tin {name Broken}',
                     'tin {name Nonmanifold points {0 0 0 0 1 0 1 0 0 2 0 0 3 0 0} triangles {1 2 3 1 2 4 1 2 5}}'):
            with self.subTest(text=text), self.assertRaises(ParseError): self.parse(text, inspection=True)

    def test_full_tin_retains_topology_and_original_visibility(self):
        doc = self.parse(FULL, inspection=True)
        obj = doc.objects[0]
        self.assertEqual(obj.preview_exclusions.tolist(), [1])
        self.assertEqual(obj.nulling.tolist(), [1,2,2,1])
        self.assertEqual(obj.neighbours.tolist(), [0,2,4,0,3,1,0,4,2,0,1,3])
        self.assertEqual(obj.geometry_issues[0]['visible'], False)
        self.assertEqual(obj.geometry_issues[0]['construction'], True)

    def test_component_presence_is_separate_from_preview_and_analysis(self):
        doc = self.parse('super_tin {name C tins {Valid Defective}}'+VALID+ZERO, inspection=True)
        source = SuppliedDocument('file','file',doc)
        c = resolve([source])['composites'][0]
        self.assertEqual((c['present_count'], c['available_count']), (2,1))
        self.assertEqual([x['status'] for x in c['components']], ['available','partial'])
        self.assertFalse(c['usable_surface'])
        result = inspection([source], include_geometry=True)
        self.assertEqual(result['inspection_version'], '1')
        self.assertFalse(result['documents'][0]['objects'][2]['native_geometry_available'])
        self.assertEqual(result['documents'][0]['objects'][2]['geometry']['excluded_triangles'], [1])

    def test_diagnostics_are_bounded_but_exclusions_and_counts_are_complete(self):
        count = MAX_ISSUE_DETAILS+1
        points = ' '.join(f'{i} {i} 0' for i in range(3*count))
        triangles = ' '.join(str(i+1) for i in range(3*count))
        obj = self.parse('tin {name Many points {'+points+'} triangles {'+triangles+'}}', inspection=True).objects[0]
        self.assertEqual(obj.geometry_issue_count, count)
        self.assertEqual(len(obj.preview_exclusions), count)
        self.assertEqual(len(obj.geometry_issues), MAX_ISSUE_DETAILS)
        self.assertTrue(obj.summary()['issue_details_truncated'])

    def test_unsupported_metadata_cannot_become_a_preview(self):
        obj = self.parse(ZERO.replace('name Defective','name Defective future 1'), inspection=True).objects[0]
        self.assertEqual(obj.summary()['preview_status'], 'unavailable')
        self.assertFalse(obj.summary()['analysis_eligible'])

