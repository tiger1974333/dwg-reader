#!/usr/bin/env python3
"""Extract standard CAD information from DWG or LibreDWG JSON, streaming raw objects."""
import argparse
import collections
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


class JSONStream:
    def __init__(self, path, chunk=1024 * 1024):
        self.file = Path(path).open(encoding="utf-8-sig")
        self.buffer, self.pos, self.eof = "", 0, False
        self.chunk = chunk
        self.decoder = json.JSONDecoder()

    def extend(self):
        self.buffer = self.buffer[self.pos:]
        self.pos = 0
        more = self.file.read(self.chunk)
        self.eof = not more
        self.buffer += more
        if len(self.buffer) > 128 * 1024 * 1024:
            raise ValueError("A single JSON value exceeds 128 MiB; inspect the raw file.")

    def peek(self):
        while True:
            while self.pos < len(self.buffer) and self.buffer[self.pos].isspace():
                self.pos += 1
            if self.pos < len(self.buffer):
                return self.buffer[self.pos]
            if self.eof:
                return ""
            self.extend()

    def expect(self, char):
        if self.peek() != char:
            raise ValueError(f"Expected JSON {char!r}, got {self.peek()!r}")
        self.pos += 1

    def value(self):
        self.peek()
        while True:
            try:
                value, end = self.decoder.raw_decode(self.buffer, self.pos)
                self.pos = end
                return value
            except json.JSONDecodeError:
                if self.eof:
                    raise
                self.extend()


def object_stream(path, metadata):
    stream, found = JSONStream(path), False
    try:
        stream.expect("{")
        while stream.peek() != "}":
            key = stream.value()
            if not isinstance(key, str):
                raise ValueError("Top-level JSON key is not a string.")
            stream.expect(":")
            if key == "OBJECTS":
                if found:
                    raise ValueError("Multiple OBJECTS arrays are unsupported.")
                found = True
                stream.expect("[")
                while stream.peek() != "]":
                    obj = stream.value()
                    if not isinstance(obj, dict):
                        raise ValueError("Non-object entry in OBJECTS.")
                    yield obj
                    if stream.peek() == ",":
                        stream.expect(",")
                        if stream.peek() == "]":
                            raise ValueError("Trailing comma in OBJECTS.")
                    elif stream.peek() != "]":
                        raise ValueError("Missing delimiter in OBJECTS.")
                stream.expect("]")
            else:
                value = stream.value()
                if key in {"created_by", "FILEHEADER", "HEADER", "CLASSES"}:
                    metadata[key] = value
            if stream.peek() == ",":
                stream.expect(",")
                if stream.peek() == "}":
                    raise ValueError("Trailing top-level comma.")
            elif stream.peek() != "}":
                raise ValueError("Missing top-level delimiter.")
        stream.expect("}")
        if stream.peek():
            raise ValueError("Data after JSON object.")
        if not found:
            raise ValueError("No LibreDWG OBJECTS array found.")
    finally:
        stream.file.close()


def handle(value):
    if isinstance(value, list) and len(value) >= 3:
        num = value[-1] if len(value) >= 4 else value[2]
        return format(int(num), "X") if num else None
    return None


def plain_text(value):
    text = str(value or "")
    text = re.sub(r"\\U\+([0-9a-fA-F]{4})", lambda m: chr(int(m[1], 16)), text)
    text = text.replace("\\P", "\n").replace("\\~", " ")
    text = re.sub(r"\\[ACFHQTWpf][^;]*;", "", text)
    text = re.sub(r"\\S([^;]*);", lambda m: m[1].replace("#", "/").replace("^", "/"), text)
    text = re.sub(r"\\[LlOoKk]", "", text)
    text = text.replace("\\{", "\x01").replace("\\}", "\x02")
    text = text.replace("{", "").replace("}", "").replace("\x01", "{").replace("\x02", "}")
    for old, new in [("%%d", "°"), ("%%p", "±"), ("%%c", "Ø")]:
        text = re.sub(re.escape(old), lambda m: new, text, flags=re.I)
    return text


ENTITY_TYPES = {
    "TEXT", "MTEXT", "ATTRIB", "ATTDEF", "INSERT", "MINSERT", "LWPOLYLINE",
    "POLYLINE_2D", "POLYLINE_3D", "VERTEX_2D", "VERTEX_3D", "LINE", "ARC", "CIRCLE",
    "POINT", "SPLINE", "ELLIPSE", "LEADER", "MULTILEADER",
}
FIELDS = {
    "entity", "object", "type", "handle", "ownerhandle", "layer", "entmode", "invisible",
    "name", "color", "flag", "flag0", "flags", "elevation", "ins_pt", "alignment_pt",
    "scale", "rotation", "extrusion", "text", "text_value", "default_value", "prompt", "tag",
    "text_height", "height", "width_factor", "x_axis_dir", "attachment", "extents_width",
    "extents_height", "rect_width", "points", "bulges", "vertex", "vertexes", "vertices",
    "point", "start", "end", "start_angle", "end_angle", "center", "radius", "closed",
    "block_header", "attribs", "num_attribs", "has_attribs", "first_entity", "last_entity",
    "entities", "base_pt", "xref_pname", "is_xref_ref", "is_xref_overlay", "is_xref_resolved",
    "horiz_alignment", "vert_alignment", "linewt", "style", "knots", "ctrl_pts",
}


