"""TAIFEX dataset-11321 Delta reference: SYNTHETIC fixtures for the bounded raw decoder (delta_reference_rows) and the
closed-schema record builder (delta_reference_records) in scripts/taifex_contract.py. A module tearDown reports the number of
attempted subtests (not passed regressions).

LOCAL_REFERENCE_ONLY and UNVERIFIED throughout: nothing here claims compatibility with the real 11321 response shape, and no
join, quote, as-of date, expiry, DTE, currency, multiplier, unit or sign convention is inferred or asserted. Every row, day
and Delta below is a made-up fixture; there is no TAIFEX contact at all (no fetch, no network, no model, no native call).
No implementation decision is monkeypatched: patch.object is used ONLY to lower the resource limits for bounded limit tests,
restored in every case, after the real default constants are asserted. The independent EOD daily_identity is untouched.
"""
from __future__ import annotations

import datetime
import json
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import taifex_contract as tc  # noqa: E402

_CODE_RE = re.compile(r"TAIFEX_DELTA_[A-Z_]+")
_SUBTESTS = [0]

DEFAULTS = {"TAIFEX_DELTA_MAX_BYTES": 8_000_000, "TAIFEX_DELTA_MAX_OUTPUT_BYTES": 16_000_000,
            "TAIFEX_DELTA_MAX_DEPTH": 2, "REFERENCE_MAX_ROWS": 20000, "REFERENCE_MAX_FIELD": 64,
            "_DELTA_RAW_STRING_MAX": 386}


def row(**over):
    base = {"Contract": "TXO", "CallPut": "Call", "ContractMonth(Week)": "202610", "StrikePrice": "25000",
            "Delta": "0.1234", "ContractSettlementDay": "20261015"}
    base.update(over)
    return base


