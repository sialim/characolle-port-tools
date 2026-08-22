"""List mesh-bearing frame names from an Illusion .xx file."""

from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path


KNOWN_FORMAT_IDS = {
    0x3F8F5C29,
    0x3F90A3D7,
    0x3F91EB85,
    0x3F933333,
    0x3F947AE1,
    0x3F95C28F,
    0x3F970A3D,
    0x3F99999A,
    0x3FA66666,
    0x3FB33333,
}


class Reader:
    def __init__(self, data: bytes, fmt: int):
        self.data = data
        self.pos = 0
        self.fmt = fmt

    def read(self, count: int) -> bytes:
        result = self.data[self.pos : self.pos + count]
        if len(result) != count:
            raise EOFError(f"short read at {self.pos}: expected {count}, got {len(result)}")
        self.pos += count
        return result

    def i32(self) -> int:
        return struct.unpack("<i", self.read(4))[0]

    def u16(self) -> int:
        return struct.unpack("<H", self.read(2))[0]

    def name(self) -> str:
        count = self.i32()
        raw = bytes((~value) & 0xFF for value in self.read(count))
        return raw.decode("shift_jis", errors="replace").rstrip("\0")

    def vertex(self) -> None:
        self.read(2 if self.fmt >= 4 else 4)
        self.read(12 + 12 + 4 + 12 + 8)
        if self.fmt >= 4:
            self.read(20)

    def frame(self, output: list[dict[str, object]], parent: str = "") -> None:
        frame_name = self.name()
        child_count = self.i32()
        self.read(64)
        self.read(32 if self.fmt >= 7 else 16)
        submesh_count = self.i32()
        self.read(24)
        self.read(64 if self.fmt >= 7 else 16)
        if self.fmt >= 6:
            self.name()

        if submesh_count > 0:
            vectors_per_vertex = self.read(1)[0]
            for _ in range(submesh_count):
                self.read(64 if self.fmt >= 7 else 16)
                self.read(4)
                face_index_count = self.i32()
                self.read(face_index_count * 2)
                vertex_count = self.i32()
                for _ in range(vertex_count):
                    self.vertex()
                if self.fmt >= 7:
                    self.read(20)
                for _ in range(vertex_count * vectors_per_vertex):
                    self.read(8)
                if self.fmt >= 2:
                    self.read(100)
                if self.fmt >= 7:
                    self.read(284)
                    if self.fmt >= 8:
                        self.read(1)
                        self.name()
                        self.read(16)
                else:
                    if self.fmt >= 3:
                        self.read(64)
                    if self.fmt >= 5:
                        self.read(20)
                    if self.fmt >= 6:
                        self.read(28)

            duplicate_count = self.u16()
            self.read(8)
            for _ in range(duplicate_count):
                self.vertex()
            bone_count = self.i32()
            for _ in range(bone_count):
                self.name()
                self.read(4 + 64)

            output.append(
                {
                    "name": frame_name,
                    "parent": parent,
                    "submeshes": submesh_count,
                    "vertices": vertex_count,
                    "offset": self.pos,
                }
            )

        for _ in range(child_count):
            self.frame(output, frame_name)


def parse(path: Path) -> dict[str, object]:
    data = path.read_bytes()
    format_buf = data[:5]
    first = format_buf[0]
    if first >= 1 and int.from_bytes(format_buf[1:5], "little") == 0:
        fmt = int.from_bytes(format_buf[:4], "little", signed=True)
    elif int.from_bytes(format_buf[:4], "little") in KNOWN_FORMAT_IDS:
        fmt = -1
    else:
        fmt = 0
    header_len = 26 if fmt >= 1 else 21
    reader = Reader(data, fmt)
    reader.read(header_len)
    meshes: list[dict[str, object]] = []
    reader.frame(meshes)
    reader.read(4)
    material_count = reader.i32()
    materials = []
    for _ in range(material_count):
        material_name = reader.name()
        reader.read(4 * 16 + 4)
        slots = []
        for _ in range(4):
            slots.append(reader.name())
            reader.read(16)
        reader.read(4 if fmt < 0 else 88)
        materials.append({"name": material_name, "textures": slots})

    texture_count = reader.i32()
    textures = []
    for index in range(texture_count):
        name = reader.name()
        reader.read(4 + 4 * 7 + 1)
        image_size = reader.i32()
        reader.read(image_size)
        textures.append({"index": index, "name": name, "size": image_size})

    return {
        "path": str(path),
        "format": fmt,
        "mesh_frames": meshes,
        "materials": materials,
        "textures": textures,
        "trailing_offset": reader.pos,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path, nargs="+")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = {str(path): parse(path) for path in args.input}
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text)


if __name__ == "__main__":
    main()
