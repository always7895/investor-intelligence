from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import phrase_zh_policy as pzp  # noqa: E402

SHARED_POLICY = ROOT / "config" / "v213-sourced-wording-policy.json"
UTC = timezone.utc
DECISION = datetime(2026, 10, 11, 12, 0, 0, tzinfo=UTC)
FORBIDDEN = [*range(0x0000, 0x0020), 0x007C, *range(0x007F, 0x00A0), *range(0x200B, 0x2010),
             *range(0x2028, 0x202F), *range(0x2060, 0x2070), 0xFEFF, 0xFF5C]
RULES = ["ENTITY_SCOPE", "EXACT_QUANTITIES_UNITS", "NEGATION_MODALITY", "NO_MATERIAL_OMISSION",
         "NO_UNSUPPORTED_CLAIMS", "PERIOD_BASIS", "TRADITIONAL_CHINESE"]


def shared_bans() -> dict:
    return json.loads(SHARED_POLICY.read_text(encoding="utf-8"))


def digest_of(policy: dict) -> str:
    body = {key: value for key, value in policy.items() if key != "policy_sha256"}
    text = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def valid_policy() -> dict:
    shared = shared_bans()
    policy = {
        "schema": "phrase-zh-policy-v1", "policy_id": "test-policy", "revision": "r1",
        "effective_from": "2026-01-01T00:00:00Z", "expires_at": "2027-01-01T00:00:00Z", "locale": "zh-TW",
        "allowed_surfaces": ["POTENTIAL_REPORT_BUSINESS"], "min_phrase_codepoints": 4,
        "max_phrase_codepoints": 40, "max_phrase_utf16_units": 80,
        "banned_phrases_zh": sorted(shared["banned_phrases_zh"]),
        "banned_phrases_en": sorted(shared["banned_phrases_en"]),
        "forbidden_controls": list(FORBIDDEN), "semantic_rules": list(RULES),
        "required_provenance_schema": "phrase-zh-generation-v1", "required_review_schema": "phrase-zh-review-v1",
        "policy_sha256": "0" * 64}
    policy["policy_sha256"] = digest_of(policy)
    return policy


class PolicyCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.count = 0

    def put(self, content, name=None) -> tuple[Path, str]:
        self.count += 1
        path = self.dir / (name or f"policy{self.count}.json")
        raw = content if isinstance(content, bytes) else content.encode("utf-8")
        path.write_bytes(raw)
        return path, hashlib.sha256(raw).hexdigest()

    def dump(self, policy: dict) -> str:
        return json.dumps(policy, ensure_ascii=False)

    def load_policy(self, policy: dict, *, resign=True, when=DECISION):
        if resign:
            policy["policy_sha256"] = digest_of(policy)
        path, pin = self.put(self.dump(policy))
        return pzp.load(path, pin, decision_time=when)

    def load_raw(self, raw, **kwargs):
        path, pin = self.put(raw)
        return pzp.load(path, pin, decision_time=kwargs.get("when", DECISION))

    def refused(self, result, reason):
        self.assertEqual(result.status, pzp.STATUS_UNAVAILABLE)
        self.assertEqual(result.reason, reason)
        self.assertIsNone(result.policy)
        self.assertIn(result.reason, pzp.REASONS)

    def mutated(self, **changes) -> dict:
        policy = valid_policy()
        policy.update(changes)
        return policy


