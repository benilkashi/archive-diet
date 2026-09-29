#!/usr/bin/env python3
"""
make_demo.py - build a synthetic photo archive to try the tool on.

    python3 make_demo.py ./demo-archive

Every file it writes is generated from scratch: coloured gradients standing in
for photographs, flat panels standing in for phone screenshots. No real image
is read, copied or needed.

Two reasons this exists.

First, documentation. Screenshots of a review interface are screenshots of
somebody's photo library, and a README is forever. Point the tool at a
generated archive and the pictures in your documentation are pictures of
nothing.

Second, trust. Anyone who finds this tool is about to let a script walk through
their family photos. Being able to run the whole workflow end to end on
throwaway data first - scan, review, quarantine, restore - is a fair thing to
want before that.

Written with the standard library alone, so it runs wherever Python does.
"""

import argparse
import os
import random
import struct
import zlib

# Real screen sizes, so the generated screenshots trip the same detector that
# real ones do. Keep in step with SCREEN_SIZES in scan.py.
SCREENS = [(750, 1334), (640, 1136), (1170, 2532), (1125, 2436),
           (1080, 1920), (768, 1024), (1536, 2048), (828, 1792)]

# Plausible camera dimensions that are deliberately NOT screen sizes, so the
# demo also exercises the "this one is a real photo, leave it alone" path.
# Note the absence of 2048x1536: that is a tablet screen with its axes swapped,
# and since the detector ignores orientation it would read as a screenshot.
# Real archives rarely hit this, because the rule only looks at PNG files and
# cameras write JPEG - but a demo should not manufacture a false positive.
CAMERA = [(3264, 2448), (4032, 3024), (2592, 1936), (1600, 1200), (2816, 2112)]


def write_png(path, width, height, rows):
    """Write an 8-bit RGB PNG. rows is an iterable of bytes, one per scanline."""
    def chunk(tag, data):
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xffffffff)

    raw = b"".join(b"\x00" + r for r in rows)
    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 6))
           + chunk(b"IEND", b""))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(png)


def photo_rows(w, h, rng):
    """A soft two-axis gradient with a little grain - compresses like a photo."""
    c0 = [rng.randint(20, 120) for _ in range(3)]
    c1 = [rng.randint(90, 240) for _ in range(3)]
    grain = rng.randint(2, 10)
    for y in range(h):
        fy = y / max(1, h - 1)
        row = bytearray(w * 3)
        for x in range(w):
            fx = x / max(1, w - 1)
            t = (fx + fy) / 2
            for c in range(3):
                v = int(c0[c] + (c1[c] - c0[c]) * t) + rng.randint(-grain, grain)
                row[x * 3 + c] = 0 if v < 0 else 255 if v > 255 else v
        yield bytes(row)


