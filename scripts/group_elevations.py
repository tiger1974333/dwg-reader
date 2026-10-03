#!/usr/bin/env python3
"""Group paired model-space INSERT elevations by explicitly confirmed planar zones."""
import argparse
import collections
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import json
import math
from pathlib import Path
import sys
from extract_dwg import write_csv, write_json


def numeric(value):
    try:
        num = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        raise ValueError(f"Nonnumeric value: {value!r}") from None
    if not num.is_finite():
        raise ValueError(f"Nonfinite value: {value!r}")
    return num


def polygon_parts(geometry):
    if geometry.geom_type == "Polygon":
        return [geometry]
    if hasattr(geometry, "geoms"):
        return [p for g in geometry.geoms for p in polygon_parts(g)]
    return []


def group(args):
    try:
        from shapely.geometry import Polygon, Point
        from shapely.validation import explain_validity
        from shapely import make_valid
        from shapely.ops import unary_union
    except ImportError:
        raise ValueError("Shapely is required. Install in a task dependency directory or selected environment.") from None
    if args.boundary_tolerance < 0 or args.overlap_area_tolerance < 0:
        raise ValueError("Tolerances cannot be negative.")
    if not 0 <= args.coordinate_decimals <= 15 or not 0 <= args.value_decimals <= 10:
        raise ValueError("Precision is out of supported range.")
    data = json.loads(Path(args.compact).read_text(encoding="utf-8"))
    manifest = json.loads(Path(args.zones).read_text(encoding="utf-8"))
    if not isinstance(manifest, list) or not manifest:
        raise ValueError("Zone manifest must be a nonempty array.")
    if data.get("schema_version") != 1:
        raise ValueError("Unsupported compact schema.")
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()) and not args.overwrite:
        raise ValueError("Output directory is not empty; choose a fresh one or --overwrite.")
    issues = {"source": data.get("source"), "units_metadata": data.get("units_metadata", {}),
              "partial_reader": bool(data.get("reader", {}).get("partial")),
              "geometry_repairs": [], "zone_overlaps": [], "rejected_blocks": [],
              "coincident_conflicts": [], "source_difference_issues": [], "overlap_points": [],
              "boundary_tolerance": args.boundary_tolerance, "coordinate_decimals": args.coordinate_decimals,
              "value_decimals": args.value_decimals, "shared_boundary": args.shared_boundary,
              "attribute_tags": {"before": args.before_tag, "after": args.after_tag, "difference": args.difference_tag}}
    zones = {}
    for row in manifest:
        name = row.get("name")
        if not isinstance(name, str) or not name or name in zones:
            raise ValueError(f"Missing or duplicate zone name: {name!r}")
        if any(abs(float(b)) > 1e-15 for b in row.get("bulges", [])):
            raise ValueError(f"Zone {name} has arcs. Tessellate/verify first.")
        pts = row.get("points", [])
        if len(pts) < 3 or any(len(p) != 2 or not all(math.isfinite(float(v)) for v in p) for p in pts):
            raise ValueError(f"Invalid planar coordinates for zone {name}")
        geo = Polygon(pts)
        if not geo.is_valid:
            reason = explain_validity(geo)
            if not args.repair_self_intersections:
                raise ValueError(f"Invalid zone {name}: {reason}; inspect before opting into repair.")
            old_area = geo.area
            parts = polygon_parts(make_valid(geo))
            if not parts:
                raise ValueError(f"Zone {name} has no polygonal area after repair.")
            geo = unary_union(parts)
            issues["geometry_repairs"].append({"zone": name, "handle": row.get("handle"),
                                               "reason": reason, "original_area": old_area,
                                               "repaired_area": geo.area})
        if geo.is_empty or geo.area <= 0:
            raise ValueError(f"Zone {name} has no area.")
        zones[name] = geo
    names = list(zones)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            area = zones[a].intersection(zones[b]).area
            if area > args.overlap_area_tolerance:
                issues["zone_overlaps"].append({"zones": [a, b], "overlap_area": area})
    quantum = Decimal(1).scaleb(-args.value_decimals)
    coord_quantum = Decimal(1).scaleb(-args.coordinate_decimals)
    records, coord_values = {}, collections.defaultdict(set)
    candidates = 0
    for block in data.get("blocks", []):
        if block.get("mode") != 2 or (args.point_layer and block.get("layer") != args.point_layer):
            continue
        attrs = collections.defaultdict(list)
        for a in block.get("attributes", []):
            attrs[a["tag"]].append(a["value"])
        if args.before_tag not in attrs and args.after_tag not in attrs:
            continue
        candidates += 1
        block_handle = block.get("handle")
        try:
            if block.get("entity", "INSERT") != "INSERT":
                raise ValueError("Array INSERT must be expanded before grouping.")
            if block.get("invisible"):
                raise ValueError("Invisible INSERT requires scope review.")
            extrusion = block.get("extrusion") or [0, 0, 1]
            if len(extrusion) != 3 or any(abs(float(a) - b) > 1e-10 for a, b in zip(extrusion, [0, 0, 1])):
                raise ValueError("Nonstandard extrusion requires coordinate transformation.")
            xy = block.get("point")
            if not isinstance(xy, list) or len(xy) < 2:
                raise ValueError("Missing insertion point.")
            x, y = numeric(xy[0]), numeric(xy[1])
            if len(attrs[args.before_tag]) != 1 or len(attrs[args.after_tag]) != 1:
                raise ValueError("Missing or duplicate before/after attributes.")
            before, after = numeric(attrs[args.before_tag][0]), numeric(attrs[args.after_tag][0])
        except ValueError as exc:
            issues["rejected_blocks"].append({"handle": block_handle, "reason": str(exc)})
            continue
        calculated = (after - before).quantize(quantum, rounding=ROUND_HALF_UP)
        source_difference = None
        check = None
        if args.difference_tag:
            try:
                if len(attrs[args.difference_tag]) != 1:
                    raise ValueError("Missing or duplicate source-difference attribute.")
                source_difference = numeric(attrs[args.difference_tag][0])
                check = calculated - source_difference
                if check != 0:
                    issues["source_difference_issues"].append({"handle": block_handle, "calculated": str(calculated),
                                                               "source": str(source_difference), "delta": str(check)})
            except ValueError as exc:
                issues["source_difference_issues"].append({"handle": block_handle, "reason": str(exc)})
        coord = (str(x.quantize(coord_quantum)), str(y.quantize(coord_quantum)))
        values = (str(before.normalize()), str(after.normalize()), str(source_difference.normalize()) if source_difference is not None else None)
        key = coord + values
        coord_values[coord].add(values)
        if key in records:
            records[key]["handles"].append(block_handle)
            continue
        records[key] = {"point_id": block_handle, "handles": [block_handle], "cad_x": float(x), "cad_y": float(y),
                        "before": float(before), "after": float(after), "difference": float(calculated),
                        "source_difference": float(source_difference) if source_difference is not None else None,
                        "difference_check": float(check) if check is not None else None, "coord_key": coord}
    for coord, value_sets in coord_values.items():
        if len(value_sets) > 1:
            conflict_handles = [p["handles"] for p in records.values() if p["coord_key"] == coord]
            issues["coincident_conflicts"].append({"rounded_coordinates": coord, "handles": conflict_handles,
                                                   "values": sorted(value_sets, key=repr)})
    points, memberships, outside = [], [], []
    for p in records.values():
        point = Point(p["cad_x"], p["cad_y"])
        hits = [n for n, geo in zones.items() if geo.distance(point) <= args.boundary_tolerance]
        status, accepted = "inside", hits
        if not hits:
            status = "outside"
        elif len(hits) > 1:
            if any(zones[n].boundary.distance(point) > args.boundary_tolerance for n in hits):
                status, accepted = "overlap_review", []
                issues["overlap_points"].append({"point_id": p["point_id"], "candidate_zones": hits})
            elif args.shared_boundary == "review":
                status, accepted = "shared_boundary_review", []
            else:
                status = "shared_boundary"
        distance, nearest = min((geo.distance(point), n) for n, geo in zones.items())
        p.update({"assignment_status": status, "zones": "、".join(accepted), "candidate_zones": "、".join(hits),
                  "nearest_zone": nearest, "nearest_distance": distance, "duplicate_count": len(p["handles"]) - 1,
                  "coincident_conflict": len(coord_values[p["coord_key"]]) > 1,
                  "source_handles": "、".join(p["handles"])})
        p.pop("coord_key")
        points.append(p)
        if not hits:
            outside.append(p)
        for name in accepted:
            memberships.append({**p, "zone": name})
    fields = ["point_id", "cad_x", "cad_y", "before", "after", "difference", "source_difference",
              "difference_check", "assignment_status", "zones", "candidate_zones", "nearest_zone",
              "nearest_distance", "duplicate_count", "coincident_conflict", "source_handles"]
    write_csv(out / "points.csv", fields, points)
    write_csv(out / "memberships.csv", ["zone"] + fields, memberships)
    write_csv(out / "outside.csv", fields, outside)
    summaries = []
    for name in names:
        pp = [p for p in memberships if p["zone"] == name]
        row = {"zone": name, "point_count": len(pp), "shared_point_count": sum(p["assignment_status"] == "shared_boundary" for p in pp)}
        for key in ["before", "after", "difference"]:
            numbers = [numeric(p[key]) for p in pp]
            row.update({f"{key}_mean": float(sum(numbers) / len(numbers)) if numbers else None,
                        f"{key}_min": float(min(numbers)) if numbers else None,
                        f"{key}_max": float(max(numbers)) if numbers else None})
        summaries.append(row)
    summary_fields = ["zone", "point_count", "before_mean", "after_mean", "difference_mean", "before_min",
                      "before_max", "after_min", "after_max", "difference_min", "difference_max", "shared_point_count"]
    write_csv(out / "summary.csv", summary_fields, summaries)
    issues["counts"] = {"zones": len(names), "candidate_blocks": candidates, "rejected_blocks": len(issues["rejected_blocks"]),
                        "unique_points": len(points), "duplicate_blocks_merged": sum(p["duplicate_count"] for p in points),
                        "assigned_unique_points": sum(bool(p["zones"]) for p in points), "membership_rows": len(memberships),
                        "outside_points": len(outside), "review_points": sum(p["assignment_status"].endswith("review") for p in points)}
    write_json(out / "issues.json", issues)
    print(json.dumps(issues["counts"], ensure_ascii=False))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--compact", required=True)
    p.add_argument("--zones", required=True)
    p.add_argument("--before-tag", required=True)
    p.add_argument("--after-tag", required=True)
    p.add_argument("--difference-tag")
    p.add_argument("--point-layer")
    p.add_argument("--boundary-tolerance", type=float, default=1e-6, help="In confirmed drawing units")
    p.add_argument("--overlap-area-tolerance", type=float, default=1e-8, help="In squared drawing units")
    p.add_argument("--coordinate-decimals", type=int, default=8, help="Explicit coordinate precision for deduplication")
    p.add_argument("--value-decimals", type=int, default=2)
    p.add_argument("--shared-boundary", choices=["all", "review"], default="all")
    p.add_argument("--repair-self-intersections", action="store_true")
    p.add_argument("--out", required=True)
    p.add_argument("--overwrite", action="store_true")
    args = p.parse_args()
    try:
        group(args)
    except (ValueError, OSError, TypeError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