class ValidLoadTests(PolicyCase):
    def test_valid_policy_loads_and_keeps_all_shared_bans_byte_identical(self):
        result = self.load_policy(valid_policy())
        self.assertEqual((result.status, result.reason), (pzp.STATUS_OK, None))
        shared = shared_bans()
        policy = result.policy
        self.assertEqual(list(policy.banned_phrases_en), sorted(shared["banned_phrases_en"]))
        self.assertEqual(len(policy.banned_phrases_en), 10)
        self.assertEqual(set(policy.banned_phrases_zh), set(shared["banned_phrases_zh"]))
        self.assertTrue(any(len(item) == 2 for item in policy.banned_phrases_zh))
        self.assertIn("strong visibility", policy.banned_phrases_en)
        self.assertEqual(policy.allowed_surfaces, ("POTENTIAL_REPORT_BUSINESS",))
        self.assertEqual(policy.policy_sha256, valid_policy()["policy_sha256"])

    def test_documented_constants_match_the_contract(self):
        self.assertEqual((pzp.MIN_PHRASE_CODEPOINTS, pzp.MAX_PHRASE_CODEPOINTS, pzp.MAX_PHRASE_UTF16_UNITS), (4, 40, 80))
        self.assertEqual((pzp.MAX_POLICY_BYTES, pzp.MAX_DEPTH, pzp.MAX_BANS, pzp.MAX_BAN_CODEPOINTS), (65536, 16, 256, 100))
        self.assertEqual(list(pzp.FORBIDDEN_CONTROLS), FORBIDDEN)
        for member in (0x1F, 0x7C, 0x7F, 0x9F, 0x200B, 0x200F, 0x2028, 0x202E, 0x2060, 0x206F, 0xFEFF, 0xFF5C):
            self.assertIn(member, pzp.FORBIDDEN_CONTROLS)
        for outside in (0x20, 0x7E, 0xA0, 0x200A, 0x2010, 0x2027, 0x202F, 0x205F, 0x2070, 0xFF5B, 0xFF5D):
            self.assertNotIn(outside, pzp.FORBIDDEN_CONTROLS)
        self.assertEqual(list(pzp.SEMANTIC_RULES), RULES)

    def test_ban_entries_are_not_held_to_the_phrase_minimum(self):
        for zh in (["大"], ["大", "大量"], ["字" * 100]):
            policy = self.mutated(banned_phrases_zh=zh)
            self.assertEqual(self.load_policy(policy).status, pzp.STATUS_OK, zh)

    def test_ban_length_and_count_bounds_at_equality_and_one_over(self):
        for size, ok in ((255, True), (256, True), (257, False)):
            bans = [f"禁{index:03d}" for index in range(size)]
            result = self.load_policy(self.mutated(banned_phrases_zh=bans))
            self.assertEqual(result.status == pzp.STATUS_OK, ok, size)
        for length, ok in ((99, True), (100, True), (101, False)):
            result = self.load_policy(self.mutated(banned_phrases_zh=["字" * length]))
            self.assertEqual(result.status == pzp.STATUS_OK, ok, length)
        astral = self.load_policy(self.mutated(banned_phrases_zh=["\U00020000" * 100]))
        self.assertEqual(astral.status, pzp.STATUS_OK)
        self.refused(self.load_policy(self.mutated(banned_phrases_zh=["\U00020000" * 101])), "VALUE")
        self.refused(self.load_policy(self.mutated(banned_phrases_zh=[])), "VALUE")
        self.refused(self.load_policy(self.mutated(banned_phrases_en=[])), "VALUE")
        self.refused(self.load_policy(self.mutated(banned_phrases_zh=["", "大量"])), "VALUE")

    def test_file_size_bound_at_equality_and_one_over(self):
        policy = valid_policy()
        raw = self.dump(policy).encode("utf-8")
        exact = raw + b" " * (pzp.MAX_POLICY_BYTES - len(raw))
        self.assertEqual(len(exact), 65536)
        self.assertEqual(self.load_raw(exact).status, pzp.STATUS_OK)
        self.refused(self.load_raw(exact + b" "), "OVERSIZE")

    def test_decision_time_window_is_half_open(self):
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = datetime(2027, 1, 1, tzinfo=UTC)
        self.assertEqual(self.load_policy(valid_policy(), when=start).status, pzp.STATUS_OK)
        self.assertEqual(self.load_policy(valid_policy(), when=end - timedelta(seconds=1)).status, pzp.STATUS_OK)
        self.refused(self.load_policy(valid_policy(), when=start - timedelta(seconds=1)), "NOT_YET_EFFECTIVE")
        self.refused(self.load_policy(valid_policy(), when=end), "EXPIRED")
        offset = datetime(2027, 1, 1, 8, 0, 0, tzinfo=timezone(timedelta(hours=8)))
        self.refused(self.load_policy(valid_policy(), when=offset), "EXPIRED")


