# Elevations grouped by confirmed zones

Inspect prompts, model-space INSERTs, blocks, layers, and label geometry first. The originating example used `ZBG-BG` = 自然标高, `SBG-BG` = 设计标高, and `SS-ZZ` = 高差. Verify these meanings in every new drawing.

Create a manifest after verifying boundaries:

```json
[
  {"name": "A1", "handle": "VERIFIED_HANDLE", "points": [[0,0],[10,0],[10,10],[0,10]], "bulges": []}
]
```

`handle` optionally links source geometry. Text insertion points may be outside a polygon even when the visual label is inside. Use text extents or a checked leader association rather than arbitrary nearest-label matching.

Use Shapely in the selected Python environment. If missing, install in a task-specific dependency directory and supply it through PYTHONPATH.

```bash
python3 scripts/group_elevations.py \
  --compact /task/dwg-data/compact.json --zones /task/confirmed-zones.json \
  --before-tag ZBG-BG --after-tag SBG-BG --difference-tag SS-ZZ \
  --boundary-tolerance 0.001 --coordinate-decimals 5 --out /task/zone-data
```

Those precision/tolerance values suit the originating metre-based drawing. Choose values for current drawing units and source precision; the helper never assumes metres. `--point-layer NAME` limits candidates to a verified layer.

`--shared-boundary all` includes common points in each relevant zone and reports unique counts. `--shared-boundary review` leaves multi-zone points for assignment instead. Outside points retain nearest-zone distance only as a locating aid.

## Exceptions

Invalid polygons stop processing by default. Inspect self-intersections, repeated vertices, gaps, and overlap. `--repair-self-intersections` explicitly uses Shapely `make_valid`, logs the change, and retains polygonal components. Use only when those components have a defensible interpretation. Dangling non-area pieces do not become zones; the DWG remains untouched.

The helper rejects missing, duplicate, nonnumeric, or nonfinite tags; merges coincident points only when all values agree under selected precision; retains and flags conflicting coincident values; calculates `after - before` with Decimal rounding; and compares to a supplied source difference tag.

Outputs are `points.csv`, `memberships.csv`, `outside.csv`, `summary.csv`, and `issues.json`. Arithmetic means use accepted memberships; these are not area-weighted thickness or earthwork volume. Inspect a plot of boundaries and points before delivery. Genuine common boundaries and substantial zone overlap must be distinguished.

## Delivery

Use 自然标高、设计标高、实测标高 labels according to evidence. Keep negative differences. Report outside points, conflicts, unsupported geometry, and mismatches beside affected records.

For one worksheet per zone, use natural zone order, preserve requested summaries, and link summary formulas to each zone's owning detail. Preserve handles/stable IDs for shared points. Retain a consolidated source only when useful; avoid separate editable copies with divergent calculations.
