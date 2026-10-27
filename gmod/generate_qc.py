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
    parser.add_argument("--scale", type=float)
    parser.add_argument("--outfit-visible", action="store_true", help="Show clothing bodygroups by default")
    parser.add_argument("--physics", action="store_true", help="Compile the exported jointed collision skeleton")
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
    combinations = 1
    for entry in manifest.get("bodygroups", []):
        combinations *= 2
        if combinations > 2**31:
            raise ValueError("Outfit has too many independent bodygroups for signed 32-bit storage; group related parts first")

    lines = [
        f'$modelname "{model_name}.mdl"',
    ]
    if args.scale is not None:
        lines.append(f"$scale {args.scale:g}")
    lines.extend([
        f'$cdmaterials "{material_path}"',
        '$body "body" "base.dmx"',
    ])
    flex_path = args.export / "flexes.json"
    flexes = json.loads(flex_path.read_text(encoding="utf-8")) if flex_path.is_file() else []
    if flexes:
        lines.append('$model "head" "head.dmx" {')
        links = {"NamidaBacetoji": "MeBaseToji", "NamidaBace": "MeBase",
                 "NamidaL": "MeWinL", "NamidaR": "MeWinR", "Namidaten": "MeTen", "Namidanik": "MeNiko"}
        for flex in flexes:
            control = flex
            if flex.startswith("PupilSmall") and "PupilSmall" in flexes:
                control = "PupilSmall"
            if flex in links and links[flex] in flexes:
                control = f"{flex} + {links[flex]}"
            lines.append(f"    %{flex} = {control}")
        lines.append("}")
    else:
        lines.extend(['$bodygroup "head"', "{", '    studio "head.dmx"', "}"])

    require_export(args.export, "base.dmx")
    require_export(args.export, "head.dmx")
    for entry in manifest.get("bodygroups", []):
        filename = f"bg_{safe_name(entry['name'])}.dmx"
        require_export(args.export, filename)
        group_name = safe_name(entry["name"])
        alternatives = [f'    studio "{filename}"', "    blank"] if args.outfit_visible else ["    blank", f'    studio "{filename}"']
        lines.extend([
            f'$bodygroup "{group_name}"',
            "{",
            *alternatives,
            "}",
        ])

    lines.extend([
        '$sequence "idle" "base.dmx" fps 1',
        f'$surfaceprop "{args.surfaceprop}"',
        "$contents \"solid\"",
        "",
    ])
    if args.physics:
        require_export(args.export, "physics.dmx")
        physics = json.loads((args.export / "physics.json").read_text(encoding="utf-8"))
        lines.extend(['$collisionjoints "physics.dmx"', "{", f'    $mass {physics["mass"]:g}',
                      '    $inertia 12', '    $damping 0.8', '    $rotdamping 4',
                      f'    $rootbone "{physics["rootbone"]}"'])
        for hull in physics["hulls"]:
            if hull["bone"] == physics["rootbone"]:
                continue
            for axis, limits in zip("xyz", hull["limits"]):
                lines.append(f'    $jointconstrain "{hull["bone"]}" {axis} limit {limits[0]:g} {limits[1]:g} 0')
        lines.extend(["}", ""])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(f"Wrote QC with {len(manifest.get('bodygroups', []))} bodygroups to {args.output}")


if __name__ == "__main__":
    main()
