#!/usr/bin/env python3
"""Güvenli sistem paketi — API key / .env yok."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_BUNDLE = _ROOT / "docs" / "bundle"
_SECRET_KEYS = frozenset(
    {
        "api_key",
        "api_secret",
        "secret",
        "password",
        "token",
        "BINANCE_API_KEY",
        "BINANCE_API_SECRET",
    }
)


def _redact(obj: object) -> object:
    if isinstance(obj, dict):
        return {
            k: "***" if str(k).lower() in _SECRET_KEYS or "secret" in str(k).lower() else _redact(v)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_redact(x) for x in obj]
    return obj


def main() -> int:
    _BUNDLE.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    endpoints = [
        "GET /api/modes",
        "GET /api/status",
        "GET /api/modes/{id}/settings",
        "GET /api/modes/{id}/decisions",
        "GET /api/modes/{id}/metrics",
        "GET /api/logs/decisions",
        "GET /api/config/export",
    ]
    (_BUNDLE / "README.md").write_text(
        "# Binance Elite Pro — 5 Mod Bundle\n\n"
        f"Generated: {ts}\n\n## Endpoints\n\n"
        + "\n".join(f"- `{e}`" for e in endpoints)
        + "\n",
        encoding="utf-8",
    )

    cfg: dict = {"profiles": {}, "panel": {}}
    mp = _ROOT / "data" / "mode_profiles.json"
    ps = _ROOT / "data" / "panel_strategy_state.json"
    if mp.is_file():
        cfg["profiles"] = _redact(json.loads(mp.read_text(encoding="utf-8")))
    if ps.is_file():
        cfg["panel"] = _redact(json.loads(ps.read_text(encoding="utf-8")))
    (_BUNDLE / "config_export.json").write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    try:
        from elite_trader.data_lake.ingest import export_decisions_jsonl

        rows = export_decisions_jsonl(500)
        out = _BUNDLE / "sample_decisions_500.jsonl"
        with out.open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
    except Exception as exc:
        print(f"  ⚠ decisions export: {exc}")

    print(f"Bundle → {_BUNDLE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
