"""Digest every input file and write a coreutils-style checksum manifest.

argv: <sha256|sha1|sha512|md5> <manifest path>

Every regular file in the working directory is hashed except the two this run
writes, so the caller names the inputs and nothing else has to be declared.
Entries are sorted by name: a manifest whose line order depended on the
filesystem would hash differently on two machines holding identical bytes.
"""

import hashlib
import json
import os
import sys

ALGORITHMS = ("sha256", "sha1", "sha512", "md5")


def finish(**fields: object) -> None:
    with open("result.json", "w", encoding="utf-8", newline="\n") as out:
        json.dump(fields, out, indent=2, sort_keys=True)
        out.write("\n")


def main() -> int:
    algorithm, manifest_path = sys.argv[1], sys.argv[2]
    if algorithm not in ALGORITHMS:
        print(f"algorithm must be one of {list(ALGORITHMS)}", file=sys.stderr)
        return 2
    skip = {manifest_path, "result.json"}
    files = []
    for name in sorted(os.listdir(".")):
        if name in skip or not os.path.isfile(name):
            continue
        with open(name, "rb") as handle:
            # file_digest streams in chunks: a manifest tool must not need the
            # largest input to fit in the sandbox's memory limit.
            files.append(
                {
                    "name": name,
                    "digest": hashlib.file_digest(handle, algorithm).hexdigest(),
                    "bytes": os.path.getsize(name),
                }
            )
    with open(manifest_path, "w", encoding="utf-8", newline="\n") as out:
        for entry in files:
            out.write(f"{entry['digest']}  {entry['name']}\n")
    finish(algorithm=algorithm, files=files, output=manifest_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