class PinAndFileTests(PolicyCase):
    def test_absent_unreadable_and_odd_paths(self):
        pin = hashlib.sha256(b"x").hexdigest()
        self.refused(pzp.load(self.dir / "missing.json", pin, decision_time=DECISION), "FILE_ABSENT")
        self.refused(pzp.load(self.dir, pin, decision_time=DECISION), "READ_ERROR")
        for odd in (None, 7, "\0"):
            self.assertEqual(pzp.load(odd, pin, decision_time=DECISION).status, pzp.STATUS_UNAVAILABLE)

    def test_invalid_pin_and_decision_time_arguments(self):
        path, pin = self.put(self.dump(valid_policy()))
        for bad in (pin.upper(), pin[:-1], pin + "0", "", None, 5, bytes.fromhex(pin), "g" * 64):
            self.refused(pzp.load(path, bad, decision_time=DECISION), "PIN_INVALID")
        for bad in (None, "2026-10-11T12:00:00Z", datetime(2026, 10, 11, 12, 0, 0), 5):
            self.refused(pzp.load(path, pin, decision_time=bad), "DECISION_TIME_INVALID")

    def test_pin_mismatch_and_swapped_path_or_pin(self):
        first, first_pin = self.put(self.dump(valid_policy()))
        other = valid_policy()
        other["revision"] = "r2"
        other["policy_sha256"] = digest_of(other)
        second, second_pin = self.put(self.dump(other))
        self.refused(pzp.load(first, second_pin, decision_time=DECISION), "DIGEST_MISMATCH")
        self.refused(pzp.load(second, first_pin, decision_time=DECISION), "DIGEST_MISMATCH")
        self.refused(pzp.load(first, "0" * 64, decision_time=DECISION), "DIGEST_MISMATCH")
        self.assertEqual(pzp.load(first, first_pin, decision_time=DECISION).status, pzp.STATUS_OK)

    def test_file_pin_is_checked_on_held_bytes_before_parsing(self):
        path, pin = self.put(b"{not json")
        wrong = "1" * 64
        self.refused(pzp.load(path, wrong, decision_time=DECISION), "DIGEST_MISMATCH")
        self.refused(pzp.load(path, pin, decision_time=DECISION), "MALFORMED")
        oversize = b"x" * (pzp.MAX_POLICY_BYTES + 1)
        path, _pin = self.put(oversize)
        self.refused(pzp.load(path, wrong, decision_time=DECISION), "OVERSIZE")

    def test_valid_file_bytes_with_stale_internal_digest_are_refused(self):
        policy = valid_policy()
        policy["revision"] = "r2"  # changed after the internal digest was computed
        self.refused(self.load_policy(policy, resign=False), "INTERNAL_DIGEST")
        policy = valid_policy()
        policy["policy_sha256"] = "A" * 64
        self.refused(self.load_policy(policy, resign=False), "VALUE")


