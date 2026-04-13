from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest import mock

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in os.sys.path:
    os.sys.path.insert(0, str(SRC))

from lidguard import config as config_module
from lidguard import platform_macos


class MacOSHotspotTests(unittest.TestCase):
    def test_hotspot_failover_reason_on_disconnect(self) -> None:
        status = platform_macos.NetworkStatus(
            associated=False,
            ssid="",
            ip_address="",
            internet_reachable=None,
        )
        reason = platform_macos.hotspot_failover_reason(
            status=status,
            target_ssid="Phone",
            reachability_failures=0,
            failure_threshold=2,
        )
        self.assertEqual(reason, "Wi-Fi is disconnected")

    def test_hotspot_failover_reason_after_reachability_failures(self) -> None:
        status = platform_macos.NetworkStatus(
            associated=True,
            ssid="Office",
            ip_address="192.168.1.10",
            internet_reachable=False,
        )
        reason = platform_macos.hotspot_failover_reason(
            status=status,
            target_ssid="Phone",
            reachability_failures=2,
            failure_threshold=2,
        )
        self.assertEqual(reason, "internet reachability check failed")

    def test_current_network_status_skips_internet_check_when_disabled(self) -> None:
        config = config_module.default_config()
        config["hotspot"]["internet_check_enabled"] = False
        with mock.patch("lidguard.platform_macos.current_wifi_ssid", return_value="Office"), mock.patch(
            "lidguard.platform_macos.current_ip_address",
            return_value="192.168.1.10",
        ), mock.patch("lidguard.platform_macos.internet_reachable") as reachable_mock:
            status = platform_macos.current_network_status(config)

        self.assertTrue(status.associated)
        self.assertIsNone(status.internet_reachable)
        reachable_mock.assert_not_called()

    def test_force_check_connects_on_lid_close_without_failover_monitor(self) -> None:
        config = config_module.default_config()
        config["hotspot"]["enabled"] = True
        config["hotspot"]["ssid"] = "Phone"
        config["hotspot"]["force_on_network_loss"] = False
        monitor = platform_macos.HotspotRecoveryMonitor(config)
        monitor.set_active(True)
        status = platform_macos.NetworkStatus(
            associated=True,
            ssid="Office",
            ip_address="192.168.1.10",
            internet_reachable=True,
        )

        with mock.patch("lidguard.platform_macos.current_network_status", return_value=status), mock.patch(
            "lidguard.platform_macos.maybe_connect_hotspot",
            return_value=True,
        ) as connect_mock:
            monitor.force_check("lid closed")

        connect_mock.assert_called_once_with(
            config,
            reason="lid closed",
            force_reconnect=False,
        )
