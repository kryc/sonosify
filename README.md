# sonosify

Build and maintain a Sonos-friendly copy of a music library by normalizing
artist tags, so albums group correctly in the Sonos app.

Sonos groups tracks into albums using the `artist` / `albumartist` tags in ways
that fragment compilations and multi-artist albums. `sonosify` produces a
separate destination library where those tags are rewritten so each album stays
together, while preserving the original per-track artist inside the title.

## How it works

For every audio file under the source directory, `sonosify` maps it to
`destination/<artist>/<album>/<filename>` (derived from the last two directory
levels of the source path) and writes it using one of three strategies:

- **Simple album** — no `albumartist`, or `albumartist == artist`:
  the file is **hard-linked** into the destination (no extra disk space, no tag
  changes).
- **Multi-artist album** — `albumartist` differs from `artist`:
  the file is copied, the original artist is appended to the title
  (`Title [Artist]`), and `artist` is set to `albumartist` so the album groups
  under one artist.
- **Compilation** — the source path contains a `Compilations` directory:
  the file is copied, the original artist is appended to the title
  (`Title [Artist]`), and `artist` is set to `Compilation`.

The source library is only ever read — it is never modified. (Hard-linked files
share an inode with the source, which increases the source file's link count but
never changes its content, size, or modification time.)

## Incremental sync

`sonosify` is idempotent and can be re-run over an existing destination. On each
run it:

- **Adds** files that are new in the source.
- **Re-processes** files whose source has changed (detected by comparing
  modification times).
- **Skips** files that are already up to date.
- **Deletes** destination files whose source no longer exists, and prunes any
  directories left empty.

Change detection is stateless — no manifest or database is kept. Every
destination file is stamped with its source's modification time (hard links
inherit it automatically; copies have it restored after tag rewriting), so an
unchanged mtime means the destination is current.

> The destination is treated as fully owned by `sonosify`: any file there that
> does not correspond to a current source file will be deleted. Do not point the
> destination at a directory containing files you want to keep, and do not nest
> the destination inside the source.

## Requirements

- Python 3
- [`mutagen`](https://mutagen.readthedocs.io/)

```sh
pip install mutagen
```

Hard-linking requires the source and destination to be on the **same
filesystem**.

## Usage

```sh
python3 sonosify.py <source> <destination> [--filter ext1,ext2,...]
```

- `source` — root of the existing music library to read from.
- `destination` — root of the Sonos-friendly library to create/update.
- `--filter` — comma-separated list of file extensions to process
  (default: `m4a`).

### Example

```sh
python3 sonosify.py ~/Music/Library /srv/sonos/Library
python3 sonosify.py ~/Music/Library /srv/sonos/Library --filter m4a,mp3,flac
```

## Output

At the end of each run a summary is printed:

```
[+] New:     12
[+] Updated: 3
[+] Skipped: 480
[+] Deleted: 5
[+] Links:   470
[+] Errors:  0
```

- **New** — files created for the first time.
- **Updated** — files rebuilt because the source changed.
- **Skipped** — files already up to date.
- **Deleted** — destination files removed because their source is gone.
- **Links** — files hard-linked (rather than copied) this run.
- **Errors** — files that could not be processed (e.g. unreadable or missing
  required tags); these are reported inline and skipped.

## Notes and limitations

- The destination path is derived from the last two directory levels of each
  source file (`.../Artist/Album/Track.ext`); a flatter source layout may not
  map as expected.
- Two source files that map to the same `Artist/Album/Filename` destination will
  collide; only one can occupy that path.