class ParseTests(PolicyCase):
    def test_encoding_and_json_level_refusals(self):
        good = self.dump(valid_policy())
        self.refused(self.load_raw(b"\xef\xbb\xbf" + good.encode("utf-8")), "MALFORMED")
        self.refused(self.load_raw(b"\xff\xfe\x00"), "MALFORMED")
        self.refused(self.load_raw(b""), "MALFORMED")
        for root in ("[]", "null", '"x"', "3"):
            self.refused(self.load_raw(root), "TYPE")

    def test_duplicate_keys_and_nonfinite_numbers(self):
        good = self.dump(valid_policy())
        self.refused(self.load_raw(good[:-1] + ', "locale": "zh-TW"}'), "DUPLICATE_KEY")
        nested = good.replace('"banned_phrases_zh": [', '"banned_phrases_zh": [{"a": 1, "a": 2}, ', 1)
        self.refused(self.load_raw(nested), "DUPLICATE_KEY")
        for token in ("NaN", "Infinity", "-Infinity"):
            self.refused(self.load_raw(good.replace('"min_phrase_codepoints": 4', f'"min_phrase_codepoints": {token}')), "NONFINITE")
        for number in ("4.0", "4e0", "4.5"):
            self.refused(self.load_raw(good.replace('"min_phrase_codepoints": 4', f'"min_phrase_codepoints": {number}')), "FLOAT_NOT_ALLOWED")

    def test_overflowing_integer_is_refused(self):
        good = self.dump(valid_policy())
        self.refused(self.load_raw(good.replace('"min_phrase_codepoints": 4', '"min_phrase_codepoints": ' + "9" * 5000)), "MALFORMED")
        self.refused(self.load_policy(self.mutated(max_phrase_codepoints=10 ** 30)), "VALUE")

    def test_depth_bound_at_equality_and_one_over(self):
        def nested(containers: int):
            value: object = 1
            for _ in range(containers):
                value = [value]
            return value

        # The policy object is container depth 1, so the extra key may hold 15 more nested containers.
        self.refused(self.load_policy(self.mutated(extra=nested(15))), "KEY_SET")  # depth 16 passes, closed key set refuses
        self.refused(self.load_policy(self.mutated(extra=nested(16))), "DEPTH")
        self.refused(self.load_raw("[" * 5000 + "]" * 5000), "DEPTH")

    def test_lone_surrogates_in_values_and_keys(self):
        good = self.dump(valid_policy())
        self.refused(self.load_raw(good.replace('"test-policy"', '"\\ud800"')), "SCALAR_INVALID")
        self.refused(self.load_raw(good.replace('"locale"', '"\\udc00"')), "SCALAR_INVALID")
        self.refused(self.load_raw(good.replace("大量", "\\ud83d", 1)), "SCALAR_INVALID")
        paired = good.replace("大量", "\\ud83d\\ude00", 1)
        self.assertNotEqual(self.load_raw(paired).reason, "SCALAR_INVALID")