def screenshot_rows(w, h, rng):
    """A flat dark panel with a status bar and a grid of tiles - reads as UI."""
    bg = (18, 18, 24)
    tile = [rng.randint(40, 200) for _ in range(3)]
    bar_h = max(2, h // 40)
    cols, gap = 4, max(2, w // 40)
    cell = (w - gap * (cols + 1)) // cols
    for y in range(h):
        row = bytearray()
        if y < bar_h:
            row = bytearray(bytes((60, 60, 70)) * w)
        else:
            row = bytearray(bytes(bg) * w)
            gy = (y - bar_h - gap) % (cell + gap)
            inside_row = (y - bar_h - gap) >= 0 and gy < cell
            if inside_row:
                for c in range(cols):
                    x0 = gap + c * (cell + gap)
                    shade = [min(255, v + c * 12) for v in tile]
                    for x in range(x0, min(x0 + cell, w)):
                        row[x * 3:x * 3 + 3] = bytes(shade)
        yield bytes(row)


def stamp(year, month, day, hour, minute, second):
    return f"{year:04d}-{month:02d}-{day:02d} {hour:02d}.{minute:02d}.{second:02d}"


_SCREEN_PAIRS = {tuple(sorted(s)) for s in SCREENS}


def photo_size(rng):
    """Pick everyday photo dimensions that cannot read as a screen size.

    The detector ignores orientation, so a 4:3 photo can land on a tablet's
    resolution with its axes swapped. Rejecting those here keeps the demo
    honest: a false positive shown to someone evaluating the tool is worse
    than one they would rarely meet in their own archive.
    """
    while True:
        w = rng.choice([1600, 1280, 1152, 1440])
        h = rng.choice([1200, 960, 864, 1080])
        if tuple(sorted((w, h))) not in _SCREEN_PAIRS:
            return w, h


def main():
    ap = argparse.ArgumentParser(description="generate a synthetic photo archive")
    ap.add_argument("out", help="folder to create")
    ap.add_argument("--photos", type=int, default=24, help="camera-style photos (default 24)")
    ap.add_argument("--screenshots", type=int, default=30, help="screenshots (default 30)")
    ap.add_argument("--seed", type=int, default=7, help="random seed, for reproducible demos")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    out = os.path.abspath(os.path.expanduser(args.out))
    if os.path.exists(out) and os.listdir(out):
        raise SystemExit(f"refusing to write into a folder that already has files: {out}")

    made = []
    folders = ["Camera Uploads", "Camera Uploads/2015 Trip", "Camera Uploads/Family"]

    # --- photos, a couple of them deliberately huge ---
    for i in range(args.photos):
        big = i < max(1, args.photos // 8)
        w, h = rng.choice(CAMERA) if big else photo_size(rng)
        name = stamp(rng.randint(2011, 2017), rng.randint(1, 12), rng.randint(1, 28),
                     rng.randint(6, 23), rng.randint(0, 59), rng.randint(0, 59)) + ".png"
        path = os.path.join(out, rng.choice(folders), name)
        write_png(path, w, h, photo_rows(w, h, rng))
        made.append(path)

    # --- screenshots at exact screen sizes ---
    for _ in range(args.screenshots):
        w, h = rng.choice(SCREENS)
        name = stamp(rng.randint(2012, 2017), rng.randint(1, 12), rng.randint(1, 28),
                     rng.randint(6, 23), rng.randint(0, 59), rng.randint(0, 59)) + ".png"
        path = os.path.join(out, "Camera Uploads", name)
        write_png(path, w, h, screenshot_rows(w, h, rng))
        made.append(path)

    # --- exact duplicates: same bytes, one of them named like a copy ---
    for src in rng.sample([p for p in made if "Family" in p or "Trip" in p] or made, k=2):
        stem, ext = os.path.splitext(os.path.basename(src))
        dst = os.path.join(out, "Camera Uploads", f"{stem} (copy){ext}")
        with open(src, "rb") as a, open(dst, "wb") as b:
            b.write(a.read())
        made.append(dst)

    # --- thumbnail-sized leftovers ---
    for i in range(4):
        path = os.path.join(out, "Camera Uploads", f"thumb_{i}.png")
        write_png(path, 64, 64, photo_rows(64, 64, rng))
        made.append(path)

    # --- files named the way messaging apps name them ---
    for i in range(3):
        name = f"IMG-2016{rng.randint(10,12)}{rng.randint(10,28)}-WA000{i}.png"
        path = os.path.join(out, "Camera Uploads", name)
        write_png(path, 800, 600, photo_rows(800, 600, rng))
        made.append(path)

    total = sum(os.path.getsize(p) for p in made)
    print(f"\n  wrote {len(made)} files, {total / 1024**2:.1f} MB")
    print(f"  -> {out}\n")
    print("  next:")
    print(f"    python3 scripts/scan.py {args.out} --big-image 4")
    print("    then open the review page it prints.\n")
    print("  everything here is generated. delete the folder when you are done.\n")


if __name__ == "__main__":
    main()
