"""Portable build checks that do not require a Windows machine or network."""
import hashlib
import importlib.util
import io
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("wopr_build", ROOT / "windows" / "build_windows.py")
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


class PackagingTests(unittest.TestCase):
    def test_source_pins_are_https_and_sha256(self):
        for url, digest in build.SOURCES.values():
            self.assertTrue(url.startswith("https://codeload.github.com/"))
            self.assertEqual(len(digest), 64)
            int(digest, 16)

    def test_cached_source_must_match_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "source.tar.gz").write_bytes(b"tampered")
            with mock.patch.dict(build.SOURCES, {"source.tar.gz": ("https://example.invalid/", "0" * 64)}):
                with self.assertRaisesRegex(RuntimeError, "SHA-256 mismatch"):
                    build.download_verified("source.tar.gz", path)

    def test_verified_cache_needs_no_network(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            data = b"verified-source"
            (path / "source.tar.gz").write_bytes(data)
            with mock.patch.dict(build.SOURCES, {"source.tar.gz": (
                "https://example.invalid/", hashlib.sha256(data).hexdigest()
            )}), mock.patch.object(build.urllib.request, "urlopen", side_effect=AssertionError("network")):
                self.assertEqual(build.download_verified("source.tar.gz", path).read_bytes(), data)

    def archive(self, folder, names):
        archive = Path(folder) / "source.tar.gz"
        with tarfile.open(archive, "w:gz") as stream:
            for name, data in names:
                member = tarfile.TarInfo(name)
                member.size = len(data)
                stream.addfile(member, io.BytesIO(data))
        return archive

    def test_extract_regular_source(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = self.archive(directory, [("source/file.c", b"int main(void) {}")])
            root = build.extract_source(archive, Path(directory) / "output")
            self.assertEqual((root / "file.c").read_bytes(), b"int main(void) {}")

    def test_reject_archive_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = self.archive(directory, [("source/../../escape", b"bad")])
            with self.assertRaisesRegex(RuntimeError, "Unsafe source archive path"):
                build.extract_source(archive, Path(directory) / "output")
            self.assertFalse((Path(directory) / "escape").exists())

    def test_launcher_does_not_bypass_policy(self):
        launcher = (ROOT / "Launch WOPR.cmd").read_text()
        powershell = (ROOT / "windows" / "Launch-WOPR.ps1").read_text()
        self.assertNotIn("-ExecutionPolicy Bypass", launcher + powershell)
        self.assertNotIn("Set-ExecutionPolicy", launcher + powershell)
        self.assertNotIn("RunAs", powershell)


if __name__ == "__main__":
    unittest.main()
