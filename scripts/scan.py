#!/usr/bin/env python3
"""
scan.py - inventory a photo archive and flag deletion candidates.

    python3 scan.py /path/to/archive
    python3 scan.py /path/to/archive --stats-only
    python3 scan.py /path/to/archive --big-video 50 --big-image 5

Reads only. Nothing is deleted, moved or modified.

Writes a self-contained review page next to the archive (or wherever --out
says) with the candidate list embedded in it. Open that page in a browser to
decide what goes; see apply.py for what happens afterwards.

A file is flagged only when there is a concrete, checkable reason - a filename
pattern, an exact pixel size, a byte count, a matching hash. There is no
guessing about what a picture shows, because a wrong guess here costs somebody
a memory they cannot get back. The reason is always carried through to the UI
so the person deciding can see why the machine raised its hand.
"""

import argparse
import hashlib
import json
import os
import re
import struct
import sys
from collections import defaultdict

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".gif", ".bmp",
             ".tif", ".tiff", ".webp", ".avif"}
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".avi", ".3gp", ".mkv", ".webm", ".mpg",
             ".mpeg", ".wmv"}
MEDIA_EXT = IMAGE_EXT | VIDEO_EXT

# Filesystem and sync-client droppings. Counted, never shown for review.
NOISE = {".ds_store", "thumbs.db", "desktop.ini", "icon\r", ".dropbox",
         ".dropbox.attr", ".localized"}

# Filename patterns from apps that rename what they save. These are
# machine-generated names that essentially never belong to a photo somebody
# framed and took, so the pattern alone is a fair reason to raise the file.
# Each entry is (category, detail, pattern-on-the-filename-stem).
NAME_RULES = [
    ("messaging", "WhatsApp",   re.compile(r"^(IMG|VID|AUD|PTT)-\d{8}-WA\d+", re.I)),
    ("screenshot", "",          re.compile(r"^screen[ _-]?shot|^screenshot", re.I)),
    ("messaging", "Facebook",   re.compile(r"^FB_IMG|^facebook", re.I)),
    ("messaging", "Snapchat",   re.compile(r"^snapchat", re.I)),
    ("messaging", "Instagram",  re.compile(r"^instagram|^insta_", re.I)),
    ("messaging", "Messenger",  re.compile(r"^received_|^messenger", re.I)),
    ("messaging", "Viber",      re.compile(r"^viber_", re.I)),
    ("messaging", "Telegram",   re.compile(r"^telegram", re.I)),
    ("web", "download",         re.compile(r"^(download|unnamed|untitled|image)[ _-]?\(?\d*\)?$", re.I)),
    ("web", "timestamp name",   re.compile(r"^\d{9,}$")),      # e.g. 1234567890.jpg
    ("web", "sticker",          re.compile(r"^sticker|^AnimatedSticker", re.I)),
]

TINY_BYTES = 50 * 1024          # thumbnails, avatars, icons
SMALL_BYTES = 150 * 1024        # small enough to be worth a second look

# Exact pixel dimensions of phone and tablet screens, orientation-independent.
# A screenshot is always the screen's exact size; a camera photo essentially
# never is. Cameras also do not produce PNG, so PNG plus an exact screen size
# is about as strong as a filesystem-level signal gets.
#
# This list will age. Add sizes as new devices appear - a missing size means a
# screenshot goes unflagged, which is the harmless direction to fail in.
_SCREENS = [
    # iPhone
    (320, 480), (640, 960), (640, 1136), (750, 1334), (828, 1792),
    (1080, 1920), (1125, 2436), (1170, 2532), (1179, 2556), (1206, 2622),
    (1242, 2208), (1242, 2688), (1284, 2778), (1290, 2796), (1320, 2868),
    # iPad
    (768, 1024), (1536, 2048), (1620, 2160), (1640, 2360), (1668, 2224),
    (1668, 2388), (2048, 2732),
    # common Android
    (720, 1280), (1440, 2560), (1080, 2340), (1080, 2400), (1440, 3040),
    (1440, 3200), (1080, 2160), (1440, 2960),
]
SCREEN_SIZES = {tuple(sorted(s)) for s in _SCREENS}

# Marks a file as the derived copy rather than the original, used only to pick
# which member of a duplicate group survives. Deliberately narrow: a trailing
# "_1234" is a camera counter (DSC_0431), not a copy marker, and treating it as
# one would flag every original in the archive. Several languages, because
# "copy" is whatever the person's operating system called it.
COPYISH = re.compile(r"\(\d+\)$|\(copy\)|[ _-]copy$|^copy[ _-]of|"
                     r"copia|kopie|kopia|kopi|עותק", re.I)

# Categories that always get reviewed one at a time, whatever their size.
# Large files need the video player and each decision is worth real space;
# duplicates need you to see which twin is being kept.
ALWAYS_SWIPE = {"large", "duplicate"}

