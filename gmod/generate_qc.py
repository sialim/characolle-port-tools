"""Generate a Source QC file for an exported CharaColle model."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--export", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--material-path", required=True)
    parser.add_argument("--model-name")
    parser.add_argument("--surfaceprop", default="flesh")
    return parser.parse_args()


def safe_name(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_")
    return value or "group"


def require_export(export_dir: Path, filename: str) -> str:
    path = export_dir / filename
    if not path.is_file():
        raise FileNotFoundError(f"Missing exported Source mesh: {path}")
    return filename


def main() -> None:
    args = parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    character = manifest["character"].lower()
    model_name = args.model_name or manifest.get("model_name") or f"characolle/{character}"
    material_path = args.material_path.replace("\\", "/").strip("/")

    lines = [
        f'$modelname "{model_name}.mdl"',
        f'$cdmaterials "{material_path}"',
        '$body "body" "base.dmx"',
        '$bodygroup "head"',
        "{",
        '    studio "head.dmx"',
        "}",
    ]

    require_export(args.export, "base.dmx")
    require_export(args.export, "head.dmx")
    for entry in manifest.get("bodygroups", []):
        filename = f"bg_{safe_name(entry['name'])}.dmx"
        require_export(args.export, filename)
        group_name = safe_name(entry["name"])
        lines.extend([
            f'$bodygroup "{group_name}"',
            "{",
            "    blank",
            f'    studio "{filename}"',
            "}",
        ])

    lines.extend([
        '$sequence "idle" "base.dmx" fps 1',
        f'$surfaceprop "{args.surfaceprop}"',
        "$contents \"solid\"",
        "",
    ])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(f"Wrote QC with {len(manifest.get('bodygroups', []))} bodygroups to {args.output}")


if __name__ == "__main__":
    main()
