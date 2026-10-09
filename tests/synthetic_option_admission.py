"""Explicit SYNTHETIC-only rights seam; real validator/sealer stay in use.

Never changes the canonical catalog. Tests must separately exercise the default
rights-NONE path outside this context; this grants no public-data admission.
"""
from contextlib import contextmanager
from unittest.mock import patch

import public_options_provider_gate as rights


@contextmanager
def synthetic_option_admission(tickers):
    admitted = frozenset(tickers)
    if not admitted or any(not isinstance(ticker, str) or not ticker for ticker in admitted):
        raise ValueError("SYNTHETIC_TICKER_SET_REQUIRED")
    real = rights.public_option_cycle_admission

    def admit(cycle, policy):
        if isinstance(cycle, dict) and cycle.get("ticker") in admitted:
            return None
        return real(cycle, policy)

    with patch.object(rights, "public_option_cycle_admission", side_effect=admit):
        yield