# Above this many files, a category is faster to review as a contact sheet than
# one card at a time. Set low deliberately: past roughly twenty, clicking
# through cards stops being looking and starts being clicking.
GRID_THRESHOLD = 20


def human(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}"
        n /= 1024


def png_dimensions(path):
    """Width and height from a PNG's IHDR header - 24 bytes read, no decoding.

    The IHDR chunk always sits immediately after the 8-byte signature, with
    width and height as big-endian uint32. Cheap enough to run over every PNG
    in a large archive without anyone noticing.
    """
    try:
        with open(path, "rb") as fh:
            head = fh.read(24)
    except OSError:
        return None
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return struct.unpack(">II", head[16:24])


def sha256(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            b = fh.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def walk(root, skip_names):
    for dirpath, dirnames, filenames in os.walk(root):
        # never re-offer files that are already waiting to be deleted, and skip
        # the resource-fork folder some archivers leave behind
        dirnames[:] = [d for d in dirnames
                       if not d.startswith("_pending-deletion") and d != "__MACOSX"]
        for name in filenames:
            if name in skip_names and os.path.dirname(os.path.join(dirpath, name)) == root:
                continue
            yield os.path.join(dirpath, name)


def find_duplicates(root, files, by_size):
    """Flag every member of an exact-duplicate group except one survivor.

    Hashing a whole archive would be wasteful, and unnecessary: two files can
    only be identical if their byte counts match exactly. Grouping by size
    first cuts the hashing down to the few percent of files that could
    possibly collide.
    """
    groups = 0
    for size, idxs in by_size.items():
        if len(idxs) < 2 or size == 0:
            continue
        by_hash = defaultdict(list)
        for i in idxs:
            try:
                by_hash[sha256(os.path.join(root, files[i]["rel"]))].append(i)
            except OSError:
                pass
        for group in by_hash.values():
            if len(group) < 2:
                continue
            groups += 1

            # Which twin survives? Never by path length - a descriptive folder
            # name is long, and ranking by length would flag the original and
            # keep the stray copy. Rank by: not copy-named, then oldest (the
            # original existed first), then shallowest, then path for a stable
            # result on ties.
            def rank(i):
                stem = os.path.splitext(os.path.basename(files[i]["rel"]))[0]
                return (bool(COPYISH.search(stem)),
                        files[i]["mtime"],
                        files[i]["rel"].count(os.sep),
                        files[i]["rel"])

            group.sort(key=rank)
            keeper = files[group[0]]["rel"]
            for i in group[1:]:
                files[i]["reasons"].append({"k": "duplicate", "d": keeper})
                files[i]["cat"] = "duplicate"
                files[i]["dupe_of"] = keeper
    return groups


def scan(root, big_video, big_image, skip_names=()):
    files, junk, by_size = [], [], defaultdict(list)

    for path in walk(root, set(skip_names)):
        name = os.path.basename(path)
        ext = os.path.splitext(name)[1].lower()

        if name.lower() in NOISE:
            junk.append(path)
            continue
        try:
            size = os.path.getsize(path)
        except OSError:
            continue
        if ext not in MEDIA_EXT:
            junk.append(path)
            continue

        files.append({
            "rel": os.path.relpath(path, root).replace(os.sep, "/"),
            "size": size,
            "mtime": int(os.path.getmtime(path)),
            "kind": "video" if ext in VIDEO_EXT else "image",
            "reasons": [],
        })
        by_size[size].append(len(files) - 1)

    dupe_groups = find_duplicates(root, files, by_size)

    for f in files:
        full = os.path.join(root, f["rel"])
        stem = os.path.splitext(os.path.basename(f["rel"]))[0]

        for cat, detail, rx in NAME_RULES:
            if rx.search(stem):
                f["reasons"].append({"k": cat, "d": detail})
                f.setdefault("cat", cat)
                break

        # Screenshots by exact dimensions. This is the rule that earns its
        # keep: export tools often rename everything to a plain timestamp, and
        # once the original filename is gone, pixel size is the only evidence
        # left that a file came off a screen rather than a lens.
        if f["rel"].lower().endswith(".png"):
            dims = png_dimensions(full)
            if dims and tuple(sorted(dims)) in SCREEN_SIZES:
                f["reasons"].append({"k": "screenshot", "d": f"{dims[0]}x{dims[1]}"})
                f.setdefault("cat", "screenshot")

        # Large files. Video is usually a few percent of an archive's files and
        # most of its bytes, so reviewing these first means the space freed
        # drops off fastest at the start and the person can stop early.
        if f["kind"] == "video" and f["size"] >= big_video:
            f["reasons"].append({"k": "large_video", "d": human(f["size"])})
            f.setdefault("cat", "large")
        elif f["kind"] == "image" and f["size"] >= big_image:
            f["reasons"].append({"k": "large_image", "d": human(f["size"])})
            f.setdefault("cat", "large")

        if f["size"] < TINY_BYTES:
            f["reasons"].append({"k": "tiny", "d": human(f["size"])})
            f.setdefault("cat", "tiny")
        elif f["size"] < SMALL_BYTES and f["kind"] == "image":
            f["reasons"].append({"k": "small", "d": human(f["size"])})
            f.setdefault("cat", "small")

    candidates = [f for f in files if f["reasons"]]
    # Group by category so one kind of judgement is made at a time, and inside
    # the large group put the biggest first.
    candidates.sort(key=lambda f: (f["cat"],
                                   -f["size"] if f["cat"] == "large" else 0,
                                   f["rel"]))
    return files, candidates, junk, dupe_groups


def percentiles(sizes):
    s = sorted(sizes)
    if not s:
        return {}
    at = lambda p: s[min(len(s) - 1, int(len(s) * p / 100))]
    return {"n": len(s), "p50": at(50), "p90": at(90), "p99": at(99), "max": s[-1]}


def report(files, candidates, junk, dupe_groups):
    total = sum(f["size"] for f in files)
    cand_bytes = sum(f["size"] for f in candidates)
    pct = 100 * cand_bytes / total if total else 0

    print(f"\n  media files : {len(files):>7}   {human(total)}")
    print(f"  candidates  : {len(candidates):>7}   {human(cand_bytes)}   ({pct:.1f}% of archive)")
    print(f"  dupe groups : {dupe_groups:>7}")
    print(f"  non-media   : {len(junk):>7}")

    print("\n  size distribution:")
    for kind in ("image", "video"):
        p = percentiles([f["size"] for f in files if f["kind"] == kind])
        if p:
            print(f"    {kind:<6} n={p['n']:<6} median={human(p['p50']):>9}"
                  f"  p90={human(p['p90']):>9}  p99={human(p['p99']):>9}"
                  f"  max={human(p['max']):>9}")

    agg = defaultdict(lambda: [0, 0])
    for f in candidates:
        agg[f["cat"]][0] += 1
        agg[f["cat"]][1] += f["size"]
    if agg:
        print("\n  candidates by category:")
        for cat, (n, b) in sorted(agg.items(), key=lambda kv: -kv[1][1]):
            print(f"    {n:>6}   {human(b):>9}   {cat}")
    return agg


def build_page(template, out, candidates, agg):
    cats = [{"key": cat, "count": n, "bytes": b,
             "mode": "swipe" if cat in ALWAYS_SWIPE or n <= GRID_THRESHOLD else "grid"}
            for cat, (n, b) in sorted(agg.items(), key=lambda kv: -kv[1][1])]

    with open(template, encoding="utf-8") as fh:
        html = fh.read()
    payload = json.dumps({"categories": cats, "items": candidates}, ensure_ascii=False)
    if "/*__DATA__*/null" not in html:
        sys.exit(f"template has no data placeholder: {template}")
    os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(html.replace("/*__DATA__*/null", payload))


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    default_tpl = os.path.normpath(os.path.join(here, "..", "assets", "review.html"))

    ap = argparse.ArgumentParser(
        description="Inventory a photo archive and flag deletion candidates. Reads only.")
    ap.add_argument("archive", help="folder to scan")
    ap.add_argument("--big-video", type=float, default=100, metavar="MB",
                    help="flag videos at or above this size (default: 100)")
    ap.add_argument("--big-image", type=float, default=8, metavar="MB",
                    help="flag images at or above this size (default: 8)")
    ap.add_argument("--out", metavar="PATH",
                    help="where to write the review page (default: <archive>/review.html)")
    ap.add_argument("--template", default=default_tpl, metavar="PATH",
                    help="review page template")
    ap.add_argument("--stats-only", action="store_true",
                    help="print the inventory and stop, writing nothing")
    args = ap.parse_args()

    root = os.path.abspath(os.path.expanduser(args.archive))
    if not os.path.isdir(root):
        sys.exit(f"not a directory: {root}")

    out = os.path.abspath(os.path.expanduser(args.out)) if args.out \
        else os.path.join(root, "review.html")

    print(f"scanning {root} ...", file=sys.stderr)
    files, candidates, junk, dupe_groups = scan(
        root,
        int(args.big_video * 1024**2),
        int(args.big_image * 1024**2),
        skip_names={os.path.basename(out)})

    agg = report(files, candidates, junk, dupe_groups)

    if args.stats_only:
        print("\n  (stats only - nothing written)\n")
        return
    if not candidates:
        print("\n  nothing flagged - no review page written.\n")
        return

    build_page(args.template, out, candidates, agg)
    print(f"\n  -> {out}\n     open it in a browser to review.\n")


if __name__ == "__main__":
    main()
