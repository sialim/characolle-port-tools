"""Build a CharaColle Source model and package it as a Garry's Mod addon."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

from validate_model import validate_model


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--qc", type=Path, required=True)
    parser.add_argument("--gmod", type=Path, required=True)
    parser.add_argument("--vtfcmd", type=Path, required=True)
    parser.add_argument("--textures", type=Path, action="append", required=True)
    parser.add_argument("--addon", type=Path, required=True)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--skip-textures", action="store_true")
    parser.add_argument("--skip-compile", action="store_true")
    parser.add_argument("--skip-package", action="store_true")
    return parser.parse_args()


def clean_image_name(value: str) -> str:
    value = re.sub(r"(\.[0-9]{3})+$", "", value)
    return Path(value).name


def source_texture_stem(value: str) -> str:
    original = Path(value).stem
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", original).casefold()
    if stem != original.casefold():
        stem += "_" + hashlib.sha256(original.encode("utf-8")).hexdigest()[:8]
    return stem


def material_entries(manifest: dict) -> dict[str, dict]:
    entries: dict[str, dict] = {}
    objects = list(manifest.get("base_objects", [])) + list(manifest.get("head_objects", []))
    objects += [mesh for entry in manifest.get("bodygroups", []) for mesh in (entry.get("meshes") or [entry["mesh"]])]
    for obj in objects:
        for material in obj.get("materials", []):
            name = material["name"].casefold()
            entries.setdefault(name, material)
    return entries


def texture_sources(roots: list[Path]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for root in roots:
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.casefold() not in {".bmp", ".tga", ".png", ".jpg", ".jpeg"}:
                continue
            result.setdefault(path.name.casefold(), path)
    return result


def run(command: list[str], cwd: Path | None = None) -> None:
    print("+", " ".join(f'"{part}"' if " " in part else part for part in command))
    subprocess.run(command, cwd=cwd, check=True)


def convert_textures(manifest: dict, roots: list[Path], vtfcmd: Path, addon: Path, material_path: str) -> int:
    source_map = texture_sources(roots)
    output = addon / "materials" / Path(material_path)
    output.mkdir(parents=True, exist_ok=True)
    converted: set[str] = set()
    for material_name, material in material_entries(manifest).items():
        images = material.get("images", [])
        usable = [image for image in images if "_sell_" not in image["name"].casefold() and "_sel_" not in image["name"].casefold()]
        if not usable:
            usable = images
        if not usable:
            continue
        image_name = clean_image_name(Path(usable[0].get("filepath", "")).name or usable[0]["name"])
        source = source_map.get(image_name.casefold())
        if source is None:
            print(f"warning: source texture not found for {material_name}: {image_name}")
            continue
        texture_stem = source_texture_stem(image_name)
        vtf_name = texture_stem + ".vtf"
        if vtf_name.casefold() not in converted:
            destination = output / vtf_name
            generated = output / (source.stem + ".vtf")
            previous_time = generated.stat().st_mtime_ns if generated.is_file() else None
            command = [str(vtfcmd), "-file", str(source), "-output", str(output), "-format", "DXT5", "-nothumbnail"]
            run([*command, "-silent"])
            if not generated.is_file() or generated.stat().st_mtime_ns == previous_time:
                print(f"Retrying texture conversion at the nearest power-of-two size: {source.name}")
                run([*command, "-resize", "-rmethod", "NEAREST", "-rfilter", "CATROM"])
            if not generated.is_file() or generated.stat().st_mtime_ns == previous_time:
                raise RuntimeError(f"VTFCmd did not produce the requested texture: {generated}")
            if generated != destination:
                generated.replace(destination)
            converted.add(vtf_name.casefold())
        vmt = output / f"{material_name}.vmt"
        normalized_material_path = material_path.replace("\\", "/").strip("/")
        base = f"{normalized_material_path}/{texture_stem}"
        alpha = '    "$translucent" "1"\n' if source.suffix.casefold() == ".tga" else ""
        vmt.write_text(
            '"VertexLitGeneric"\n{\n'
            f'    "$basetexture" "{base}"\n'
            '    "$model" "1"\n'
            f'{alpha}'
            '}\n',
            encoding="utf-8",
            newline="\n",
        )
    return len(converted)


def compiled_model_files(gmod: Path, qc: Path) -> list[Path]:
    text = qc.read_text(encoding="utf-8")
    match = re.search(r'^\$modelname\s+"([^"/]+(?:/[^"/]+)*)\.mdl"', text, re.MULTILINE | re.IGNORECASE)
    if match is None:
        raise RuntimeError(f"Could not read $modelname from {qc}")
    model_rel = Path(match.group(1))
    source_dir = gmod / "garrysmod" / "models" / model_rel.parent
    return sorted(source_dir.glob(model_rel.name + ".*"))


def copy_compiled_files(files: list[Path], gmod: Path, addon: Path) -> int:
    if not files:
        raise RuntimeError("StudioMDL produced no compiled model files")
    text = addon / "models"
    for source in files:
        relative = source.relative_to(gmod / "garrysmod" / "models")
        destination = text / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    return len(files)


def write_spawnlist(addon: Path, model: Path) -> None:
    relative = model.relative_to(addon).as_posix()
    identifier = re.sub(r"[^a-z0-9_]+", "_", relative.casefold())
    destination = addon / "lua" / "autorun" / "client" / f"{identifier}.lua"
    destination.parent.mkdir(parents=True, exist_ok=True)
    model_literal = json.dumps(relative)
    destination.write_text(
        f'list.Set("CharaColleModels", {model_literal}, {{type="model", model={model_literal}}})\n'
        'hook.Add("PopulatePropMenu", "CharaColleModels", function()\n'
        '    local contents = {}\n'
        '    for _, entry in SortedPairs(list.Get("CharaColleModels")) do\n'
        '        contents[#contents + 1] = entry\n'
        '    end\n'
        '    spawnmenu.AddPropCategory("CharaColle", "CharaColle", contents, "icon16/user.png")\n'
        'end)\n', encoding="utf-8", newline="\n")


def main() -> None:
    args = parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    material_path = re.sub(r"^materials[\\/]?", "", manifest.get("material_path", "")) or f"models/characolle/{manifest['character'].lower()}"
    qc_text = args.qc.read_text(encoding="utf-8")
    material_match = re.search(r'^\$cdmaterials\s+"([^"]+)"', qc_text, re.MULTILINE | re.IGNORECASE)
    if material_match:
        material_path = material_match.group(1)

    args.addon.mkdir(parents=True, exist_ok=True)
    addon_info = {
        "title": f"CharaColle {manifest['character']}",
        "type": "model",
        "tags": ["cartoon"],
        "author": "characolle-port-tools",
    }
    (args.addon / "addon.json").write_text(json.dumps(addon_info, indent=2) + "\n", encoding="utf-8")
    texture_count = 0
    if not args.skip_textures:
        texture_count = convert_textures(manifest, args.textures, args.vtfcmd, args.addon, material_path)
    if not args.skip_compile:
        run([str(args.gmod / "bin" / "studiomdl.exe"), "-game", str(args.gmod / "garrysmod"), str(args.qc)], cwd=args.qc.parent)
    files = compiled_model_files(args.gmod, args.qc)
    model_count = copy_compiled_files(files, args.gmod, args.addon)
    model = next((path for path in files if path.suffix.casefold() == ".mdl"), None)
    if model is None:
        raise RuntimeError("StudioMDL produced no MDL file")
    validation = validate_model(model, args.addon, bool(re.search(r'^\$collisionjoints\s', qc_text, re.MULTILINE | re.IGNORECASE)))
    validation_path = args.addon.parent / f"{args.addon.name}_validation.json"
    validation_path.write_text(json.dumps(validation, indent=2) + "\n", encoding="utf-8")
    if not validation["passed"]:
        raise RuntimeError(f"Compiled model failed validation: {validation['errors']}")
    if validation["has_physics"]:
        write_spawnlist(args.addon, args.addon / "models" / model.relative_to(args.gmod / "garrysmod" / "models"))
    if not args.skip_package:
        args.package.parent.mkdir(parents=True, exist_ok=True)
        run([str(args.gmod / "bin" / "gmad.exe"), "create", "-folder", str(args.addon), "-out", str(args.package)])
    print(json.dumps({"textures": texture_count, "compiled_files": model_count, "addon": str(args.addon), "package": str(args.package)}, indent=2))


if __name__ == "__main__":
    main()
