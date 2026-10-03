#!/usr/bin/env python3
"""Regression checks using fictional drawings; requires Shapely."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from extract_dwg import object_stream, plain_text


def run(script, *args, expected=0):
    result = subprocess.run([sys.executable, str(Path(__file__).parent / script), *map(str, args)], capture_output=True, text=True)
    if result.returncode != expected:
        raise AssertionError(result.stdout + result.stderr)
    return result


def main():
    if importlib.util.find_spec("shapely") is None:
        raise SystemExit("Install Shapely to run these checks.")
    with tempfile.TemporaryDirectory(prefix="dwg-reader-verify-") as tmp:
        root = Path(tmp)
        objects = [{"object": "LAYER", "handle": [0, 1, 6], "name": "测试标高"},
                   {"object": "BLOCK_HEADER", "handle": [0, 1, 30], "name": "标高块"}]
        for i, (tag, prompt) in enumerate([("B", "自然标高"), ("A", "设计标高"), ("D", "高差")], 40):
            objects.append({"entity": "ATTDEF", "handle": [0, 1, i], "ownerhandle": [5, 1, 30, 30], "tag": tag, "prompt": prompt})
        def block(h, point, before, after, diff, mode=2, duplicate=False, tilted=False):
            refs = []
            pairs = [("B", before), ("A", after), ("D", diff)] + ([("B", before)] if duplicate else [])
            for i, (tag, value) in enumerate(pairs):
                a = h * 10 + i
                refs.append([5, 2, a, a])
                objects.append({"entity": "ATTRIB", "handle": [0, 2, a], "ownerhandle": [5, 1, h, h],
                                "tag": tag, "text_value": value, "ins_pt": point, "entmode": 0})
            objects.append({"entity": "INSERT", "handle": [0, 1, h], "layer": [5, 1, 6, 6], "entmode": mode,
                            "ins_pt": point, "extrusion": [0, 1, 0] if tilted else [0, 0, 1],
                            "block_header": [5, 1, 30, 30], "attribs": refs})
        block(100, [1, 1, 0], "10.00", "12.00", "2.00")
        block(101, [1, 1, 0], "10.00", "12.00", "2.00")
        block(102, [1, 1, 0], "10.00", "13.00", "3.00")
        block(103, [10, 5, 0], "2.00", "1.00", "-1.00")
        block(104, [30, 5, 0], "1.00", "1.00", "0.00")
        block(105, [5, 5, 0], "1.00", "2.00", "1.00", duplicate=True)
        block(106, [15, 5, 0], "7.00", "8.00", "2.00")
        block(107, [5, 5, 0], "1.00", "2.00", "1.00", tilted=True)
        block(108, [5, 5, 0], "1.00", "2.00", "1.00", mode=0)
        objects.append({"entity": "MTEXT", "handle": [0, 2, 500], "text": "\\A1;区块\\PA1", "ins_pt": [5, 5, 0], "entmode": 2})
        objects.append({"object": "UNKNOWN_OBJ", "type": 537, "handle": [0, 2, 600]})
        source = root / "测试 drawing.json"
        source.write_text(json.dumps({"created_by": "fictional fixture", "HEADER": {"INSUNITS": 6}, "OBJECTS": objects}, ensure_ascii=False), encoding="utf-8")
        meta = {}
        assert list(object_stream(source, meta)) == objects
        assert meta["HEADER"]["INSUNITS"] == 6
        assert plain_text("\\A1;区块\\PA1") == "区块\nA1"
        run("extract_dwg.py", "--input", source, "--out", root / "extracted")
        compact = root / "extracted/compact.json"
        doc = json.loads(compact.read_text())
        assert doc["blocks"][0]["attributes"][0]["prompt"] == "自然标高"
        inv = json.loads((root / "extracted/inventory.json").read_text())
        assert inv["object_count"] == len(objects) and inv["unknown_or_proxy_types"] == {"537": 1}
        zones = root / "zones.json"
        zones.write_text(json.dumps([{"name": "左区", "points": [[0,0],[10,0],[10,10],[0,10]]},
                                     {"name": "右区", "points": [[10,0],[20,0],[20,10],[10,10]]}], ensure_ascii=False))
        common = ["--compact", compact, "--zones", zones, "--before-tag", "B", "--after-tag", "A", "--difference-tag", "D"]
        run("group_elevations.py", *common, "--out", root / "grouped")
        issues = json.loads((root / "grouped/issues.json").read_text())
        assert issues["counts"] == {"zones": 2, "candidate_blocks": 8, "rejected_blocks": 2, "unique_points": 5,
                                    "duplicate_blocks_merged": 1, "assigned_unique_points": 4, "membership_rows": 5,
                                    "outside_points": 1, "review_points": 0}, issues["counts"]
        assert len(issues["coincident_conflicts"]) == 1
        assert len(issues["source_difference_issues"]) == 1
        assert "-1.0" in (root / "grouped/points.csv").read_text(encoding="utf-8-sig")
        run("group_elevations.py", *common, "--shared-boundary", "review", "--out", root / "review")
        counts = json.loads((root / "review/issues.json").read_text())["counts"]
        assert counts["membership_rows"] == 3 and counts["review_points"] == 1
        zones.write_text(json.dumps([{"name": "自交区", "points": [[0,0],[10,10],[0,10],[10,0]]}]))
        run("group_elevations.py", *common, "--out", root / "invalid", expected=1)
        run("group_elevations.py", *common, "--repair-self-intersections", "--out", root / "repaired")
        assert json.loads((root / "repaired/issues.json").read_text())["geometry_repairs"]
        bad = root / "truncated.json"
        bad.write_text('{"OBJECTS":[{"entity":"TEXT"}')
        run("extract_dwg.py", "--input", bad, "--out", root / "truncated", expected=1)
        print("PASS: extraction/ownership, duplicate/conflict handling, boundaries, outside points, negative differences, mismatches, invalid geometry, truncated JSON.")


if __name__ == "__main__":
    main()
