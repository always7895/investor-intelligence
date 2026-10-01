from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import v213_adaptive_reasoning as adaptive  # noqa: E402


class FakeDecider:
    def __init__(self, choice=None, error=None):
        self.choice, self.error, self.calls = choice, error, []

    def answer(self, state, question, options):
        self.calls.append((state, question, options))
        if self.error:
            raise self.error
        return self.choice, 0.9


class SelectEffortTests(unittest.TestCase):
    def test_line_budget_at_measured_rate_allows_medium_not_high(self):
        # 18 s LINE compact budget, 90 tokens/s, 400 answer tokens.
        plan = adaptive.select_effort("xhigh", timeout_ms=18000, answer_tokens=400, rate=90.0)
        self.assertEqual(plan["effective"], "medium")
        self.assertTrue(plan["enable_thinking"])
        self.assertEqual(plan["max_tokens"], 400 + adaptive.THINKING_TOKENS["medium"])
        self.assertEqual(plan["reason"], "TIME_BUDGET")

    def test_ceiling_is_never_raised_and_none_stays_none(self):
        plan = adaptive.select_effort("low", timeout_ms=20000, answer_tokens=200, rate=400.0)
        self.assertEqual((plan["effective"], plan["reason"]), ("low", "CEILING"))
        plan = adaptive.select_effort("none", timeout_ms=20000, answer_tokens=200, rate=400.0)
        self.assertEqual((plan["effective"], plan["enable_thinking"], plan["reason"]), ("none", False, "CEILING_NONE"))

    def test_slow_lane_or_short_timeout_turns_thinking_off(self):
        plan = adaptive.select_effort("max", timeout_ms=5000, answer_tokens=400, rate=30.0)
        self.assertEqual((plan["effective"], plan["max_tokens"]), ("none", 400))

    def test_system_one_simple_skips_thinking(self):
        plan = adaptive.select_effort("xhigh", timeout_ms=20000, answer_tokens=300, rate=200.0, screen="SIMPLE")
        self.assertEqual((plan["effective"], plan["reason"]), ("none", "SYSTEM_ONE_SIMPLE"))

    def test_profile_output_cap_limits_thinking(self):
        plan = adaptive.select_effort("max", timeout_ms=20000, answer_tokens=400, rate=400.0, max_output_tokens=1024)
        self.assertEqual(plan["effective"], "medium")
        self.assertLessEqual(plan["max_tokens"], 1024)

    def test_invalid_inputs_fail_closed(self):
        for kwargs in ({"timeout_ms": 0, "answer_tokens": 10}, {"timeout_ms": 1000, "answer_tokens": 0},
                       {"timeout_ms": 1000.0, "answer_tokens": 10}):
            with self.assertRaises(ValueError):
                adaptive.select_effort("low", rate=50.0, **kwargs)
        with self.assertRaises(ValueError):
            adaptive.select_effort("extreme", timeout_ms=1000, answer_tokens=10, rate=50.0)


class DecodeRateTests(unittest.TestCase):
    def test_moving_average_ignores_tiny_samples_and_clamps(self):
        rate = adaptive.DecodeRate(initial=60.0, alpha=0.5)
        rate.observe(10, 1.0)
        rate.observe(900, 0.01)
        self.assertEqual(rate.value, 60.0)
        rate.observe(900, 10.0)  # 90 tokens/s
        self.assertAlmostEqual(rate.value, 75.0)
        rate.observe(1_000_000, 1.0)  # clamped to the 400 ceiling
        self.assertAlmostEqual(rate.value, 237.5)
        rate.observe(float("nan"), 1.0)
        self.assertAlmostEqual(rate.value, 237.5)
        with self.assertRaises(ValueError):
            adaptive.DecodeRate(initial=1.0)


class ScreenTests(unittest.TestCase):
    def test_screen_sends_features_not_text_and_tolerates_failure(self):
        decider = FakeDecider("SIMPLE")
        features = adaptive.question_features("NVDA 目前股價？")
        self.assertEqual(adaptive.system_one_screen(decider, features), "SIMPLE")
        self.assertNotIn("NVDA", str(decider.calls[0][0]))
        self.assertEqual(decider.calls[0][2], ["SIMPLE", "COMPLEX"])
        self.assertIsNone(adaptive.system_one_screen(FakeDecider(error=RuntimeError("down")), features))
        self.assertIsNone(adaptive.system_one_screen(FakeDecider("MAYBE"), features))
        self.assertIsNone(adaptive.system_one_screen(None, features))