def payload(rows, *, bom=False):
    text = json.dumps(list(rows), ensure_ascii=False, separators=(",", ":"))
    return (b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8")


def tearDownModule():
    # Attempted subtests, not passed regressions: this runs even when failfast stops the suite.
    print("TAIFEX_DELTA_SUBTESTS_ATTEMPTED=%d" % _SUBTESTS[0])


class DeltaFixture(unittest.TestCase):
    def setUp(self):
        for name, value in DEFAULTS.items():  # real default constants before any test-specific temporary cap
            self.assertEqual(getattr(tc, name), value, name)

    def sub(self, **labels):
        _SUBTESTS[0] += 1
        return self.subTest(**labels)

    def code(self, call):
        """Fixed code only: the message must be exactly one TAIFEX_DELTA_* code, never a raw offending value."""
        with self.assertRaises(ValueError) as ctx:
            call()
        message = str(ctx.exception)
        self.assertTrue(_CODE_RE.fullmatch(message), repr(message))
        return message

    def records(self, rows, *, origin="COLLECTOR_CAPTURE_UNQUALIFIED"):
        return tc.delta_reference_records(rows, origin_verification=origin)


class DeltaValidRowTests(DeltaFixture):
    def test_valid_six_string_rows_decode_then_build_reference_records(self):
        for right, option_type in (("Call", "call"), ("Put", "put"), ("\u8cb7\u6b0a", "call"), ("\u8ce3\u6b0a", "put")):
            with self.sub(right=right):
                found = self.records(tc.delta_reference_rows(payload([row(CallPut=right)])))
                self.assertEqual(len(found), 1)
                self.assertEqual(found[0]["option_type"], option_type)
                self.assertEqual(found[0]["reference_scope"], "LOCAL_REFERENCE_ONLY")
                self.assertEqual(found[0]["reference_time_status"], "UNALIGNED_NO_PROVIDER_ASOF")
                self.assertEqual(found[0]["source_row_index"], 0)
                self.assertEqual((found[0]["publication_eligible"], found[0]["line_quote_eligible"], found[0]["executable_quote"]),
                                 (False, False, False))
        for series in ("202610", "202610W1", "202610F5"):
            with self.sub(series=series):
                found = self.records(tc.delta_reference_rows(payload([row(**{"ContractMonth(Week)": series})])))
                self.assertEqual(found[0]["contract_month_week"], series)
        for day_text, reported in (("20261015", "2026-10-15"), ("2026-10-15", "2026-10-15")):
            with self.sub(day=day_text):
                found = self.records(tc.delta_reference_rows(payload([row(ContractSettlementDay=day_text)])))
                self.assertEqual(found[0]["contract_settlement_day_text"], day_text)  # raw text preserved verbatim
                self.assertEqual(found[0]["reported_contract_day"], reported)  # date-only reference, no expiry/DTE inference
                self.assertEqual(found[0]["contract_day_status"], "REPORTED_REFERENCE_DAY_FORMAT_UNVERIFIED")
        for strike, delta in (("25000", "0.1234"), ("25000.0", "-0.5"), ("0.5", "1"), ("25000", "-1")):
            with self.sub(strike=strike, delta=delta):
                found = self.records(tc.delta_reference_rows(payload([row(StrikePrice=strike, Delta=delta)])))
                self.assertEqual((found[0]["strike_text"], found[0]["delta_text"]), (strike, delta))
                self.assertEqual(found[0]["delta_lexical_status"], "LEXICAL_DECIMAL_UNIT_SIGN_UNDOCUMENTED")
        for bom in (False, True):
            with self.sub(bom=bom):
                found = self.records(tc.delta_reference_rows(payload([row(), row(Contract="TX1", CallPut="\u8ce3\u6b0a")], bom=bom)))
                self.assertEqual([r["source_row_index"] for r in found], [0, 1])  # index and order preserved
                self.assertEqual([r["contract"] for r in found], ["TXO", "TX1"])
        for origin in ("COLLECTOR_CAPTURE_UNQUALIFIED", "UNVERIFIED_LOCAL_FILE"):
            with self.sub(origin=origin):
                found = self.records(tc.delta_reference_rows(payload([row()])), origin=origin)
                self.assertEqual(found[0]["origin_verification"], origin)

    def test_empty_and_out_of_range_delta_and_day_stay_raw(self):
        found = self.records(tc.delta_reference_rows(payload([row(Delta="", ContractSettlementDay="")])))
        self.assertEqual((found[0]["delta_text"], found[0]["delta_lexical_status"]), ("", "EMPTY"))
        self.assertEqual((found[0]["contract_settlement_day_text"], found[0]["reported_contract_day"], found[0]["contract_day_status"]),
                         ("", None, "EMPTY"))
        for delta in ("1.75", "-1.75", "999", "0", "1", "-1"):  # outside [-1,1] stays raw and UNDOCUMENTED, never scaled or rejected
            with self.sub(delta=delta):
                found = self.records(tc.delta_reference_rows(payload([row(Delta=delta)])))
                self.assertEqual((found[0]["delta_text"], found[0]["delta_lexical_status"]),
                                 (delta, "LEXICAL_DECIMAL_UNIT_SIGN_UNDOCUMENTED"))


class DeltaDecoderTests(DeltaFixture):
    def test_decoder_rejects_payload_type_empty_and_size(self):
        for bad in ("[]", None, 12, b"", bytearray()):
            with self.sub(payload=repr(bad)):
                self.assertEqual(self.code(lambda b=bad: tc.delta_reference_rows(b)), "TAIFEX_DELTA_INVALID_PAYLOAD_SIZE")
        with patch.object(tc, "TAIFEX_DELTA_MAX_BYTES", 4):
            self.assertEqual(tc.delta_reference_rows(b"[{}]"), [{}])  # exact cap accepted
            self.assertEqual(self.code(lambda: tc.delta_reference_rows(b"[{}] ")), "TAIFEX_DELTA_INVALID_PAYLOAD_SIZE")
        self.assertEqual(self.code(lambda: tc.delta_reference_rows(b"[\xff]")), "TAIFEX_DELTA_INVALID_ENCODING")

    def test_decoder_rejects_malformed_truncated_and_duplicate_json_with_fixed_codes(self):
        for bad in (b"[", b"[{", b'["abc]', b"[,]", b"[]]", b'{"a": "b"', b"not json", b'["a" "b"]', b'{"a" "b"}'):
            with self.sub(payload=repr(bad)):
                self.assertEqual(self.code(lambda b=bad: tc.delta_reference_rows(b)), "TAIFEX_DELTA_INVALID_JSON")
        self.assertEqual(self.code(lambda: tc.delta_reference_rows(b"")), "TAIFEX_DELTA_INVALID_PAYLOAD_SIZE")
        self.assertEqual(self.code(lambda: tc.delta_reference_rows(b'[{"Contract": "TXO", "Contract": "TXO"}]')),
                         "TAIFEX_DELTA_DUPLICATE_JSON_FIELD")

    def test_decoder_refuses_every_json_number_and_constant_without_raw_text(self):
        for bad, expected in ((b"[25000]", "TAIFEX_DELTA_INVALID_FIELD_TYPE"), (b"[0.5]", "TAIFEX_DELTA_INVALID_FIELD_TYPE"),
                              (b"[1e-1]", "TAIFEX_DELTA_INVALID_FIELD_TYPE"), (b"[-0]", "TAIFEX_DELTA_INVALID_FIELD_TYPE"),
                              (b"[NaN]", "TAIFEX_DELTA_INVALID_CONSTANT"), (b"[Infinity]", "TAIFEX_DELTA_INVALID_CONSTANT"),
                              (b"[-Infinity]", "TAIFEX_DELTA_INVALID_CONSTANT"),
                              (b'[{"Delta": 1}]', "TAIFEX_DELTA_INVALID_FIELD_TYPE")):
            with self.sub(payload=repr(bad)):
                self.assertEqual(self.code(lambda b=bad: tc.delta_reference_rows(b)), expected)

    def test_depth_rules_brackets_in_strings_and_the_escape_bound_are_decoder_only(self):
        self.assertEqual(tc.delta_reference_rows(payload([row()])), [row()])  # array = 1, row object = 2 is the accepted shape
        self.assertEqual(self.code(lambda: tc.delta_reference_rows(b'[[{"a": "b"}]]')), "TAIFEX_DELTA_TOO_DEEP")
        self.assertEqual(tc.delta_reference_rows(b'["' + b"[" * 200 + b'"]'), ["[" * 200])  # brackets inside a string are not structure
        self.assertEqual(self.code(lambda: tc.delta_reference_rows(b'["a"')), "TAIFEX_DELTA_INVALID_JSON")  # depth never closes
        escapes = b"\\u0041"
        self.assertEqual(tc.delta_reference_rows(b'["' + escapes * 64 + b'"]'), ["A" * 64])  # 64 escapes = the bound, accepted
        self.assertEqual(self.code(lambda: tc.delta_reference_rows(b'["' + escapes * 65 + b'"]')), "TAIFEX_DELTA_INVALID_FIELD_TYPE")


class DeltaRecordsTests(DeltaFixture):
    def test_records_refuse_the_closed_schema_and_root_shape(self):
        for wrong_root in (b'{"Contract": "TXO"}', b'"just a string"', b"[]", b'{"a": ["b"]}'):
            with self.sub(root=repr(wrong_root)):
                decoded = tc.delta_reference_rows(wrong_root)
                self.assertEqual(self.code(lambda d=decoded: self.records(d)), "TAIFEX_DELTA_INVALID_ROWS")
        for bad_rows, expected in (([], "TAIFEX_DELTA_INVALID_ROWS"), ("not a list", "TAIFEX_DELTA_INVALID_ROWS"),
                                   (12, "TAIFEX_DELTA_INVALID_ROWS"),
                                   (["not a dict"], "TAIFEX_DELTA_SCHEMA_CHANGED"),
                                   ([row(Extra="x")], "TAIFEX_DELTA_SCHEMA_CHANGED"),
                                   ([{k: v for k, v in row().items() if k != "Delta"}], "TAIFEX_DELTA_SCHEMA_CHANGED"),
                                   ([dict(row(), StrikePrice=25000)], "TAIFEX_DELTA_INVALID_FIELD_TYPE"),
                                   ([dict(row(), Delta=None)], "TAIFEX_DELTA_INVALID_FIELD_TYPE"),
                                   ([dict(row(), Contract="X" * 65)], "TAIFEX_DELTA_INVALID_FIELD_TYPE")):
            with self.sub(rows=repr(bad_rows)[:60]):
                self.assertEqual(self.code(lambda r=bad_rows: self.records(r)), expected)

    def test_records_refuse_invalid_origin_contract_right_strike_delta_and_day(self):
        self.assertEqual(self.code(lambda: self.records([row()], origin="VERIFIED_BY_BROKER")), "TAIFEX_DELTA_INVALID_ORIGIN_LABEL")
        self.assertEqual(self.code(lambda: self.records([row()], origin="")), "TAIFEX_DELTA_INVALID_ORIGIN_LABEL")
        for bad_contract in ("txo", "", "TOO LONG NAME", "TXO;X", "\u8af8\u5982"):
            with self.sub(contract=bad_contract):
                self.assertEqual(self.code(lambda c=bad_contract: self.records([row(Contract=c)])), "TAIFEX_DELTA_INVALID_CONTRACT")
        for bad_series in ("20261", "2026101", "202610W6", "202610X1", "20261W1", "", "202613"):
            with self.sub(series=bad_series):
                self.assertEqual(self.code(lambda s=bad_series: self.records([row(**{"ContractMonth(Week)": s})])),
                                 "TAIFEX_DELTA_INVALID_CONTRACT")
        # C/P are not admitted by THIS implementation's vocabulary; real 11321 value compatibility remains UNVERIFIED.
        for bad_right in ("C", "P", "c", "call", "put", "", "\u8cb7", "BUY"):
            with self.sub(right=bad_right):
                self.assertEqual(self.code(lambda r=bad_right: self.records([row(CallPut=r)])), "TAIFEX_DELTA_INVALID_CONTRACT")
        for bad_strike in ("0", "-100", "25,000", "1e3", "", " 25000", "25000.", "0x10"):
            with self.sub(strike=bad_strike):
                expected = "TAIFEX_DELTA_INVALID_STRIKE" if bad_strike == "0" else "TAIFEX_DELTA_INVALID_CONTRACT"
                self.assertEqual(self.code(lambda s=bad_strike: self.records([row(StrikePrice=s)])), expected)
        for bad_delta in ("+0.1", ".1", "1e-1", " 0.1", "0.1 ", "NaN", "0.12.3", "--1", "abc", "-.5"):
            with self.sub(delta=bad_delta):
                self.assertEqual(self.code(lambda d=bad_delta: self.records([row(Delta=d)])), "TAIFEX_DELTA_INVALID_DELTA")
        for bad_day in ("20261340", "20260230", "2026-02-30", "2026-13-01", "15/10/2026", "2026101", "202610155",
                        "2026-10-15T00:00"):
            with self.sub(day=bad_day):
                self.assertEqual(self.code(lambda d=bad_day: self.records([row(ContractSettlementDay=d)])), "TAIFEX_DELTA_INVALID_DAY")

    def test_duplicate_identity_uses_decimal_equality_and_keeps_strings(self):
        self.assertEqual(self.code(lambda: self.records([row(), row(StrikePrice="25000.0")])), "TAIFEX_DELTA_DUPLICATE_CONTRACT")
        self.assertEqual(self.code(lambda: self.records([row(StrikePrice="25000.00"), row(StrikePrice="25000.000")])),
                         "TAIFEX_DELTA_DUPLICATE_CONTRACT")
        high_a, high_b = "25000.0000000000000001", "25000.0000000000000002"  # identical as floats, distinct as Decimal text
        self.assertEqual(float(high_a), float(high_b))
        found = self.records([row(StrikePrice=high_a), row(StrikePrice=high_b)])
        self.assertEqual([r["strike_text"] for r in found], [high_a, high_b])  # strings preserved, no float conversion
        self.assertEqual([r["source_row_index"] for r in found], [0, 1])
        both = self.records([row(CallPut="Call"), row(CallPut="Put")])  # everything else equal, right differs -> distinct rows
        self.assertEqual([r["option_type"] for r in both], ["call", "put"])
        self.assertNotIn("reported_expiry", found[0])  # no inferred timestamp/expiry field was invented

    def test_a_later_invalid_row_refuses_the_whole_batch(self):
        # unique contracts per case: identity is checked BEFORE the Delta/day lexical rules, so a repeated contract would
        # mask the intended code. Fixture independence only - the production precedence is not changed here.
        self.assertEqual(self.code(lambda: self.records([row(), row(Contract="TX1"), row(Contract="TX2", Delta="+0.1")])),
                         "TAIFEX_DELTA_INVALID_DELTA")
        self.assertEqual(self.code(lambda: self.records([row(), row(Contract="TX1", ContractSettlementDay="20261340")])),
                         "TAIFEX_DELTA_INVALID_DAY")
        self.assertEqual(self.code(lambda: self.records([row(), row(Contract="TXO")])), "TAIFEX_DELTA_DUPLICATE_CONTRACT")

    def test_resource_boundaries_use_restored_test_only_caps(self):
        with patch.object(tc, "REFERENCE_MAX_ROWS", 2):
            self.assertEqual(self.code(lambda: self.records([row(), row(Contract="TX1"), row(Contract="TX2")])),
                             "TAIFEX_DELTA_INVALID_ROWS")  # records row cap
            self.assertEqual(self.code(lambda: tc.delta_reference_rows(b'[{},{},{},{}]')), "TAIFEX_DELTA_INVALID_ROWS")  # containers
            self.assertEqual(self.code(lambda: tc.delta_reference_rows(b"[" + b"0," * 30 + b"0]")), "TAIFEX_DELTA_INVALID_ROWS")
            self.assertEqual(self.records([row(), row(Contract="TX1")])[0]["contract"], "TXO")  # inside the cap still works
        with patch.object(tc, "TAIFEX_DELTA_MAX_OUTPUT_BYTES", 16):
            self.assertEqual(self.code(lambda: self.records([row()])), "TAIFEX_DELTA_OUTPUT_TOO_LARGE")
        with patch.object(tc, "TAIFEX_DELTA_MAX_DEPTH", 1):
            self.assertEqual(self.code(lambda: tc.delta_reference_rows(payload([row()]))), "TAIFEX_DELTA_TOO_DEEP")
        with patch.object(tc, "REFERENCE_MAX_FIELD", 4):
            self.assertEqual(self.code(lambda: self.records([row()])), "TAIFEX_DELTA_INVALID_FIELD_TYPE")
        for name, value in DEFAULTS.items():
            self.assertEqual(getattr(tc, name), value, name)  # every temporary cap was restored


class DeltaEodIndependenceTests(DeltaFixture):
    def test_independent_eod_daily_identity_is_untouched(self):
        today = datetime.date(2026, 10, 5)
        good = {"Date": "20261002", "Contract": "TXO", "ContractMonth(Week)": "202610", "CallPut": "Call",
                "TradingSession": "\u4e00\u822c"}
        with self.sub(case="valid EOD identity is separate from the Delta codes"):
            self.assertEqual(tc.daily_identity(good, taipei_day=today),
                             (datetime.date(2026, 10, 2), "TXO", "202610", "C", "\u4e00\u822c"))
        with self.sub(case="EOD keeps its own TAIFEX_EOD_* codes"):
            with self.assertRaises(ValueError) as ctx:
                tc.daily_identity(dict(good, Date="202613"), taipei_day=today)
            self.assertEqual(str(ctx.exception), "TAIFEX_EOD_INVALID_DATE")


if __name__ == "__main__":
    unittest.main()
