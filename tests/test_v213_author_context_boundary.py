"""Author/context-only boundary tests for the v2.1.3 source-independence gate.

Scope (partial enforcement, not full per-claim lineage independence):
known author-view families (serenity_public_source, author_statement) and the
context-only situational-awareness.ai family, plus explicit author-view /
portfolio-disclosure claim types, must stay visible for display but must not
count as company-claim families, must not inflate
``evidence_independence_score``, and must not flip
``eligible_for_high_confidence_model_inference``.

Covers the base ``build_record`` and the actual v4 wrapper import
(v3 -> v4 -> v2 -> core). No network, no providers, no default-cache writes.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE_PATH = ROOT / "scripts" / "v213_source_independence_gate.py"
V4_PATH = ROOT / "scripts" / "v213_source_independence_gate_v4.py"
POLICY_PATH = ROOT / "config" / "v213-serenity-public-logic-policy.json"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader, f"unable to load {path}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


core = _load("ii_author_boundary_core", CORE_PATH)
v4 = _load("ii_author_boundary_v4_wrapper", V4_PATH)

STAMP = (date.today() - timedelta(days=1)).isoformat()
FRESH_AS_OF = STAMP


def _policy() -> dict:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8-sig"))


def _sec_filing(cik: int = 1000100) -> dict:
    return {
        "source_id": "sec_edgar",
        "claim_type": "xbrl_fact",
        "title": "Synthetic 10-K revenue fact",
        "url": (
            "https://www.sec.gov/Archives/edgar/data/"
            f"{cik}/0001000100/synthetic-10k.htm"
        ),
        "as_of": STAMP,
    }


def _serenity_view() -> dict:
    return {
        "source_id": "serenity_public_source",
        "claim_type": "source_view",
        "title": "Serenity public source view (context only)",
        "url": "https://x.com/aleabitoreddit/status/1900000000000000001",
        "as_of": STAMP,
    }


def _leopold_essay() -> dict:
    return {
        "source_id": "leopold_aschenbrenner_essay",
        "claim_type": "macro_scenario_view",
        "title": "Situational-awareness compute scenario essay",
        "url": "https://situational-awareness.ai/essays/compute-power",
        "as_of": STAMP,
    }


def _portfolio_13f() -> dict:
    return {
        "source_id": "sec_edgar",
        "claim_type": "author_portfolio_context",
        "title": "SEC 13F filed as author portfolio context",
        "url": (
            "https://www.sec.gov/Archives/edgar/data/"
            "1000100/0001000100/synthetic-13f.htm"
        ),
        "as_of": STAMP,
    }


def _counterparty_ir() -> dict:
    return {
        "source_id": "counterparty_ir_release",
        "claim_type": "counterparty_filing",
        "title": "Counterparty issuer release",
        "url": "https://investors.counterparty.com/press/synthetic",
        "as_of": STAMP,
    }


def _reuters_context() -> dict:
    return {
        "source_id": "reuters",
        "claim_type": "industry_context",
        "title": "Synthetic independent industry context",
        "url": "https://www.reuters.com/technology/synthetic-1/",
        "as_of": STAMP,
    }


def _fresh_market_observations() -> list:
    """Synthetic dated, comparable, non-conflicting market observations."""
    return [
        core.Observation(
            "stooq_daily_csv",
            "stooq_market",
            "https://stooq.com/q/d/l/?s=abck.us",
            "LIVE",
            f"{STAMP}T00:00:00Z",
            as_of=FRESH_AS_OF,
            long_term_return_pct=20.0,
            short_term_return_pct=5.0,
        ),
        core.Observation(
            "nasdaq_historical_api",
            "nasdaq_market",
            "https://api.nasdaq.com/api/quote/ABCK/historical",
            "LIVE",
            f"{STAMP}T00:00:00Z",
            as_of=FRESH_AS_OF,
            long_term_return_pct=20.2,
            short_term_return_pct=4.8,
        ),
    ]


def _macro() -> dict:
    return {
        "status": "CACHED",
        "url": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10",
        "as_of": STAMP,
    }


def _record(ticker: str, evidence: list) -> dict:
    return {"rank": 1, "ticker": ticker, "as_of": STAMP, "evidence": evidence}


def _report() -> dict:
    return {
        "long_term_return_pct": 20.0,
        "short_term_return_pct": 5.0,
        "retrieved_at": STAMP,
    }


def _scored_metrics(row: dict) -> dict:
    """Metrics that feed the score or claim eligibility (display excluded).

    unique_independent_units counts scored (non-context) sources, so it is
    comparable across baseline/padded rows; only the context-only display
    counters differ by design.
    """
    metrics = dict(row["source_metrics"])
    metrics.pop("context_only_source_count", None)
    metrics.pop("context_only_families", None)
    metrics.pop("total_source_count", None)
    return metrics


STRUCTURAL_FIELDS = (
    "architecture",
    "dependency_graph",
    "bottleneck_or_expansion",
    "company_capture",
    "valuation_expectations",
    "thesis_killers",
    "lifecycle",
    "model_inference_confidence",
)


def _sensitive_serenity_row() -> dict:
    return {
        "source_id": "serenity_public_source",
        "claim_type": "source_view",
        "title": "Bottleneck capacity qualification investment thesis",
        "url": "https://x.com/aleabitoreddit/status/1900000000000000009",
        "as_of": STAMP,
    }


def _author_view_row() -> dict:
    return {
        "source_id": "social_view",
        "claim_type": "author_view",
        "title": "Bottleneck scarcity dependency capacity thesis",
        "url": "https://x.com/someone/status/1900000000000000010",
        "as_of": STAMP,
    }


def _build_one(ticker: str, evidence: list) -> dict:
    return core.build_record(
        _record(ticker, evidence),
        _report(),
        {"current_order_source_urls": [], "future_order_source_urls": []},
        _fresh_market_observations(),
        _policy(),
        _macro(),
    )


class FamilyClassificationTests(unittest.TestCase):
    def test_misleading_source_id_on_known_author_host_is_context_only(self) -> None:
        # Host wins over a misleading source-id hint.
        self.assertEqual(
            core.family_for(
                "sec_edgar_verified_filing",
                "https://x.com/aleabitoreddit/status/1",
            ),
            "author_statement",
        )
        self.assertEqual(
            core.family_for(
                "issuer_disclosure",
                "https://twitter.com/leopoldaschenbrenner/status/2",
            ),
            "author_statement",
        )
        self.assertEqual(
            core.family_for(
                "nasdaq_issuer_notice",
                "https://blog.situational-awareness.ai/2026/essay",
            ),
            "situational_context",
        )

    def test_domain_matching_is_exact_and_subdomain_safe(self) -> None:
        # Not substring matching against arbitrary URLs.
        self.assertNotEqual(
            core.family_for("author", "https://notx.com/post/1"),
            "author_statement",
        )
        self.assertNotEqual(
            core.family_for("author", "https://nottwitter.com/post/1"),
            "author_statement",
        )
        self.assertNotEqual(
            core.family_for("essay", "https://notsituational-awareness.ai/e"),
            "situational_context",
        )
        # Canonical official domains keep their families.
        self.assertEqual(
            core.family_for(
                "serenity_public_source",
                "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany",
            ),
            "regulator_filing",
        )
        self.assertEqual(
            core.family_for(
                "fred_official_macro",
                "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10",
            ),
            "official_macro",
        )


class BuildRecordBoundaryTests(unittest.TestCase):
    def test_sec_plus_serenity_view_does_not_inflate_claims(self) -> None:
        baseline = _build_one("ABCK", [_sec_filing()])
        enriched = _build_one("ABCK", [_sec_filing(), _serenity_view()])

        self.assertEqual(
            baseline["source_metrics"]["claim_relevant_independent_families"], 1
        )
        self.assertEqual(
            enriched["source_metrics"]["claim_relevant_independent_families"], 1
        )
        self.assertEqual(
            enriched["source_metrics"]["claim_relevant_primary_sources"], 1
        )
        self.assertFalse(
            enriched["eligible_for_high_confidence_model_inference"],
            "an author view must not flip high-confidence eligibility",
        )
        self.assertEqual(
            baseline["evidence_independence_score"],
            enriched["evidence_independence_score"],
        )
        self.assertEqual(
            baseline["source_metrics"]["maximum_single_family_share"],
            enriched["source_metrics"]["maximum_single_family_share"],
        )
        # Display visibility is preserved.
        urls = [str(item["url"]) for item in enriched["sources"]]
        self.assertIn("https://x.com/aleabitoreddit/status/1900000000000000001", urls)
        # Honest status: attached but never company-claim proof.
        self.assertNotEqual(
            enriched["public_logic_state"]["serenity_source_view"], "SUPPORTED"
        )
        self.assertEqual(
            enriched["public_logic_state"]["serenity_source_view"],
            "CONTEXT_ONLY_UNVERIFIED",
        )
        self.assertEqual(
            baseline["public_logic_state"]["serenity_source_view"], "NOT_ATTACHED"
        )

    def test_sec_plus_leopold_situational_context_excluded(self) -> None:
        enriched = _build_one("ABCK", [_sec_filing(), _leopold_essay()])
        self.assertEqual(
            enriched["source_metrics"]["claim_relevant_independent_families"], 1
        )
        self.assertFalse(
            enriched["eligible_for_high_confidence_model_inference"]
        )
        families = enriched["source_metrics"]["families"]
        self.assertNotIn("situational_context", families)
        urls = [str(item["url"]) for item in enriched["sources"]]
        self.assertIn("https://situational-awareness.ai/essays/compute-power", urls)
        self.assertEqual(
            enriched["source_metrics"]["context_only_source_count"], 1
        )

    def test_misleading_sec_id_on_author_host_is_not_claim_primary(self) -> None:
        record = {
            "rank": 1,
            "ticker": "ABCK",
            "as_of": STAMP,
            "evidence": [
                _sec_filing(),
                {
                    "source_id": "sec_edgar_author_view",
                    "claim_type": "source_view",
                    "title": "Misleading id on an X post",
                    "url": "https://x.com/aleabitoreddit/status/1900000000000000002",
                    "as_of": STAMP,
                },
            ],
        }
        built = core.build_record(
            record,
            _report(),
            {"current_order_source_urls": [], "future_order_source_urls": []},
            _fresh_market_observations(),
            _policy(),
            _macro(),
        )
        self.assertEqual(
            built["source_metrics"]["claim_relevant_independent_families"], 1
        )
        self.assertEqual(
            built["source_metrics"]["claim_relevant_primary_sources"], 1
        )
        self.assertFalse(built["eligible_for_high_confidence_model_inference"])

    def test_sec_13f_portfolio_disclosure_is_context_only(self) -> None:
        built = _build_one("ABCK", [_sec_filing(), _portfolio_13f()])
        self.assertEqual(
            built["source_metrics"]["claim_relevant_independent_families"], 1
        )
        self.assertEqual(
            built["source_metrics"]["claim_relevant_primary_sources"], 1
        )
        self.assertEqual(
            built["public_logic_state"]["serenity_source_view"], "NOT_ATTACHED"
        )
        urls = [str(item["url"]) for item in built["sources"]]
        self.assertIn(
            "https://www.sec.gov/Archives/edgar/data/"
            "1000100/0001000100/synthetic-13f.htm",
            urls,
        )
        self.assertEqual(
            built["source_metrics"]["context_only_source_count"], 1
        )

    def test_baseline_vs_author_context_identity(self) -> None:
        baseline = _build_one("ABCK", [_sec_filing(), _reuters_context()])
        enriched = _build_one(
            "ABCK",
            [
                _sec_filing(),
                _reuters_context(),
                _serenity_view(),
                _leopold_essay(),
                _portfolio_13f(),
            ],
        )
        self.assertFalse(
            baseline["eligible_for_high_confidence_model_inference"],
            "legacy source inventory lacks exact current claim bindings",
        )
        self.assertEqual(
            baseline["evidence_independence_score"],
            enriched["evidence_independence_score"],
        )
        self.assertEqual(
            _scored_metrics(baseline), _scored_metrics(enriched)
        )
        self.assertEqual(
            enriched["source_metrics"]["context_only_source_count"], 3
        )
        self.assertEqual(
            baseline["source_metrics"]["context_only_source_count"], 0
        )
        self.assertEqual(
            enriched["source_metrics"]["claim_relevant_independent_families"], 2
        )
        self.assertFalse(
            enriched["eligible_for_high_confidence_model_inference"]
        )

    def test_legitimate_counterparty_evidence_still_counts(self) -> None:
        built = _build_one("ABCK", [_sec_filing(), _counterparty_ir()])
        self.assertEqual(
            built["source_metrics"]["claim_relevant_independent_families"], 2
        )
        self.assertEqual(
            built["source_metrics"]["claim_relevant_primary_sources"], 2
        )
        self.assertFalse(
            built["eligible_for_high_confidence_model_inference"],
            "issuer/counterparty inventory counts survive but cannot replace exact claim proof",
        )
        with_views = _build_one(
            "ABCK",
            [_sec_filing(), _counterparty_ir(), _serenity_view(), _leopold_essay()],
        )
        self.assertEqual(
            built["evidence_independence_score"],
            with_views["evidence_independence_score"],
        )
        self.assertEqual(
            with_views["source_metrics"]["claim_relevant_independent_families"], 2
        )
        self.assertFalse(
            with_views["eligible_for_high_confidence_model_inference"]
        )


def _top20_rows(extra_by_ticker: dict) -> list:
    rows = []
    for index in range(20):
        ticker = f"T{index:02d}"
        evidence = [_sec_filing(1000100 + index), _reuters_context()]
        evidence.extend(extra_by_ticker.get(ticker, []))
        rows.append(_record(ticker, evidence))
    return rows


def _run_v4(tmp: Path, name: str, extra_by_ticker: dict) -> dict:
    top20_path = tmp / f"{name}_top20.json"
    report_path = tmp / f"{name}_report.json"
    order_path = tmp / f"{name}_order.json"
    top20_path.write_text(
        json.dumps(_top20_rows(extra_by_ticker)), encoding="utf-8"
    )
    report_path.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "ticker": f"T{index:02d}",
                        "long_term_return_pct": 20.0,
                        "short_term_return_pct": 5.0,
                        "retrieved_at": STAMP,
                    }
                    for index in range(20)
                ]
            }
        ),
        encoding="utf-8",
    )
    order_path.write_text(json.dumps({"records": []}), encoding="utf-8")

    top20 = core.extract_rows(json.loads(top20_path.read_text(encoding="utf-8")))
    reports = core.index_records(json.loads(report_path.read_text(encoding="utf-8")))
    orders = core.index_records(json.loads(order_path.read_text(encoding="utf-8")))
    result, _updated_cache = v4.gate.build(
        top20, reports, orders, _policy(), {}, True
    )
    return result


class V4WrapperBoundaryTests(unittest.TestCase):
    def test_wrapper_import_is_the_patched_active_build(self) -> None:
        # v4 re-exports the core module as `gate` and wraps its build.
        self.assertTrue(hasattr(v4.gate, "build"))
        self.assertNotEqual(
            v4.gate.build.__name__, "build",
            "v4 must wrap the core build with market-quality degradation",
        )

    def test_author_context_neutral_at_v4_consumer(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ii-author-boundary-") as tmp:
            tmp_path = Path(tmp)
            baseline = _run_v4(tmp_path, "baseline", {})
            enriched = _run_v4(
                tmp_path,
                "enriched",
                {
                    "T00": [
                        _serenity_view(),
                        _leopold_essay(),
                        _portfolio_13f(),
                    ]
                },
            )

            for doc in (baseline, enriched):
                for record in doc["records"]:
                    self.assertNotEqual(
                        record["public_logic_state"]["serenity_source_view"],
                        "SUPPORTED",
                    )

            base_rows = {
                str(row["ticker"]): row for row in baseline["records"]
            }
            rich_rows = {
                str(row["ticker"]): row for row in enriched["records"]
            }
            for ticker in base_rows:
                self.assertEqual(
                    base_rows[ticker]["evidence_independence_score"],
                    rich_rows[ticker]["evidence_independence_score"],
                    ticker,
                )
                self.assertEqual(
                    _scored_metrics(base_rows[ticker]),
                    _scored_metrics(rich_rows[ticker]),
                    ticker,
                )
                self.assertEqual(
                    base_rows[ticker]["eligible_for_high_confidence_model_inference"],
                    rich_rows[ticker]["eligible_for_high_confidence_model_inference"],
                    ticker,
                )

            t00 = rich_rows["T00"]
            self.assertEqual(
                rich_rows["T00"]["source_metrics"]["unique_independent_units"],
                base_rows["T00"]["source_metrics"]["unique_independent_units"],
                "scored unit count must not rise with author padding",
            )
            self.assertEqual(
                len(t00["sources"]),
                len(base_rows["T00"]["sources"]) + 3,
                "author views remain visible in the display source list",
            )
            self.assertEqual(
                t00["public_logic_state"]["serenity_source_view"],
                "CONTEXT_ONLY_UNVERIFIED",
            )
            urls = [str(item["url"]) for item in t00["sources"]]
            self.assertIn("https://x.com/aleabitoreddit/status/1900000000000000001", urls)
            self.assertIn("https://situational-awareness.ai/essays/compute-power", urls)
            self.assertEqual(
                t00["source_metrics"]["context_only_source_count"], 3
            )
            self.assertEqual(
                enriched["portfolio"]["context_only_source_count"], 3
            )
            self.assertEqual(
                baseline["portfolio"]["context_only_source_count"], 0
            )
            # No high-confidence upgrade anywhere from added views.
            self.assertEqual(
                baseline["portfolio"]["high_confidence_model_inference_eligible_count"],
                enriched["portfolio"]["high_confidence_model_inference_eligible_count"],
            )


class StructuralStateBoundaryTests(unittest.TestCase):
    """Author padding (title/claim-type) must not flip public-logic
    structural states or scored metrics (slice-3 regression)."""

    def test_author_view_sensitive_title_does_not_flip_structural_state(self) -> None:
        baseline = _build_one("ABCK", [_sec_filing(), _counterparty_ir()])
        padded = _build_one(
            "ABCK",
            [_sec_filing(), _counterparty_ir(), _sensitive_serenity_row()],
        )
        # Legacy independent inventory is not an exact corroborated claim.
        # No sensitive company claim -> structural fields UNPROVEN.
        self.assertFalse(
            baseline["eligible_for_high_confidence_model_inference"]
        )
        self.assertFalse(baseline["sensitive_claim_present"])
        for field in ("architecture", "dependency_graph", "bottleneck_or_expansion"):
            self.assertEqual(baseline["public_logic_state"][field], "UNPROVEN")
        # An author X view with a sensitive title must not flip anything.
        self.assertFalse(padded["sensitive_claim_present"])
        for field in STRUCTURAL_FIELDS:
            self.assertEqual(
                padded["public_logic_state"][field],
                baseline["public_logic_state"][field],
                field,
            )
        self.assertEqual(
            baseline["evidence_independence_score"],
            padded["evidence_independence_score"],
        )
        self.assertEqual(_scored_metrics(baseline), _scored_metrics(padded))
        self.assertEqual(baseline["missing_or_review"], padded["missing_or_review"])

    def test_author_context_claim_type_sensitive_title_excluded(self) -> None:
        baseline = _build_one("ABCK", [_sec_filing(), _counterparty_ir()])
        padded = _build_one(
            "ABCK", [_sec_filing(), _counterparty_ir(), _author_view_row()]
        )
        self.assertFalse(padded["sensitive_claim_present"])
        self.assertEqual(
            padded["public_logic_state"]["bottleneck_or_expansion"], "UNPROVEN"
        )
        self.assertEqual(_scored_metrics(baseline), _scored_metrics(padded))

    def test_company_sensitive_title_without_exact_claim_stays_unproven(self) -> None:
        row = {
            "source_id": "counterparty_ir_release",
            "claim_type": "counterparty_filing",
            "title": "Bottleneck capacity qualification investment thesis",
            "url": "https://investors.counterparty.com/press/synthetic-sensitive",
            "as_of": STAMP,
        }
        built = _build_one("ABCK", [_sec_filing(), row])
        self.assertTrue(built["sensitive_claim_present"])
        self.assertEqual(
            built["public_logic_state"]["bottleneck_or_expansion"],
            "UNPROVEN",
        )
        self.assertEqual(
            built["public_logic_state"]["architecture"], "UNPROVEN"
        )
        self.assertEqual(
            built["source_metrics"]["claim_relevant_independent_families"], 2
        )

    def test_v4_author_padding_neutral(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ii-struct-boundary-") as tmp:
            tmp_path = Path(tmp)
            baseline = _run_v4(tmp_path, "struct_baseline", {})
            padded = _run_v4(
                tmp_path,
                "struct_padded",
                {"T00": [_sensitive_serenity_row(), _author_view_row()]},
            )
            base_rows = {str(r["ticker"]): r for r in baseline["records"]}
            rich_rows = {str(r["ticker"]): r for r in padded["records"]}
            for ticker in base_rows:
                self.assertEqual(
                    base_rows[ticker]["sensitive_claim_present"],
                    rich_rows[ticker]["sensitive_claim_present"],
                    ticker,
                )
                for field in STRUCTURAL_FIELDS:
                    self.assertEqual(
                        base_rows[ticker]["public_logic_state"][field],
                        rich_rows[ticker]["public_logic_state"][field],
                        f"{ticker}:{field}",
                    )
                self.assertEqual(
                    _scored_metrics(base_rows[ticker]),
                    _scored_metrics(rich_rows[ticker]),
                    ticker,
                )
            t00 = rich_rows["T00"]
            self.assertFalse(t00["sensitive_claim_present"])
            self.assertEqual(
                t00["source_metrics"]["unique_independent_units"],
                base_rows["T00"]["source_metrics"]["unique_independent_units"],
            )
            self.assertEqual(
                len(t00["sources"]),
                len(base_rows["T00"]["sources"]) + 2,
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
