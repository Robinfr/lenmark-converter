"""Validate reviewed release assets before uploading them to PyPI."""

import argparse
from email.parser import BytesParser
from pathlib import Path
import re
import runpy
import tarfile
import zipfile


def check_metadata(data, expected_version, label):
    metadata = BytesParser().parsebytes(data)
    for field, expected in (("Name", "lenmark-converter"), ("Version", expected_version)):
        values = metadata.get_all(field, [])
        if field == "Name":
            values = [re.sub(r"[-_.]+", "-", value).lower() for value in values]
        if values != [expected]:
            raise ValueError(f"{label}: {field} must be {expected!r}")


def check_release(directory, tag):
    if not re.fullmatch(r"v[0-9][A-Za-z0-9.]*", tag):
        raise ValueError("Release tag must be v followed by the exact package version")
    version = tag[1:]
    stem = f"lenmark_converter-{version}"
    wheel = f"{stem}-py3-none-any.whl"
    source = f"{stem}.tar.gz"
    directory = Path(directory)
    if {path.name for path in directory.iterdir()} != {wheel, source}:
        raise ValueError(f"Release must contain exactly {wheel} and {source}")
    with zipfile.ZipFile(directory / wheel) as archive:
        metadata_path = f"{stem}.dist-info/METADATA"
        if archive.namelist().count(metadata_path) != 1:
            raise ValueError("Wheel must have exactly one matching METADATA record")
        check_metadata(archive.read(metadata_path), version, wheel)
    with (directory / source).open("rb") as stream:
        header = stream.read(10)
    if len(header) != 10 or header[3] != 0 or header[4:8] != bytes(4):
        raise ValueError("Source archive must have anonymous gzip headers and timestamps")
    with tarfile.open(directory / source, "r:gz") as archive:
        metadata = []
        for member in archive:
            if not (member.isfile() or member.isdir()):
                raise ValueError(f"Unsupported source archive member: {member.name}")
            if (member.uid, member.gid, member.uname, member.gname, member.mtime) != (0, 0, "", "", 0):
                raise ValueError("Source archive must have anonymous ownership/time metadata")
            if set(member.pax_headers) & {"atime", "ctime"}:
                raise ValueError("Source archive contains local timestamps")
            if member.name == f"{stem}/PKG-INFO":
                with archive.extractfile(member) as stream:
                    metadata.append(stream.read())
        if len(metadata) != 1:
            raise ValueError("Source archive must have exactly one matching PKG-INFO record")
        check_metadata(metadata[0], version, source)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", help="Release tag; defaults to the project's __version__ for local checks")
    parser.add_argument("--dist", default=Path("dist"), type=Path)
    args = parser.parse_args()
    tag = args.tag
    if tag is None:
        project = Path(__file__).resolve().parents[1] / "lenmark_converter" / "__init__.py"
        tag = "v" + runpy.run_path(str(project))["__version__"]
    try:
        check_release(args.dist, tag)
    except (ValueError, OSError, KeyError, tarfile.TarError, zipfile.BadZipFile) as exc:
        parser.exit(1, f"Release validation failed: {exc}\n")
    print(f"Release assets match {tag}; source archive metadata is anonymous")


if __name__ == "__main__":
    main()
