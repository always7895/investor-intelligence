"""I3 claimed-validity history shadow — contract candidate tests (synthetic only).

Synthetic fixtures only; acceptance is separate. No real issuer/name authority.
"""
import copy
import contextlib
import io
import json
import socket
import subprocess
import tempfile
from datetime import date
from unittest import mock
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import v213_identity_history_shadow as i3
from scripts import v213_identity_search_shadow as i1


def make_record(company_id, security_id, exchange, ticker, canonical=None, aliases=None):
    auth = "official_issuer_exchange_government_zh_tw" if canonical is not None else None
    src = "example.com" if canonical is not None else None
    return {
        "company_id": company_id,
        "security_id": security_id,
        "exchange": exchange,
        "ticker": ticker,
        "canonical_name_zh_tw": canonical,
        "aliases": aliases if aliases is not None else [],
        "name_authority": auth,
        "name_source": src,
    }


def make_entry(record, valid_from, valid_to):
    return {"record": record, "valid_from": valid_from, "valid_to": valid_to}


class TestI3HistoryShadow(unittest.TestCase):
    def test_half_open_boundaries(self):
        rec = make_record("syn-co-a", "syn-sec-a", "SYN-X", "SYN-A", canonical="合成甲", aliases=["SYNTH ALPHA"])
        entries = [make_entry(rec, "2020-01-01", "2021-01-01")]
        self.assertEqual(i3.resolve_history_query("SYNTH ALPHA", entries, "2020-01-01")["status"], "MATCH")
        self.assertEqual(i3.resolve_history_query("SYNTH ALPHA", entries, "2021-01-01")["status"], "NOT_FOUND")
        entries_adj = [make_entry(rec, "2021-01-01", "2022-01-01")]
        self.assertEqual(i3.resolve_history_query("SYNTH ALPHA", entries_adj, "2021-01-01")["status"], "MATCH")
        entries_gap = [make_entry(rec, "2020-01-01", "2021-01-01"), make_entry(rec, "2022-01-01", "2023-01-01")]
        self.assertEqual(i3.resolve_history_query("SYNTH ALPHA", entries_gap, "2021-06-01")["status"], "NOT_FOUND")
        entries_open = [make_entry(rec, "2020-01-01", None)]
        self.assertEqual(i3.resolve_history_query("SYNTH ALPHA", entries_open, "9999-12-31")["status"], "MATCH")
        entries_leap = [make_entry(rec, "2020-02-29", "2020-03-01")]
        self.assertEqual(i3.resolve_history_query("SYNTH ALPHA", entries_leap, "2020-02-29")["status"], "MATCH")

    def test_alias_carry(self):
        rec_old = make_record("syn-co-a", "syn-sec-a", "SYN-X", "SYN-A", canonical="合成甲", aliases=["SYNTH ALPHA"])
        rec_new = make_record("syn-co-a", "syn-sec-a", "SYN-X", "SYN-A", canonical="合成甲", aliases=["SYNTH BETA"])
        entries = [make_entry(rec_old, "2020-01-01", "2021-01-01"), make_entry(rec_new, "2021-01-01", None)]
        self.assertEqual(i3.resolve_history_query("SYNTH ALPHA", entries, "2025-01-01")["status"], "NOT_FOUND")
        self.assertEqual(i3.resolve_history_query("SYNTH BETA", entries, "2025-01-01")["status"], "MATCH")
        rec_new2 = make_record("syn-co-a", "syn-sec-a", "SYN-X", "SYN-A", canonical="合成甲", aliases=["SYNTH BETA", "SYNTH ALPHA"])
        entries2 = [make_entry(rec_old, "2020-01-01", "2021-01-01"), make_entry(rec_new2, "2021-01-01", None)]
        self.assertEqual(i3.resolve_history_query("SYNTH ALPHA", entries2, "2025-01-01")["status"], "MATCH")

    def test_ticker_reuse_and_ambiguity(self):
        rec1 = make_record("syn-co-a", "syn-sec-a", "SYN-X", "SYN-A", canonical="合成甲", aliases=["SYNTH ALPHA"])
        rec2 = make_record("syn-co-b", "syn-sec-b", "SYN-X", "SYN-A", canonical="合成乙", aliases=["OTHER"])
        entries = [make_entry(rec1, "2020-01-01", "2021-01-01"), make_entry(rec2, "2021-01-01", None)]
        result = i3.resolve_history_query("SYN-A", entries, "2025-01-01")
        self.assertEqual(result["status"], "MATCH")
        self.assertEqual(result["candidates"][0]["company_id"], "syn-co-b")
        rec_adr1 = make_record("syn-co-a", "syn-sec-a", "SYN-X", "SYN-A", canonical="合成甲", aliases=["SYNTH ALPHA"])
        rec_adr2 = make_record("syn-co-a", "syn-sec-b", "SYN-Y", "SYNTH BETA", canonical="合成甲", aliases=["SYNTH ALPHA"])
        entries_adr = [make_entry(rec_adr1, "2020-01-01", None), make_entry(rec_adr2, "2020-01-01", None)]
        self.assertEqual(i3.resolve_history_query("SYNTH ALPHA", entries_adr, "2025-01-01")["status"], "AMBIGUOUS")
        self.assertEqual(i3.resolve_history_query("SYNTH ALPHA", entries_adr, "2025-01-01", exchange="SYN-X")["status"], "MATCH")

    def test_inactive_overlap_and_reparent(self):
        rec1 = make_record("syn-co-a", "syn-sec-a", "SYN-X", "SYN-A", canonical="合成甲", aliases=["SYNTH ALPHA"])
        rec2 = make_record("syn-co-a", "syn-sec-a", "SYN-X", "SYN-A", canonical="合成甲", aliases=["SYNTH ALPHA"])
        entries = [make_entry(rec1, "2020-01-01", "2021-01-01"), make_entry(rec2, "2020-06-01", "2022-01-01")]
        with self.assertRaises(ValueError):
            i3.resolve_history_query("SYNTH ALPHA", entries, "2025-01-01")
        rec3 = make_record("syn-co-b", "syn-sec-a", "SYN-X", "SYN-A", canonical="合成甲", aliases=["SYNTH ALPHA"])
        entries2 = [make_entry(rec1, "2020-01-01", "2021-01-01"), make_entry(rec3, "2021-01-01", None)]
        with self.assertRaises(ValueError):
            i3.resolve_history_query("SYNTH ALPHA", entries2, "2025-01-01")

    def test_i1_original_strings_and_non_mutation(self):
        rec = make_record("syn-co-a", "syn-sec-a", "SYN-X", "SYN-A", canonical="合成甲", aliases=["SYNTH ALPHA"])
        entries = [make_entry(rec, "2020-01-01", None)]
        original_entries = copy.deepcopy(entries)
        original_resolve = i1.resolve_query
        seen = {}

        def spy_resolve(query, records, exchange=None):
            seen["query"] = query
            seen["records"] = copy.deepcopy(records)
            seen["exchange"] = exchange
            return original_resolve(query, records, exchange)

        i1.resolve_query = spy_resolve
        try:
            i3.resolve_history_query("SYNTH ALPHA", entries, "2025-01-01")
        finally:
            i1.resolve_query = original_resolve
        self.assertEqual(seen["query"], "SYNTH ALPHA")
        self.assertEqual(seen["records"][0]["ticker"], "SYN-A")
        self.assertEqual(seen["records"][0]["canonical_name_zh_tw"], "合成甲")
        self.assertEqual(entries, original_entries)