class TableTests(PolicyCase):
    def test_closed_key_set(self):
        for key in valid_policy():
            policy = valid_policy()
            del policy[key]
            self.refused(self.load_policy(policy, resign=False), "KEY_SET")
        policy = valid_policy()
        policy["unknown"] = 1
        self.refused(self.load_policy(policy), "KEY_SET")

    def test_literals_and_integers_reject_wrong_value_and_wrong_type(self):
        cases = [("schema", "phrase-zh-policy-v2"), ("locale", "zh-CN"), ("locale", "zh-tw"),
                 ("required_provenance_schema", "phrase-zh-generation-v2"), ("required_review_schema", "x"),
                 ("min_phrase_codepoints", 3), ("min_phrase_codepoints", 5), ("max_phrase_codepoints", 39),
                 ("max_phrase_codepoints", 41), ("max_phrase_utf16_units", 79), ("max_phrase_utf16_units", 81)]
        for key, value in cases:
            self.refused(self.load_policy(self.mutated(**{key: value})), "VALUE")
        for key, value in (("schema", 1), ("locale", None), ("min_phrase_codepoints", True),
                           ("max_phrase_codepoints", "40"), ("max_phrase_utf16_units", None),
                           ("required_review_schema", ["x"])):
            self.refused(self.load_policy(self.mutated(**{key: value})), "TYPE")

    def test_identifier_bounds(self):
        for key, limit in (("policy_id", 64), ("revision", 32)):
            self.assertEqual(self.load_policy(self.mutated(**{key: "a" * limit})).status, pzp.STATUS_OK)
            for bad in ("a" * (limit + 1), "", "-a", ".a", "a b", "a\n", "é", "a|b"):
                self.refused(self.load_policy(self.mutated(**{key: bad})), "VALUE")
            self.refused(self.load_policy(self.mutated(**{key: 5})), "TYPE")

    def test_time_fields(self):
        for key in ("effective_from", "expires_at"):
            for bad in ("2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00.0Z", "2026-01-01t00:00:00z",
                        "2026-01-01 00:00:00Z", "2026-01-01T00:00:60Z", "2026-02-30T00:00:00Z",
                        "1999-12-31T23:59:59Z", "2100-01-01T00:00:00Z", "2026-01-01T24:00:00Z",
                        "2026-01-01T00:00:00Z ", "２０２６-01-01T00:00:00Z", ""):
                self.refused(self.load_policy(self.mutated(**{key: bad})), "VALUE")
            self.refused(self.load_policy(self.mutated(**{key: 20260101})), "TYPE")
        self.assertEqual(self.load_policy(self.mutated(effective_from="2000-01-01T00:00:00Z")).status, pzp.STATUS_OK)
        self.assertEqual(self.load_policy(self.mutated(expires_at="2099-12-31T23:59:59Z")).status, pzp.STATUS_OK)
        same = "2026-06-01T00:00:00Z"
        self.refused(self.load_policy(self.mutated(effective_from=same, expires_at=same)), "VALUE")
        self.refused(self.load_policy(self.mutated(effective_from="2027-01-01T00:00:00Z", expires_at="2026-01-01T00:00:00Z")), "VALUE")

    def test_allowed_surfaces_closed_enum_and_v1_singleton(self):
        for bad in ([], ["NOPE"], ["TOP20_DEEP_BUSINESS"], ["BOTTLENECK_V3_DETAIL_BUSINESS"],
                    ["POTENTIAL_REPORT_BUSINESS", "TOP20_DEEP_BUSINESS"], ["potential_report_business"],
                    ["BOTTLENECK_V3_DETAIL_BUSINESS", "POTENTIAL_REPORT_BUSINESS", "TOP20_DEEP_BUSINESS", "X"]):
            self.refused(self.load_policy(self.mutated(allowed_surfaces=bad)), "VALUE")
        for bad in (["POTENTIAL_REPORT_BUSINESS", "POTENTIAL_REPORT_BUSINESS"],
                    ["TOP20_DEEP_BUSINESS", "POTENTIAL_REPORT_BUSINESS"]):
            self.refused(self.load_policy(self.mutated(allowed_surfaces=bad)), "ORDER")
        for bad in ("POTENTIAL_REPORT_BUSINESS", None, [1]):
            self.refused(self.load_policy(self.mutated(allowed_surfaces=bad)), "TYPE")

    def test_forbidden_controls_must_be_the_exact_set(self):
        for removed in (0x0000, 0x007C, 0xFF5C, 0xFEFF, 0x009F):
            controls = [item for item in FORBIDDEN if item != removed]
            self.refused(self.load_policy(self.mutated(forbidden_controls=controls)), "CONTROLS")
        for added in (0x0020, 0x00A0, 0x2000):
            self.refused(self.load_policy(self.mutated(forbidden_controls=sorted(FORBIDDEN + [added]))), "CONTROLS")
        self.refused(self.load_policy(self.mutated(forbidden_controls=[])), "CONTROLS")
        self.refused(self.load_policy(self.mutated(forbidden_controls=list(reversed(FORBIDDEN)))), "ORDER")
        self.refused(self.load_policy(self.mutated(forbidden_controls=FORBIDDEN + [FORBIDDEN[-1]])), "ORDER")
        self.refused(self.load_policy(self.mutated(forbidden_controls=[True] + FORBIDDEN[1:])), "TYPE")
        self.refused(self.load_policy(self.mutated(forbidden_controls=[str(item) for item in FORBIDDEN])), "TYPE")

    def test_semantic_rules_must_be_all_seven_exactly(self):
        for index in range(len(RULES)):
            self.refused(self.load_policy(self.mutated(semantic_rules=RULES[:index] + RULES[index + 1:])), "SEMANTIC_RULES")
        self.refused(self.load_policy(self.mutated(semantic_rules=sorted(RULES + ["EXTRA_RULE"]))), "SEMANTIC_RULES")
        self.refused(self.load_policy(self.mutated(semantic_rules=list(reversed(RULES)))), "ORDER")
        self.refused(self.load_policy(self.mutated(semantic_rules=RULES + RULES[:1])), "ORDER")
        self.refused(self.load_policy(self.mutated(semantic_rules=[*RULES[:-1], 7])), "TYPE")


