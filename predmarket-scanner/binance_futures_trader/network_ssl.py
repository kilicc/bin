"""Binance REST/WS için tek SSL yapılandırması — certifi, TLS 1.2+."""
from __future__ import annotations

import os
import ssl
from functools import lru_cache


@lru_cache(maxsize=1)
def ca_bundle() -> str:
    path = (
        os.getenv("SSL_CERT_FILE")
        or os.getenv("REQUESTS_CA_BUNDLE")
        or ""
    ).strip()
    if path and os.path.isfile(path):
        return path
    try:
        import certifi

        return certifi.where()
    except ImportError:
        return ssl.get_default_verify_paths().cafile or ""


@lru_cache(maxsize=1)
def ssl_context() -> ssl.SSLContext:
    bundle = ca_bundle()
    if bundle:
        ctx = ssl.create_default_context(cafile=bundle)
    else:
        ctx = ssl.create_default_context()
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.check_hostname = True
    ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx


def httpx_verify() -> str | bool:
    bundle = ca_bundle()
    return bundle if bundle else True


def ws_sslopt() -> dict:
    return {"ssl_context": ssl_context()}


def apply_cert_env() -> None:
    """Process başında certifi yolunu ortam değişkenlerine yaz."""
    bundle = ca_bundle()
    if bundle:
        os.environ.setdefault("SSL_CERT_FILE", bundle)
        os.environ.setdefault("REQUESTS_CA_BUNDLE", bundle)
