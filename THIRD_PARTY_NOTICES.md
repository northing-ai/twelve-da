# Provenance and third-party notices

The implementation record describes an independent implementation using the
published 12d Solutions V15 interchange specification (June 2025):
https://downloads.12dmodel.com/v15/12d_Model_15_C1t/12d_A_File_Format.pdf
The specification is copyrighted by 12d Solutions and is not redistributed here.

The development record reports no incorporated third-party reader implementation.
Separately built Katana reader revision
`4ddb3a8b9031e5f04418465c9a951f4be6be7e25` (GPL-3.0-or-later with additional section 7 terms; see
[upstream licensing](https://github.com/kjarada/Katana/blob/4ddb3a8b9031e5f04418465c9a951f4be6be7e25/LICENSING.md)) and QFAT reader revision
`f6ddf3d22fd9936f73397fb3e302a6d6c3bd148b` were used as compatibility comparisons.
Neither reader, its source, binaries, fixture data nor comparison output is included
or required to build or run this package. Comparisons do not establish engineering
correctness. Source/history review supports this separation; it is not independent
proof of authorship or a legal rights determination.

Runtime code uses the Python standard library only. Python and build/test tools
retain their own licences. Bundled fixtures are invented synthetic examples.
No customer archives or derived customer acceptance records are included.

This package is licensed under MIT; see LICENSE.
