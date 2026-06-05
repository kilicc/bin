"""
Canlı Polymarket paneli — yalnızca live.db + gerçek USDC bakiye.

    uvicorn live_dashboard:app --port 8002 --reload
    # veya: python live_dashboard.py
"""
from __future__ import annotations

import asyncio
import json
import math
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()

ROOT = Path(__file__).parent
STATIC = ROOT / "static"

try:
    import httpx

    _HTTPX = True
except ImportError:
    _HTTPX = False

import live_portfolio as lp
import live_wallet as lw

# dashboard fiyat zenginleştirme (paper.db'ye dokunmaz)
try:
    from dashboard import _enrich_snapshot, _dumps
except ImportError:
    def _dumps(obj: Any) -> str:
        return json.dumps(obj)

    async def _enrich_snapshot(snap: dict) -> dict:
        return snap


def _sanitize(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    return obj


def _snapshot() -> dict[str, Any]:
    portfolio = lp.read_live_portfolio()
    wallet = lw.fetch_wallet_snapshot()
    usdc = wallet.get("usdc")
    realized = portfolio["stats"].get("realized_pnl", 0.0)
    return _sanitize({
        "ts": datetime.utcnow().isoformat() + "Z",
        "mode": "LIVE",
        "wallet": wallet,
        "portfolio": portfolio,
        "summary": {
            "usdc_balance": usdc,
            "realized_pnl": realized,
            "open_trades": portfolio["stats"].get("open_trades", 0),
            "closed_trades": portfolio["stats"].get("closed_trades", 0),
            "max_position_usd": wallet.get("max_position_usd"),
            "exit_rule": portfolio.get("exit_rule", {}),
        },
    })


class _WsManager:
    def __init__(self) -> None:
        self.clients: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.clients.append(ws)

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self.clients:
            self.clients.remove(ws)

    async def broadcast(self, data: dict) -> None:
        if not self.clients:
            return
        txt = _dumps(data)
        dead: list[WebSocket] = []
        for ws in list(self.clients):
            try:
                await ws.send_text(txt)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


ws_mgr = _WsManager()


async def _push_loop(interval: int = 8) -> None:
    while True:
        await asyncio.sleep(interval)
        if not ws_mgr.clients:
            continue
        try:
            loop = asyncio.get_running_loop()
            snap = await loop.run_in_executor(None, _snapshot)
            snap = await _enrich_snapshot(snap)
            await ws_mgr.broadcast(snap)
        except Exception as exc:
            print(f"[live_dashboard] push: {exc}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(_push_loop())
    yield


app = FastAPI(title="PredMarket Live", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


@app.get("/", response_class=HTMLResponse)
async def index():
    p = STATIC / "live.html"
    return p.read_text(encoding="utf-8") if p.exists() else "<h1>static/live.html eksik</h1>"


@app.get("/api/live")
async def api_live():
    loop = asyncio.get_running_loop()
    snap = await loop.run_in_executor(None, _snapshot)
    return await _enrich_snapshot(snap)


@app.websocket("/ws")
async def ws_live(ws: WebSocket):
    await ws_mgr.connect(ws)
    try:
        loop = asyncio.get_running_loop()
        snap = await loop.run_in_executor(None, _snapshot)
        snap = await _enrich_snapshot(snap)
        await ws.send_text(_dumps(snap))
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        ws_mgr.disconnect(ws)


if __name__ == "__main__":
    import uvicorn

    port = int(__import__("os").getenv("LIVE_DASHBOARD_PORT", "8002"))
    uvicorn.run("live_dashboard:app", host="0.0.0.0", port=port, reload=True)
