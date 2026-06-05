"""Admin settings schema depends_on and preview."""
from __future__ import annotations

import unittest

from elite_trader import admin_settings as adm


class AdminSettingsTests(unittest.TestCase):
    def test_schema_has_depends_on(self) -> None:
        schema = adm.build_schema()
        env_fields = [f for f in schema["fields"] if f.get("scope") == "env"]
        self.assertTrue(env_fields)
        with_deps = [f for f in env_fields if f.get("depends_on")]
        self.assertTrue(with_deps)

    def test_preview_diff(self) -> None:
        values = adm.get_values()
        key = next(iter(values.get("runtime_env") or {}), None)
        if not key:
            self.skipTest("no env keys")
        cur = values["runtime_env"][key]
        prev = adm.preview_settings({key: cur})
        self.assertTrue(prev.get("ok"))
        self.assertEqual(prev.get("diff"), [])

    def test_impact_depends_chain(self) -> None:
        imp = adm.get_impact("ELITE_MIN_STAKE_USD")
        self.assertIn("depends_on", imp)


if __name__ == "__main__":
    unittest.main()
