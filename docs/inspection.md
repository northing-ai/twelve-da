# Inspection and explicit dependencies

`load(path, inspection=True)` and `load_set(..., inspection=True)` also retain
TIN faces with exactly zero plan area and three distinct point references.
These are the only otherwise-invalid faces admitted by inspection mode. All other
validation still runs; a later error rejects the document atomically. Source
coordinates, topology and triangle ordinals never change. There is no epsilon.

Structured quality fields distinguish integrity, preview availability and eligibility
under implemented checks. Eligibility is not native engineering acceptance.
`zero_plan_area` issues contain source one-based triangle/point references,
visibility and construction flags. Details are capped at 128 per object with
explicit truncation and exact counts; the complete preview exclusion array remains
bounded by source triangle count. Consumers must exclude these faces themselves
when drawing a partial preview. The CLI remains strict.

## Super TIN definitions

`Object.super_tin` preserves ordered component names and the observed `exact` flag.
It invents no composite triangles. `resolve` takes an explicit list of
`SuppliedDocument(file_id, immutable_version, document)` records. `load_set` takes
explicit `(file_id, version, path)` tuples. No filesystem search or network download
resolves dependencies. Primary failure raises; rejected companions contribute no
geometry and prevent a complete-namespace claim.

Names match case-insensitively after trimming in the combined TIN/super-TIN
namespace. Forward references work. Duplicates retain candidates, cycles are
iteratively diagnosed, and nested composites are unsupported. Counts of present
components differ from counts of complete native geometry available for inspection.
Partial geometry never becomes a complete component.

**Composition remains unverified even with every component present.**
`usable_surface` remains false; quantities and domain remain null. Units, datum,
name-derived offsets, overlap priority, `exact` semantics, boundary clipping and
composite geometry are never inferred. Inspect native TINs separately and respect
visibility/construction flags.

`ResolutionLimits` defaults: 16 documents, 100,000 objects, 100,000 references,
100,000 candidate outputs, depth 32. CLI commands accept repeated `--companion`
paths and protect every selected input against output replacement.
JSON schema 3 and inspection version 1 are unchanged by this packaging release.