class TestI3ContractMatrix(unittest.TestCase):
    def row(self, sid="syn-s1", cid="syn-c1", venue="SYN-X", ticker="00700", name=None, aliases=None, start="2020-01-01", end=None):
        return make_entry(make_record(cid, sid, venue, ticker, name, aliases), start, end)

    def expected(self, status, candidates, as_of="2024-01-01"):
        return {"status": status, "AMBIGUOUS": status == "AMBIGUOUS", "candidates": candidates,
                "shadow_only": True, "production_authorized": False, "as_of": as_of,
                "history_profile": "I3_CLAIMED_VALIDITY_V1", "source_authenticated": False,
                "current_identity_authorized": False}

    def test_literal_outputs_order_normalization_and_absence(self):
        a = self.row(sid="syn-a", name="合成甲", aliases=["SYNTH A"])
        b = self.row(sid="syn-b", venue="SYN-Y", ticker="OTHER", aliases=["00700", "SYNTH A"])
        expected = [{"company_id": "syn-c1", "security_id": "syn-a", "exchange": "SYN-X", "ticker": "00700", "name": "合成甲"},
                    {"company_id": "syn-c1", "security_id": "syn-b", "exchange": "SYN-Y", "ticker": "OTHER", "name": None}]
        for rows in ([a, b], [b, a]):
            for query in ("00700", " ＳＹＮＴＨ   Ａ ", "sYnTh A"):
                with self.subTest(query=query, first=rows[0]["record"]["security_id"]):
                    self.assertEqual(i3.resolve_history_query(query, rows, "2024-01-01"), self.expected("AMBIGUOUS", expected))
            self.assertEqual(i3.resolve_history_query("700", rows, "2024-01-01"), self.expected("NOT_FOUND", []))
            self.assertEqual(i3.resolve_history_query("00700", rows, "2024-01-01", "ＳＹＮ－Ｘ"), self.expected("MATCH", expected[:1]))
        dot = self.row(ticker="SYN.A")
        self.assertEqual(i3.resolve_history_query("SYN-A", [dot], "2024-01-01")["status"], "NOT_FOUND")

    def test_original_strings_forwarded_and_inputs_unchanged(self):
        row = self.row(aliases=["SYNTH A"], name="合成甲")
        original = copy.deepcopy(row)
        with mock.patch.object(i1, "resolve_query", wraps=i1.resolve_query) as call:
            result = i3.resolve_history_query(" ＳＹＮＴＨ Ａ ", [row], "2024-01-01", " ＳＹＮ－Ｘ ")
        self.assertEqual(result["status"], "MATCH")
        self.assertEqual(call.call_args.args, (" ＳＹＮＴＨ Ａ ", [row["record"]], " ＳＹＮ－Ｘ "))
        self.assertEqual(row, original)

    def test_dates_canonical_bounds_and_invalid_inactive_entries(self):
        class Str(str): pass
        bad = [None, True, 20240101, date(2024, 1, 1), Str("2024-01-01"), "20240101", "2024-W01-1", "2024-1-01",
               "2024-01-01 ", "２０２４-01-01", "0000-01-01", "10000-01-01", "2023-02-29", "2024-04-31", "2024-01-01T00:00:00Z"]
        for value in bad:
            with self.subTest(value=repr(value)):
                with self.assertRaises(ValueError): i3.resolve_history_query("00700", [], value)
                row = self.row(start=value)
                with self.assertRaises(ValueError): i3.resolve_history_query("OTHER", [row], "2024-01-01", "ABSENT")
                if value is not None:
                    row = self.row(end=value)
                    with self.assertRaises(ValueError): i3.resolve_history_query("OTHER", [row], "2024-01-01")
        for end in ("2020-01-01", "2019-12-31"):
            with self.assertRaises(ValueError): i3.resolve_history_query("00700", [self.row(end=end)], "2024-01-01")
        for day in ("0001-01-01", "2024-02-29", "9999-12-31"):
            self.assertEqual(i3.resolve_history_query("00700", [self.row(start="0001-01-01")], day)["status"], "MATCH")
        for query, venue in ((True, None), ("ok", []), ("\u202e", None)):
            with self.assertRaises(ValueError): i3.resolve_history_query(query, [], "2024-01-01", venue)

    def test_closed_builtins_and_keys_without_custom_equality(self):
        class List(list): pass
        class Dict(dict): pass
        class Str(str): pass
        class Poison(str):
            __hash__ = str.__hash__
            def __eq__(self, other): raise AssertionError("custom key equality invoked")
        for rows in ((), {}, List([]), [Dict(self.row())]):
            with self.subTest(rows=type(rows)):
                with self.assertRaises(ValueError): i3.resolve_history_query("00700", rows, "2024-01-01")
        for level, field in (("entry", "record"), ("record", "company_id")):
            for key in (Poison(field), True):
                row = self.row(); target = row if level == "entry" else row["record"]
                value = target.pop(field); target[key] = value
                with self.assertRaises(ValueError): i3.resolve_history_query("00700", [row], "2024-01-01")
        variants = []
        for field, value in (("company_id", Str("syn-c1")), ("security_id", " padded "), ("aliases", List([])),
                             ("aliases", [Str("ALIAS")]), ("ticker", True), ("name_authority", "llm"),
                             ("name_source", "unpaired-source")):
            row = self.row(); row["record"][field] = value; variants.append(row)
        row = self.row(); row["record"] = Dict(row["record"]); variants.append(row)
        row = self.row(); row["extra"] = 1; variants.append(row)
        row = self.row(); row["record"]["extra"] = 1; variants.append(row)
        row = self.row(); del row["valid_to"]; variants.append(row)
        for row in variants:
            with self.assertRaises(ValueError): i3.resolve_history_query("00700", [row], "2024-01-01")

    def test_caps(self):
        rows = [self.row(sid=f"syn-s{i}", cid=f"syn-c{i}", ticker=f"T{i}") for i in range(1024)]
        self.assertEqual(i3.resolve_history_query("T0", rows, "2024-01-01")["candidates"][0]["security_id"], "syn-s0")
        with self.assertRaises(ValueError): i3.resolve_history_query("T0", rows + [self.row()], "2024-01-01")
        self.assertEqual(i3.resolve_history_query("ALIAS", [self.row(aliases=["ALIAS"] * 32)], "2024-01-01")["status"], "MATCH")
        with self.assertRaises(ValueError): i3.resolve_history_query("ALIAS", [self.row(aliases=["ALIAS"] * 33)], "2024-01-01")
        with self.assertRaises(ValueError): i3.resolve_history_query("Q" * 257, [], "2024-01-01")

    def test_all_ledger_conflicts_and_metadata_policy(self):
        a = self.row(end="2021-01-01")
        same_security = copy.deepcopy(a)
        same_key = self.row(sid="syn-s2", cid="syn-c2", venue="ｓｙｎ－ｘ", ticker="００７００", end="2021-01-01")
        reparent = self.row(cid="syn-new-company", start="2021-01-01")
        for b in (same_security, same_key, reparent):
            for rows in ([a, b], [b, a]):
                with self.assertRaises(ValueError): i3.resolve_history_query("UNRELATED", rows, "2099-01-01", "ABSENT")
        name_a = self.row(name="SYNTH A")
        name_b = self.row(sid="syn-s2", venue="SYN-Y", name="ＳＹＮＴＨ Ａ")
        with self.assertRaises(ValueError): i3.resolve_history_query("00700", [name_a, name_b], "2024-01-01")
        name_b["record"]["canonical_name_zh_tw"] = "SYNTH A"
        name_b["record"]["name_authority"] = "reviewed_curated_transliteration"
        name_b["record"]["name_source"] = "https://example.com/synthetic-other-claim"
        self.assertEqual(i3.resolve_history_query("00700", [name_a, name_b], "2024-01-01")["status"], "AMBIGUOUS")
        name_b["record"].update(canonical_name_zh_tw=None, name_authority=None, name_source=None)
        self.assertEqual(i3.resolve_history_query("00700", [name_a, name_b], "2024-01-01")["candidates"][1]["name"], None)
        moved = self.row(venue="SYN-Y", ticker="NEW", name="合成乙", start="2021-01-01")
        for rows in ([a, moved], [moved, a]):
            self.assertEqual(i3.resolve_history_query("NEW", rows, "2021-01-01")["status"], "MATCH")
            self.assertEqual(i3.resolve_history_query("00700", rows, "2021-01-01")["status"], "NOT_FOUND")

    def test_former_name_and_ticker_are_not_implicitly_carried(self):
        old = self.row(ticker="OLD", name="合成舊", end="2021-01-01")
        new = self.row(ticker="NEW", name="合成新", start="2021-01-01")
        for query in ("OLD", "合成舊"):
            self.assertEqual(i3.resolve_history_query(query, [new, old], "2020-01-01")["status"], "MATCH")
            self.assertEqual(i3.resolve_history_query(query, [new, old], "2021-01-01")["status"], "NOT_FOUND")
        new["record"]["aliases"] = ["OLD", "合成舊"]
        other = self.row(sid="syn-z", ticker="OLD", start="2021-01-01")
        self.assertEqual(i3.resolve_history_query("OLD", [old, new, other], "2024-01-01")["status"], "AMBIGUOUS")
        # Inactive payload errors and cross-venue duplicate security remain invalid.
        invalid = self.row(end="2021-01-01"); invalid["record"]["aliases"] = [False]
        with self.assertRaises(ValueError): i3.resolve_history_query("NONE", [invalid], "2099-01-01", "ABSENT")
        with self.assertRaises(ValueError): i3.resolve_history_query("00700", [self.row(), self.row(venue="SYN-Y")], "2024-01-01")

    def test_api_no_io_clock_or_network(self):
        row = self.row(); before = copy.deepcopy(row)
        with mock.patch("builtins.open", side_effect=AssertionError("filesystem")), mock.patch("socket.socket", side_effect=AssertionError("network")), mock.patch("time.time", side_effect=AssertionError("clock")), mock.patch("time.monotonic", side_effect=AssertionError("clock")):
            self.assertEqual(i3.resolve_history_query("00700", [row], "2024-01-01")["status"], "MATCH")
        self.assertEqual(row, before)


