"""Offline behavioral proofs. All price/rights bodies below are SYNTHETIC, not real evidence."""
from __future__ import annotations

import copy
import hashlib
import json
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import corporate_actions as actions
import distribution_adjusted_returns as dar


def action():
    return next(row for row in actions.load_actions(today=date(2026, 11, 8))["entries"]
                if row["target_symbol"] == "MOD")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def evidence(start, end, *, shares=100000, events=None, cil=None):
    """Synthetic document bodies exercise the exact installed-review boundary only."""
    events = [] if events is None else events
    docs = []
    def document(key, role, url, body, source_day=None):
        row = {"id": key, "role": role, "source_url": url,
               "source_date": (source_day or end).isoformat(), "body": body,
               "sha256": hashlib.sha256(body.encode()).hexdigest()}
        docs.append(row)
        return key
    document("completion", "TERMS", dar.MOD_SOURCE, "SYNTHETIC fixture of reviewed completion terms", date(2026, 10, 1))
    document("terms", "TERMS", dar.MOD_TERMS_SOURCE, "SYNTHETIC fixture of reviewed due-bill terms", date(2026, 9, 17))
    document("special", "TERMS", dar.THRM_FINAL_SOURCE, "SYNTHETIC fixture: special dividend belongs to old THRM shares", date(2026, 10, 1))
    mod_start = f"MOD | {start.isoformat()} | USD | UNADJUSTED_OFFICIAL | AS_TRADED | 100"
    mod_end = f"MOD | {end.isoformat()} | USD | UNADJUSTED_OFFICIAL | AS_TRADED | 80"
    thrm_end = f"THRM | {end.isoformat()} | USD | UNADJUSTED_OFFICIAL | AS_TRADED | 50"
    document("mod", "PRICE", "https://www.nyse.com/quote/XNYS:MOD/history", mod_start + "\n" + mod_end)
    document("thrm", "PRICE", "https://www.nasdaq.com/market-activity/stocks/thrm/historical", thrm_end)
    document("rights", "RIGHTS", "https://www.nyse.com/market-data/agreements", "SYNTHETIC public-derived-return license fixture")
    document("ledger", "ACTION_LEDGER", "https://www.nyse.com/quote/XNYS:MOD/actions",
             "SYNTHETIC complete two-security action ledger\n" + "\n".join(row["source_excerpt"] for row in events))
    def price(symbol, day, close, key, excerpt):
        return {"symbol": symbol, "security_id": {"MOD": "CIK:0000067347", "THRM": "CIK:0000903129"}[symbol],
                "day": day.isoformat(), "currency": "USD", "price_basis": "UNADJUSTED_OFFICIAL",
                "split_basis": "AS_TRADED", "close": close, "document_id": key, "source_excerpt": excerpt}
    cash = {"amount": 0, "currency": "USD", "paid_on": None, "document_id": None, "source_excerpt": None}
    if cil is not None:
        excerpt = f"SYNTHETIC actual net CIL paid USD {cil}"
        key = document("cil", "CASH_IN_LIEU", "https://www.nasdaq.com/market-activity/stocks/thrm/settlement", excerpt)
        cash = {"amount": cil, "currency": "USD", "paid_on": end.isoformat(), "document_id": key, "source_excerpt": excerpt}
    return {"schema": "distribution-entitlement-input-v2", "target_symbol": "MOD", "related_symbol": "THRM",
            "start_day": start.isoformat(), "end_day": end.isoformat(), "currency": "USD",
            "method": "CASH_HELD_NO_REINVESTMENT", "ex_date": "2026-10-02", "record_date": "2026-09-28",
            "due_bill_start": "2026-09-28", "due_bill_end": "2026-10-01",
            "ledger_start": start.isoformat(), "ledger_end": end.isoformat(), "ledger_document_id": "ledger",
            "benchmark_target_shares": shares, "cash_and_split_events": events, "cash_in_lieu": cash,
            "prices": {"start_target": price("MOD", start, 100, "mod", mod_start),
                       "end_target": price("MOD", end, 80, "mod", mod_end),
                       "end_related": price("THRM", end, 50, "thrm", thrm_end)}, "primary_documents": docs}


