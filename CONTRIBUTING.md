# Contributing

The scope is read-only format interpretation and explicit diagnostics. Propose
larger element families before implementation. Do not add inference of units,
CRS, missing elevations, geometry repairs or composite TIN semantics without an
explicit design and native-reference evidence.

Use synthetic, minimal reproductions. Never post customer files, derived geometry,
project names, screenshots or private paths in public issues or pull requests.
Only contribute code and test data you have authority to redistribute. Contributions
are proposed under the project's MIT licence. No support SLA or response time is promised.

## Build and test (Python 3.12+)

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pip install --no-deps --no-build-isolation -e .
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/build_release.py --output /tmp/twelve-da-build
```

The builder requires an absent or empty output directory. It creates a source
distribution, builds a wheel from that archive, audits archive contents and writes
SHA256SUMS. It does not upload, push, tag or publish anything. Keep private testing
outside this checkout. Use process limits when testing untrusted inputs.
