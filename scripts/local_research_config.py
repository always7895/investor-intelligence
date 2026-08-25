#!/usr/bin/env python3
"""Load local-only research configuration without committing owner data.

Repository-tracked owner watchlists and preference files are forbidden. Local
research tools may read explicitly supplied paths or the ignored
``config/*.local.json`` defaults below. Shared LINE/Worker code must never import
this module.
"""
from __future__ import annotations

import copy
import json
import os
import re
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parents[1]
CONFIG_DIR = BASE_DIR / "config"
DEFAULT_LOCAL_UNIVERSE_PATH = CONFIG_DIR / "research-universe.local.json"
DEFAULT_LOCAL_PREFERENCES_PATH = CONFIG_DIR / "user-preferences.local.json"
UNIVERSE_ENV = "LOCAL_RESEARCH_UNIVERSE_PATH"
PREFERENCES_ENV = "LOCAL_USER_PREFERENCES_PATH"
TICKER_RE = re.compile(r"^[A-Z0-9][A-Z0-9.-]{0,14}$")

DEFAULT_LOCAL_PREFERENCES: dict[str, Any] = {
    "schema_version": 1,
    "privacy_class": "local_user_configuration",
    "long_term_overlay": {
        "enabled": False,
        "minimum_holding_years": 2,
        "owner": "local_user",
        "affects_source_view": False,
        "affects_methodology_research_score": False,
        "report_title": "Local user-defined long-term suitability overlay",
        "labels": {
            "high": "較適合長期研究",
            "conditional": "條件式長期觀察",
            "event_driven": "偏事件／交易型",
            "insufficient": "資料不足",
        },
    },
}


class LocalResearchConfigError(ValueError):
    """Raised when a local-only configuration file is malformed or unsafe."""


def _selected_path(
    explicit: Path | str | None,
    *,
    environment_name: str,
    default: Path,
) -> Path:
    raw = explicit if explicit is not None else os.getenv(environment_name)
    return Path(raw).expanduser() if raw else default


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(
            f"{label} is required at an explicit local path; copy the reviewed "
            f"example to an ignored *.local.json file: {path}"
        )
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise LocalResearchConfigError(f"{label} is invalid JSON") from exc
    if not isinstance(document, dict):
        raise LocalResearchConfigError(f"{label} must contain an object")
    return document


def load_research_universe(path: Path | str | None = None) -> list[dict[str, Any]]:
    source = _selected_path(
        path,
        environment_name=UNIVERSE_ENV,
        default=DEFAULT_LOCAL_UNIVERSE_PATH,
    )
    document = _load_json_object(source, "Local research universe")
    allowed_top = {"schema_version", "privacy_class", "updated", "stocks"}
    unknown_top = sorted(set(document).difference(allowed_top))
    if unknown_top:
        raise LocalResearchConfigError(
            "Local research universe has unknown top-level field(s): "
            + ", ".join(unknown_top)
        )
    if document.get("privacy_class", "local_user_configuration") != "local_user_configuration":
        raise LocalResearchConfigError(
            "Local research universe must declare privacy_class=local_user_configuration"
        )
    stocks = document.get("stocks")
    if not isinstance(stocks, list) or not stocks:
        raise LocalResearchConfigError(
            "Local research universe must contain a non-empty stocks array"
        )

    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(stocks):
        if not isinstance(item, dict):
            raise LocalResearchConfigError(
                f"Local research universe stock {index} must be an object"
            )
        ticker = str(item.get("ticker") or "").strip().upper()
        if not TICKER_RE.fullmatch(ticker) or ".." in ticker or ticker.endswith(('.', '-')):
            raise LocalResearchConfigError(
                f"Local research universe stock {index} has an invalid ticker"
            )
        if ticker in seen:
            raise LocalResearchConfigError(f"Duplicate local research ticker: {ticker}")
        seen.add(ticker)
        normalized.append({**item, "ticker": ticker})
    return normalized


def load_local_preferences(
    path: Path | str | None = None,
    *,
    default: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source = _selected_path(
        path,
        environment_name=PREFERENCES_ENV,
        default=DEFAULT_LOCAL_PREFERENCES_PATH,
    )
    fallback = copy.deepcopy(default or DEFAULT_LOCAL_PREFERENCES)
    if not source.is_file():
        return fallback
    document = _load_json_object(source, "Local user preferences")
    if document.get("privacy_class", "local_user_configuration") != "local_user_configuration":
        raise LocalResearchConfigError(
            "Local user preferences must declare privacy_class=local_user_configuration"
        )
    overlay = document.get("long_term_overlay")
    if overlay is not None and not isinstance(overlay, dict):
        raise LocalResearchConfigError("long_term_overlay must be an object")
    return document