def approved_action(windows, end):
    """A separate controlled registry fixture, not approval in the pricing payload."""
    row = action()
    row.pop("flags", None)
    row["entitlement_receipts"] = [
        {"evidence_sha256": digest(ev), "approved_on": end.isoformat(), "rights_scope": "PUBLIC_DERIVED_RETURN",
         "primary_documents": [{"source_url": d["source_url"], "sha256": d["sha256"]} for d in ev["primary_documents"]]}
        for ev in windows.values()]
    raw = json.dumps({"schema_version": 1, "entries": [row]}).encode()
    return actions.load_actions_bytes(raw, today=end)["entries"][0]


def market(end):
    return {"asof": end.isoformat(), "ret_6m": .2, "ret_1y": .3, "cagr_2y": .4,
            "cagr_listed": None, "long_term_basis": "TWO_YEAR"}


class EntitlementTests(unittest.TestCase):
    def test_record_date_does_not_override_due_bill_entitlement(self):
        end = date(2026, 11, 8)
        for start in (date(2026, 9, 20), date(2026, 9, 30), date(2026, 10, 1)):
            ev = evidence(start, end)
            result = dar.calculate_entitled_return(action(), ev, start_day=start, end_day=end)
            self.assertEqual(result["status"], "CALCULATED_RESEARCH_ONLY")
            self.assertEqual(result["distributed_whole_shares"], 44619)
            self.assertAlmostEqual(result["return"], (80 + .44619 * 50) / 100 - 1)
        start = date(2026, 10, 2)
        self.assertIsNone(dar.calculate_entitled_return(action(), evidence(start, end), start_day=start, end_day=end))

    def test_fraction_receives_actual_net_cash_not_fraction_and_end_close(self):
        start, end = date(2026, 10, 1), date(2026, 11, 8)
        ev = evidence(start, end, shares=3, cil=9)
        out = dar.calculate_entitled_return(action(), ev, start_day=start, end_day=end)
        self.assertEqual(out["distributed_whole_shares"], 1)
        self.assertAlmostEqual(out["return"], (3 * 80 + 50 + 9) / 300 - 1)
        ev["cash_in_lieu"]["paid_on"] = "2026-11-09"
        self.assertIsNone(dar.calculate_entitled_return(action(), ev, start_day=start, end_day=end))
        self.assertIsNone(dar.calculate_entitled_return(action(), evidence(start, end, shares=3), start_day=start, end_day=end))
        self.assertIsNone(dar.calculate_entitled_return(action(), evidence(start, end, cil=9), start_day=start, end_day=end))

    def test_split_and_cash_ledger_does_not_reinvest_or_credit_old_thrm_dividend(self):
        start, end = date(2026, 9, 20), date(2026, 11, 8)
        events = [
            {"symbol": "MOD", "kind": "SPLIT", "ex_date": "2026-10-03", "value": 2, "source_excerpt": "SYNTHETIC MOD split 2"},
            {"symbol": "MOD", "kind": "DIVIDEND", "ex_date": "2026-10-04", "value": 1, "source_excerpt": "SYNTHETIC MOD dividend 1"},
            {"symbol": "THRM", "kind": "SPLIT", "ex_date": "2026-10-05", "value": 2, "source_excerpt": "SYNTHETIC THRM split 2"},
            {"symbol": "THRM", "kind": "DIVIDEND", "ex_date": "2026-10-08", "value": 1, "source_excerpt": "SYNTHETIC THRM dividend 1"},
        ]
        ev = evidence(start, end, events=events)
        out = dar.calculate_entitled_return(action(), ev, start_day=start, end_day=end)
        self.assertAlmostEqual(out["return"], (200000 * 81 + 89238 * 51) / 10000000 - 1)
        for special_day in ("2026-10-02", "2026-10-07"):
            bad = events + [{"symbol": "THRM", "kind": "DIVIDEND", "ex_date": special_day, "value": 2.07, "source_excerpt": "SYNTHETIC ineligible special dividend"}]
            self.assertIsNone(dar.calculate_entitled_return(action(), evidence(start, end, events=bad), start_day=start, end_day=end))

    def test_identity_dates_currency_split_basis_and_bodies_fail_closed(self):
        start, end = date(2026, 10, 1), date(2026, 11, 8)
        good = evidence(start, end)
        for field, value in (("symbol", "THRM"), ("security_id", "CIK:0000903129"),
                             ("day", "2026-09-30"), ("currency", "CAD"),
                             ("split_basis", "ADJUSTED"), ("price_basis", "YAHOO_ALREADY_ADJUSTED"),
                             ("close", True), ("close", float("nan")), ("source_excerpt", "not present")):
            bad = copy.deepcopy(good)
            bad["prices"]["start_target"][field] = value
            with self.subTest(field=field, value=value):
                self.assertIsNone(dar.calculate_entitled_return(action(), bad, start_day=start, end_day=end))
        for update in ({"source_date": "2026-11-09"}, {"body": "tampered"},
                       {"source_url": "https://www.nyse.com.evil.invalid/quote/MOD"}, {"source_url": []}):
            bad = copy.deepcopy(good)
            bad["primary_documents"][3].update(update)
            self.assertIsNone(dar.calculate_entitled_return(action(), bad, start_day=start, end_day=end))

    def test_crossing_boundary_is_ex_date_and_never_leaks_old_overlay(self):
        row = action()
        before = dar.apply_qualified_market(market(date(2026, 10, 1)), [row], None)
        self.assertEqual(before["ret_6m"], .2)  # due-bill close still includes the right
        edge_end = date(2026, 10, 1) + timedelta(days=182)
        blocked = dar.apply_qualified_market(market(edge_end), [row], None)
        self.assertIsNone(blocked["ret_6m"])  # start Oct1, after completion but BEFORE ex date
        self.assertIn("一手", blocked["distribution_unavailable_reason_zh"])
        safe = dar.apply_qualified_market(market(date(2026, 10, 2) + timedelta(days=182)), [row], None)
        self.assertEqual(safe["ret_6m"], .2)  # start ex day: no inherited THRM right
        stale = {**market(date(2026, 11, 8)), "distribution_adjustment": {"values": {"ret_6m": 9}},
                 "distribution_evidence": {"primary_data_reviewed": True}, "distribution_adjusted_candidates": {"ret_6m": 9}}
        out = dar.apply_qualified_market(stale, [row], None)
        self.assertIsNone(out["ret_6m"])
        self.assertNotIn("distribution_adjustment", out)
        self.assertNotIn("distribution_evidence", out)
        self.assertNotIn("distribution_adjusted_candidates", out)
        research = dar.restore_crossing_returns(stale, row, {})
        self.assertIsNone(research["ret_6m"])

    def test_only_independently_pinned_complete_windows_restore_atomically(self):
        end = date(2026, 11, 8)
        windows = {key: evidence(end - timedelta(days=days), end) for key, (days, _) in dar.WINDOWS.items()}
        review = {"schema": "distribution-entitlement-reviewed-v2", "target_symbol": "MOD", "related_symbol": "THRM",
                  "asof": end.isoformat(), "reviewed_at": end.isoformat(), "windows": windows,
                  "primary_data_reviewed": True, "research_rights_approved": True}
        review["input_sha256"] = digest(review)
        self.assertIsNone(dar.apply_qualified_market(market(end), [action()], review)["ret_6m"])
        row = approved_action(windows, end)
        result = dar.apply_qualified_market(market(end), [row], review)
        self.assertAlmostEqual(result["ret_6m"], (80 + .44619 * 50) / 100 - 1)
        self.assertNotIn("return_reasons", result)
        self.assertEqual(result, dar.apply_qualified_market(result, [row], review))
        for bad in ({**review, "windows": {"ret_6m": windows["ret_6m"]}}, {**review, "reviewed_at": "not-a-date"}):
            self.assertIsNone(dar.apply_qualified_market(market(end), [row], bad)["ret_6m"])
        tampered = copy.deepcopy(review)
        tampered["windows"]["ret_6m"]["prices"]["end_target"]["close"] = 9000
        tampered["input_sha256"] = digest({key: value for key, value in tampered.items() if key != "input_sha256"})
        self.assertIsNone(dar.apply_qualified_market(market(end), [row], tampered)["ret_6m"])
        missing_pin = copy.deepcopy(row)
        missing_pin["entitlement_receipts"][0]["primary_documents"][0]["sha256"] = "0" * 64
        self.assertIsNone(dar.apply_qualified_market(market(end), [missing_pin], review)["ret_6m"])
        # The public projection never exposes approval documents or raw bodies.
        self.assertNotIn("entitlement_receipts", actions.distribution_note(row))


if __name__ == "__main__":
    unittest.main()
