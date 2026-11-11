"""Build and audit local artifacts. Never publishes or accesses the network."""
import argparse
import gzip
import hashlib
import io
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tarfile
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TOP_FILES = {'README.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'CONTRIBUTING.md',
             'CHANGELOG.md', 'SECURITY.md', 'requirements-dev.txt', 'pyproject.toml',
             'MANIFEST.in', 'PKG-INFO', 'setup.cfg'}
MODULES = {'__init__.py', '__main__.py', 'cli.py', 'container.py', 'grammar.py',
           'header.py', 'inspection.py', 'model.py', 'parser.py', 'precision.py', 'resolution.py'}
TESTS = {'test_parser.py', 'test_compatibility.py', 'test_precision.py',
         'test_super_tin.py', 'test_inspection_recovery.py', 'test_release.py'}
EGG_INFO = {'PKG-INFO', 'SOURCES.txt', 'dependency_links.txt', 'entry_points.txt', 'top_level.txt'}
DIST_INFO = {'METADATA', 'WHEEL', 'entry_points.txt', 'top_level.txt', 'RECORD'}
GENERATED_SOURCE = {'PKG-INFO', 'setup.cfg'}


def allowed_source(name):
    p = PurePosixPath(name)
    if name in TOP_FILES:
        return True
    if len(p.parts) == 3 and p.parts[:2] == ('src', 'twelve_da'):
        return p.name in MODULES
    if len(p.parts) == 3 and p.parts[:2] == ('src', 'twelve_da.egg-info'):
        return p.name in EGG_INFO
    if name in {'docs/inspection.md', 'scripts/build_release.py',
                'tests/fixtures/synthetic/complete.12da'}:
        return True
    return len(p.parts) == 2 and p.parts[0] == 'tests' and p.name in TESTS


def allowed_wheel(name):
    p = PurePosixPath(name)
    if len(p.parts) == 2 and p.parts[0] == 'twelve_da':
        return p.name in MODULES
    if not p.parts or not p.parts[0].endswith('.dist-info'):
        return False
    return ((len(p.parts) == 2 and p.name in DIST_INFO) or
            (len(p.parts) == 3 and p.parts[1] == 'licenses' and
             p.name in {'LICENSE', 'THIRD_PARTY_NOTICES.md'}))


def audit_sdist(path):
    with tarfile.open(path, 'r:gz') as archive:
        names = []
        for member in archive.getmembers():
            p = PurePosixPath(member.name)
            if p.is_absolute() or '..' in p.parts or not p.parts:
                raise ValueError(f'unsafe source member: {member.name}')
            if member.isdir():
                continue
            name = str(PurePosixPath(*p.parts[1:]))
            if not member.isfile() or not allowed_source(name):
                raise ValueError(f'unexpected source member: {member.name}')
            names.append(name)
        if len(names) != len(set(names)):
            raise ValueError('duplicate source members')
        required = (TOP_FILES - GENERATED_SOURCE) | {
            'docs/inspection.md', 'tests/fixtures/synthetic/complete.12da',
            'scripts/build_release.py'}
        required |= {f'src/twelve_da/{name}' for name in MODULES}
        required |= {f'tests/{name}' for name in TESTS}
        if not required.issubset(names):
            raise ValueError('source distribution missing required files')


def audit_wheel(path):
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or not all(allowed_wheel(n) for n in names):
            raise ValueError('unexpected or duplicate wheel member')
        required = {f'twelve_da/{name}' for name in MODULES}
        if not required.issubset(names):
            raise ValueError('wheel missing runtime modules')
        for suffix in ('/METADATA', '/licenses/LICENSE', '/licenses/THIRD_PARTY_NOTICES.md'):
            if sum(n.endswith(suffix) for n in names) != 1:
                raise ValueError(f'wheel missing metadata: {suffix}')


def normalize_sdist(path, epoch):
    # Build backends include current filesystem mtimes; normalize tar/gzip headers.
    with tarfile.open(path, 'r:gz') as src:
        items = [(m, src.extractfile(m).read() if m.isfile() else None) for m in src.getmembers()]
    with path.open('wb') as raw:
        with gzip.GzipFile(filename='', fileobj=raw, mode='wb', mtime=epoch) as compressed:
            with tarfile.open(fileobj=compressed, mode='w', format=tarfile.PAX_FORMAT) as out:
                for member, data in sorted(items, key=lambda item: item[0].name):
                    member.mtime = epoch
                    member.uid = member.gid = 0
                    member.uname = member.gname = ''
                    member.pax_headers = {}
                    member.mode = 0o755 if member.isdir() else 0o644
                    out.addfile(member, io.BytesIO(data) if data is not None else None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    out = args.output.resolve()
    if out == ROOT or ROOT in out.parents:
        parser.error('output must be outside the source tree')
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()):
        parser.error('output directory must be empty')
    # Stage only allowlisted files so unexpected checkout files cannot enter archives.
    with tempfile.TemporaryDirectory(prefix='twelve-da-build-') as tmp:
        stage = Path(tmp) / 'source'
        stage.mkdir()
        for path in ROOT.rglob('*'):
            if path.is_symlink():
                continue
            rel = path.relative_to(ROOT).as_posix()
            if (path.is_file() and allowed_source(rel) and rel not in GENERATED_SOURCE
                    and '.egg-info/' not in rel):
                dest = stage / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(path.read_bytes())
        epoch = 1794355200  # Fixed packaging epoch for this candidate; not a validation claim.
        env = dict(os.environ, SOURCE_DATE_EPOCH=str(epoch), PYTHONHASHSEED='0')
        subprocess.run([sys.executable, '-m', 'build', '--no-isolation', '--sdist',
                        '--outdir', str(out), str(stage)], check=True, env=env)
        sdist, = out.glob('*.tar.gz')
        audit_sdist(sdist)
        normalize_sdist(sdist, epoch)
        extracted = Path(tmp) / 'extracted'
        with tarfile.open(sdist) as archive:
            archive.extractall(extracted, filter='data')
        source_dir, = extracted.iterdir()
        subprocess.run([sys.executable, '-m', 'build', '--no-isolation', '--wheel',
                        '--outdir', str(out), str(source_dir)], check=True, env=env)
        wheel, = out.glob('*.whl')
        audit_wheel(wheel)
        artifacts = sorted([sdist, wheel])
        (out / 'SHA256SUMS').write_text(''.join(
            f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n' for p in artifacts))
        print('Built and audited:', ', '.join(p.name for p in artifacts))


if __name__ == '__main__':
    main()
