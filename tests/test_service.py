from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in os.sys.path:
    os.sys.path.insert(0, str(SRC))

from lidguard import service


class ServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.home = Path(self.temp_dir.name) / "home"
        self.home.mkdir(parents=True, exist_ok=True)
        self.env = mock.patch.dict(
            os.environ,
            {"LID_GUARD_DATA_HOME": str(Path(self.temp_dir.name) / "data")},
            clear=False,
        )
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_install_service_writes_systemd_files_without_enabling(self) -> None:
        with mock.patch.object(service.sys, "platform", "linux"), mock.patch(
            "lidguard.service.Path.home",
            return_value=self.home,
        ):
            path = service.install_service(enable=False)

        self.assertEqual(path.name, "lid-guard.service")
        self.assertTrue(path.exists())
        self.assertIn("ExecStart=", path.read_text(encoding="utf-8"))

    def test_install_service_writes_launchd_files_without_enabling(self) -> None:
        with mock.patch.object(service.sys, "platform", "darwin"), mock.patch(
            "lidguard.service.Path.home",
            return_value=self.home,
        ):
            path = service.install_service(enable=False)

        self.assertEqual(path.name, "io.github.jasonlevigoodison.lid-guard.plist")
        self.assertTrue(path.exists())
        self.assertIn("RunAtLoad", path.read_text(encoding="utf-8"))

    def test_uninstall_service_removes_wrapper_and_unit(self) -> None:
        with mock.patch.object(service.sys, "platform", "linux"), mock.patch(
            "lidguard.service.Path.home",
            return_value=self.home,
        ):
            path = service.install_service(enable=False)
            removed = service.uninstall_service(disable=False)

        self.assertIn(path, removed)
        self.assertFalse(path.exists())

    def test_service_installed_checks_expected_location(self) -> None:
        with mock.patch.object(service.sys, "platform", "darwin"), mock.patch(
            "lidguard.service.Path.home",
            return_value=self.home,
        ):
            self.assertFalse(service.service_installed())
            path = service.install_service(enable=False)
            self.assertEqual(service.service_file(), path)
            self.assertTrue(service.service_installed())

    def test_launch_command_uses_current_interpreter_for_pyz(self) -> None:
        archive = Path(self.temp_dir.name) / "lid-guard.pyz"
        archive.write_text("", encoding="utf-8")

        with mock.patch.object(service.sys, "argv", [str(archive)]), mock.patch.object(
            service.sys,
            "executable",
            "/opt/homebrew/bin/python3.11",
        ):
            command, pythonpath = service._launch_command()

        self.assertEqual(command, ["/opt/homebrew/bin/python3.11", str(archive.resolve()), "run"])
        self.assertIsNone(pythonpath)
