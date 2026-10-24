"""Exercise an installed distribution outside its source checkout."""

import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    fixture = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "rectangle.emd"
    executable = Path(sys.executable).parent / (
        "lenmark-converter.exe" if os.name == "nt" else "lenmark-converter"
    )
    module = [sys.executable, "-m", "lenmark_converter"]
    installed_version = version("lenmark-converter")
    with tempfile.TemporaryDirectory(prefix="lenmark-install-") as directory:
        root = Path(directory)

        def run(command):
            result = subprocess.run(command, cwd=root, capture_output=True, text=True)
            if result.returncode:
                raise RuntimeError(f"Command failed: {command}\n{result.stdout}\n{result.stderr}")
            return result.stdout

        assert run([str(executable), "--version"]).strip() == installed_version
        assert run(module + ["--version"]).strip() == installed_version
        assert "convert" in run([str(executable), "--help"])
        source = root / "example design.emd"
        source.write_bytes(fixture.read_bytes())
        original = hashlib.sha256(source.read_bytes()).hexdigest()
        dry_output = root / "dry-run"
        run(module + ["convert", str(source), "--output", str(dry_output), "--dry-run"])
        assert not dry_output.exists(), "Dry run published output"
        output = root / "converted"
        report = root / "report.json"
        run([str(executable), "convert", str(source), "--output", str(output), "--report", str(report)])
        row = json.loads(report.read_text())["files"][0]
        assert row["status"] == "converted"
        assert row["source_sha256"] == original
        verified = json.loads(run(module + ["verify", str(output / "example design.emx")]))
        assert verified["coordinate_sha256"] == row["coordinate_sha256"]
        assert hashlib.sha256(source.read_bytes()).hexdigest() == original, "Source changed"
    print(f"Installed package checks passed ({installed_version})")


if __name__ == "__main__":
    main()
