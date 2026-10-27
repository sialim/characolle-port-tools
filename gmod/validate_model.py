"""Check compiled Source model structure and packaged material references."""

from __future__ import annotations

import argparse
import json
import math
import re
import struct
from pathlib import Path


def validate_model(path: Path, addon: Path | None = None, require_physics: bool = False) -> dict:
    data = path.read_bytes()
    errors = []

    def integer(offset: int) -> int:
        return struct.unpack_from("<i", data, offset)[0]

    def string(offset: int) -> str:
        if not 0 <= offset < len(data):
            raise ValueError(f"String offset outside MDL: {offset}")
        return data[offset:data.index(b"\0", offset)].decode("utf-8")

    if len(data) < 408 or data[:4] != b"IDST" or integer(4) != 48:
        raise ValueError(f"Unsupported or truncated Source model: {path}")
    if integer(76) != len(data):
        errors.append("MDL length does not match its header")
    checksum = integer(8)
    physics_path = path.with_suffix(".phy")
    physics_solids = 0
    if physics_path.is_file():
        blob = physics_path.read_bytes()
        if len(blob) < 16:
            errors.append("Truncated PHY header")
        else:
            size, identifier, physics_solids, physics_checksum = struct.unpack_from("<4i", blob)
            if size != 16 or not 0 < physics_solids <= 32:
                errors.append(f"Invalid PHY header or solid count: {physics_solids}")
            if physics_checksum != checksum:
                errors.append("PHY checksum does not match MDL")
    elif require_physics:
        errors.append("Ragdoll build is missing its PHY file")
    bone_count = integer(156)
    if not 0 < bone_count <= 256:
        errors.append(f"Unsupported bone count: {bone_count}")
    flex_descriptors, flex_controllers, flex_rules = integer(260), integer(268), integer(276)
    if flex_controllers and not flex_rules:
        errors.append("Facial controllers have no compiled flex rules")
    combinations = 1
    bodyparts = []
    for index in range(integer(232)):
        offset = integer(236) + 16 * index
        name = string(offset + integer(offset))
        models, base = integer(offset + 4), integer(offset + 8)
        if models <= 0 or base != combinations or base <= 0:
            errors.append(f"Invalid bodygroup table: {name}, models={models}, base={base}, expected={combinations}")
        combinations *= max(1, models)
        bodyparts.append({"name": name, "models": models, "base": base})
    if combinations > 2**31:
        errors.append("Bodygroup combinations exceed signed 32-bit storage")
    bounds = [[math.inf] * 3, [-math.inf] * 3]
    for suffix, checksum_offset in ((".vvd", 8), (".dx90.vtx", 16)):
        companion = path.with_suffix(suffix)
        if not companion.is_file():
            errors.append(f"Missing {suffix}")
            continue
        blob = companion.read_bytes()
        if struct.unpack_from("<i", blob, checksum_offset)[0] != checksum:
            errors.append(f"{suffix} checksum does not match MDL")
        if suffix != ".vvd":
            continue
        count = struct.unpack_from("<i", blob, 16)[0]
        offset = struct.unpack_from("<i", blob, 56)[0]
        if count <= 0 or offset + count * 48 > len(blob):
            errors.append("Invalid VVD vertex buffer")
            continue
        for index in range(count):
            point = struct.unpack_from("<3f", blob, offset + 48 * index + 16)
            for axis, value in enumerate(point):
                if not math.isfinite(value):
                    raise ValueError("Non-finite compiled vertex position")
                bounds[0][axis] = min(bounds[0][axis], value)
                bounds[1][axis] = max(bounds[1][axis], value)
    height = bounds[1][2] - bounds[0][2]
    if not 16 <= height <= 128:
        errors.append(f"Character height outside 16–128 Source units: {height:g}")

    materials = []
    directories = [string(integer(integer(216) + 4 * i)) for i in range(integer(212))]
    for index in range(integer(204)):
        offset = integer(208) + 64 * index
        name = string(offset + integer(offset)).replace("\\", "/").casefold()
        materials.append(name)
        if addon is None:
            continue
        candidates = [addon / "materials" / f"{prefix}{name}.vmt" for prefix in ["", *directories]]
        vmt = next((candidate for candidate in candidates if candidate.is_file()), None)
        if vmt is None:
            errors.append(f"Missing VMT for compiled material: {name}")
            continue
        match = re.search(r'"\$basetexture"\s+"([^"]+)"', vmt.read_text(encoding="utf-8"), re.IGNORECASE)
        if match is None or not (addon / "materials" / f"{match.group(1)}.vtf").is_file():
            errors.append(f"Missing base texture referenced by {vmt.name}")
    return {"model": str(path), "bone_count": bone_count, "bodyparts": bodyparts,
            "flex_descriptors": flex_descriptors, "flex_controllers": flex_controllers, "flex_rules": flex_rules,
            "body_combinations": combinations, "vertex_bounds": bounds, "height": height,
            "materials": materials, "has_physics": physics_path.is_file(), "physics_solids": physics_solids,
            "errors": errors, "passed": not errors}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("model", type=Path)
    parser.add_argument("--addon", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--require-physics", action="store_true")
    args = parser.parse_args()
    result = validate_model(args.model, args.addon, args.require_physics)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
