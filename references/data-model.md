# Export schema and interpretation

| File | Purpose |
|---|---|
| `inventory.json` | Source checksum/signature, reader status, raw counts, layers, class names, unsupported types, and units metadata |
| `compact.json` | Selected standard entities, layer/block maps, INSERTs and attached attributes |
| `texts.csv` | Text values, raw formatting, coordinates, owner, layer, mode, and invisibility |
| `attributes.csv` | Attributes joined to block references with definition prompts |
| `boundaries.json` | LWPOLYLINE candidates, vertices, bulges, flag, and elevation; candidates are not confirmed zones |
| `drawing.json`, `conversion.log` | Raw reader output and diagnostics for targeted recovery |

Existing JSON is read directly, not copied. Extraction uses standard-library Python. Only the grouping helper needs Shapely.

## Ownership

Own LibreDWG `handle` arrays typically store an ID in component 3. References containing resolved IDs use the last component. Outputs use hexadecimal handles and retain selected source fields for rechecking.

`INSERT.attribs` references its actual attributes; `ownerhandle` is a fallback when this list is absent. Join by these handles. Duplicate tags on one INSERT are ambiguous and must not be overwritten. `ATTDEF.prompt` helps explain a tag within its block definition; tag names are not universal business meanings.

For the tested LibreDWG schema, `entmode` 2 is model space, 1 is paper space, and 0 may be an entity owned by a block/INSERT. Confirm if another version differs. ATTRIBs commonly have mode 0 while their INSERT is model space.

## Coordinates and visibility

- `cad_x`/`cad_y` are raw CAD coordinates, without a promised easting/northing convention. Establish survey naming from drawing evidence.
- Grouping accepts model-space INSERT insertion points with standard Z extrusion and rejects tilted extrusion. Library/paper-space INSERTs are excluded.
- Extraction does not recursively transform nested blocks. Nested INSERTs, OCS/extrusion, scale, rotation, and xrefs need an explicit coordinate transform or CAD flattening before combining geometry.
- Uninstantiated block definitions are not independently displayed observations; they remain useful for interpreting symbols/tags.
- Layer state and invisibility are retained, but no full CAD viewport visibility engine is provided.
- LWPOLYLINE bulges indicate arcs. Grouping rejects nonzero bulges; tessellate with verified tolerance or use a flattened boundary.
- INSUNITS/MEASUREMENT may be absent or ambiguous. Preserve codes and establish physical units from confirmed evidence.

`text_plain` removes common MTEXT formatting while `text_raw` remains authoritative. Stacked fractions, fields, and unusual escapes may need further interpretation. Keep source numeric strings during discovery, then parse once meaning is confirmed.