def write_csv(path, fields, rows):
    with Path(path).open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path, data):
    with Path(path).open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, allow_nan=False)


def find_reader(explicit):
    if explicit:
        return str(Path(explicit).expanduser().resolve())
    if os.environ.get("DWGREAD_BIN"):
        return os.path.expanduser(os.environ["DWGREAD_BIN"])
    located = shutil.which("dwgread")
    if located:
        return located
    home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    for candidate in sorted((home / "tools/libredwg").glob("*/bin/dwgread"), reverse=True):
        if os.access(candidate, os.X_OK):
            return str(candidate)
    raise ValueError("dwgread missing. Supply --dwgread or follow references/toolchain.md.")


def extract(args):
    source = Path(args.input).expanduser().resolve()
    if not source.is_file():
        raise ValueError(f"Source file does not exist: {source}")
    out = Path(args.out).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()) and not args.overwrite:
        raise ValueError("Output directory is not empty; choose a fresh one or --overwrite.")
    reader_status = {"used": False, "partial": False}
    checksum = hashlib.sha256()
    with source.open("rb") as f:
        signature = f.read(6)
        f.seek(0)
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            checksum.update(chunk)
    if source.suffix.lower() == ".json":
        raw = source
    else:
        if not re.fullmatch(rb"AC[0-9]{4}", signature):
            raise ValueError(f"Unrecognized DWG signature {signature!r}; confirm source format.")
        reader = find_reader(args.dwgread)
        raw = out / "drawing.json"
        if raw == source:
            raise ValueError("Output would overwrite source.")
        version = subprocess.run([reader, "--version"], capture_output=True, text=True, timeout=20)
        reader_status.update({"used": True, "executable": reader,
                              "version": (version.stdout + version.stderr).strip()[:2000]})
        with (out / "conversion.log").open("w", encoding="utf-8") as log:
            result = subprocess.run([reader, "-O", "JSON", "-o", str(raw), str(source)],
                                    stdout=log, stderr=log, timeout=args.timeout)
        reader_status["returncode"] = result.returncode
        if result.returncode != 0:
            reader_status["partial"] = True
            if not args.allow_partial:
                raise ValueError(f"dwgread exit {result.returncode}; inspect conversion.log. Raw output retained.")
        if not raw.is_file() or raw.stat().st_size == 0:
            raise ValueError("Reader produced no JSON.")
    metadata, counts, unknown, objects = {}, collections.Counter(), collections.Counter(), []
    for obj in object_stream(raw, metadata):
        kind = obj.get("entity", obj.get("object", "UNCLASSIFIED"))
        counts[kind] += 1
        if kind.startswith("UNKNOWN") or "PROXY" in kind:
            unknown[str(obj.get("type"))] += 1
        if kind in ENTITY_TYPES or kind.startswith("DIMENSION_") or kind in {"LAYER", "BLOCK_HEADER"}:
            objects.append({k: v for k, v in obj.items() if k in FIELDS})
    if not sum(counts.values()):
        raise ValueError("No drawing objects found.")
    by_handle = {handle(o.get("handle")): o for o in objects if handle(o.get("handle"))}
    layers = {handle(o.get("handle")): o.get("name", "") for o in objects if o.get("object") == "LAYER"}
    definitions = {handle(o.get("handle")): o.get("name", "") for o in objects if o.get("object") == "BLOCK_HEADER"}
    prompts = collections.defaultdict(dict)
    owners = collections.defaultdict(list)
    for o in objects:
        if o.get("entity") == "ATTDEF":
            prompts[handle(o.get("ownerhandle"))][o.get("tag", "")] = o.get("prompt", "")
        if o.get("entity") == "ATTRIB":
            owners[handle(o.get("ownerhandle"))].append(o)
    layer_counts = collections.Counter(layers.get(handle(o.get("layer")), "<unresolved>") for o in objects if o.get("entity"))
    blocks = []
    for o in objects:
        if o.get("entity") not in {"INSERT", "MINSERT"}:
            continue
        bh = handle(o.get("block_header"))
        attrs = [by_handle.get(handle(ref)) for ref in o.get("attribs", [])]
        attrs = [a for a in attrs if a and a.get("entity") == "ATTRIB"]
        if not attrs:
            attrs = owners[handle(o.get("handle"))]
        attrs = [{"handle": handle(a.get("handle")), "tag": a.get("tag", ""),
                  "value": a.get("text_value", ""), "prompt": prompts[bh].get(a.get("tag", ""), ""),
                  "ins_pt": a.get("ins_pt"), "invisible": a.get("invisible", 0),
                  "flags": a.get("flags", 0)} for a in attrs]
        tag_counts = collections.Counter(a["tag"] for a in attrs)
        blocks.append({"handle": handle(o.get("handle")), "block_handle": bh,
                       "block_name": definitions.get(bh), "owner": handle(o.get("ownerhandle")),
                       "layer": layers.get(handle(o.get("layer"))), "mode": o.get("entmode"),
                       "entity": o["entity"], "point": o.get("ins_pt"), "scale": o.get("scale"),
                       "rotation": o.get("rotation"), "extrusion": o.get("extrusion"),
                       "invisible": o.get("invisible", 0), "attributes": attrs,
                       "duplicate_tags": [t for t, c in tag_counts.items() if c > 1]})
    text_rows = []
    for o in objects:
        if o.get("entity") not in {"TEXT", "MTEXT", "ATTRIB", "ATTDEF"}:
            continue
        value = o.get("text_value", o.get("text", o.get("default_value", "")))
        pt = o.get("ins_pt") or [None, None]
        text_rows.append({"handle": handle(o.get("handle")), "entity": o["entity"],
                          "owner": handle(o.get("ownerhandle")), "layer": layers.get(handle(o.get("layer"))),
                          "mode": o.get("entmode"), "invisible": o.get("invisible", 0),
                          "cad_x": pt[0], "cad_y": pt[1], "z": pt[2] if len(pt) > 2 else o.get("elevation"),
                          "tag": o.get("tag"), "prompt": o.get("prompt"),
                          "text_raw": value, "text_plain": plain_text(value)})
    boundaries = [{"handle": handle(o.get("handle")), "layer": layers.get(handle(o.get("layer"))),
                   "mode": o.get("entmode"), "raw_flag": o.get("flag"), "elevation": o.get("elevation"),
                   "points": o.get("points", []), "bulges": o.get("bulges", [])}
                  for o in objects if o.get("entity") == "LWPOLYLINE"]
    header = metadata.get("HEADER", {})
    info = {"schema_version": 1, "source": str(source), "sha256": checksum.hexdigest(),
            "signature": signature.decode("ascii", errors="replace"), "reader": reader_status,
            "created_by": metadata.get("created_by"), "fileheader": metadata.get("FILEHEADER", {}),
            "units_metadata": {k: v for k, v in header.items() if "UNIT" in k.upper() or k.upper() == "MEASUREMENT"},
            "object_count": sum(counts.values()), "object_types": dict(counts),
            "unknown_or_proxy_types": dict(unknown), "layer_entity_counts": dict(layer_counts),
            "layers": layers, "classes": metadata.get("CLASSES", []),
            "selected_entity_count": len(objects), "block_count": len(blocks),
            "block_duplicate_tag_count": sum(bool(b["duplicate_tags"]) for b in blocks),
            "limitations": ["Nested transforms and CAD viewport visibility are not evaluated.",
                            "Proxy/custom classes may contain additional unreadable information."]}
    write_json(out / "inventory.json", info)
    write_json(out / "compact.json", {"schema_version": 1, "source": str(source), "reader": reader_status,
                                     "layers": layers, "block_definitions": definitions,
                                     "units_metadata": info["units_metadata"], "objects": objects, "blocks": blocks})
    write_json(out / "boundaries.json", boundaries)
    write_csv(out / "texts.csv", ["handle", "entity", "owner", "layer", "mode", "invisible", "cad_x", "cad_y", "z", "tag", "prompt", "text_raw", "text_plain"], text_rows)
    attribute_rows = []
    for block in blocks:
        for a in block["attributes"]:
            pt = block["point"] or [None, None]
            attribute_rows.append({"block_handle": block["handle"], "block_name": block["block_name"],
                                   "layer": block["layer"], "mode": block["mode"], "cad_x": pt[0], "cad_y": pt[1],
                                   "attribute_handle": a["handle"], "tag": a["tag"], "prompt": a["prompt"],
                                   "value": a["value"], "invisible": a["invisible"]})
    write_csv(out / "attributes.csv", ["block_handle", "block_name", "layer", "mode", "cad_x", "cad_y", "attribute_handle", "tag", "prompt", "value", "invisible"], attribute_rows)
    print(json.dumps({"output": str(out), "objects": info["object_count"], "selected": len(objects),
                      "blocks": len(blocks), "text_rows": len(text_rows), "boundary_candidates": len(boundaries),
                      "unsupported": sum(unknown.values()), "partial": reader_status["partial"]}, ensure_ascii=False))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", required=True, help="DWG or existing LibreDWG JSON")
    p.add_argument("--out", required=True)
    p.add_argument("--dwgread", help="Trusted reader executable")
    p.add_argument("--timeout", type=int, default=600, help="Reader timeout in seconds")
    p.add_argument("--allow-partial", action="store_true", help="Analyze valid JSON after a nonzero reader exit")
    p.add_argument("--overwrite", action="store_true")
    args = p.parse_args()
    try:
        extract(args)
    except (ValueError, OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
