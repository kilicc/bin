"""LLM client — Vertex AI Gemini (GCP), OpenAI, Ollama fallback."""
from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from typing import Any

_TIMEOUT_SEC = 60.0


def _provider() -> str:
    return os.getenv("LAB_LLM_PROVIDER", "openai").strip().lower()


def _fallback() -> str:
    return os.getenv("LAB_LLM_FALLBACK", "ollama").strip().lower()


def _gcp_project() -> str:
    for key in ("GCP_PROJECT", "GOOGLE_CLOUD_PROJECT", "GCLOUD_PROJECT"):
        val = os.getenv(key, "").strip()
        if val:
            return val
    try:
        req = urllib.request.Request(
            "http://metadata.google.internal/computeMetadata/v1/project/project-id",
            headers={"Metadata-Flavor": "Google"},
        )
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            pid = resp.read().decode().strip()
            if pid:
                return pid
    except Exception:
        pass
    return ""


def gcp_project_resolved() -> str:
    """Ops panel — metadata dahil çözümlenmiş proje id."""
    return _gcp_project()


def _vertex_chat(messages: list[dict[str, str]], *, model: str | None = None) -> dict[str, Any]:
    project = _gcp_project()
    if not project:
        raise RuntimeError("GCP_PROJECT missing for vertex provider")
    region = os.getenv("GCP_REGION", "asia-northeast1").strip()
    mdl = model or os.getenv("LAB_LLM_MODEL", "gemini-2.5-flash")

    import vertexai
    from vertexai.generative_models import GenerativeModel

    vertexai.init(project=project, location=region)
    gen = GenerativeModel(mdl)

    system_parts: list[str] = []
    contents: list[str] = []
    for msg in messages:
        role = msg.get("role", "user")
        text = msg.get("content", "")
        if role == "system":
            system_parts.append(text)
        elif role == "assistant":
            contents.append(f"Assistant: {text}")
        else:
            contents.append(f"User: {text}")

    prompt = "\n".join(contents)
    if system_parts:
        prompt = "\n\n".join(system_parts) + "\n\n" + prompt

    resp = gen.generate_content(prompt, generation_config={"temperature": 0.4, "max_output_tokens": 2048})
    text = resp.text if resp.text else ""
    return {"ok": True, "provider": "vertex", "text": text, "model": mdl, "raw": {"candidates": len(getattr(resp, "candidates", []) or [])}}


def _openai_chat(messages: list[dict[str, str]], *, model: str | None = None) -> dict[str, Any]:
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("OPENAI_API_KEY missing")
    base = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1").rstrip("/")
    mdl = model or os.getenv("LAB_LLM_MODEL", "gpt-4o-mini")
    body = json.dumps({"model": mdl, "messages": messages, "temperature": 0.4}).encode()
    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=_TIMEOUT_SEC) as resp:
        data = json.loads(resp.read().decode())
    text = data["choices"][0]["message"]["content"]
    return {"ok": True, "provider": "openai", "text": text, "raw": data}


