"""Remove local account metadata from source distributions before release."""

import argparse
import copy
import gzip
import os
from pathlib import Path
import tarfile
import tempfile


def normalize_archive(path):
    """Keep file payloads while neutralizing ownership and archive headers."""
    path = Path(path)
    temporary = None
    try:
        with tarfile.open(path, "r:gz") as source:
            with tempfile.NamedTemporaryFile(prefix=".sdist-", dir=path.parent, delete=False) as stream:
                temporary = Path(stream.name)
                with gzip.GzipFile(filename="", mode="wb", fileobj=stream, mtime=0) as compressed:
                    with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as target:
                        for original in source:
                            if not (original.isfile() or original.isdir()):
                                raise ValueError(f"Unsupported source archive member: {original.name}")
                            member = copy.copy(original)
                            member.uid = member.gid = 0
                            member.uname = member.gname = ""
                            member.mtime = 0
                            member.pax_headers = {}
                            member.mode = 0o755 if member.isdir() or original.mode & 0o111 else 0o644
                            if original.isfile():
                                with source.extractfile(original) as payload:
                                    target.addfile(member, payload)
                            else:
                                target.addfile(member)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archives", nargs="*", type=Path)
    args = parser.parse_args()
    archives = args.archives or sorted(Path("dist").glob("*.tar.gz"))
    if not archives:
        parser.error("No source archives found in dist/")
    for archive in archives:
        normalize_archive(archive)
        print(f"Normalized release metadata: {archive}")


if __name__ == "__main__":
    main()
