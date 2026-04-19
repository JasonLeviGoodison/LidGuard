from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

import build_backend


class BuildBackendTests(unittest.TestCase):
    def test_prepare_metadata_for_build_wheel_writes_dist_info(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            dist_info = build_backend.prepare_metadata_for_build_wheel(tmpdir)
            metadata_dir = Path(tmpdir) / dist_info

            self.assertTrue((metadata_dir / "METADATA").exists())
            self.assertTrue((metadata_dir / "WHEEL").exists())
            self.assertTrue((metadata_dir / "entry_points.txt").exists())
            self.assertIn("Name: lid-guard", (metadata_dir / "METADATA").read_text())

    def test_build_wheel_packages_sources_and_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as metadata_dir, tempfile.TemporaryDirectory() as wheel_dir:
            build_backend.prepare_metadata_for_build_wheel(metadata_dir)
            wheel_name = build_backend.build_wheel(
                wheel_dir, metadata_directory=metadata_dir
            )

            self.assertTrue(wheel_name.endswith("py3-none-any.whl"))

            wheel_path = Path(wheel_dir) / wheel_name
            with zipfile.ZipFile(wheel_path) as archive:
                members = set(archive.namelist())

                self.assertIn("lidguard/__init__.py", members)
                self.assertIn("lidguard/cli.py", members)
                self.assertFalse(any("__pycache__" in member for member in members))

                dist_info = f"{build_backend._dist_info_dir()}/METADATA"
                self.assertIn(dist_info, members)
                self.assertIn(
                    f"{build_backend._dist_info_dir()}/entry_points.txt", members
                )
                self.assertIn(f"{build_backend._dist_info_dir()}/RECORD", members)
