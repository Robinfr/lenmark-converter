import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from lenmark_converter.batch import Job, convert_job, plan
from lenmark_converter.__main__ import main


FIXTURE = Path(__file__).parent / "fixtures" / "rectangle.emd"


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "orders" / "1048" / "glass.emd"
        self.source.parent.mkdir(parents=True)
        self.source.write_bytes(FIXTURE.read_bytes())
        self.output = self.root / "converted"

    def test_recursive_batch_preserves_structure_and_deduplicates_sources(self):
        jobs = plan([self.root / "orders", self.source], self.output, recursive=True)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].destination, self.output / "1048" / "glass.emx")
        self.assertEqual(convert_job(jobs[0])["status"], "converted")
        self.assertEqual(self.source.read_bytes(), FIXTURE.read_bytes())

    def test_collisions_fail_before_writing(self):
        other = self.root / "elsewhere" / "glass.emd"
        other.parent.mkdir()
        other.write_bytes(FIXTURE.read_bytes())
        with self.assertRaisesRegex(ValueError, "collision"):
            plan([self.source, other], self.output)
        self.assertFalse(self.output.exists())

    def test_existing_output_survives_failed_overwrite(self):
        destination = self.root / "existing.emx"
        destination.write_bytes(b"keep existing result")
        self.source.write_bytes(b"invalid source")
        row = convert_job(Job(self.source, destination), overwrite=True)
        self.assertEqual(row["status"], "failed")
        self.assertEqual(destination.read_bytes(), b"keep existing result")
        self.assertFalse(list(self.root.glob(".lenmark-*")))

    def test_existing_destination_skipped_and_racing_writer_not_clobbered(self):
        destination = self.root / "existing.emx"
        destination.write_bytes(b"existing")
        self.assertEqual(convert_job(Job(self.source, destination))["status"], "skipped")
        destination.unlink()

        def concurrent_link(source, target):
            Path(target).write_bytes(b"other writer")
            raise FileExistsError("concurrent destination")

        with patch("lenmark_converter.batch.os.link", side_effect=concurrent_link):
            self.assertEqual(convert_job(Job(self.source, destination))["status"], "failed")
        self.assertEqual(destination.read_bytes(), b"other writer")

    def test_dry_run_checks_real_translation_without_output(self):
        job = plan([self.source], self.output)[0]
        row = convert_job(job, dry_run=True)
        self.assertEqual(row["status"], "validated")
        self.assertEqual(len(row["source_sha256"]), 64)
        self.assertEqual(len(row["output_sha256"]), 64)
        self.assertFalse(self.output.exists())

    def test_output_symlink_cannot_redirect_nested_writes(self):
        jobs = plan([self.root / "orders"], self.output, recursive=True)
        self.output.mkdir()
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        (self.output / "1048").symlink_to(elsewhere, target_is_directory=True)
        self.assertEqual(convert_job(jobs[0])["status"], "failed")
        self.assertFalse((elsewhere / "glass.emx").exists())

    def test_cli_continues_after_failure_and_reports_nonzero(self):
        broken = self.source.with_name("broken.emd")
        broken.write_bytes(b"bad version")
        report = self.root / "report.json"
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            status = main(["convert", str(self.source.parent), "-o", str(self.output), "--report", str(report)])
        self.assertEqual(status, 1)
        result = json.loads(report.read_text())
        self.assertEqual(result["summary"], {"failed": 1, "converted": 1})
        self.assertTrue((self.output / "glass.emx").exists())
        self.assertFalse((self.output / "broken.emx").exists())

    def test_cli_report_cannot_replace_source_or_output(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as failure:
            main(["convert", str(self.source), "-o", str(self.output), "--report", str(self.source)])
        self.assertEqual(failure.exception.code, 2)
        self.assertEqual(self.source.read_bytes(), FIXTURE.read_bytes())


if __name__ == "__main__":
    unittest.main()
