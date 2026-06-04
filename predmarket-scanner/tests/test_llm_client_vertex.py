"""Vertex LLM client tests (mocked)."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from elite_trader.training_lab import llm_client


class VertexLlmClientTests(unittest.TestCase):
    def test_provider_vertex_dispatch(self) -> None:
        with patch.dict(
            "os.environ",
            {"LAB_LLM_PROVIDER": "vertex", "GCP_PROJECT": "test-proj", "LAB_LLM_MODEL": "gemini-2.5-flash"},
            clear=False,
        ):
            with patch.object(
                llm_client,
                "_vertex_chat",
                return_value={"ok": True, "provider": "vertex", "text": "hello from gemini", "model": "gemini-2.5-flash", "raw": {}},
            ):
                out = llm_client.chat([{"role": "user", "content": "ping"}])
            self.assertTrue(out.get("ok"))
            self.assertEqual(out.get("provider"), "vertex")
            self.assertIn("hello", out.get("text", ""))

    def test_ping_missing_gcp_project(self) -> None:
        with patch.dict("os.environ", {"LAB_LLM_PROVIDER": "vertex", "GCP_PROJECT": ""}, clear=False):
            out = llm_client.ping()
            self.assertFalse(out.get("ok"))
            self.assertIn("GCP_PROJECT", out.get("error", ""))

    def test_fallback_to_ollama(self) -> None:
        with patch.dict(
            "os.environ",
            {"LAB_LLM_PROVIDER": "vertex", "GCP_PROJECT": "", "LAB_LLM_FALLBACK": "ollama", "OLLAMA_HOST": "http://127.0.0.1:11434"},
            clear=False,
        ):
            with patch.object(llm_client, "_vertex_chat", side_effect=RuntimeError("no vertex")):
                with patch.object(
                    llm_client,
                    "_ollama_chat",
                    return_value={"ok": True, "provider": "ollama", "text": "pong", "raw": {}},
                ):
                    out = llm_client.chat([{"role": "user", "content": "ping"}])
            self.assertTrue(out.get("ok"))
            self.assertEqual(out.get("provider"), "ollama")


if __name__ == "__main__":
    unittest.main()
