"""Deterministic batch planning and atomic, independently checked output."""

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import tempfile

from .project import convert_stream
from .verify import verify_file


@dataclass(frozen=True)
class Job:
    source: Path
    destination: Path
    output_root: Path | None = None


def plan(inputs, output, recursive=False):
    """Keep directory-relative paths; reject ambiguous destination collisions."""
    output = Path(output).expanduser().absolute()
    jobs, sources, destinations = [], set(), {}
    for argument in inputs:
        root = Path(argument).expanduser().absolute()
        if not root.exists():
            raise ValueError(f"Input does not exist: {root}")
        if root.is_dir():
            files = root.rglob("*") if recursive else root.iterdir()
            files = sorted(p for p in files if p.suffix.lower() == ".emd" and p.is_file())
        else:
            if root.suffix.lower() != ".emd":
                raise ValueError(f"Expected an .emd input: {root}")
            files = [root]
        for source in files:
            resolved = source.resolve()
            if resolved in sources:
                continue
            relative = source.relative_to(root) if root.is_dir() else Path(source.name)
            destination = output / relative.with_suffix(".emx")
            # File names are case-insensitive on common macOS/Windows setups.
            key = str(destination).casefold()
            if key in destinations:
                raise ValueError(f"Output collision: {source} and {destinations[key]} -> {destination}")
            destinations[key] = source
            sources.add(resolved)
            jobs.append(Job(source, destination, output))
    if not jobs:
        raise ValueError("No .emd files found (use --recursive for nested folders)")
    return jobs


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def convert_job(job, *, overwrite=False, dry_run=False):
    source, destination = job.source, job.destination
    row = {"source": str(source), "destination": str(destination)}
    temporary = None
    try:
        if destination.exists() and not overwrite and not dry_run:
            return {**row, "status": "skipped", "reason": "Destination already exists"}
        if destination.is_symlink():
            raise ValueError("Refusing a symbolic-link destination")
        if job.output_root is not None and not destination.resolve().is_relative_to(job.output_root.resolve()):
            raise ValueError("Destination escapes the output folder through a symbolic link")
        if source.resolve() == destination.resolve():
            raise ValueError("Source and destination refer to the same file")
        if not dry_run:
            destination.parent.mkdir(parents=True, exist_ok=True)
        directory = None if dry_run else destination.parent
        with tempfile.NamedTemporaryFile(prefix=".lenmark-", suffix=".emx", dir=directory, delete=False) as target:
            temporary = Path(target.name)
            with source.open("rb") as stream:
                stats = convert_stream(stream, target)
        verified = verify_file(temporary)
        # This reader is independent of the EMD translator. Check every stored
        # coordinate, traversal order and record count before publishing.
        check_keys = {"coordinate_sha256", "points", "polylines", "bezier_nodes", "fills", "entities", "top_level_objects"}
        check_keys.update(key for key in stats if key.startswith("type_"))
        if "bitmap_bmp_sha256" in stats:
            check_keys.update({"bitmap_bmp_sha256", "bitmap_images", "bitmap_bytes", "bitmap_pixels", "raster_pixels"})
        for key in sorted(check_keys):
            if stats.get(key, 0) != verified.get(key, 0):
                raise ValueError(f"Output verification mismatch for {key}: {stats.get(key)} != {verified.get(key)}")
        row.update(stats)
        row["verification"] = {key: verified[key] for key in ("validation", "toolpaths_sha256")}
        row.update(source_sha256=sha256_file(source), output_sha256=sha256_file(temporary), output_bytes=temporary.stat().st_size)
        if not dry_run:
            if overwrite:
                os.replace(temporary, destination)
            else:
                # Atomic no-clobber publication, including races after the
                # initial exists() check. Temporary file lives on this volume.
                os.link(temporary, destination)
            row["status"] = "converted"
        else:
            row["status"] = "validated"
    except (ValueError, OSError, RecursionError) as exc:
        row.update(status="failed", reason=str(exc))
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return row


def write_report(path, report):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", prefix=".lenmark-report-", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(report, stream, indent=2, ensure_ascii=True)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
