"""Check privacy and payload preservation of release archive normalization."""

import gzip
import io
from pathlib import Path
import struct
import tarfile
import tempfile
import unittest
import zipfile

from scripts.check_release import check_release
from scripts.normalize_sdist import normalize_archive


class ReleaseArchiveTests(unittest.TestCase):
    def test_normalization_removes_identity_and_preserves_payloads(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "release.tar.gz"
            name = "package/" + "long-" * 30 + ".emd"
            payload = b"generic binary fixture\x00\xff\r\n"
            with tarfile.open(path, "w:gz") as archive:
                member = tarfile.TarInfo(name)
                member.uid, member.gid = 1234, 5678
                member.uname, member.gname = "private-user", "private-group"
                member.mtime = 1234567890.5
                member.pax_headers = {"atime": "1234567891", "ctime": "1234567892"}
                member.size = len(payload)
                archive.addfile(member, io.BytesIO(payload))
            normalize_archive(path)
            normalized = path.read_bytes()
            self.assertEqual(normalized[3] & 8, 0, "Gzip retained an original filename")
            self.assertEqual(struct.unpack("<I", normalized[4:8])[0], 0)
            self.assertNotIn(b"private-user", gzip.decompress(normalized))
            self.assertNotIn(b"private-group", gzip.decompress(normalized))
            with tarfile.open(path, "r:gz") as archive:
                member = archive.getmember(name)
                self.assertEqual((member.uid, member.gid, member.uname, member.gname), (0, 0, "", ""))
                self.assertEqual(member.mtime, 0)
                self.assertNotIn("atime", member.pax_headers)
                self.assertNotIn("ctime", member.pax_headers)
                with archive.extractfile(member) as source:
                    self.assertEqual(source.read(), payload)
            normalize_archive(path)
            self.assertEqual(path.read_bytes(), normalized)

    def test_unsupported_member_does_not_replace_original(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "release.tar.gz"
            with tarfile.open(path, "w:gz") as archive:
                member = tarfile.TarInfo("package/link")
                member.type = tarfile.SYMTYPE
                member.linkname = "other-file"
                archive.addfile(member)
            original = path.read_bytes()
            with self.assertRaisesRegex(ValueError, "Unsupported source archive member"):
                normalize_archive(path)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(Path(directory).iterdir()), [path])


class ReleasePublicationTests(unittest.TestCase):
    def make_assets(self, directory, wheel_version="0.1.2", source_version="0.1.2", name="lenmark-converter", normalize=True):
        root = Path(directory)
        stem = "lenmark_converter-0.1.2"
        with zipfile.ZipFile(root / f"{stem}-py3-none-any.whl", "w") as wheel:
            wheel.writestr(f"{stem}.dist-info/METADATA", f"Name: {name}\nVersion: {wheel_version}\n")
        source = root / f"{stem}.tar.gz"
        payload = f"Name: lenmark-converter\nVersion: {source_version}\n".encode()
        with tarfile.open(source, "w:gz") as archive:
            member = tarfile.TarInfo(f"{stem}/PKG-INFO")
            member.size = len(payload)
            member.uid = 1234
            member.uname = "private-user"
            archive.addfile(member, io.BytesIO(payload))
        if normalize:
            normalize_archive(source)

    def test_matching_reviewed_assets_are_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            self.make_assets(directory)
            check_release(directory, "v0.1.2")

    def test_assets_for_a_different_tag_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            self.make_assets(directory)
            with self.assertRaisesRegex(ValueError, "Release must contain exactly"):
                check_release(directory, "v0.2.0")

    def test_wheel_and_source_metadata_must_match_tag(self):
        for option in ("wheel_version", "source_version"):
            with self.subTest(archive=option), tempfile.TemporaryDirectory() as directory:
                self.make_assets(directory, **{option: "0.2.0"})
                with self.assertRaisesRegex(ValueError, "Version must be"):
                    check_release(directory, "v0.1.2")

    def test_another_project_cannot_be_published(self):
        with tempfile.TemporaryDirectory() as directory:
            self.make_assets(directory, name="other-project")
            with self.assertRaisesRegex(ValueError, "Name must be"):
                check_release(directory, "v0.1.2")

    def test_missing_or_extra_assets_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            self.make_assets(directory)
            (Path(directory) / "unexpected.txt").write_text("extra")
            with self.assertRaisesRegex(ValueError, "Release must contain exactly"):
                check_release(directory, "v0.1.2")
            (Path(directory) / "unexpected.txt").unlink()
            (Path(directory) / "lenmark_converter-0.1.2.tar.gz").unlink()
            with self.assertRaisesRegex(ValueError, "Release must contain exactly"):
                check_release(directory, "v0.1.2")

    def test_identifying_archive_metadata_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            self.make_assets(directory, normalize=False)
            with self.assertRaisesRegex(ValueError, "anonymous gzip"):
                check_release(directory, "v0.1.2")
            # Remove only the gzip metadata, leaving the tar owner untouched.
            source = Path(directory) / "lenmark_converter-0.1.2.tar.gz"
            payload = gzip.decompress(source.read_bytes())
            with source.open("wb") as stream:
                with gzip.GzipFile(filename="", mode="wb", fileobj=stream, mtime=0) as compressed:
                    compressed.write(payload)
            with self.assertRaisesRegex(ValueError, "anonymous ownership"):
                check_release(directory, "v0.1.2")

    def test_gzip_comments_cannot_expose_local_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            self.make_assets(directory)
            source = Path(directory) / "lenmark_converter-0.1.2.tar.gz"
            raw = source.read_bytes()
            commented = raw[:3] + bytes([raw[3] | 16]) + raw[4:10] + b"private-builder-account\0" + raw[10:]
            self.assertEqual(gzip.decompress(commented), gzip.decompress(raw))
            source.write_bytes(commented)
            with self.assertRaisesRegex(ValueError, "anonymous gzip"):
                check_release(directory, "v0.1.2")


if __name__ == "__main__":
    unittest.main()
