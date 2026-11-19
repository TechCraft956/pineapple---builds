#!/usr/bin/env python3
"""Fetch the trading-lab tree from PR branch claude/lse-trading-setup-dw4siy
of TechCraft956/localedge-site via the GitHub connector CLI (read-only).
Writes files under DEST/trading-lab/<path>. Also writes a manifest."""
import json, os, subprocess, sys

OWNER = "TechCraft956"
REPO = "localedge-site"
REF = "refs/heads/claude/lse-trading-setup-dw4siy"
DEST = os.path.expanduser("~/workspace/pineapple/builds/trading-lab/src")

def gh(args):
    out = subprocess.run(
        ["/opt/hatch/bin/github", "call-read-tool", "--name", "get_file_contents",
         "--arguments-json", json.dumps(args)],
        capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        raise RuntimeError(f"github CLI failed: {out.stderr[:500]}")
    return json.loads(out.stdout)

def list_dir(path):
    r = gh({"owner": OWNER, "repo": REPO, "path": path, "ref": REF,
            "fields": ["type", "name", "path", "size"]})
    entries = json.loads(r["result"]["content"][0]["text"])
    return entries

def walk(path):
    files, dirs = [], []
    for e in list_dir(path):
        if e["type"] == "dir":
            dirs.append(e["path"])
        else:
            files.append(e["path"])
    for d in dirs:
        f, dd = walk(d)
        files += f
        dirs += dd
    return files, dirs

def fetch_file(path):
    r = gh({"owner": OWNER, "repo": REPO, "path": path, "ref": REF})
    contents = r["result"]["content"]
    # resource entries carry the text; binary files may come back differently
    texts = []
    for c in contents:
        if c.get("type") == "resource":
            t = c.get("resource", {}).get("text")
            if t is not None:
                texts.append(t)
    if not texts:
        # Empty file: resource has no "text" key at all.
        if any(c.get("type") == "resource" for c in contents) and any(
            "empty file" in (c.get("text") or "") for c in contents):
            return ""
    if not texts:
        # maybe a plain text entry
        texts = [c.get("text") for c in contents if c.get("type") == "text"
                 and not c["text"].startswith("successfully")]
    if not texts:
        raise RuntimeError(f"no text content for {path}: {json.dumps(contents)[:300]}")
    return texts[0]

def main():
    files, dirs = walk("trading-lab")
    print(f"tree: {len(files)} files, {len(dirs)} dirs")
    manifest = []
    for p in sorted(files):
        rel = p[len("trading-lab/"):]
        dest = os.path.join(DEST, "trading-lab", rel)
        if os.path.exists(dest):
            manifest.append({"path": p, "size": os.path.getsize(dest), "skipped": True})
            continue
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        text = fetch_file(p)
        with open(dest, "w", encoding="utf-8") as f:
            f.write(text)
        manifest.append({"path": p, "size": len(text)})
        print(f"  fetched {p} ({len(text)} bytes)")
    with open(os.path.join(DEST, "MANIFEST.json"), "w") as f:
        json.dump({"ref": REF, "owner": OWNER, "repo": REPO, "files": manifest}, f, indent=2)
    print(f"done: {len(manifest)} files -> {DEST}")

if __name__ == "__main__":
    main()
