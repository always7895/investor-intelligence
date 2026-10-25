"""Nasdaq historical corroboration: ISO query dates (the API rejects MM/DD/YYYY since 2026-09), MM/DD/YYYY rows. No network."""
from __future__ import annotations

import datetime as dt
import json
import sys
import unittest
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import v213_multi_source_fidelity as fidelity  # noqa: E402
import v213_source_independence_gate as gate  # noqa: E402


def payload(days: int = 800) -> str:
    today = dt.date.today()
    rows = [{"date": (today - dt.timedelta(days=offset)).strftime("%m/%d/%Y"), "close": f"${100 + offset / 10:.2f}"}
            for offset in range(1, days, 7)]
    return json.dumps({"data": {"tradesTable": {"rows": rows}}, "status": {"rCode": 200}})


class NasdaqHistoricalQueryTests(unittest.TestCase):
    def check_query(self, url: str) -> None:
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        for key in ("fromdate", "todate"):
            dt.date.fromisoformat(query[key][0])  # ISO, never 07/18/2024

    def test_gate_sends_iso_dates_and_parses_slash_rows(self):
        seen = []
        saved = gate.fetch_text
        gate.fetch_text = lambda url, *args, **kwargs: seen.append(url) or payload()
        try:
            observation = gate.observe_nasdaq("NVDA")
        finally:
            gate.fetch_text = saved
        self.check_query(seen[0])
        self.assertEqual(observation.status, "LIVE")

    def test_gate_reports_the_api_rejection_as_unavailable(self):
        saved = gate.fetch_text
        gate.fetch_text = lambda url, *args, **kwargs: json.dumps({"data": None, "status": {"rCode": 400}})
        try:
            observation = gate.observe_nasdaq("NVDA")
        finally:
            gate.fetch_text = saved
        self.assertEqual(observation.status, "UNAVAILABLE")

    def test_fidelity_sends_iso_dates(self):
        seen = []
        original = fidelity.urllib.request.urlopen

        class Response:
            def __init__(self, body):
                self.body = body.encode("utf-8")

            def read(self, *args):
                return self.body

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def fake_urlopen(request, *args, **kwargs):
            seen.append(getattr(request, "full_url", request))
            return Response(payload())
        fidelity.urllib.request.urlopen = fake_urlopen
        try:
            fidelity.observe_nasdaq("NVDA")
        finally:
            fidelity.urllib.request.urlopen = original
        self.assertTrue(seen)
        self.check_query(seen[0])


if __name__ == "__main__":
    unittest.main()
