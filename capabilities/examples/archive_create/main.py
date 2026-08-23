"""Create a reproducible tar, tar.gz or zip from the working directory.

argv: <output> <tar|targz|zip> [names...]   (default: every regular file here)

Everything an archive normally records about the machine that built it is
zeroed: mtime, uid, gid, user and group names, and permission bits beyond a
fixed 0644. Two runs over identical bytes then produce an identical archive,
which is the only way an archive can be the subject of a digest.

The tar path is byte-reproducible anywhere. `targz` and `zip` compress, and
DEFLATE output depends on the zlib build the interpreter links -- pinning the
artifact by digest is what makes those two reproducible in practice.
"""

import gzip
import hashlib
import io
import json
import os
import sys
import tarfile
import zipfile

FIXED_MODE = 0o644
ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)  # the earliest a zip entry can express


def finish(**fields: object) -> None:
    with open("result.json", "w", encoding="utf-8", newline="\n") as out:
        json.dump(fields, out, indent=2, sort_keys=True)
        out.write("\n")


def digest(path: str) -> str:
    with open(path, "rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def member(name: str, size: int) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name=name)
    info.size = size
    info.mtime = 0
    info.mode = FIXED_MODE
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    return info


def write_tar(output: str, names: list[str], compress: bool) -> None:
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for name in names:
            with open(name, "rb") as handle:
                archive.addfile(member(name, os.path.getsize(name)), handle)
    body = raw.getvalue()
    with open(output, "wb") as out:
        if not compress:
            out.write(body)
            return
        # mtime=0 and an empty filename: gzip otherwise stamps the clock and
        # the source name into the header, which alone breaks reproducibility.
        with gzip.GzipFile(filename="", mode="wb", fileobj=out, mtime=0) as gz:
            gz.write(body)


def write_zip(output: str, names: list[str]) -> None:
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in names:
            info = zipfile.ZipInfo(filename=name, date_time=ZIP_EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = FIXED_MODE << 16
            with open(name, "rb") as handle:
                archive.writestr(info, handle.read())


def main() -> int:
    output, archive_format = sys.argv[1], sys.argv[2]
    if archive_format not in {"tar", "targz", "zip"}:
        print("format must be tar, targz or zip", file=sys.stderr)
        return 2
    skip = {output, "result.json"}
    names = sys.argv[3:] or [
        name for name in os.listdir(".") if name not in skip and os.path.isfile(name)
    ]
    # Sorted, because a filesystem's listing order is not a property of the
    # bytes being archived.
    names = sorted(names)
    missing = [name for name in names if not os.path.isfile(name)]
    if missing:
        print(f"not regular files: {missing}", file=sys.stderr)
        return 2

    if archive_format == "zip":
        write_zip(output, names)
    else:
        write_tar(output, names, compress=archive_format == "targz")
    finish(
        format=archive_format,
        entries=[{"name": name, "bytes": os.path.getsize(name)} for name in names],
        output=output,
        sha256=digest(output),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
