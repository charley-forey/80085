"""Extract a zip or tar archive, refusing anything that escapes the destination.

argv: <archive> <destination directory>

An archive is the classic hostile input. Every entry is checked before a byte
is written, and a refused entry is reported rather than silently skipped:

  * absolute paths and `..` components  -- zip slip / tar slip;
  * symlinks, hardlinks, devices, fifos -- a link is a write primitive
    pointing wherever the archive says, so only regular files are extracted;
  * a resolved destination outside the target directory, checked again after
    joining, because the first two rules are necessary and not sufficient;
  * a total-bytes and entry-count ceiling -- a zip bomb declares a small
    archive and expands forever, so the reader is capped as it streams rather
    than trusted to declare its size honestly.
"""

import json
import os
import sys
import tarfile
import zipfile
from pathlib import PurePosixPath
from typing import IO

MAX_ENTRIES = 10_000
MAX_TOTAL_BYTES = 64 * 1024 * 1024
CHUNK = 64 * 1024


def finish(**fields: object) -> None:
    with open("result.json", "w", encoding="utf-8", newline="\n") as out:
        json.dump(fields, out, indent=2, sort_keys=True)
        out.write("\n")


def rejection(name: str, kind: str) -> str | None:
    """Why this entry must not be written, or None if it is safe."""
    if kind != "file":
        return f"unsupported entry type: {kind}"
    if not name or name.endswith("/"):
        return "empty name"
    if name.startswith(("/", "\\")) or ":" in name.split("/")[0]:
        return "absolute path"
    parts = PurePosixPath(name.replace("\\", "/")).parts
    if ".." in parts:
        return "parent traversal"
    return None


def destination(root: str, name: str) -> str | None:
    """Resolved path inside `root`, or None if it lands outside it."""
    target = os.path.realpath(os.path.join(root, name))
    if os.path.commonpath([target, root]) != root:
        return None
    return target


def write(handle: IO[bytes], target: str, budget: int) -> int:
    """Stream one entry to disk, stopping at `budget` bytes. Returns bytes written."""
    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
    written = 0
    with open(target, "wb") as out:
        while True:
            chunk = handle.read(min(CHUNK, budget - written + 1))
            if not chunk:
                return written
            written += len(chunk)
            if written > budget:
                raise ValueError("archive exceeds the extraction budget")
            out.write(chunk)


def entries(archive: str) -> tuple[str, list[tuple[str, str]]]:
    """(format, [(name, kind)]) without extracting anything."""
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as zf:
            return "zip", [
                (info.filename, "directory" if info.is_dir() else "file") for info in zf.infolist()
            ]
    with tarfile.open(archive) as tf:
        kinds = []
        for member in tf.getmembers():
            if member.isfile():
                kind = "file"
            elif member.isdir():
                kind = "directory"
            elif member.issym() or member.islnk():
                kind = "link"
            else:
                kind = "special"
            kinds.append((member.name, kind))
        return "tar", kinds


def main() -> int:
    archive, root = sys.argv[1], sys.argv[2]
    os.makedirs(root, exist_ok=True)
    root = os.path.realpath(root)
    try:
        archive_format, listing = entries(archive)
    except (tarfile.TarError, zipfile.BadZipFile, OSError) as exc:
        print(f"unreadable archive: {exc}", file=sys.stderr)
        return 2
    if len(listing) > MAX_ENTRIES:
        print(f"archive declares {len(listing)} entries, limit is {MAX_ENTRIES}", file=sys.stderr)
        return 2

    extracted: list[dict[str, object]] = []
    refused: list[dict[str, str]] = []
    directories = 0
    total = 0
    if archive_format == "zip":
        opener: zipfile.ZipFile | tarfile.TarFile = zipfile.ZipFile(archive)
    else:
        opener = tarfile.open(archive)  # noqa: SIM115 - closed by the with below
    with opener as container:
        for name, kind in listing:
            # Directory entries carry no data and the parents are created on
            # demand, so they are neither extracted nor a refusal.
            if kind == "directory":
                directories += 1
                continue
            reason = rejection(name, kind)
            target = None if reason else destination(root, name)
            if target is None and reason is None:
                reason = "resolves outside the destination"
            if reason:
                refused.append({"name": name, "reason": reason})
                continue
            source = (
                container.open(name)
                if isinstance(container, zipfile.ZipFile)
                else container.extractfile(name)
            )
            if source is None:
                refused.append({"name": name, "reason": "unreadable entry"})
                continue
            with source:
                try:
                    written = write(source, str(target), MAX_TOTAL_BYTES - total)
                except ValueError as exc:
                    print(exc, file=sys.stderr)
                    return 2
            total += written
            extracted.append({"name": name, "bytes": written})

    extracted.sort(key=lambda entry: str(entry["name"]))
    refused.sort(key=lambda entry: entry["name"])
    finish(
        format=archive_format,
        destination=sys.argv[2],
        directories=directories,
        extracted=extracted,
        refused=refused,
        total_bytes=total,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
