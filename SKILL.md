---
name: archive-diet
description: Move a photo and video archive out of one cloud service into another, and strip the dead weight on the way out - screenshots, exact duplicates, oversized videos, thumbnail leftovers - through a local review page where the person approves every single deletion themselves. Use this whenever someone wants to migrate photos between cloud services, cancel a second or duplicate cloud subscription, export a photo library and clean it up, shrink a photo backup before uploading it somewhere, or has a ZIP export of photos they want to sort through. Also reach for it when they mention paying for two clouds at once, running out of space in a photo archive, or wanting to leave a storage service without losing anything.
---

# archive-diet

Someone is leaving a cloud service and taking their photos with them. The
archive is usually irreplaceable and usually part junk, and those two facts
pull in opposite directions: they want it smaller, and they cannot afford a
mistake.

The whole design follows from that tension. The tooling narrows thousands of
files down to a few hundred worth looking at; the person decides; nothing is
ever deleted, only moved somewhere they can see it; and the old service stays
paid for until the new copy has been counted and verified. The expensive,
irreversible step - cancelling, emptying - is theirs to take last.

## Rules that do not bend

These exist because the failure mode here is somebody losing a photo of a
relative who has died. Treat them as load-bearing.

- **Never delete a file.** Not with `rm`, not to the system bin, not "obviously
  junk" ones. `apply.py` moves approved files into a visible holding folder and
  stops there. The person empties it themselves, at the end.
- **Never mark files on their behalf.** Flagging a candidate is the tool's job;
  approving it is not. Do not pre-select, do not "helpfully" accept a whole
  category for them, do not run `apply.py --apply` against decisions they have
  not seen.
- **Nothing leaves the machine.** The review page is a local file that reads
  images off disk. Never upload an archive, a sample, or a file listing
  anywhere - not to inspect it, not to a transfer service. A file listing alone
  is personal data: names, dates, places.
- **The source stays alive until the destination is verified.** Do not let them
  cancel a subscription, empty a holding folder, or delete the downloaded
  archive before counts have been compared. Say so plainly if they are about to.
- **Verify by counting, never by looking.** "It seems done" has no place here.
  Every stage has a number that should match the stage before it.

## The order of work

Each step ends with something checkable. Do not carry an unverified result
forward.

1. Export the archive from the source service.
2. Extract it locally, and verify the extraction.
3. Scan it, and look at the shape of what came back.
4. Let them review candidates in the local page.
5. Move only what they approved into the holding folder.
6. Move the slimmed archive to the destination.
7. Verify it arrived.
8. Only then: they empty the holding folder and cancel the old service.

## 1. Getting the archive out

Most services can hand over a ZIP of everything. **Try that before installing
anything** - people assume large archives need a sync client, and a single
export is simpler, has no background process, and leaves nothing behind. Limits
are usually higher than expected; a refusal is instant and costs nothing to
discover, so test it rather than predicting it.

If the export is refused, the cap is as often on **file count** as on size -
splitting the download by folder can succeed where one big request failed. A
desktop sync client is the fallback, not the starting point.

Three things worth checking with them before exporting:

- **A "Photos" section in a service is usually a filtered view across the whole
  account, not a folder.** Exporting from it can silently skip formats the
  filter excludes, and files under its size floor. Export from the full file
  list instead. This one genuinely loses data and is easy to miss.
- **The service's trash.** If anything was deleted recently it may still be
  recoverable, and it will not show up in any export. Worth a look before the
  account goes away.
- **Anything that is not a file.** Collaborative documents, notes and similar
  live in the account but do not come down as usable files. Rare in a photo
  archive, but it disappears quietly when a subscription lapses.

## 2. Extract and verify

Large archives use an extended ZIP format that not every extractor handles, and
the ugly failure is not a clean error - **some tools extract happily for a while
and then stop partway, leaving a folder that looks entirely plausible.** If an
extraction fails or looks short, try a different extractor before suspecting the
archive.

This is why the verification is not optional:

```
# compare against what the archive itself declares
python3 -c "import zipfile,sys; z=zipfile.ZipFile(sys.argv[1]); f=[i for i in z.infolist() if not i.is_dir()]; print(len(f),'files', sum(i.file_size for i in f),'bytes')" ARCHIVE.zip
```

Then count what actually landed on disk, and compare both the file count and the
byte total. Both should match exactly. A count that matches while bytes do not
means a truncated file somewhere.

Reading the archive's index first is also the cheapest way to answer "did I
export everything?" - it lists every folder without extracting anything.

**Expect timestamps to be wrong.** Export tools routinely stamp every file with
the moment the export was built rather than the original date. Filenames and
embedded EXIF usually survive intact, so the dates are not lost - but if the
destination builds a timeline from file modification dates, everything will land
on today. Mention this before choosing a destination, not after.

