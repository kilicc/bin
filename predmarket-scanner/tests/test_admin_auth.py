"""Admin auth tests."""
from __future__ import annotations

import unittest

from elite_trader.admin_auth import create_session, session_valid, verify_password


class AdminAuthTests(unittest.TestCase):
    def test_default_password(self):
        self.assertTrue(verify_password("x369"))
        self.assertFalse(verify_password("wrong"))

    def test_session_roundtrip(self):
        tok = create_session()
        self.assertTrue(session_valid(tok))
        self.assertFalse(session_valid("invalid-token"))


if __name__ == "__main__":
    unittest.main()