class BanTextTests(PolicyCase):
    def test_whitespace_rules(self):
        for key in ("banned_phrases_zh", "banned_phrases_en"):
            for ok in ("a b", "大 量"):
                self.assertEqual(self.load_policy(self.mutated(**{key: [ok]})).status, pzp.STATUS_OK, ok)
            for bad in (" lead", "trail ", "two  spaces", " ", "a b", "a　b", "a b", "a b",
                        "a b", "a b", "a\u0085b"):
                self.refused(self.load_policy(self.mutated(**{key: [bad]})), "WHITESPACE" if "\u0085" not in bad else "CONTROLS")
            for bad in ("a\tb", "a\nb", "a\rb", "a\x0bb", "a\x0cb"):
                self.refused(self.load_policy(self.mutated(**{key: [bad]})), "CONTROLS")

    def test_forbidden_codepoints_inside_bans(self):
        for char in ("|", "｜", "\x00", "\x7f", "\u009f", "​", "‏", " ", "‮", "⁠",
                     "⁯", "﻿"):
            for key in ("banned_phrases_zh", "banned_phrases_en"):
                self.refused(self.load_policy(self.mutated(**{key: ["a" + char + "b"]})), "CONTROLS")
        for char in ("｛", "｝", "‐", "¡"):
            self.assertEqual(self.load_policy(self.mutated(banned_phrases_zh=["a" + char + "b"])).status, pzp.STATUS_OK)

    def test_ban_arrays_are_code_point_sorted_and_unique(self):
        for key in ("banned_phrases_zh", "banned_phrases_en"):
            self.refused(self.load_policy(self.mutated(**{key: ["b", "a"]})), "ORDER")
            self.refused(self.load_policy(self.mutated(**{key: ["a", "a"]})), "ORDER")
            self.refused(self.load_policy(self.mutated(**{key: ["Zz", "aa"][::-1]})), "ORDER")
            self.assertEqual(self.load_policy(self.mutated(**{key: ["Zz", "aa"]})).status, pzp.STATUS_OK)
            self.refused(self.load_policy(self.mutated(**{key: [5]})), "TYPE")
        self.assertEqual(self.load_policy(self.mutated(banned_phrases_zh=["ab", "abc"])).status, pzp.STATUS_OK)
        self.refused(self.load_policy(self.mutated(banned_phrases_zh=["abc", "ab"])), "ORDER")

    def test_astral_sorts_after_private_use_and_fullwidth_values(self):
        astral = "\U00010000"
        for bmp in ("", "Ａ", "￮"):
            self.assertEqual(self.load_policy(self.mutated(banned_phrases_zh=[bmp, astral])).status, pzp.STATUS_OK, hex(ord(bmp)))
            self.refused(self.load_policy(self.mutated(banned_phrases_zh=[astral, bmp])), "ORDER")


class InertTests(unittest.TestCase):
    def test_no_caller_and_no_policy_file_exist(self):
        needle = "phrase_zh_policy"
        for path in (ROOT / "scripts").glob("*.py"):
            if path.name != "phrase_zh_policy.py":
                self.assertNotIn(needle, path.read_text(encoding="utf-8", errors="replace"), path.name)
        for path in (ROOT / "cloud" / "src").rglob("*.ts"):
            self.assertNotIn(needle, path.read_text(encoding="utf-8", errors="replace"), path.name)
        self.assertFalse((ROOT / "config" / "phrase-zh-wording-policy-v1.json").exists())

    def test_result_objects_are_immutable_and_failure_never_carries_a_ban_set(self):
        policy = valid_policy()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "p.json"
            raw = json.dumps(policy, ensure_ascii=False).encode("utf-8")
            path.write_bytes(raw)
            ok = pzp.load(path, hashlib.sha256(raw).hexdigest(), decision_time=DECISION)
            bad = pzp.load(path, "0" * 64, decision_time=DECISION)
        with self.assertRaises(Exception):
            ok.policy.banned_phrases_zh = ()
        self.assertIsInstance(ok.policy.banned_phrases_zh, tuple)
        self.assertEqual((bad.status, bad.reason, bad.policy), (pzp.STATUS_UNAVAILABLE, "DIGEST_MISMATCH", None))
        self.assertEqual(copy.deepcopy(bad), bad)


if __name__ == "__main__":
    unittest.main()
