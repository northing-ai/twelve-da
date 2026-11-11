"""Invented geometry and dependency graph regressions."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from twelve_da import load, ParseError, SuppliedDocument, ResolutionLimits, resolve, load_set
from twelve_da.cli import main
from twelve_da.inspection import inspection

TIN = 'tin {name "%s" points {0 0 1 0 1 1 1 0 1} triangles {1 2 3}}'
SUPER = 'super_tin {name "%s" exact true tins {%s}}'


class SuperTinTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.ordinal = 0

    def source(self, text):
        self.ordinal += 1
        path = self.root / f'{self.ordinal}.12da'
        path.write_text(text)
        doc = load(path)
        return SuppliedDocument(str(self.ordinal), doc.source_sha256, doc)

    def test_forward_order_and_identity(self):
        for text in ((SUPER % ('C', '" a " "B"')) + (TIN % 'A') + (TIN % 'b'),
                     (TIN % 'A') + (TIN % 'b') + (SUPER % ('C', '" a " "B"'))):
            source = self.source(text)
            report = inspection([source], include_geometry=True)
            c = report['composites'][0]
            self.assertEqual(c['available_count'], 2)
            self.assertEqual([x['name'] for x in c['components']], [' a ', 'B'])
            self.assertEqual(c['identity']['source_sha256'], source.document.source_sha256)
            self.assertFalse(c['usable_surface'])
            self.assertIsNone(c['quantities'])
            self.assertEqual(c['composition'], 'unverified')
            self.assertEqual(c['definition']['exact'], True)
            self.assertEqual(c['components'][0]['candidates'][0]['name'], 'A')

    def test_missing_and_mixed_case_ambiguity_combined_namespace(self):
        primary = self.source(SUPER % ('C', 'A Missing C'))
        report = resolve([primary, self.source(TIN % 'a'), self.source(TIN % ' A ')])
        c = report['composites'][0]
        self.assertEqual([x['status'] for x in c['components']], ['ambiguous', 'missing', 'unsupported'])
        self.assertEqual(len(c['components'][0]['candidates']), 2)
        self.assertEqual(c['components'][2]['code'], 'self_reference')
        self.assertEqual(len(report['duplicate_names']), 1)
        duplicate = self.source((TIN % 'C') + (SUPER % ('C', 'C')))
        self.assertEqual(resolve([duplicate])['composites'][0]['components'][0]['status'], 'ambiguous')

    def test_nesting_cycles_and_depth_are_explicit_without_recursion(self):
        source = self.source((SUPER % ('A', 'B')) + (SUPER % ('B', 'A')))
        result = resolve([source])['composites']
        self.assertTrue(all(x['graph_diagnostics'] == ['cycle_or_transitive_cycle'] for x in result))
        self.assertEqual(result[0]['components'][0]['code'], 'cycle_or_transitive_cycle')
        source = self.source((SUPER % ('A', 'B')) + (SUPER % ('B', 'C')) + (TIN % 'C'))
        result = resolve([source], limits=ResolutionLimits(depth=1))['composites']
        self.assertEqual(result[0]['components'][0]['code'], 'depth_limit')
        self.assertFalse(result[0]['usable_surface'])
        result = resolve([source])['composites']
        self.assertEqual(result[0]['components'][0]['code'], 'unsupported_nesting')
        self.assertEqual(result[0]['available_count'], 0)

    def test_unknown_fields_and_invalid_definition(self):
        source = self.source(SUPER % ('C', 'A') + ' super_tin {name D tins {A} future {x y}}')
        self.assertTrue(any('unsupported field: future' in x for x in source.document.objects[1].diagnostics))
        for text in ('super_tin {tins {A}}', 'super_tin {name C}', 'super_tin {name C tins {}}',
                     'super_tin {name C tins {A} exact maybe}', 'super_tin {name C tins {{A}}}'):
            with self.subTest(text=text), self.assertRaises(ParseError): self.source(text)

    def test_unsupported_geometry_is_not_missing(self):
        source = self.source((SUPER % ('C', 'A')) + (TIN % 'A').replace('triangles', 'future 1 triangles'))
        c = resolve([source])['composites'][0]
        self.assertEqual(c['components'][0]['status'], 'unsupported')
        self.assertEqual(c['available_count'], 0)

    def test_limits_and_unique_versions(self):
        a = self.source(SUPER % ('C', 'A B'))
        for kwargs in ({'references':1}, {'objects':1}):
            sources = [a, self.source(TIN % 'A')]
            with self.assertRaises(ParseError): resolve(sources, limits=ResolutionLimits(**kwargs))
        with self.assertRaises(ParseError): resolve([a, a])
        with self.assertRaises(ParseError): resolve([a, self.source(TIN % 'A')], limits=ResolutionLimits(documents=1))

    def test_atomic_rejected_companion_retains_primary_native_geometry(self):
        source = self.source((SUPER % ('C', 'A')) + (TIN % 'Independent'))
        bad = self.root/'bad.12da'
        bad.write_text((TIN % 'A') + ' tin {name Invalid points {0 0 0} triangles {1 2 3}}')
        supplied, rejected = load_set([('primary','v1', self.root/'1.12da'), ('bad','v2',bad)])
        result = inspection(supplied, rejected=rejected, include_geometry=True)
        self.assertEqual(rejected[0].code, 'malformed_document')
        self.assertEqual(result['composites'][0]['components'][0]['status'], 'unknown')
        self.assertEqual(len(result['documents']), 1)
        self.assertIn('geometry', result['documents'][0]['objects'][1])
        self.assertEqual(result['composites'][0]['available_count'], 0)

    def test_rejected_document_does_not_claim_namespace_is_complete(self):
        from twelve_da import RejectedDocument
        source = self.source((SUPER % ('C', 'A')) + (TIN % 'A'))
        c = resolve([source], rejected=[RejectedDocument('bad', 'v1', 'malformed_document', 'bad data')])['composites'][0]
        self.assertEqual(c['components'][0]['status'], 'unknown')
        self.assertEqual(c['available_count'], 0)
        self.assertEqual(len(c['components'][0]['candidates']), 1)

    def test_cli_companion_and_source_protection(self):
        primary = self.source(SUPER % ('C', 'A'))
        self.source(TIN % 'A')
        path, companion = self.root/'1.12da', self.root/'2.12da'
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = main(['list', str(path), '--companion', str(companion)])
        self.assertEqual(code, 3)
        self.assertEqual(json.loads(out.getvalue())['resolution']['composites'][0]['available_count'], 1)
        before = companion.read_bytes()
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(['get', str(path), primary.document.objects[0].id, '--output', str(companion), '--companion', str(companion)]), 2)
        self.assertEqual(companion.read_bytes(), before)

