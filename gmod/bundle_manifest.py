"""Combine related material submeshes into one outfit bodygroup without joining geometry."""

import argparse
import json
import re
from pathlib import Path


def bundle(manifest: dict, prefixes: list[str]) -> dict:
    groups = list(manifest.get("bodygroups", []))
    for prefix in prefixes:
        selected = []
        for entry in groups:
            meshes = entry.get("meshes") or [entry["mesh"]]
            if all(re.fullmatch(re.escape(prefix) + r"_\d+(?:\.\d+)?", mesh["name"].split("__", 1)[-1], re.I)
                   for mesh in meshes):
                selected.append(entry)
        if len(selected) < 2:
            raise ValueError(f"Expected at least two submeshes for {prefix}")
        layers = {entry["layer"] for entry in selected}
        if len(layers) != 1:
            raise ValueError("Bundle an outfit-specific manifest; do not combine different layers")
        combined = {"name": f"{selected[0]['layer']}_{prefix.lower()}", "layer": selected[0]["layer"],
                    "meshes": [mesh for entry in selected for mesh in (entry.get("meshes") or [entry["mesh"]])]}
        index = groups.index(selected[0])
        groups = [entry for entry in groups if entry not in selected]
        groups.insert(index, combined)
    return {**manifest, "bodygroups": groups}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--prefix", action="append", required=True)
    args = parser.parse_args()
    result = bundle(json.loads(args.input.read_text(encoding="utf-8")), args.prefix)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(result['bodygroups'])} bodygroups to {args.output}")


if __name__ == "__main__":
    main()
