"""Restore face-part links using matching expression slots in the original XA."""

import re
import sys
from pathlib import Path


def aliases_from_xa(path: Path, flexes: list[str]) -> dict[str, str]:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
    from xa_morph_extract import parse_xa

    def clean(value):
        return ''.join(p[:1].upper() + p[1:] for p in re.findall(r'[A-Za-z0-9]+', value)).casefold()

    names = {name.casefold(): name for name in flexes}
    clips = {c['name']: c for c in parse_xa(path.read_bytes())[1]['clips']}
    result = {}
    for target_clip, source_clip in [('Parts_top', 'Face_top'), ('Parts_bottom', 'Face_bottom')]:
        if target_clip not in clips or source_clip not in clips:
            continue
        target, source = clips[target_clip]['keyframes'], clips[source_clip]['keyframes']
        if len(target) != len(source):
            raise ValueError('Face and parts expression slots have different lengths')
        candidates = {}
        for t, s in zip(target, source):
            if clean(t['name']) in names and clean(s['name']) in names:
                candidates.setdefault(names[clean(t['name'])], set()).add(names[clean(s['name'])])
        for target, sources in candidates.items():
            if len(sources) != 1:
                raise ValueError(f'Ambiguous recovered expression link: {target}')
            result[target] = sources.pop()
    for target, source in [('NamidaToji', 'BaceToji'), ('NamidaEinkL', 'WinkLToji'), ('NamidaEinkR', 'WinkRToji')]:
        if target in flexes and source in flexes:
            result[target] = source
    return result
