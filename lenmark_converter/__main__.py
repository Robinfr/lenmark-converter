"""Run with python3 -m lenmark_converter."""

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from . import __version__
from .batch import convert_job, plan, write_report
from .verify import verify_file


def main(argv=None):
    parser = argparse.ArgumentParser(description="Experimental LenMark 3DS EMD 3.0 → EMX 3.7 batch converter")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)
    convert = sub.add_parser("convert", help="Convert one or more files/folders, preserving folder structure")
    convert.add_argument("inputs", nargs="+")
    convert.add_argument("-o", "--output", required=True, type=Path)
    convert.add_argument("-r", "--recursive", action="store_true")
    convert.add_argument("--overwrite", action="store_true", help="Replace existing destination files after successful validation")
    convert.add_argument("--dry-run", action="store_true", help="Translate and validate temporary outputs without publishing files")
    convert.add_argument("--report", type=Path, help="Write per-file results, checksums and errors as JSON")
    verify = sub.add_parser("verify", help="Independently parse an EMX file and show geometry statistics")
    verify.add_argument("file", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "verify":
            print(json.dumps(verify_file(args.file), indent=2))
            return 0
        jobs = plan(args.inputs, args.output, args.recursive)
        if args.report:
            report = args.report.expanduser().resolve()
            protected = {job.source.resolve() for job in jobs} | {job.destination.resolve() for job in jobs}
            if report in protected:
                raise ValueError("Report path must differ from every source and destination file")
        print("Experimental format translation; review a sample in LenMark before using the batch.", file=sys.stderr)
        rows = []
        for index, job in enumerate(jobs, 1):
            row = convert_job(job, overwrite=args.overwrite, dry_run=args.dry_run)
            rows.append(row)
            detail = f" — {row['reason']}" if "reason" in row else ""
            print(f"[{index}/{len(jobs)}] {row['status']}: {job.source}{detail}", flush=True)
        counts = Counter(row["status"] for row in rows)
        if args.report:
            write_report(args.report.expanduser(), {"converter_version": __version__, "created_at": datetime.now(timezone.utc).isoformat(), "summary": dict(counts), "files": rows})
        print(", ".join(f"{count} {status}" for status, count in sorted(counts.items())))
        return 1 if counts["failed"] else 0
    except (ValueError, OSError) as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
