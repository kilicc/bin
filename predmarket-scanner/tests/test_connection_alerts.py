"""Panel bağlantı uyarıları — 9007 demo desk yanlış auth/paper filtreleri."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from elite_trader.connection_alerts import build_alerts


class ConnectionAlertsTests(unittest.TestCase):
    def _client(self, base: str = "https://demo-fapi.binance.com") -> MagicMock:
        mc = MagicMock()
        mc._api_base.return_value = base
        return mc

    def test_guard_pause_not_auth_critical(self) -> None:
        out = build_alerts(
            api_ok=True,
            api_paper=False,
            auth_error="REST paused (network guard)",
            client=self._client(),
            desk_id="9007",
        )
        codes = [a["code"] for a in out["alerts"]]
        self.assertNotIn("auth_error", codes)
        self.assertEqual(out["severity"], "ok")

    def test_signed_rest_disabled_not_auth_on_9007(self) -> None:
        out = build_alerts(
            api_ok=True,
            api_paper=False,
            auth_error="Signed REST disabled (paper port)",
            client=self._client(),
            desk_id="9007",
        )
        self.assertNotIn("auth_error", [a["code"] for a in out["alerts"]])

    def test_9007_skips_demo_endpoint_warn_when_live(self) -> None:
        out = build_alerts(
            api_ok=True,
            api_paper=False,
            auth_error=None,
            client=self._client(),
            desk_id="9007",
        )
        self.assertNotIn("demo_endpoint", [a["code"] for a in out["alerts"]])
        self.assertEqual(out["severity"], "ok")

    def test_9007_paper_message_is_recovery_not_mainnet(self) -> None:
        out = build_alerts(
            api_ok=False,
            api_paper=True,
            auth_error=None,
            client=self._client(),
            desk_id="9007",
        )
        paper = next(a for a in out["alerts"] if a["code"] == "paper_mode")
        self.assertIn("recovery", paper["detail"].lower())


if __name__ == "__main__":
    unittest.main()
