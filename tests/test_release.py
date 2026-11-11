"""Installed CLI release smoke checks use invented inputs only."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile


class InstalledCliTests(unittest.TestCase):
    def test_installed_cli_success_partial_failure_and_output_protection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'example.12da'
            data = b'string super { name Example data_3d {0 0 0 1 1 1} }'
            source.write_bytes(data)
            env = {k: v for k, v in os.environ.items() if k != 'PYTHONPATH'}
            def run(*args):
                return subprocess.run([sys.executable, '-I', '-m', 'twelve_da', *map(str, args)],
                                      cwd=root, env=env, text=True, capture_output=True)
            result = run('list', source)
            self.assertEqual(result.returncode, 0, result.stderr)
            obj_id = json.loads(result.stdout)['objects'][0]['id']
            archive = root / 'example.12daz'
            with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
                z.writestr('example.12da', data)
            self.assertEqual(run('inspect', archive).returncode, 0)
            output = root / 'object.json'
            self.assertEqual(run('get', archive, obj_id, '--output', output).returncode, 0)
            self.assertEqual(json.loads(output.read_text())['object']['name'], 'Example')
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            self.assertEqual(run('get', source, obj_id, '--output', source).returncode, 2)
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), digest)
            source.write_text('future_object {name Unknown}')
            self.assertEqual(run('inspect', source).returncode, 3)
            source.write_text('tin {name Broken points {0 0 0} triangles {1 2 3}}')
            previous = output.read_bytes()
            result = run('get', source, obj_id, '--output', output)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, '')
            self.assertIn('error', json.loads(result.stderr))
            self.assertEqual(output.read_bytes(), previous)
