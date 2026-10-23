#!/usr/bin/env python3
"""Finish an authored AI Infrastructure Monitoring pack before publishing.

The ITSI 5.0 authoring page packages lookups/ai_model_prices.csv but not its lookup definition, and
the provider base search needs the definition for wildcard model matching. This adds
default/transforms.conf and can drop screenshots (updating itsi/manifest.json to match).

Usage: postbuild.py <authored.tar.gz> <output.tar.gz> [--drop-screenshot "<file name>" ...]
"""
import argparse
import io
import json
import tarfile

TRANSFORMS = """[ai_model_prices]
filename = ai_model_prices.csv
match_type = WILDCARD(model_pattern)
max_matches = 1
case_sensitive_match = 0
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("output")
    ap.add_argument("--drop-screenshot", action="append", default=[])
    args = ap.parse_args()

    with tarfile.open(args.source, "r:gz") as src:
        members = src.getmembers()
        root = members[0].name.split("/")[0]
        files = {m.name: (m, src.extractfile(m).read() if m.isfile() else None) for m in members}

    if f"{root}/default/transforms.conf" in files:
        raise SystemExit("transforms.conf already present: check it instead of overwriting")

    dropped = {f"{root}/appserver/static/screenshots/{n}" for n in args.drop_screenshot}
    missing = dropped - files.keys()
    if missing:
        raise SystemExit(f"screenshots not found: {sorted(missing)}")

    manifest_path = f"{root}/itsi/manifest.json"
    manifest = json.loads(files[manifest_path][1])
    names = set(args.drop_screenshot)
    if manifest.get("main_screenshot", {}).get("path") in names:
        raise SystemExit("cannot drop the main screenshot")
    manifest["screenshots"] = [s for s in manifest.get("screenshots", []) if s["path"] not in names]

    def add(out, name, data, template):
        info = tarfile.TarInfo(name)
        info.size, info.mode, info.mtime = len(data), template.mode, template.mtime
        info.uid, info.gid, info.uname, info.gname = template.uid, template.gid, template.uname, template.gname
        out.addfile(info, io.BytesIO(data))

    with tarfile.open(args.output, "w:gz") as out:
        for name, (member, data) in files.items():
            if name in dropped:
                continue
            if name == manifest_path:
                add(out, name, (json.dumps(manifest, indent=4) + "\n").encode(), member)
            elif member.isfile():
                out.addfile(member, io.BytesIO(data))
            else:
                out.addfile(member)
        conf = files[f"{root}/default/app.conf"][0]
        add(out, f"{root}/default/transforms.conf", TRANSFORMS.encode(), conf)

    print(f"wrote {args.output}: added default/transforms.conf, dropped {len(dropped)} screenshot(s)")


if __name__ == "__main__":
    main()