class GatewayIntegrationTests(unittest.TestCase):
    """Actual authenticated gateway handler with a fake upstream and decider."""

    PROFILE = dict(schema_version=1, model="synthetic-model-a", enable_thinking=True, reasoning_effort="xhigh",
                   max_output_tokens=1024, smoke_output_tokens=128, timeout_ms=18000)

    def body(self):
        from v213_compact_qa_gateway import POLICY
        return {"model": self.PROFILE["model"], "ii_context_mode": POLICY["mode"], "max_tokens": 300,
                "ii_model_profile": dict(self.PROFILE),
                "messages": [{"role": "system", "content": POLICY["system"] + '\nDATA={"v":1,"freshness":"FRESH"}'},
                             {"role": "user", "content": "比較兩家公司的訂單能見度與估值風險，並說明理由。"}]}

    def reply(self, finish="stop"):
        from unittest.mock import Mock
        response = Mock(ok=True, status_code=200)
        response.json.return_value = {"model": self.PROFILE["model"], "choices": [
            {"finish_reason": finish, "message": {"content": "合成完整回答" * 20}}]}
        return response

    def run_gateway(self, responses, screen=None):
        import json
        import os
        import secrets
        import threading
        import urllib.request
        from http.server import ThreadingHTTPServer
        from unittest.mock import Mock, patch
        import v213_local_llm_gateway as gateway
        auth = secrets.token_hex(32)
        server = ThreadingHTTPServer(("127.0.0.1", 0), gateway.V213GatewayHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        screen_client = Mock(answer=Mock(return_value=(screen, 0.9))) if screen else None
        with patch.dict(os.environ, {"II_LOCAL_LLM_SHARED_SECRET": auth, "V213_MODEL_PROFILE_JSON": json.dumps(self.PROFILE)}), \
                patch.object(gateway, "_available_model_catalog", return_value=[{"id": self.PROFILE["model"]}]), \
                patch.object(gateway, "_decision_client", return_value=Mock(answer=Mock(return_value=("SUFFICIENT", 0.9)))), \
                patch.object(gateway, "_screen_client", return_value=screen_client), \
                patch.object(gateway, "capability_context_evidence", return_value=262144), \
                patch.object(gateway, "structured_json_probe", return_value=True), \
                patch.object(gateway, "DECODE_RATE", adaptive.DecodeRate(initial=90.0)), \
                patch.object(gateway, "_loopback_http", side_effect=responses) as upstream:
            thread.start()
            try:
                request = urllib.request.Request(f"http://127.0.0.1:{server.server_port}/v1/chat/completions",
                                                 data=json.dumps(self.body()).encode(),
                                                 headers={"content-type": "application/json", "x-investor-shared-secret": auth})
                with urllib.request.urlopen(request, timeout=10) as result:
                    return result.status, json.load(result), upstream.call_args_list
            finally:
                server.shutdown(); server.server_close(); thread.join(timeout=5)

    def test_time_budget_picks_medium_under_the_xhigh_ceiling(self):
        status, result, calls = self.run_gateway([self.reply()])
        self.assertEqual(status, 200)
        sent = calls[0].kwargs["json"]
        self.assertEqual((sent["reasoning_effort"], sent["chat_template_kwargs"]["enable_thinking"]), ("medium", True))
        self.assertEqual(sent["max_tokens"], 300 + adaptive.THINKING_TOKENS["medium"])
        self.assertEqual((result["ii_reasoning"]["ceiling"], result["ii_reasoning"]["effective"]), ("xhigh", "medium"))

    def test_thinking_overrun_retries_once_without_thinking(self):
        status, result, calls = self.run_gateway([self.reply("length"), self.reply()])
        self.assertEqual(status, 200)
        self.assertEqual(len(calls), 2)
        retry = calls[1].kwargs["json"]
        self.assertEqual((retry["chat_template_kwargs"]["enable_thinking"], retry["max_tokens"]), (False, 300))
        self.assertEqual(result["ii_reasoning"]["reason"], "THINKING_OVERRAN_RETRIED_WITHOUT")

    def test_system_one_simple_screen_answers_without_thinking(self):
        status, result, calls = self.run_gateway([self.reply()], screen="SIMPLE")
        self.assertEqual(status, 200)
        self.assertFalse(calls[0].kwargs["json"]["chat_template_kwargs"]["enable_thinking"])
        self.assertEqual(result["ii_reasoning"]["reason"], "SYSTEM_ONE_SIMPLE")


if __name__ == "__main__":
    unittest.main()