class TestI3CLI(unittest.TestCase):
    INVALID = {"status": "INVALID", "AMBIGUOUS": False, "candidates": [], "shadow_only": True,
               "production_authorized": False, "as_of": None, "history_profile": "I3_CLAIMED_VALIDITY_V1",
               "source_authenticated": False, "current_identity_authorized": False}

    def invoke(self, raw, args=None, module=False):
        with tempfile.TemporaryDirectory(prefix="i3-synthetic-") as directory:
            path = Path(directory) / "input.json"; path.write_bytes(raw)
            command = [sys.executable, "-m", "scripts.v213_identity_history_shadow"] if module else [sys.executable, str(ROOT / "scripts/v213_identity_history_shadow.py")]
            proc = subprocess.run(command + ([str(path)] if args is None else args), cwd=ROOT, capture_output=True, timeout=15)
            self.assertEqual(path.read_bytes(), raw)
            self.assertEqual(sorted(x.name for x in Path(directory).iterdir()), ["input.json"])
            self.assertEqual(proc.stderr, b"")
            return proc.returncode, json.loads(proc.stdout)

    def payload(self):
        return {"query": "SYN-A", "entries": [make_entry(make_record("syn-c", "syn-s", "SYN-X", "SYN-A"), "2020-01-01", None)], "as_of": "2024-01-01"}

    def test_real_direct_and_module_cli_valid_states(self):
        p = self.payload()
        expected = dict(self.INVALID, status="MATCH", as_of="2024-01-01", candidates=[{"company_id": "syn-c", "security_id": "syn-s", "exchange": "SYN-X", "ticker": "SYN-A", "name": None}])
        for module in (False, True): self.assertEqual(self.invoke(json.dumps(p).encode(), module=module), (0, expected))
        raw = json.dumps(p).encode()
        self.assertEqual(self.invoke(b" " * (8 * 1024 * 1024 - len(raw)) + raw), (0, expected))
        p["query"] = "MISSING"
        self.assertEqual(self.invoke(json.dumps(p).encode()), (0, dict(self.INVALID, status="NOT_FOUND", as_of="2024-01-01")))
        p["query"] = "SYN-A"
        p["entries"].append(make_entry(make_record("syn-c", "syn-z", "SYN-Y", "SYN-A"), "2020-01-01", None))
        expected["status"] = "AMBIGUOUS"; expected["AMBIGUOUS"] = True
        expected["candidates"].append({"company_id": "syn-c", "security_id": "syn-z", "exchange": "SYN-Y", "ticker": "SYN-A", "name": None})
        self.assertEqual(self.invoke(json.dumps(p).encode()), (0, expected))

    def test_actual_cli_invalid_matrix(self):
        p = self.payload(); raw = json.dumps(p)
        invalid = [b"{broken", b"\xff", ("[" * 2000 + "0" + "]" * 2000).encode(), b" " * (8 * 1024 * 1024 + 1 - len(raw.encode())) + raw.encode(),
                   b"[]", b"null", b'{"query":"a","query":"b","entries":[],"as_of":"2024-01-01"}',
                   raw.replace('"company_id": "syn-c"', '"company_id": "syn-c", "company_id": "syn-c"').encode()]
        for key in ("query", "entries", "as_of"):
            v = copy.deepcopy(p); del v[key]; invalid.append(json.dumps(v).encode())
        for update in ({"extra": 1}, {"as_of": True}, {"as_of": "2023-02-29"}, {"entries": {}}, {"query": None}, {"exchange": []}):
            invalid.append(json.dumps(dict(p, **update)).encode())
        v = copy.deepcopy(p); v["entries"][0]["record"]["name_source"] = "unpaired"; invalid.append(json.dumps(v).encode())
        for index, data in enumerate(invalid):
            with self.subTest(index=index): self.assertEqual(self.invoke(data), (2, self.INVALID))
        for args in ([], ["first", "second"]): self.assertEqual(self.invoke(b"{}", args=args), (2, self.INVALID))
        with tempfile.TemporaryDirectory(prefix="i3-synthetic-missing-") as directory:
            for path in (str(Path(directory) / "absent.json"), directory):
                self.assertEqual(self.invoke(b"{}", args=[path]), (2, self.INVALID))

    def test_explicit_payload_key_type_guard(self):
        class Poison(str):
            __hash__ = str.__hash__
            def __eq__(self, other): raise AssertionError("payload key equality")
        payload = {Poison("query"): "SYN-A", "entries": [], "as_of": "2024-01-01"}
        output = io.StringIO()
        with mock.patch("builtins.open", mock.mock_open(read_data=b"{}")), mock.patch.object(i3.json, "loads", return_value=payload), contextlib.redirect_stdout(output):
            self.assertEqual(i3.main(["synthetic-input"]), 2)
        self.assertEqual(json.loads(output.getvalue()), self.INVALID)

    def test_inert_package_import(self):
        code = 'from unittest.mock import patch\nwith patch("builtins.open", side_effect=AssertionError("file IO")), patch("socket.socket", side_effect=AssertionError("network")), patch("time.time", side_effect=AssertionError("clock")):\n import scripts.v213_identity_history_shadow\nprint("INERT_IMPORT")\n'
        p = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, timeout=15)
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, b"INERT_IMPORT\r\n" if sys.platform == "win32" else b"INERT_IMPORT\n", b""))


if __name__ == "__main__":
    unittest.main()