def _ollama_chat(messages: list[dict[str, str]], *, model: str | None = None) -> dict[str, Any]:
    base = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
    mdl = model or os.getenv("LAB_OLLAMA_MODEL", "llama3.2")
    prompt = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
    body = json.dumps({"model": mdl, "prompt": prompt, "stream": False}).encode()
    req = urllib.request.Request(
        f"{base}/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=_TIMEOUT_SEC) as resp:
        data = json.loads(resp.read().decode())
    return {"ok": True, "provider": "ollama", "text": data.get("response", ""), "raw": data}


def _dispatch_chat(provider: str, messages: list[dict[str, str]], *, model: str | None = None) -> dict[str, Any]:
    if provider == "ollama":
        return _ollama_chat(messages, model=model)
    if provider == "vertex":
        return _vertex_chat(messages, model=model)
    return _openai_chat(messages, model=model)


def chat(messages: list[dict[str, str]], *, model: str | None = None) -> dict[str, Any]:
    primary = _provider()
    order = [primary]
    fb = _fallback()
    if fb and fb != primary:
        order.append(fb)
    errors: list[str] = []
    for prov in order:
        try:
            return _dispatch_chat(prov, messages, model=model)
        except (urllib.error.URLError, urllib.error.HTTPError, RuntimeError, KeyError, ImportError, ValueError) as exc:
            errors.append(f"{prov}: {exc}")
    return {"ok": False, "error": "; ".join(errors) or "no provider"}


def ping() -> dict[str, Any]:
    """Non-blocking LLM availability check."""
    prov = _provider()
    if prov == "openai" and not os.getenv("OPENAI_API_KEY", "").strip():
        return {"ok": False, "provider": "openai", "error": "no key"}
    if prov == "vertex" and not _gcp_project():
        return {"ok": False, "provider": "vertex", "error": "GCP_PROJECT missing"}
    try:
        resp = chat([{"role": "user", "content": "ping"}], model=os.getenv("LAB_LLM_MODEL"))
        return {
            "ok": resp.get("ok", False),
            "provider": resp.get("provider"),
            "latency_hint": "ok" if resp.get("ok") else resp.get("error"),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def probe_provider(provider: str) -> dict[str, Any]:
    """Test a single LLM provider (ops monitor)."""
    import time as _time

    prov = (provider or "").strip().lower()
    if prov == "openai" and not os.getenv("OPENAI_API_KEY", "").strip():
        return {"ok": False, "provider": "openai", "error": "OPENAI_API_KEY missing"}
    if prov == "vertex" and not _gcp_project():
        return {"ok": False, "provider": "vertex", "error": "GCP_PROJECT missing"}
    if prov == "ollama":
        base = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
        t0 = _time.perf_counter()
        try:
            req = urllib.request.Request(f"{base}/api/tags")
            with urllib.request.urlopen(req, timeout=4) as resp:
                resp.read()
            return {
                "ok": True,
                "provider": "ollama",
                "latency_ms": round((_time.perf_counter() - t0) * 1000, 1),
            }
        except Exception as exc:
            return {
                "ok": False,
                "provider": "ollama",
                "error": str(exc),
                "latency_ms": round((_time.perf_counter() - t0) * 1000, 1),
            }
    t0 = _time.perf_counter()
    try:
        resp = _dispatch_chat(prov, [{"role": "user", "content": "ping"}], model=os.getenv("LAB_LLM_MODEL"))
        return {
            "ok": bool(resp.get("ok")),
            "provider": resp.get("provider", prov),
            "model": resp.get("model"),
            "latency_ms": round((_time.perf_counter() - t0) * 1000, 1),
            "error": resp.get("error"),
        }
    except Exception as exc:
        return {
            "ok": False,
            "provider": prov,
            "error": str(exc),
            "latency_ms": round((_time.perf_counter() - t0) * 1000, 1),
        }


def vision_chat(image_b64: str, prompt: str, *, mime: str = "image/png", model: str | None = None) -> dict[str, Any]:
    prov = _provider()
    if prov == "vertex" or (prov == "openai" and not os.getenv("OPENAI_API_KEY", "").strip() and _gcp_project()):
        return _vertex_vision_chat(image_b64, prompt, mime=mime, model=model)

    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        if _gcp_project():
            return _vertex_vision_chat(image_b64, prompt, mime=mime, model=model)
        return {"ok": False, "error": "vision unavailable — OPENAI_API_KEY missing"}
    base = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1").rstrip("/")
    mdl = model or os.getenv("LAB_VISION_MODEL", os.getenv("LAB_LLM_MODEL", "gpt-4o"))
    body = json.dumps(
        {
            "model": mdl,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_b64}"}},
                    ],
                }
            ],
            "max_tokens": 800,
        }
    ).encode()
    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_SEC) as resp:
            data = json.loads(resp.read().decode())
        text = data["choices"][0]["message"]["content"]
        return {"ok": True, "provider": "openai", "text": text, "model": mdl}
    except Exception as exc:
        if _gcp_project():
            return _vertex_vision_chat(image_b64, prompt, mime=mime, model=model)
        return {"ok": False, "error": f"vision unavailable: {exc}"}


def _vertex_vision_chat(image_b64: str, prompt: str, *, mime: str = "image/png", model: str | None = None) -> dict[str, Any]:
    project = _gcp_project()
    if not project:
        return {"ok": False, "error": "vision unavailable — GCP_PROJECT missing"}
    region = os.getenv("GCP_REGION", "asia-northeast1").strip()
    mdl = model or os.getenv("LAB_VISION_MODEL", os.getenv("LAB_LLM_MODEL", "gemini-2.5-pro"))

    import vertexai
    from vertexai.generative_models import GenerativeModel, Part

    vertexai.init(project=project, location=region)
    gen = GenerativeModel(mdl)
    image_bytes = base64.b64decode(image_b64)
    part = Part.from_data(image_bytes, mime_type=mime)
    resp = gen.generate_content([prompt, part], generation_config={"max_output_tokens": 800})
    text = resp.text if resp.text else ""
    return {"ok": True, "provider": "vertex", "text": text, "model": mdl}