## 3. Scan

```
python3 scripts/scan.py ARCHIVE_DIR --stats-only
```

Reads only. Prints the inventory, the size distribution, and how many files fall
into each category. **Look at this before deciding anything**, because the shape
of an archive determines where the person's time is worth spending, and it is
rarely where they expect.

The usual shape: video is a few percent of the files and most of the bytes.
Reviewing a few dozen large videos can free a third of an archive, while
thousands of screenshots are a fifth of the files and almost none of the space.
Say which is which out loud - it changes what they choose to do.

Then generate the review page:

```
python3 scripts/scan.py ARCHIVE_DIR --big-video 100 --big-image 8
```

Tune the thresholds from the distribution the stats pass printed, rather than
leaving the defaults. `--big-video 50` on an archive whose median video is 30 MB
flags most of them; on one whose median is 200 MB it flags nothing useful.

**How files get flagged.** Every rule is a fact about the file, never a guess
about what the picture shows - a wrong guess costs somebody a memory:

- *screenshots*, by exact pixel dimensions matching a known screen size. This is
  the rule that earns its keep, because export tools often rename everything to
  a plain timestamp and then pixel size is the only evidence left.
- *exact duplicates*, by hash, comparing only files of identical byte length so
  the hashing stays cheap. One copy of each group survives.
- *large files*, above the thresholds, sorted biggest first.
- *thumbnail-sized files*, tiny leftovers that are never photographs.
- *app-named files*, filename patterns from messaging apps and web downloads.

## 4. Review

The scan writes a self-contained page into the archive folder. Opening it
directly usually works; if images do not appear, a browser is refusing local
file access, and a throwaway local server fixes it:

```
cd ARCHIVE_DIR && python3 -m http.server 8790 --bind 127.0.0.1
```

Bound to the loopback address, serving their own files to their own browser,
stopped with Ctrl-C. Nothing is exposed.

The page groups candidates by category and picks a mode per category: one at a
time where each decision is expensive and needs a proper look, a contact sheet
where there are too many for that to be honest. It has an English/Hebrew toggle.

Tell them they can stop after any category. The first one is worth the most, and
finishing is not the goal - the goal is a smaller archive they still trust.

When they are done, the page downloads a `decisions.json`. It contains only what
they explicitly marked.

## 5. Apply

```
python3 scripts/apply.py ARCHIVE_DIR decisions.json           # dry run
python3 scripts/apply.py ARCHIVE_DIR decisions.json --apply   # move
python3 scripts/apply.py ARCHIVE_DIR --undo FOLDER_NAME       # reverse
python3 scripts/apply.py ARCHIVE_DIR --list                   # what is waiting
```

Dry run first, always, and show them the summary before running it for real.
Files move into `_pending-deletion_<timestamp>/` inside the archive, keeping
their folder structure, with a log that makes `--undo` exact.

Moving within one filesystem is instant regardless of size, because nothing is
copied - only a directory entry changes. Worth saying if someone expects a
20 GB operation to take a while and wonders whether it really happened.

Then count: files remaining plus files in the holding folder should equal what
you started with.

**Suggest they look through the holding folder before the archive moves on.** A
mistake found now is one command away from being fixed; found later, the undo
path is tangled.

## 6. Move to the destination, and verify

Exclude the holding folder and the generated review page - neither belongs in
the destination. Move the archive content itself.

If the destination is a synced cloud folder, the move is where behaviour
changes: from that moment deletions propagate, and a mistake is no longer local.
Say so before doing it, not after.

**Uploading thousands of small files is slower than downloading the same bytes
as one file**, often by a lot - connections are asymmetric, and each file is a
separate transaction. If they are surprised by the estimate, measure the actual
throughput for a minute or two and extrapolate rather than guessing; a real
number ends the conversation.

Then verify: count files at the destination against the count after the move.
Same number, or stop and find out why.

## 7. Only now

Once the counts match, they can empty the holding folder and cancel the old
service. In that order, deliberately, and by their own hand.

Worth raising while it is still relevant: after the source is gone, how many
copies do they actually have? A synced cloud folder is one copy that happens to
exist in several places - deleting a file deletes it everywhere. If the archive
matters, this is the moment to talk about a second copy that does not sync.

## Trying it safely

```
python3 scripts/make_demo.py ./demo-archive
python3 scripts/scan.py ./demo-archive --big-image 4
```

Generates a synthetic archive - coloured gradients and flat panels, no real
images anywhere - with screenshots at genuine screen dimensions, duplicates,
oversized files and thumbnails, so every category populates. Use it to walk the
whole workflow before touching anything real, and for any screenshot that ends
up in documentation. A screenshot of this tool is a screenshot of somebody's
photo library; generated data is the only kind safe to publish.
