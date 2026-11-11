# Release notes

## 0.4.0rc1 — community release candidate

First standalone community release candidate: read-only library and CLI, JSON
schema 3, inspection version 1. MIT licensed.

Parser behaviour is inherited unchanged from the private 0.3.1 library; only the
reported version changes. Packaging, standalone documentation and synthetic tests
are prepared separately. Existing private wheels/toolkits are not replaced.

Supported content includes strings, selected arc/text/circle metadata, TIN/full-TIN
arrays and Super TIN definitions/dependency inspection. Unsupported content is
explicitly partial or rejected. Native-reference engineering validation and composite
semantics remain incomplete. See README for limits and exact contracts.

The artifact bundle includes a wheel, source distribution and SHA256SUMS.
No package registry publishing or application integration is included in this change.
