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


if __name__ == "__main__":
    unittest.main()
