#!/usr/bin/env python3
"""
Unit tests for v2.1.3 Market Products (Macro Industry & Options).
Verifies:
- Macro candidate evaluation (0, <5, 5, >5 candidates).
- Shortfall reporting when <5 admitted candidates.
- Rejection of company-count percentage as market growth.
- Corrupted / incomplete growth rate rejection.
- Opportunity rubric scoring bounds (0-100 System Operationalization).
- 4 standalone educational strategy cards arithmetic & UNBOUNDED maxprofit.
- Option quote validation (crossed quotes, negative values, mid average, timestamps, strict types).
- Strict calendar date, period, and source-binding validation.
- CLI builder execution.
- Review findings A, B, C, D, E financial safety assertions.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_v213_macro_industry_research import (  # noqa: E402
    evaluate_candidates,
    build_macro_overview_output,
    calculate_opportunity_score,
    validate_candidate,
    SYNTHETIC_FIVE_QUALIFIED,
)
from validate_v213_market_products import (  # noqa: E402
    validate_macro_overview,
    validate_educational_strategy,
    validate_option_quote,
    validate_covered_call_cycle,
    validate_growth_rate,
    MarketProductValidationError,
)


class TestV213MarketProducts(unittest.TestCase):
    def test_macro_builder_with_zero_candidates(self) -> None:
        qualified, disqualified = evaluate_candidates([])
        report = build_macro_overview_output(qualified, disqualified)
        self.assertEqual(report["qualified_count"], 0)
        self.assertEqual(report["shortfall"], 5)
        self.assertEqual(report["status"], "SHORTFALL_NOT_QUALIFIED")
        self.assertFalse(report["publication_qualified"])
        self.assertIn("短缺通報", report["shortfall_report"])

    def test_macro_builder_with_fewer_than_five_qualified(self) -> None:
        candidates = [
            copy.deepcopy(SYNTHETIC_FIVE_QUALIFIED[0]),
            {
                "industry_id": "missing_growth_industry",
                "industry_name": "無公開成長率產業",
                "growth": None,
                "scores": {"demand": 20, "chokepoint": 20}
            }
        ]
        qualified, disqualified = evaluate_candidates(candidates)
        self.assertEqual(len(qualified), 1)
        self.assertEqual(len(disqualified), 1)
        self.assertEqual(disqualified[0]["disqualification_reason"], "GROWTH_RATE_MISSING_UNAVAILABLE")
        self.assertIsNone(disqualified[0]["rank"])
        self.assertEqual(disqualified[0]["admission_status"], "NOT_PUBLICATION_QUALIFIED")

        report = build_macro_overview_output(qualified, disqualified)
        self.assertEqual(report["qualified_count"], 1)
        self.assertEqual(report["shortfall"], 4)
        self.assertEqual(report["status"], "SHORTFALL_NOT_QUALIFIED")
        self.assertFalse(report["publication_qualified"])

    def test_macro_builder_with_exactly_five_qualified(self) -> None:
        qualified, disqualified = evaluate_candidates(SYNTHETIC_FIVE_QUALIFIED)
        self.assertEqual(len(qualified), 5)
        self.assertEqual(len(disqualified), 0)

        report = build_macro_overview_output(qualified, disqualified, is_synthetic=True)
        self.assertEqual(report["qualified_count"], 5)
        self.assertEqual(report["shortfall"], 0)
        self.assertEqual(report["status"], "ADMITTED_TOP5")
        self.assertEqual(len(report["industries"]), 5)
        for idx, ind in enumerate(report["industries"]):
            self.assertEqual(ind["rank"], idx + 1)
            self.assertGreater(ind["opportunity_score"], 0)

        # Validate through shared validator
        validate_macro_overview(report)

    def test_a_higher_opportunity_score_never_ranks_lower(self) -> None:
        # Rotation order puts confirmed phases first; the published rank must still follow the score the card shows.
        candidates = copy.deepcopy(SYNTHETIC_FIVE_QUALIFIED)
        for index, (cand, strength) in enumerate(zip(candidates, (35, 83, 57, 42, 70))):
            cand["data_strength"], cand["rotation_rank"] = strength, index + 1
        qualified, _ = evaluate_candidates(candidates)
        self.assertEqual([c["opportunity_score"] for c in qualified], [83, 70, 57, 42, 35])
        self.assertEqual([c["rank"] for c in qualified], [1, 2, 3, 4, 5])

    def test_macro_builder_ranks_by_opportunity_rubric(self) -> None:
        candidates = []
        for i in range(6):
            c = copy.deepcopy(SYNTHETIC_FIVE_QUALIFIED[0])
            c["industry_id"] = f"ind_{i}"
            c["scores"] = {"demand": 10 + i * 2, "chokepoint": 10, "pricing": 10, "value_chain": 5, "catalysts": 5}
            candidates.append(c)

        qualified, _ = evaluate_candidates(candidates)
        self.assertEqual(len(qualified), 6)
        for i in range(len(qualified) - 1):
            self.assertGreaterEqual(qualified[i]["opportunity_score"], qualified[i + 1]["opportunity_score"])

        report = build_macro_overview_output(qualified, [])
        self.assertEqual(len(report["industries"]), 5)
        self.assertEqual(report["industries"][0]["industry_id"], "ind_5")

    def test_rejects_company_count_percentage_as_market_growth(self) -> None:
        candidate = copy.deepcopy(SYNTHETIC_FIVE_QUALIFIED[0])
        candidate["growth"]["units"] = "% of companies"
        ok, reason = validate_candidate(candidate)
        self.assertFalse(ok)
        self.assertEqual(reason, "COMPANY_COUNT_PERCENTAGE_CANNOT_BE_MARKET_GROWTH")

        candidate2 = copy.deepcopy(SYNTHETIC_FIVE_QUALIFIED[0])
        candidate2["growth"]["raw_passage"] = "候選家數占比為 50%"
        ok2, reason2 = validate_candidate(candidate2)
        self.assertFalse(ok2)
        self.assertEqual(reason2, "COMPANY_COUNT_PERCENTAGE_CANNOT_BE_MARKET_GROWTH")

    def test_corrupted_growth_metadata_rejected(self) -> None:
        for missing_field in ["units", "period", "publisher", "date"]:
            candidate = copy.deepcopy(SYNTHETIC_FIVE_QUALIFIED[0])
            del candidate["growth"][missing_field]
            ok, reason = validate_candidate(candidate)
            self.assertFalse(ok)
            self.assertEqual(reason, "INCOMPLETE_GROWTH_METADATA")

        # Missing source_id rejected
        candidate_no_src = copy.deepcopy(SYNTHETIC_FIVE_QUALIFIED[0])
        del candidate_no_src["growth"]["source_id"]
        ok, reason = validate_candidate(candidate_no_src)
        self.assertFalse(ok)
        self.assertEqual(reason, "UNADMITTED_GROWTH_SOURCE")

    def test_growth_rate_strict_validation(self) -> None:
        valid_growth = copy.deepcopy(SYNTHETIC_FIVE_QUALIFIED[0]["growth"])
        validate_growth_rate(valid_growth)

        # Invalid date
        bad_date = copy.deepcopy(valid_growth)
        bad_date["date"] = "not-a-date"
        with self.assertRaises(MarketProductValidationError):
            validate_growth_rate(bad_date)

        # Invalid period
        bad_period = copy.deepcopy(valid_growth)
        bad_period["period"] = "future-now"
        with self.assertRaises(MarketProductValidationError):
            validate_growth_rate(bad_period)

        # Missing source binding (no url, no raw_passage)
        no_source = copy.deepcopy(valid_growth)
        no_source["url"] = ""
        no_source["raw_passage"] = ""
        with self.assertRaises(MarketProductValidationError):
            validate_growth_rate(no_source)

        # Missing source_id
        no_source_id = copy.deepcopy(valid_growth)
        del no_source_id["source_id"]
        with self.assertRaises(MarketProductValidationError):
            validate_growth_rate(no_source_id)

    def test_opportunity_rubric_bounded(self) -> None:
        cand = {
            "scores": {
                "demand": 999,
                "chokepoint": 999,
                "pricing": 999,
                "value_chain": 999,
                "catalysts": 999
            }
        }
        score = calculate_opportunity_score(cand)
        self.assertEqual(score, 100)

        cand_neg = {
            "scores": {
                "demand": -10,
                "chokepoint": -10,
                "pricing": -10,
                "value_chain": -10,
                "catalysts": -10
            }
        }
        self.assertEqual(calculate_opportunity_score(cand_neg), 0)

    def test_educational_strategy_arithmetic(self) -> None:
        # 1. Covered Call
        stock_cost = 100.0
        call_strike = 105.0
        call_prem = 3.0
        cc_be = stock_cost - call_prem
        cc_max_profit = (call_strike - stock_cost) + call_prem
        cc_max_loss = stock_cost - call_prem
        self.assertEqual(cc_be, 97.0)
        self.assertEqual(cc_max_profit, 8.0)
        self.assertEqual(cc_max_loss, 97.0)

        # 2. Cash-Secured Put
        put_strike = 90.0
        put_prem = 2.50
        csp_be = put_strike - put_prem
        csp_max_profit = put_prem
        csp_max_loss = put_strike - put_prem
        self.assertEqual(csp_be, 87.50)
        self.assertEqual(csp_max_profit, 2.50)
        self.assertEqual(csp_max_loss, 87.50)

        # 3. Bull Call Spread
        k1, p1 = 100.0, 4.0
        k2, p2 = 110.0, 1.50
        net_debit = p1 - p2
        bcs_be = k1 + net_debit
        bcs_max_profit = (k2 - k1) - net_debit
        bcs_max_loss = net_debit
        self.assertEqual(net_debit, 2.50)
        self.assertEqual(bcs_be, 102.50)
        self.assertEqual(bcs_max_profit, 7.50)
        self.assertEqual(bcs_max_loss, 2.50)

        # 4. Protective Put
        put_prot_strike = 95.0
        put_prot_prem = 3.0
        pp_be = stock_cost + put_prot_prem
        pp_max_loss = (stock_cost - put_prot_strike) + put_prot_prem
        self.assertEqual(pp_be, 103.0)
        self.assertEqual(pp_max_loss, 8.0)

    def test_educational_strategy_validation(self) -> None:
        card = {
            "strategy_id": "protective_put",
            "strategy_name": "保護性賣權",
            "illustrative_ticker": "EXAMPLE",
            "expiry_dte": "30天",
            "strikes": "$95 Put",
            "debit_credit": "$3.00",
            "breakeven": "$103.00",
            "maxprofit": "UNBOUNDED（理論無限）",
            "maxloss": "$8.00",
            "assignment_exercise_risk": "無被動指派風險",
            "appropriate_scenarios": "長線看好",
            "inappropriate_scenarios": "低波動整理",
            "disclaimer": "教學範例，非推薦",
            "status": "SYNTHETIC_EDUCATIONAL",
            "simulated_as_of": "2026-09-14T00:00:00Z",
            "assumptions": {
                "quantity_multiplier": "100股",
                "cost_basis": "$100",
                "collateral": "現股全額持有",
                "premium_fees": "無額外手續費",
                "exercise_assignment_tax": "一般資本損益",
                "specific_caveats": "時間價值耗損"
            }
        }
        validate_educational_strategy(card)

        # Missing UNBOUNDED for protective put
        card_bad = copy.deepcopy(card)
        card_bad["maxprofit"] = "$0.00"
        with self.assertRaises(MarketProductValidationError):
            validate_educational_strategy(card_bad)

    def test_option_quote_validation(self) -> None:
        quote = {
            "ticker": "NVDA",
            "expiry": "2026-09-25",
            "dte": 11,
            "strike": 130.0,
            "type": "call",
            "bid": 2.50,
            "ask": 2.70,
            "mid": 2.60,
            "spread": 0.20,
            "delta": 0.45,
            "iv": 0.48,
            "oi": 1500,
            "volume": 320,
            "breakeven": None,
            "maxprofit": None,
            "maxloss": None,
            "annualized_yield": None,
            "assignment_risk": "無指派風險",
            "liquidity_warning": "流動性良好",
            "timestamp": "2026-09-14T12:00:00Z",
            "quote_basis": "delayed",
            "source": "yfinance",
            "provenance": "PUBLIC_MARKET_TEST",
            "currency": "USD",
            "multiplier": 100,
            "rights_status": "reviewed_public_access",
        }
        validate_option_quote(quote, evaluated_at="2026-09-14T12:00:00Z")

        # Finding A: Bare quote strategy metrics prohibited
        with_be = copy.deepcopy(quote)
        with_be["breakeven"] = 132.60
        with self.assertRaises(MarketProductValidationError):
            validate_option_quote(with_be, evaluated_at="2026-09-14T12:00:00Z")

        # Finding C: Multiplier & Currency check
        bad_curr = copy.deepcopy(quote)
        bad_curr["currency"] = "EUR"
        with self.assertRaises(MarketProductValidationError):
            validate_option_quote(bad_curr, evaluated_at="2026-09-14T12:00:00Z")

        # Expired contract check
        expired = copy.deepcopy(quote)
        expired["expiry"] = "2026-09-10"
        with self.assertRaises(MarketProductValidationError):
            validate_option_quote(expired, evaluated_at="2026-09-14T12:00:00Z")

        # Crossed quotes
        crossed = copy.deepcopy(quote)
        crossed["bid"] = 3.00
        crossed["ask"] = 2.00
        crossed["mid"] = 2.50
        with self.assertRaises(MarketProductValidationError):
            validate_option_quote(crossed, evaluated_at="2026-09-14T12:00:00Z")

        # Negative bid
        negative = copy.deepcopy(quote)
        negative["bid"] = -1.0
        with self.assertRaises(MarketProductValidationError):
            validate_option_quote(negative, evaluated_at="2026-09-14T12:00:00Z")

        # Mid mismatch
        bad_mid = copy.deepcopy(quote)
        bad_mid["mid"] = 99.99
        with self.assertRaises(MarketProductValidationError):
            validate_option_quote(bad_mid, evaluated_at="2026-09-14T12:00:00Z")

        # Stale timestamp
        stale = copy.deepcopy(quote)
        stale["timestamp"] = "2020-01-01T00:00:00Z"
        with self.assertRaises(MarketProductValidationError):
            validate_option_quote(stale, evaluated_at="2026-09-14T12:00:00Z")

        # Future timestamp
        future = copy.deepcopy(quote)
        future["timestamp"] = "2026-09-14T13:00:00Z"
        with self.assertRaises(MarketProductValidationError):
            validate_option_quote(future, evaluated_at="2026-09-14T12:00:00Z")

        # Non-numeric string coercion
        bad_type = copy.deepcopy(quote)
        bad_type["strike"] = "130.0"
        with self.assertRaises(MarketProductValidationError):
            validate_option_quote(bad_type, evaluated_at="2026-09-14T12:00:00Z")

    def test_cli_builder_synthetic_fixture(self) -> None:
        cmd = [
            sys.executable,
            "-B",
            str(ROOT / "scripts" / "build_v213_macro_industry_research.py"),
            "--synthetic-fixture",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="strict", check=True)
        data = json.loads(res.stdout)
        self.assertEqual(data["title"], "TOP5產業總覽")
        self.assertEqual(data["qualified_count"], 5)
        self.assertEqual(data["shortfall"], 0)
        self.assertEqual(data["status"], "ADMITTED_TOP5")
        self.assertEqual(len(data["industries"]), 5)

    def test_covered_call_cycle_timestamp_and_admission(self) -> None:
        from datetime import datetime, timezone, timedelta
        base_dt = datetime(2026, 9, 30, 12, 0, 0, tzinfo=timezone.utc)
        base_stamp = "2026-09-30T12:00:00Z"
        expiry_dt = base_dt + timedelta(days=21)
        valid_cycle = {
            "ticker": "TSM",
            "strategy": "COVERED_CALL",
            "expiry": expiry_dt.date().isoformat(),
            "dte": 21,
            "spot": 300.0,
            "currency": "USD",
            "multiplier": 100,
            "quote_basis": "delayed",
            "timestamp": "2026-09-30T11:30:00Z",
            "source": "Yahoo Finance (unofficial, delayed)",
            "provenance": "https://finance.yahoo.com/quote/TSM/options",
            "rights_status": "unadmitted_third_party",
            "suggestions": [{
                "role": "HIGH_STRIKE",
                "strike": 330.0,
                "bid": 2.0,
                "ask": 2.1,
                "mid": 2.05,
                "limit_price": 2.05,
                "premium_per_contract": 205.0,
                "period_yield": 2.05 / 300.0,
                "annualized_yield": 2.05 / 300.0 * 365 / 21,
                "upside_to_strike": 330.0 / 300.0 - 1,
                "delta": 0.18,
                "delta_basis": "QUOTED_IV",
                "iv": 0.4,
            }],
        }
        # Healthy cycle passes
        validate_covered_call_cycle(copy.deepcopy(valid_cycle), evaluated_at=base_stamp, document_at=base_stamp)

        # Missing timestamp
        no_ts = copy.deepcopy(valid_cycle)
        del no_ts["timestamp"]
        with self.assertRaises(MarketProductValidationError) as ctx:
            validate_covered_call_cycle(no_ts, evaluated_at=base_stamp)
        self.assertEqual(str(ctx.exception), "INVALID_QUOTE_TIMESTAMP")

        # Invalid format / not UTC
        for bad_ts in ["not-a-time", "2026-09-30 12:00:00", "2026-09-30T12:00:00+08:00", "2026-02-30T12:00:00Z"]:
            bad = copy.deepcopy(valid_cycle)
            bad["timestamp"] = bad_ts
            with self.assertRaises(MarketProductValidationError):
                validate_covered_call_cycle(bad, evaluated_at=base_stamp)

        # Future timestamp rejected by publisher
        future = copy.deepcopy(valid_cycle)
        future["timestamp"] = (base_dt + timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self.assertRaises(MarketProductValidationError) as ctx:
            validate_covered_call_cycle(future, evaluated_at=base_stamp)
        self.assertEqual(str(ctx.exception), "FUTURE_TIMESTAMP_REJECTED")

        # Stale timestamp (> 5h) rejected by publisher
        stale = copy.deepcopy(valid_cycle)
        stale["timestamp"] = (base_dt - timedelta(hours=5, seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self.assertRaises(MarketProductValidationError) as ctx:
            validate_covered_call_cycle(stale, evaluated_at=base_stamp)
        self.assertEqual(str(ctx.exception), "STALE_TIMESTAMP_REJECTED")

        # Exactly 5h passes
        at_limit = copy.deepcopy(valid_cycle)
        at_limit["timestamp"] = (base_dt - timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
        validate_covered_call_cycle(at_limit, evaluated_at=base_stamp)

        # Row later than document by > 300s rejected
        late_doc = copy.deepcopy(valid_cycle)
        late_doc["timestamp"] = base_stamp
        with self.assertRaises(MarketProductValidationError) as ctx:
            validate_covered_call_cycle(late_doc, evaluated_at=base_stamp, document_at="2026-09-30T11:54:00Z")
        self.assertEqual(str(ctx.exception), "ROW_TIMESTAMP_LATER_THAN_DOCUMENT")

        # Expired contract rejected
        expired = copy.deepcopy(valid_cycle)
        expired["expiry"] = "2026-09-29"
        with self.assertRaises(MarketProductValidationError) as ctx:
            validate_covered_call_cycle(expired, evaluated_at=base_stamp)
        self.assertEqual(str(ctx.exception), "EXPIRED_CONTRACT_REJECTED")

    def _covered_call_cycle(self, dte: int, expiry: str, timestamp: str = "2026-09-30T11:30:00Z") -> dict:
        spot, limit = 300.0, 2.05
        return {
            "ticker": "TSM", "strategy": "COVERED_CALL", "expiry": expiry, "dte": dte, "spot": spot,
            "currency": "USD", "multiplier": 100, "quote_basis": "delayed", "timestamp": timestamp,
            "source": "Yahoo Finance (unofficial, delayed)", "provenance": "https://finance.yahoo.com/quote/TSM/options",
            "rights_status": "unadmitted_third_party",
            "suggestions": [{
                "role": "HIGH_STRIKE", "strike": 330.0, "bid": 2.0, "ask": 2.1, "mid": 2.05, "limit_price": limit,
                "premium_per_contract": limit * 100, "period_yield": limit / spot,
                "annualized_yield": limit / spot * 365 / dte, "upside_to_strike": 330.0 / spot - 1,
                "delta": 0.18, "delta_basis": "QUOTED_IV", "iv": 0.4,
            }],
        }

    def test_covered_call_period_dte_bucket(self) -> None:
        """B2: a weekly/monthly request must carry a DTE inside its producer bucket (weekly 3-14, monthly 21-45)."""
        from datetime import datetime, timezone, timedelta
        base_dt = datetime(2026, 9, 30, 12, 0, 0, tzinfo=timezone.utc)
        base_stamp = "2026-09-30T12:00:00Z"
        exp = lambda dte: (base_dt + timedelta(days=dte)).date().isoformat()
        # In-bucket boundaries pass for the matching period.
        for dte in (3, 14):
            validate_covered_call_cycle(self._covered_call_cycle(dte, exp(dte)), evaluated_at=base_stamp, period="weekly")
        for dte in (21, 45):
            validate_covered_call_cycle(self._covered_call_cycle(dte, exp(dte)), evaluated_at=base_stamp, period="monthly")
        # Out-of-bucket in both directions is rejected (21-day contract under weekly is the concrete B2 case).
        for dte, period in ((2, "weekly"), (15, "weekly"), (21, "weekly"), (20, "monthly"), (46, "monthly"), (7, "monthly")):
            with self.assertRaises(MarketProductValidationError) as ctx:
                validate_covered_call_cycle(self._covered_call_cycle(dte, exp(dte)), evaluated_at=base_stamp, period=period)
            self.assertEqual(str(ctx.exception), "DTE_OUTSIDE_PERIOD_BUCKET")
        # Without period context the bucket is not enforced (existing callers stay compatible).
        validate_covered_call_cycle(self._covered_call_cycle(7, exp(7)), evaluated_at=base_stamp)
        validate_covered_call_cycle(self._covered_call_cycle(30, exp(30)), evaluated_at=base_stamp)

    def test_covered_call_suggestion_shape_rejected(self) -> None:
        """B5: a non-record suggestion entry raises the domain error instead of an AttributeError."""
        from datetime import datetime, timezone, timedelta
        base_stamp = "2026-09-30T12:00:00Z"
        expiry = (datetime(2026, 9, 30, tzinfo=timezone.utc) + timedelta(days=7)).date().isoformat()
        for bad in ([None], ["not-a-record"], [123]):
            cycle = self._covered_call_cycle(7, expiry)
            cycle["suggestions"] = bad
            with self.assertRaises(MarketProductValidationError) as ctx:
                validate_covered_call_cycle(cycle, evaluated_at=base_stamp, period="weekly")
            self.assertEqual(str(ctx.exception), "COVERED_CALL_SUGGESTION_SHAPE")

    def test_lazy_market_bodies_preserves_healthy_sibling(self) -> None:
        """B5: a malformed one-cycle suggestion marks only that cycle unavailable; the healthy sibling and the whole
        document survive (no AttributeError-driven whole-document collapse to {})."""
        import os
        import tempfile
        from datetime import datetime, timezone, timedelta
        from publish_sealed_snapshot import lazy_market_bodies
        now = datetime(2026, 9, 30, 12, 0, 0, tzinfo=timezone.utc)
        gen = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        ts = (now - timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
        monthly = self._covered_call_cycle(21, (now + timedelta(days=21)).date().isoformat(), timestamp=ts)
        bad_weekly = self._covered_call_cycle(7, (now + timedelta(days=7)).date().isoformat(), timestamp=ts)
        bad_weekly["suggestions"] = [None]  # the AttributeError root cause pre-fix
        doc = {
            "schema": "v213-market-observations-v2", "generated_at": gen,
            "quotes": {"SIVE.ST": {"symbol": "SIVE.ST"}},
            "options": {"TSM": {"monthly": monthly, "weekly": bad_weekly}},
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as handle:
            json.dump(doc, handle)
            path = handle.name
        try:
            bodies = lazy_market_bodies(Path(path), now)
        finally:
            os.unlink(path)
        self.assertIn("v213:options:v2", bodies)  # document not collapsed to {}
        tsm = json.loads(bodies["v213:options:v2"])["options"]["TSM"]
        self.assertEqual(tsm["monthly"]["ticker"], "TSM")  # healthy sibling retained with its real quote
        self.assertIn("unavailable", tsm["weekly"])       # malformed cycle explicitly unavailable
        self.assertNotIn("suggestions", tsm["weekly"])

    def test_covered_call_optional_liquidity_fields_validated(self) -> None:
        """I2 (amendment-02): supplied oi/volume/spread_pct must be a finite non-negative number; a nonfinite value
        (raw JSON 1e309 -> inf), a wrong type or a negative raises the per-cycle domain error, while null/missing stays
        an accepted unknown. Ports the independent probe's rejection assertions into a durable test."""
        base_stamp = "2026-09-30T12:00:00Z"
        from datetime import datetime, timezone, timedelta
        exp = (datetime(2026, 9, 30, tzinfo=timezone.utc) + timedelta(days=21)).date().isoformat()
        # A legitimate null or missing optional field is accepted (stays unknown downstream).
        for field in ("oi", "volume", "spread_pct"):
            ok = self._covered_call_cycle(21, exp)
            ok["suggestions"][0][field] = None
            validate_covered_call_cycle(copy.deepcopy(ok), evaluated_at=base_stamp, period="monthly")
            missing = self._covered_call_cycle(21, exp)
            missing["suggestions"][0].pop(field, None)
            validate_covered_call_cycle(copy.deepcopy(missing), evaluated_at=base_stamp, period="monthly")
            # A finite non-negative value is accepted.
            good = self._covered_call_cycle(21, exp)
            good["suggestions"][0][field] = 0 if field != "spread_pct" else 0.0
            validate_covered_call_cycle(copy.deepcopy(good), evaluated_at=base_stamp, period="monthly")
        # Nonfinite (parsed from raw JSON 1e309), wrong types and negatives are rejected.
        for field in ("oi", "volume", "spread_pct"):
            for value, expected in (
                (float("inf"), "STRICT_FINITE_NUMBER_REQUIRED"),
                (float("nan"), "STRICT_FINITE_NUMBER_REQUIRED"),
                (True, "STRICT_FINITE_NUMBER_REQUIRED"),
                ("5", "STRICT_FINITE_NUMBER_REQUIRED"),
                ([1], "STRICT_FINITE_NUMBER_REQUIRED"),
                ({}, "STRICT_FINITE_NUMBER_REQUIRED"),
                (-1, "INVALID_LIQUIDITY_FIELD"),
            ):
                bad = self._covered_call_cycle(21, exp)
                bad["suggestions"][0][field] = value
                with self.assertRaises(MarketProductValidationError) as ctx:
                    validate_covered_call_cycle(bad, evaluated_at=base_stamp, period="monthly")
                self.assertIn(expected, str(ctx.exception))
                self.assertIn(field, str(ctx.exception))

    def test_publisher_bridge_fixture_is_reproducible(self) -> None:
        """Durable producer->consumer bridge (amendment-02): the committed exact emitted-body fixture must equal a fresh
        regeneration from the real publisher; every case preserves the healthy GOOD sibling and the quote object, and
        no published body ever contains a nonfinite literal. The Worker test consumes the same committed bodies."""
        sys.path.insert(0, str(ROOT / "tests" / "fixtures"))
        import options_global_publisher_cases as bridgegen

        regenerated = bridgegen.serialize(bridgegen.generate_bridge())
        committed = bridgegen.FIXTURE_PATH.read_text(encoding="utf-8")
        self.assertEqual(regenerated, committed, "cloud/test/fixtures/options-global-publisher.json is stale; regenerate "
                         "with python tests/fixtures/options_global_publisher_cases.py")

        bridge = json.loads(committed)
        self.assertEqual(bridge["clock"], "2026-09-30T12:00:00Z")
        admitted = 0
        for name, case in bridge["cases"].items():
            body = case["options_body"]
            self.assertTrue(body, f"{name}: whole document collapsed to empty")
            for token in ("Infinity", "NaN", "1e309"):
                self.assertNotIn(token, body, f"{name}: nonfinite literal leaked into a published body")
            doc = json.loads(body)
            good = doc["options"]["GOOD"]["monthly"]
            self.assertIn("suggestions", good, f"{name}: healthy sibling GOOD lost")
            self.assertIn("TSM", case["quotes_body"], f"{name}: quote object lost")
            tsm = doc["options"]["TSM"][case["period"]]
            self.assertEqual("suggestions" in tsm, case["admitted"])
            admitted += 1 if case["admitted"] else 0
        self.assertEqual(admitted, 6)  # healthy, edge_5h, weekly 3/14, monthly 21/45

        # I2/I2a focus: both the exponent (1e309) and the big-integer (10**309) representation reject only the TSM
        # cycle with an explicit reason; the sibling and quotes survive and no big-integer literal leaks either.
        for prefix in ("overflow_", "bigint_"):
            for field in ("oi", "volume", "spread_pct"):
                case = bridge["cases"][f"{prefix}{field}"]
                self.assertFalse(case["admitted"])
                self.assertTrue(case["sibling_healthy"], f"{prefix}{field}: GOOD sibling lost")
                self.assertNotIn("1" + "0" * 309, case["options_body"], f"{prefix}{field}: big-integer literal leaked")
                tsm = json.loads(case["options_body"])["options"]["TSM"]["monthly"]
                self.assertIn("unavailable", tsm)
                self.assertIn(field, tsm["unavailable"])

    def test_covered_call_numeric_representation_matrix(self) -> None:
        """I2a (round3): the strict-finite helper must translate every out-of-float-range numeric *representation* to the
        per-cycle domain error, not just the exponent spelling. A raw JSON big-integer (10**309) is a valid Python int
        whose float() overflows; before the fix that escaped as an uncaught OverflowError past both the per-cycle and
        the outer publisher handler. This systematically drives the exponent +/-inf, big-integer +/-10**309 and NaN
        across representative required numeric fields (cycle spot and per-suggestion prices) and every optional liquidity
        field, asserting STRICT_FINITE_NUMBER_REQUIRED naming the field each time; the publisher-level healthy-sibling
        survival is proved by the bridge fixture's bigint_* cases."""
        from datetime import datetime, timezone, timedelta
        base_stamp = "2026-09-30T12:00:00Z"
        exp = (datetime(2026, 9, 30, tzinfo=timezone.utc) + timedelta(days=21)).date().isoformat()
        representations = {
            "exponent_pos_inf": float("inf"),   # raw JSON 1e309
            "exponent_neg_inf": float("-inf"),  # raw JSON -1e309
            "bigint_pos": 10 ** 309,            # raw JSON 10**309, overflows float()
            "bigint_neg": -(10 ** 309),         # raw JSON -10**309
            "nan": float("nan"),
        }
        optional_fields = ("oi", "volume", "spread_pct")
        required_suggestion_fields = ("strike", "bid", "ask", "mid", "limit_price")
        for label, value in representations.items():
            for field in optional_fields + required_suggestion_fields:
                bad = self._covered_call_cycle(21, exp)
                bad["suggestions"][0][field] = value
                with self.assertRaises(MarketProductValidationError) as ctx:
                    validate_covered_call_cycle(bad, evaluated_at=base_stamp, period="monthly")
                self.assertIn("STRICT_FINITE_NUMBER_REQUIRED", str(ctx.exception), f"{label}/{field}")
                self.assertIn(field, str(ctx.exception), f"{label}/{field}")
            # Representative required cycle-level numeric field.
            bad_spot = self._covered_call_cycle(21, exp)
            bad_spot["spot"] = value
            with self.assertRaises(MarketProductValidationError) as ctx:
                validate_covered_call_cycle(bad_spot, evaluated_at=base_stamp, period="monthly")
            self.assertIn("STRICT_FINITE_NUMBER_REQUIRED", str(ctx.exception), f"{label}/spot")
            self.assertIn("spot", str(ctx.exception), f"{label}/spot")
        # The matrix does not over-reject: a large-but-representable value and the healthy baseline still pass.
        big_finite = self._covered_call_cycle(21, exp)
        big_finite["suggestions"][0]["oi"] = 10 ** 18  # large yet finite as a float, must stay accepted
        validate_covered_call_cycle(copy.deepcopy(big_finite), evaluated_at=base_stamp, period="monthly")
        validate_covered_call_cycle(self._covered_call_cycle(21, exp), evaluated_at=base_stamp, period="monthly")

if __name__ == "__main__":
    unittest.main()
