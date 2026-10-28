"""Combine approved GMA builds into a local folder addon with its own catalog."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path


def approved_models(inventory: dict) -> list[dict]:
    entries = []
    seen = set()
    for category in ("main", "previews"):
        for item in inventory[category]:
            model = item["model"]
            if not re.fullmatch(r"models/characolle/[a-z0-9_]+\.mdl", model):
                raise ValueError(f"Invalid model path: {model}")
            if model in seen:
                raise ValueError(f"Duplicate model: {model}")
            seen.add(model)
            package = Path(item["package"])
            if hashlib.sha256(package.read_bytes()).hexdigest() != item["sha256"]:
                raise ValueError(f"Package checksum mismatch: {package}")
            entries.append(item)
    return entries


def catalog_script(inventory: dict) -> str:
    lines = ["local main={"]
    lines += [" " + json.dumps(item["model"]) + "," for item in inventory["main"]]
    lines += ["}", "local previews={"]
    lines += [" " + json.dumps(item["model"]) + "," for item in inventory["previews"]]
    lines += ["}", "for _,models in ipairs({main,previews}) do",
              " for _,model in ipairs(models) do",
              "  list.Set('CharaColleModels',model,{type='model',model=model})",
              " end", "end",
              "hook.Add('PopulatePropMenu','CharaColleModels',function()",
              " local function contents(models)", "  local entries={}",
              "  for _,model in ipairs(models) do",
              "   if file.Exists(model,'GAME') then entries[#entries+1]={type='model',model=model} end",
              "  end", "  return entries", " end",
              " local current,testing=contents(main),contents(previews)",
              " spawnmenu.AddPropCategory('CharaColle','CharaColle',current,'icon16/user.png')",
              " spawnmenu.AddPropCategory('CharaColle outfit previews','CharaColle outfit previews',testing,'icon16/user_edit.png')",
              " file.Write('characolle_catalog.json',util.TableToJSON({main=#current,outfit_previews=#testing},true))",
              "end)"]
    return "\n".join(lines) + "\n"


def merge_assets(source: Path, output: Path) -> None:
    for kind in ("models", "materials"):
        for path in (source / kind).rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(source)
            destination = output / relative
            if destination.exists():
                if destination.read_bytes() != path.read_bytes():
                    raise ValueError(f"Conflicting addon asset: {relative}")
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, destination)


def assemble(inventory: dict, gmad: Path, output: Path) -> None:
    entries = approved_models(inventory)
    output.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix="characolle_extract_", dir=output.parent) as temporary:
        for index, item in enumerate(entries):
            extracted = Path(temporary) / str(index)
            result = subprocess.run([str(gmad), "extract", "-file", str(Path(item["package"]).resolve()),
                                     "-out", str(extracted)], capture_output=True, text=True)
            if result.returncode:
                raise RuntimeError(result.stdout + result.stderr)
            if not (extracted / item["model"]).is_file():
                raise ValueError(f"Package is missing its declared model: {item['model']}")
            merge_assets(extracted, output)
    destination = output / "lua/autorun/client/zz_characolle_preview_catalog.lua"
    destination.parent.mkdir(parents=True)
    destination.write_text(catalog_script(inventory), encoding="utf-8", newline="\n")
    (output / "addon.json").write_text(json.dumps({"title": "CharaColle verified builds", "type": "model",
                                                  "tags": ["roleplay", "fun"]}, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", required=True, type=Path)
    parser.add_argument("--gmad", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    assemble(json.loads(args.inventory.read_text()), args.gmad, args.output.resolve())
    print(f"Assembled verified folder addon: {args.output}")
