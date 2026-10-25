"""Gateway on a non-TabbyAPI server with the System One decider retired (operator 2026-09-26: ninfer serves
Qwen3.8-27B on :8080; AGENTS.md retires the decider). No network: HTTP and configuration are stubbed."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import v213_local_llm_gateway as gw  # noqa: E402

CONFIG = json.loads((ROOT / "config" / "local-runtime-independence-v1.json").read_text(encoding="utf-8-sig"))


class Response:
    def __init__(self, status, payload=None, text=None):
        self.status_code, self._payload = status, payload
        self.text = text if text is not None else json.dumps(payload)
        self.ok = 200 <= status < 300

    def json(self):
        return self._payload


class ConsultingDecider:
    def answer(self, state, question, options):
        raise AssertionError("a retired decider must not be consulted")


class RetiredDeciderGateTests(unittest.TestCase):
    def test_project_config_marks_the_decider_retired(self):
        self.assertIs(CONFIG["decision_router"]["retired"], True)

    def test_source_qualification_alone_decides_when_retired(self):
        with patch.object(gw, "_load_local_ai_config", return_value=CONFIG), patch.object(gw, "_DECIDER_CLIENT", ConsultingDecider()):
            allowed = gw._reasoner_decision_gate({"source_diversity_status": "PASS"}, "Qwen3.8-27B")
            unknown = gw._reasoner_decision_gate({}, "Qwen3.8-27B")
            denied = gw._reasoner_decision_gate({"source_diversity_status": "STALE"}, "Qwen3.8-27B")
            self.assertIsNone(gw._screen_client())
        self.assertTrue(allowed["allowed"] and unknown["allowed"])
        self.assertEqual(allowed["authority"], "source_qualification_decider_retired")
        self.assertEqual(gw._format_decision_annotation(allowed)["decider"], "RETIRED")
        self.assertFalse(denied["allowed"])
        self.assertEqual(denied["authority"], "source_qualification")

    def test_an_active_decider_is_still_required(self):
        active = json.loads(json.dumps(CONFIG))
        active["decision_router"]["retired"] = False

        class Down:
            def answer(self, state, question, options):
                raise gw.DeciderError("DECIDER_UPSTREAM_FAILED:503")
        with patch.object(gw, "_load_local_ai_config", return_value=active), patch.object(gw, "_DECIDER_CLIENT", Down()):
            gate = gw._reasoner_decision_gate({"source_diversity_status": "PASS"}, "m")
        self.assertEqual((gate["allowed"], gate["authority"]), (False, "decider_unavailable"))


class NonTabbyServerTests(unittest.TestCase):
    ROWS = [{"id": "Qwen3.8-27B", "max_model_len": 262144, "object": "model"}, {"id": "other", "max_model_len": "big"}]

    def test_served_context_from_the_models_row_when_there_is_no_model_card(self):
        with patch.object(gw, "local_llm_base_url", return_value="http://127.0.0.1:8080"), \
                patch.object(gw, "_loopback_http", return_value=Response(404, {"error": "not found"})), \
                patch.object(gw, "_available_model_catalog", return_value=self.ROWS), \
                patch.dict("os.environ", {"II_CAPABILITY_METADATA_URL": ""}):
            self.assertEqual(gw.capability_context_evidence("qwen3.8-27b"), 262144)
            self.assertIsNone(gw.capability_context_evidence("other"))  # a non-integer length is no evidence
            self.assertIsNone(gw.capability_context_evidence("absent"))
        with patch.object(gw, "local_llm_base_url", return_value="http://127.0.0.1:8080"), \
                patch.object(gw, "_loopback_http", return_value=Response(500, {})), \
                patch.object(gw, "_available_model_catalog", return_value=self.ROWS):
            self.assertIsNone(gw.capability_context_evidence("Qwen3.8-27B"))  # only a missing card falls back

    def test_json_capability_without_constrained_decoding(self):
        refusal = Response(400, {"error": {"code": "response_format_not_supported"}})
        sent = []

        def fake(method, url, json=None, **kwargs):
            sent.append(json)
            return refusal if len(sent) == 1 else Response(200, {"choices": [{"message": {"content": reply}}]})
        with patch.object(gw, "local_llm_base_url", return_value="http://127.0.0.1:8080"), patch.object(gw, "_loopback_http", fake):
            reply = '{"status": "ready"}'
            self.assertTrue(gw.structured_json_probe("Qwen3.8-27B"))
            self.assertNotIn("response_format", sent[1])
            self.assertEqual(sent[1]["chat_template_kwargs"], {"enable_thinking": False})
            sent.clear()
            reply = "Sure! Here is some text."
            self.assertFalse(gw.structured_json_probe("Qwen3.8-27B"))  # still proved by parsing, never assumed


if __name__ == "__main__":
    unittest.main()
