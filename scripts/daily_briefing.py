#!/usr/bin/env python3
"""Local-only daily market briefing orchestrator.

This local-only pipeline may use an ignored local research universe and an
explicitly enabled loopback-only IBKR read-only provider. Its output is local
only and is never delivered to LINE, Worker, public KV or another tenant.
Shared LINE replies are produced exclusively by the public-only Worker path.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.join(BASE_DIR, "scripts")
DATA_DIR = os.path.join(BASE_DIR, "data", "cache")

sys.path.insert(0, SCRIPTS_DIR)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(BASE_DIR, "daily_briefing.log"), encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("daily_briefing")


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def run_step(name, func, *args, required: bool = False, **kwargs):
    logger.info("=== STEP: %s ===", name)
    started = time.monotonic()
    try:
        result = func(*args, **kwargs)
    except Exception:
        logger.exception("=== %s FAILED ===", name)
        if required:
            raise
        return None
    logger.info("=== %s completed in %.1fs ===", name, time.monotonic() - started)
    return result


def save_indices(indices):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(os.path.join(DATA_DIR, "indices_latest.json"), "w", encoding="utf-8") as handle:
        json.dump(indices, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def main() -> int:
    logger.info("=" * 60)
    logger.info("LOCAL DAILY BRIEFING START - %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("=" * 60)

    try:
        from fetch_market import fetch_all, fetch_market_indices

        indices = run_step("Market Indices", fetch_market_indices) or {}
        run_step("Save Indices", save_indices, indices, required=True)

        market_data = run_step("Market Data (Local Research Universe)", fetch_all, required=True)
        if not market_data:
            raise RuntimeError("No market data fetched")

        # Local IBKR read-only data may be used here when explicitly enabled.
        # No order path exists and this local result can never enter LINE/public KV.
        from options_service import fetch_options

        options_data = run_step("Local Options BID/ASK (Weekly + Monthly)", fetch_options) or []

        from render_options_report import render_options_report

        run_step(
            "Render Local Weekly/Monthly BID-ASK Options Report",
            render_options_report,
            options_data,
            required=True,
        )

        from score_stocks import score_all

        scores = run_step("Scoring & Ranking", score_all, required=True)
        if not scores:
            raise RuntimeError("No stocks were scored")

        from active_scan import run_active_scan

        run_step(
            "Active Scan",
            run_active_scan,
            apply=env_bool("ACTIVE_SCAN_APPLY_CHANGES", False),
            required=True,
        )

        from scan_movers import scan_sp500_movers, scan_watchlist_moves

        movers = run_step("Scan Movers", scan_sp500_movers) or []
        watch_moves = run_step("Local Research Universe Moves", scan_watchlist_moves) or []

        from generate_report import generate_report

        report_path = run_step(
            "Generate Local Report",
            generate_report,
            indices,
            market_data,
            scores,
            options_data,
            movers,
            watch_moves,
            required=True,
        )
        if not report_path:
            raise RuntimeError("Report generation returned no path")

        logger.info("Local report generated; external delivery is structurally unavailable")

    except Exception:
        logger.exception("LOCAL DAILY BRIEFING FAILED")
        return 1

    logger.info("LOCAL DAILY BRIEFING COMPLETE - %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
