"""Extract CharaColle XA morph data into JSON for Blender conversion."""

from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path


class Reader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.offset = 0

    def read(self, size: int) -> bytes:
        end = self.offset + size
        if end > len(self.data):
            raise ValueError(f"Unexpected end of XA data at 0x{self.offset:X}")
        value = self.data[self.offset:end]
        self.offset = end
        return value

    def u8(self) -> int:
        return self.read(1)[0]

    def i32(self) -> int:
        return struct.unpack("<i", self.read(4))[0]

    def u16_array(self, count: int) -> list[int]:
        if count < 0 or count > 10_000_000:
            raise ValueError(f"Invalid XA array length: {count}")
        if count == 0:
            return []
        return list(struct.unpack(f"<{count}H", self.read(count * 2)))

    def f32_triplets(self, count: int) -> list[list[float]]:
        if count < 0 or count > 10_000_000:
            raise ValueError(f"Invalid XA vector count: {count}")
        if count == 0:
            return []
        values = struct.unpack(f"<{count * 3}f", self.read(count * 12))
        return [list(values[i : i + 3]) for i in range(0, len(values), 3)]

    def name(self) -> str:
        length = self.i32()
        if length < 0 or length > 1_000_000:
            raise ValueError(f"Invalid XA name length: {length}")
        encrypted = self.read(length)
        decoded = bytes((value ^ 0xFF) for value in encrypted)
        return decoded.decode("shift_jis", errors="replace").rstrip("\0")

    def skip(self, size: int) -> None:
        self.read(size)


def checked_count(reader: Reader, label: str, maximum: int = 10_000_000) -> int:
    count = reader.i32()
    if count < 0 or count > maximum:
        raise ValueError(f"Invalid {label} count: {count}")
    return count


def parse_materials(reader: Reader, count: int) -> None:
    for _ in range(count):
        reader.name()
        colors = checked_count(reader, "material color")
        reader.skip(colors * 72)


def parse_material_section(reader: Reader, forced_count: int | None = None) -> None:
    if forced_count is None:
        present = reader.u8()
        if present == 0:
            return
        forced_count = reader.i32()
    parse_materials(reader, forced_count)


def parse_section2(reader: Reader) -> None:
    if reader.u8() == 0:
        return
    for _ in range(checked_count(reader, "section 2 item")):
        reader.skip(4)
        reader.name()
        reader.skip(8)
        blocks = checked_count(reader, "section 2 block")
        reader.skip(4)
        for _ in range(blocks):
            reader.skip(5)
        reader.skip(1)


def parse_morph_section(reader: Reader) -> dict:
    if reader.u8() == 0:
        return {"index_sets": [], "keyframes": [], "clips": []}

    index_sets = []
    for _ in range(checked_count(reader, "morph index set")):
        unknown = reader.read(1).hex()
        count = checked_count(reader, "morph index")
        mesh_indices = reader.u16_array(count)
        morph_indices = reader.u16_array(count)
        index_sets.append(
            {
                "unknown": unknown,
                "name": reader.name(),
                "mesh_indices": mesh_indices,
                "morph_indices": morph_indices,
            }
        )

    keyframes = []
    for _ in range(checked_count(reader, "morph keyframe")):
        count = checked_count(reader, "morph keyframe vertex")
        positions = reader.f32_triplets(count)
        normals = reader.f32_triplets(count)
        keyframes.append(
            {
                "name": reader.name(),
                "positions": positions,
                "normals": normals,
            }
        )

    clips = []
    for _ in range(checked_count(reader, "morph clip")):
        mesh_name = reader.name()
        clip_name = reader.name()
        refs = []
        for _ in range(checked_count(reader, "morph keyframe reference")):
            unknown1 = reader.read(1).hex()
            index = reader.i32()
            unknown2 = reader.read(1).hex()
            refs.append(
                {
                    "unknown1": unknown1,
                    "index": index,
                    "unknown2": unknown2,
                    "name": reader.name(),
                }
            )
        clips.append(
            {
                "mesh": mesh_name,
                "name": clip_name,
                "keyframes": refs,
                "unknown": reader.read(4).hex(),
            }
        )

    return {"index_sets": index_sets, "keyframes": keyframes, "clips": clips}


def parse_xa(data: bytes) -> tuple[int, dict, int]:
    reader = Reader(data)
    first = reader.u8()
    if first == 0:
        format_id = -1
        parse_section2(reader)
    elif first in (2, 3):
        format_id = struct.unpack("<i", reader.read(4))[0]
        parse_material_section(reader)
        parse_section2(reader)
    elif first == 1:
        test = reader.read(4)
        if (test[0] | test[1] | test[2]) == 0:
            format_id = struct.unpack("<i", test)[0]
            parse_material_section(reader)
            parse_section2(reader)
        else:
            format_id = -1
            parse_materials(reader, struct.unpack("<i", test)[0])
            parse_section2(reader)
    else:
        raise ValueError(f"Unknown XA format marker: 0x{first:02X}")
    return format_id, parse_morph_section(reader), reader.offset


def validate_morphs(morph: dict, requested_clips: set[str] | None) -> dict:
    keyframes = {item["name"]: item for item in morph["keyframes"]}
    index_sets = {item["name"]: item for item in morph["index_sets"]}
    clips = morph["clips"]
    if requested_clips is not None:
        clips = [item for item in clips if item["name"] in requested_clips]

    result = []
    for clip in clips:
        index_set = index_sets.get(clip["name"])
        clip_result = {
            "name": clip["name"],
            "mesh": clip["mesh"],
            "keyframe_count": len(clip["keyframes"]),
            "index_set_found": index_set is not None,
            "invalid_keyframes": [],
            "max_mesh_index": max(index_set["mesh_indices"], default=-1) if index_set else -1,
            "max_morph_index": max(index_set["morph_indices"], default=-1) if index_set else -1,
        }
        if index_set:
            for ref in clip["keyframes"]:
                keyframe = keyframes.get(ref["name"])
                if keyframe is None:
                    clip_result["invalid_keyframes"].append({"name": ref["name"], "reason": "missing keyframe"})
                elif clip_result["max_morph_index"] >= len(keyframe["positions"]):
                    clip_result["invalid_keyframes"].append(
                        {
                            "name": ref["name"],
                            "reason": "morph index exceeds keyframe vertex count",
                            "keyframe_vertices": len(keyframe["positions"]),
                        }
                    )
        result.append(clip_result)
    return {"clips": result}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--clip", action="append", help="Limit output to one or more morph clip names")
    args = parser.parse_args()

    format_id, morph, consumed = parse_xa(args.input.read_bytes())
    selected = set(args.clip) if args.clip else None
    output = {
        "source": str(args.input),
        "format": format_id,
        "morph_data_end": consumed,
        "trailing_bytes": len(args.input.read_bytes()) - consumed,
        "validation": validate_morphs(morph, selected),
        "index_sets": morph["index_sets"],
        "keyframes": morph["keyframes"],
        "clips": [
            clip for clip in morph["clips"] if selected is None or clip["name"] in selected
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False), encoding="utf-8")
    print(
        f"Parsed format {format_id}; {len(output['clips'])} clip(s), "
        f"{len(output['keyframes'])} keyframe(s); trailing bytes: {output['trailing_bytes']}"
    )


if __name__ == "__main__":
    main()
