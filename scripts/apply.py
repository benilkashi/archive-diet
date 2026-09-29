#!/usr/bin/env python3
"""
apply.py - act on the decisions made in the review page.

    python3 apply.py <archive> <decisions.json>            # dry run
    python3 apply.py <archive> <decisions.json> --apply    # move them
    python3 apply.py <archive> --undo _pending-deletion_20260101-1200
    python3 apply.py <archive> --list

Nothing is deleted. Approved files are MOVED into a timestamped
_pending-deletion_* folder inside the archive, keeping their original folder
structure, with a log that makes the move reversible.

The last step is not automated on purpose. Somebody has to look at that folder
and drag it to the bin themselves, once the archive has reached wherever it is
going and been verified there. An irreversible step belongs to a person, not to
a script - and having it sit there, visible and browsable, is what makes the
rest of this safe to run.

Guard rails:
  * dry run unless --apply is passed
  * only paths named in the decisions file are touched
  * any path resolving outside the archive is refused outright
  * a file already missing is reported, never guessed at
  * an existing file is never overwritten on the way back
"""

import argparse
import json
import os
import shutil
import sys
from datetime import datetime

PREFIX = "_pending-deletion_"
LOG = "moved-files.tsv"


def human(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}"
        n /= 1024


def safe_join(root, rel):
    """Resolve rel under root, refusing anything that climbs out.

    A decisions file is just JSON on disk; it could have been edited, or come
    from somewhere else entirely. Nothing outside the archive gets moved.
    """
    p = os.path.realpath(os.path.join(root, rel))
    if p != root and not p.startswith(root + os.sep):
        raise ValueError(f"path escapes the archive: {rel}")
    return p


def holding_folders(root):
    return sorted(d for d in os.listdir(root)
                  if d.startswith(PREFIX) and os.path.isdir(os.path.join(root, d)))


def do_list(root):
    folders = holding_folders(root)
    if not folders:
        print("no pending-deletion folders in this archive.")
        return
    for d in folders:
        full = os.path.join(root, d)
        files = [os.path.join(dp, f) for dp, _, fs in os.walk(full)
                 for f in fs if f != LOG]
        size = sum(os.path.getsize(f) for f in files)
        print(f"{d}   {len(files)} files   {human(size)}")
    print("\nnothing here is deleted. remove a folder yourself when you are sure.")


def do_apply(root, decisions_path, live):
    with open(decisions_path, encoding="utf-8") as fh:
        doc = json.load(fh)
    entries = doc.get("delete", [])
    if not entries:
        print("the decisions file marks nothing for deletion. nothing to do.")
        return

    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    hold = os.path.join(root, PREFIX + stamp)

    planned, missing, total = [], [], 0
    for e in entries:
        rel = e["rel"]
        try:
            src = safe_join(root, rel)
        except ValueError as err:
            sys.exit(f"REFUSED: {err}")
        if not os.path.isfile(src):
            missing.append(rel)
            continue
        planned.append((rel, src, os.path.join(hold, rel)))
        total += os.path.getsize(src)

    print(f"archive   : {root}")
    print(f"decisions : {decisions_path}")
    print(f"to move   : {len(planned)} files, {human(total)}")
    if missing:
        print(f"not found : {len(missing)}  (already moved, or renamed since the scan)")
        for rel in missing[:10]:
            print(f"            {rel}")

    if not live:
        print("\n-- DRY RUN. nothing moved. --")
        for rel, _, _ in planned[:20]:
            print(f"   would move  {rel}")
        if len(planned) > 20:
            print(f"   ... and {len(planned) - 20} more")
        print(f"\nrerun with --apply to move them into {PREFIX}{stamp}/")
        return

    os.makedirs(hold, exist_ok=True)
    moved = 0
    with open(os.path.join(hold, LOG), "w", encoding="utf-8") as log:
        log.write("original_relative_path\n")
        for rel, src, dst in planned:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.move(src, dst)
            log.write(rel + "\n")
            moved += 1

    print(f"\nmoved {moved} files ({human(total)}) into {PREFIX}{stamp}/")
    print("the archive is slimmer. every one of those files is still on disk.")
    print(f"\nto reverse : python3 apply.py <archive> --undo {PREFIX}{stamp}")
    print("to finish  : delete that folder yourself, after the archive is "
          "safely at its destination and verified there.")


def do_undo(root, name):
    hold = os.path.join(root, os.path.basename(name))
    logp = os.path.join(hold, LOG)
    if not os.path.isfile(logp):
        sys.exit(f"no log found at {logp}")

    restored, blocked = 0, []
    with open(logp, encoding="utf-8") as fh:
        next(fh, None)
        for line in fh:
            rel = line.rstrip("\n")
            if not rel:
                continue
            src = os.path.join(hold, rel)
            dst = safe_join(root, rel)
            if not os.path.isfile(src):
                continue
            if os.path.exists(dst):
                blocked.append(rel)          # something is there now; leave both alone
                continue
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.move(src, dst)
            restored += 1

    print(f"restored {restored} files")
    if blocked:
        print(f"skipped {len(blocked)} - a file already exists at the destination:")
        for rel in blocked[:10]:
            print(f"   {rel}")
        print(f"\nthose are still in {os.path.basename(hold)}/")
    else:
        shutil.rmtree(hold, ignore_errors=True)
        print(f"removed the now-empty {os.path.basename(hold)}/")


def main():
    ap = argparse.ArgumentParser(
        description="Move approved files out of an archive into a reversible holding folder.")
    ap.add_argument("archive", help="the archive folder")
    ap.add_argument("decisions", nargs="?", help="decisions.json exported from the review page")
    ap.add_argument("--apply", action="store_true", help="actually move the files")
    ap.add_argument("--undo", metavar="FOLDER", help="restore everything from a holding folder")
    ap.add_argument("--list", action="store_true", help="show holding folders in this archive")
    args = ap.parse_args()

    root = os.path.realpath(os.path.expanduser(args.archive))
    if not os.path.isdir(root):
        sys.exit(f"not a directory: {root}")

    if args.list:
        do_list(root)
    elif args.undo:
        do_undo(root, args.undo)
    elif args.decisions:
        do_apply(root, os.path.expanduser(args.decisions), args.apply)
    else:
        ap.error("give a decisions file, or --undo FOLDER, or --list")


if __name__ == "__main__":
    main()
