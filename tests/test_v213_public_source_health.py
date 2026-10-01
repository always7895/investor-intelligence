"""Fail-closed archive-metadata health admission for the v2.1.3 public-source refresh.

The canonical Serenity public-post archive is author-statement/research-lead
material. Its upstream ``sync_state.json`` carries bounded ``source_health``
metadata in which the cursor fields ``latest_returned_id`` /
``latest_returned_time`` are NESTED inside ``source_health`` (actual upstream
schema). Root-level cursor fields are ignored and can never override the
nested values.

A fresh failure-only commit (stale_unverified / unverified health) must NOT be
promoted to ``latest_available_verified=True``. Only the reviewed positive
status/freshness/direct_status/verification_source pairing qualifies, with
checked-time age inside the existing 24h window/skew, sync-update ordering and
nested-cursor consistency.

Cache fallback is permitted ONLY for pure transport failure and ONLY when the
cached document re-validates through the same shared validator: contract
flags (latest_available_verified / source_health_admitted / verification_scope)
are necessary but never sufficient. Invalid live evidence (unparseable or
non-dict sync_state, malformed source_health, unreviewed shapes) is a refusal,
never a transport fallback.

Determinism: the script's ``utc_now`` is patched to ``FIXED_NOW`` for every
build/main call; every fixture timestamp derives from it. All IO is confined
to TemporaryDirectory.
"""
from __future__ import annotations

import base64
import contextlib
import importlib.util
import io
import json
import os
import socket
import sys
import tempfile
import unittest
import unittest.mock
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "v213_refresh_serenity_public_sources.py"
PY312 = ROOT.parent / "audit-runtime" / "python312" / "python.exe"


def _load(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


mod = _load("ii_public_source_health", SCRIPT_PATH)

HEAD_SHA = "b3784cb591025a2881a33cff76db2c01a064fc36"

# ---------------------------------------------------------------------------
# Deterministic synthetic clock. Every fixture time derives from FIXED_NOW.
# ---------------------------------------------------------------------------
FIXED_NOW = datetime(2026, 9, 12, 3, 0, 0, tzinfo=timezone.utc)
NOW_ISO = "2026-09-12T03:00:00Z"          # FIXED_NOW
COMMIT_DATE = "2026-09-12T01:30:00Z"      # 1.5h before FIXED_NOW
LAST_TWEET_ID = "2097815176838017066"
LAST_UPDATE_TIME = "2026-09-12T01:00:00Z"  # 2h before FIXED_NOW
CHECKED_TIME = "2026-09-12T02:00:00Z"      # 1h before FIXED_NOW
STALE_CHECKED = "2026-09-11T02:00:00Z"     # 25h before FIXED_NOW
FUTURE_CHECKED = "2026-09-12T05:00:00Z"    # 2h after FIXED_NOW

REVIEWED = {
    "status": "available_fallback",
    "direct_status": "stale_unverified",
    "freshness": "new_posts",
    "verification_source": "x_public_profile+jina_status",
}


def _fixed_clock():
    return unittest.mock.patch.object(mod, "utc_now", lambda: FIXED_NOW)


def _failing_fetcher(url: str) -> Any:
    # Faithful transport failure: api_json surfaces acquisition/network
    # errors as PublicSourceTransportError, the genuine (and only) failure
    # class main() treats as transport (cache fallback).
    raise mod.PublicSourceTransportError(
        f"GitHub API request failed: {url}: URLError"
    )


def _ordering_fetcher(
    sync_content: bytes,
    aux_transport: bool = False,
) -> tuple[Callable[[str], Any], list[str]]:
    """Fake fetcher serving every configured repository from the shared
    payload table while recording the exact request order.

    With ``aux_transport=True`` the fetcher raises the genuine
    PublicSourceTransportError for every non-canonical repository URL while
    the canonical URLs still resolve (the post-fix build must never reach
    them, so the trap stays disarmed).
    """
    payloads = _payloads(sync_content)
    calls: list[str] = []
    canonical_repo = [
        repo for repo, is_canonical in mod.REPOSITORIES if is_canonical
    ][0]
    prefix = f"{mod.API}/repos/{canonical_repo}"

    def fetcher(url: str) -> Any:
        calls.append(url)
        if aux_transport and not (url == prefix or url.startswith(prefix + "/")):
            raise mod.PublicSourceTransportError(
                f"GitHub API request failed: {url}: URLError"
            )
        return payloads[url]

    return fetcher, calls


def _bare_recording_fetcher() -> tuple[Callable[[str], Any], list[str]]:
    """Fetcher that records any call and fails loudly if one happens."""
    calls: list[str] = []

    def fetcher(url: str) -> Any:
        calls.append(url)
        raise AssertionError(f"fetch must not be called: {url}")

    return fetcher, calls


# ---------------------------------------------------------------------------
# Synthetic upstream fixtures (fake fetchers only; no network).
# ---------------------------------------------------------------------------
def _payloads(sync_content: bytes) -> dict[str, Any]:
    payloads: dict[str, Any] = {}
    for repo, canonical in mod.REPOSITORIES:
        payloads[f"{mod.API}/repos/{repo}"] = {
            "default_branch": "main",
            "pushed_at": COMMIT_DATE,
            "updated_at": COMMIT_DATE,
            "license": {"spdx_id": "MIT"},
        }
        sha = HEAD_SHA if canonical else "c" * 40
        payloads[f"{mod.API}/repos/{repo}/commits/main"] = {
            "sha": sha,
            "commit": {"committer": {"date": COMMIT_DATE}},
        }
        if canonical:
            payloads[
                f"{mod.API}/repos/{repo}/contents/data/sync_state.json?ref={sha}"
            ] = {
                "content": base64.b64encode(sync_content).decode("ascii"),
                "encoding": "base64",
            }
    return payloads


def _fetch_doc(sync_doc: dict[str, Any]) -> Callable[[str], Any]:
    payloads = _payloads(json.dumps(sync_doc).encode("utf-8"))
    return lambda url: payloads[url]


def _build(sync_doc: dict[str, Any]) -> dict[str, Any]:
    with _fixed_clock():
        return mod.build(_fetch_doc(sync_doc))


def _build_with_fetcher(fetcher: Callable[[str], Any]) -> dict[str, Any]:
    with _fixed_clock():
        return mod.build(fetcher)


def _positive_sync(
    *,
    checked_time: str = CHECKED_TIME,
    last_tweet_id: str = LAST_TWEET_ID,
    last_update_time: str = LAST_UPDATE_TIME,
    status: str | None = REVIEWED["status"],
    freshness: str | None = REVIEWED["freshness"],
    direct_status: str | None = REVIEWED["direct_status"],
    verification_source: str | None = REVIEWED["verification_source"],
    include_cursor: bool = True,
    cursor_id: str | None = None,
    cursor_time: str | None = None,
    omit: tuple[str, ...] = (),
    extra_health: dict[str, Any] | None = None,
    root_cursor_id: str | None = None,
    root_cursor_time: str | None = None,
    health_override: Any = None,
) -> dict[str, Any]:
    """Pinned observed positive shape: cursor NESTED in source_health.

    ``root_cursor_*`` optionally add WRONG-schema root-level cursor fields,
    which the script must ignore (they can never override nested values).
    """
    health: dict[str, Any] = {}
    for key, value in (
        ("status", status),
        ("direct_status", direct_status),
        ("freshness", freshness),
        ("verification_source", verification_source),
        ("checked_time", checked_time),
    ):
        if value is not None:
            health[key] = value
    if include_cursor:
        health["latest_returned_id"] = (
            cursor_id if cursor_id is not None else last_tweet_id
        )
        health["latest_returned_time"] = (
            cursor_time if cursor_time is not None else last_update_time
        )
    if extra_health:
        health.update(extra_health)
    for key in omit:
        health.pop(key, None)
    if health_override is not None:
        health = health_override
    doc: dict[str, Any] = {
        "last_tweet_id": last_tweet_id,
        "last_update_time": last_update_time,
    }
    if root_cursor_id is not None:
        doc["latest_returned_id"] = root_cursor_id
    if root_cursor_time is not None:
        doc["latest_returned_time"] = root_cursor_time
    doc["source_health"] = health
    return doc


def _failed_sync(checked_time: str = CHECKED_TIME) -> dict[str, Any]:
    """Observed failure-only commit shape (no nested cursor, no
    verification_source): must never be admitted."""
    return {
        "last_tweet_id": LAST_TWEET_ID,
        "last_update_time": LAST_UPDATE_TIME,
        "source_health": {
            "status": "stale_unverified",
            "direct_status": "stale_unverified",
            "freshness": "unverified",
            "checked_time": checked_time,
        },
    }


def _valid_cache_doc(sentinel: str | None = None) -> dict[str, Any]:
    """A cache document exactly as a passing live refresh would write it."""
    document = _build(_positive_sync())
    if sentinel is not None:
        document["sentinel"] = sentinel
    return document


def _forge_admission(document: dict[str, Any]) -> dict[str, Any]:
    """Flip contract flags over a document whose actual health failed."""
    document["latest_available_verified"] = True
    document["source_health_admitted"] = True
    document["source_health_reason"] = "ADMITTED_REVIEWED_FALLBACK_SHAPE"
    document["verification_scope"] = mod.VERIFICATION_SCOPE
    return document


def _main(
    tmp: Path, argv_extra: list[str], fetcher: Callable[[str], Any]
) -> tuple[int | None, str, Exception | None]:
    out = tmp / "out.json"
    with unittest.mock.patch.object(
        sys, "argv", ["refresh", *argv_extra, "--output", str(out)]
    ), _fixed_clock(), contextlib.redirect_stdout(io.StringIO()) as stdout:
        try:
            code = mod.main(fetcher=fetcher)
        except Exception as exc:  # surfaced by assertions, never swallowed
            code = None
            exception: Exception | None = exc
        else:
            exception = None
    return code, stdout.getvalue(), exception


class BuildHealthAdmissionTests(unittest.TestCase):
    def test_failed_health_fresh_commit_not_qualified(self):
        document = _build(_failed_sync())
        self.assertFalse(document["latest_available_verified"])
        self.assertFalse(document["source_health_admitted"])
        self.assertEqual(document["source_health_reason"], "UNKNOWN_STATUS")
        self.assertEqual(
            document["source_health"]["status"], "stale_unverified"
        )
        self.assertEqual(
            document["source_health"]["direct_status"], "stale_unverified"
        )
        self.assertEqual(document["source_health"]["freshness"], "unverified")
        self.assertNotIn("verification_source", document["source_health"])
        self.assertEqual(document["author_latest_view_verified"], False)

    def test_missing_health_not_qualified(self):
        document = _build(
            {
                "last_tweet_id": LAST_TWEET_ID,
                "last_update_time": LAST_UPDATE_TIME,
            }
        )
        self.assertFalse(document["latest_available_verified"])
        self.assertEqual(document["source_health_reason"], "MISSING")
        self.assertIsNone(document["source_health"])

    def test_malformed_health_not_qualified(self):
        for bad in ("stale_unverified", {"status": 5}):
            document = _build(_positive_sync(health_override=bad))
            self.assertFalse(document["latest_available_verified"])
            self.assertEqual(document["source_health_reason"], "MALFORMED")
            self.assertIsNone(document["source_health"])

    def test_unreviewed_positive_shapes_rejected(self):
        wrong = _build(
            _positive_sync(status="available_direct")
        )
        self.assertEqual(wrong["source_health_reason"], "UNKNOWN_STATUS")
        stale = _build(_positive_sync(freshness="stale_posts"))
        self.assertEqual(stale["source_health_reason"], "UNKNOWN_FRESHNESS")
        for doc in (wrong, stale):
            self.assertFalse(doc["latest_available_verified"])
            self.assertFalse(doc["source_health_admitted"])

    def test_missing_direct_status_rejected(self):
        document = _build(_positive_sync(omit=("direct_status",)))
        self.assertFalse(document["latest_available_verified"])
        self.assertEqual(
            document["source_health_reason"], "DIRECT_STATUS_UNREVIEWED"
        )

    def test_wrong_verification_source_rejected(self):
        document = _build(
            _positive_sync(verification_source="x_public_profile")
        )
        self.assertFalse(document["latest_available_verified"])
        self.assertEqual(
            document["source_health_reason"], "VERIFICATION_SOURCE_UNREVIEWED"
        )

    def test_retrieval_does_not_renew_stale_health(self):
        document = _build(_positive_sync(checked_time=STALE_CHECKED))
        self.assertFalse(document["latest_available_verified"])
        self.assertEqual(document["source_health_reason"], "CHECKED_TIME_STALE")
        self.assertEqual(document["retrieved_at"], NOW_ISO)

    def test_future_checked_time_rejected(self):
        document = _build(_positive_sync(checked_time=FUTURE_CHECKED))
        self.assertFalse(document["latest_available_verified"])
        self.assertEqual(
            document["source_health_reason"], "CHECKED_TIME_FUTURE"
        )

    def test_checked_before_sync_update_rejected(self):
        document = _build(
            _positive_sync(
                checked_time="2026-09-12T00:30:00Z",
                last_update_time=LAST_UPDATE_TIME,
            )
        )
        self.assertEqual(
            document["source_health_reason"], "CHECK_TIME_BEFORE_SYNC_UPDATE"
        )
        self.assertFalse(document["latest_available_verified"])

    def test_nested_cursor_mismatch_rejected(self):
        bad_id = _build(_positive_sync(cursor_id="999"))
        self.assertEqual(bad_id["source_health_reason"], "CURSOR_MISMATCH")
        bad_time = _build(_positive_sync(cursor_time=COMMIT_DATE))
        self.assertEqual(bad_time["source_health_reason"], "CURSOR_MISMATCH")
        absent = _build(_positive_sync(include_cursor=False))
        self.assertEqual(absent["source_health_reason"], "CURSOR_MISMATCH")
        for doc in (bad_id, bad_time, absent):
            self.assertFalse(doc["latest_available_verified"])

    def test_root_only_cursor_ignored_not_admitted(self):
        """Cursor at the sync ROOT (old wrong-schema fixture) is not the
        authoritative value and must not substitute for the nested one."""
        document = _build(
            _positive_sync(
                include_cursor=False,
                root_cursor_id=LAST_TWEET_ID,
                root_cursor_time=LAST_UPDATE_TIME,
            )
        )
        self.assertFalse(document["latest_available_verified"])
        self.assertEqual(document["source_health_reason"], "CURSOR_MISMATCH")
        self.assertEqual(document["sync_latest_returned_id"], "")
        self.assertEqual(document["sync_latest_returned_time"], "")

    def test_root_cursor_never_overrides_nested(self):
        """Conflicting root-level cursor fields must be ignored; the nested
        values remain authoritative."""
        document = _build(
            _positive_sync(
                root_cursor_id="999",
                root_cursor_time="2020-01-01T00:00:00Z",
            )
        )
        self.assertTrue(document["latest_available_verified"])
        self.assertEqual(
            document["source_health_reason"], "ADMITTED_REVIEWED_FALLBACK_SHAPE"
        )
        self.assertEqual(document["sync_latest_returned_id"], LAST_TWEET_ID)
        self.assertEqual(document["sync_latest_returned_time"], LAST_UPDATE_TIME)

    def test_valid_observed_fallback_metadata_admitted(self):
        document = _build(_positive_sync(extra_health={"notes": "free form"}))
        self.assertTrue(document["latest_available_verified"])
        self.assertTrue(document["source_health_admitted"])
        self.assertEqual(
            document["source_health_reason"], "ADMITTED_REVIEWED_FALLBACK_SHAPE"
        )
        self.assertEqual(document["verification_scope"], mod.VERIFICATION_SCOPE)
        self.assertEqual(document["source_health"]["status"], "available_fallback")
        self.assertEqual(
            document["source_health"]["direct_status"], "stale_unverified"
        )
        self.assertEqual(document["source_health"]["freshness"], "new_posts")
        self.assertEqual(
            document["source_health"]["verification_source"],
            "x_public_profile+jina_status",
        )
        self.assertEqual(
            document["source_health"]["latest_returned_id"], LAST_TWEET_ID
        )
        self.assertEqual(
            document["source_health"]["latest_returned_time"], LAST_UPDATE_TIME
        )
        self.assertEqual(
            document["sync_latest_returned_id"], LAST_TWEET_ID
        )
        self.assertEqual(
            document["sync_latest_returned_time"], LAST_UPDATE_TIME
        )
        self.assertEqual(
            document["canonical_sync_last_tweet_id"], LAST_TWEET_ID
        )
        self.assertEqual(
            document["canonical_sync_last_update_time"], LAST_UPDATE_TIME
        )
        # Free-form health payload stays out of the bounded document.
        self.assertNotIn("notes", document["source_health"])
        self.assertFalse(document["raw_posts_redistributed"])
        self.assertFalse(document["company_fact_authority"])
        self.assertFalse(document["official_serenity_formula_claimed"])
        self.assertFalse(document["private_method_reproduced"])
        self.assertFalse(document["author_latest_view_verified"])
        self.assertEqual(document["canonical_head_sha"], HEAD_SHA)


class CacheAdmissionTests(unittest.TestCase):
    def _write(self, tmp: Path, document: dict[str, Any]) -> Path:
        out = tmp / "out.json"
        out.write_text(json.dumps(document, indent=2), encoding="utf-8")
        return out

    def test_legacy_cache_without_reviewed_health_not_fresh(self):
        with tempfile.TemporaryDirectory(prefix="ii_v213_health_") as raw:
            tmp = Path(raw)
            document = _valid_cache_doc()
            for key in (
                "source_health_admitted",
                "source_health_reason",
                "verification_scope",
            ):
                document.pop(key, None)
            out = self._write(tmp, document)
            self.assertIsNone(mod.cached_is_fresh(out, FIXED_NOW))

    def test_flagged_cache_not_fresh(self):
        with tempfile.TemporaryDirectory(prefix="ii_v213_health_") as raw:
            tmp = Path(raw)
            document = _valid_cache_doc()
            document["latest_available_verified"] = False
            out = self._write(tmp, document)
            self.assertIsNone(mod.cached_is_fresh(out, FIXED_NOW))

    def test_qualified_fresh_cache_accepted(self):
        with tempfile.TemporaryDirectory(prefix="ii_v213_health_") as raw:
            tmp = Path(raw)
            document = _valid_cache_doc("sentinel")
            self.assertEqual(
                document["verification_scope"], mod.VERIFICATION_SCOPE
            )
            out = self._write(tmp, document)
            admitted = mod.cached_is_fresh(out, FIXED_NOW)
            self.assertEqual(admitted, document)
            self.assertEqual(admitted["sentinel"], "sentinel")

    def test_fresh_cache_with_stale_health_rejected(self):
        with tempfile.TemporaryDirectory(prefix="ii_v213_health_") as raw:
            tmp = Path(raw)
            document = _valid_cache_doc()
            document["source_health"]["checked_time"] = STALE_CHECKED
            out = self._write(tmp, document)
            self.assertIsNone(mod.cached_is_fresh(out, FIXED_NOW))

    def test_stale_retrieved_cache_not_fresh(self):
        with tempfile.TemporaryDirectory(prefix="ii_v213_health_") as raw:
            tmp = Path(raw)
            document = _valid_cache_doc()
            document["retrieved_at"] = STALE_CHECKED
            out = self._write(tmp, document)
            self.assertIsNone(mod.cached_is_fresh(out, FIXED_NOW))

    def test_forged_admission_flags_over_failed_health_not_fresh(self):
        with tempfile.TemporaryDirectory(prefix="ii_v213_health_") as raw:
            tmp = Path(raw)
            failed = _build(_failed_sync())
            self.assertFalse(failed["latest_available_verified"])
            _forge_admission(failed)
            self.assertEqual(
                failed["source_health"]["status"], "stale_unverified"
            )
            out = self._write(tmp, failed)
            self.assertIsNone(mod.cached_is_fresh(out, FIXED_NOW))

    def test_forged_admission_flags_over_malformed_health_not_fresh(self):
        with tempfile.TemporaryDirectory(prefix="ii_v213_health_") as raw:
            tmp = Path(raw)
            document = _valid_cache_doc()
            document["source_health"] = "stale_unverified"
            _forge_admission(document)
            out = self._write(tmp, document)
            self.assertIsNone(mod.cached_is_fresh(out, FIXED_NOW))

    def test_exact_verification_scope_required(self):
        with tempfile.TemporaryDirectory(prefix="ii_v213_health_") as raw:
            tmp = Path(raw)
            short = _valid_cache_doc()
            short["verification_scope"] = (
                "canonical_archive_head_and_sync_metadata_health_only"
            )
            out = self._write(tmp, short)
            self.assertIsNone(mod.cached_is_fresh(out, FIXED_NOW))
            extended = _valid_cache_doc()
            extended["verification_scope"] = (
                f"{mod.VERIFICATION_SCOPE} plus_more"
            )
            out = self._write(tmp, extended)
            self.assertIsNone(mod.cached_is_fresh(out, FIXED_NOW))

    def test_cache_cursor_mismatch_rejected(self):
        with tempfile.TemporaryDirectory(prefix="ii_v213_health_") as raw:
            tmp = Path(raw)
            bad_id = _valid_cache_doc()
            bad_id["sync_latest_returned_id"] = "999"
            self.assertIsNone(mod.cached_is_fresh(self._write(tmp, bad_id), FIXED_NOW))
            bad_time = _valid_cache_doc()
            bad_time["sync_latest_returned_time"] = COMMIT_DATE
            self.assertIsNone(mod.cached_is_fresh(self._write(tmp, bad_time), FIXED_NOW))

    def test_cache_nested_cursor_missing_rejected(self):
        with tempfile.TemporaryDirectory(prefix="ii_v213_health_") as raw:
            tmp = Path(raw)
            for omit in (
                ("latest_returned_id",),
                ("latest_returned_time",),
                ("latest_returned_id", "latest_returned_time"),
            ):
                document = _valid_cache_doc()
                for key in omit:
                    del document["source_health"][key]
                out = self._write(tmp, document)
                self.assertIsNone(
                    mod.cached_is_fresh(out, FIXED_NOW),
                    f"nested cursor missing {omit} must be rejected",
                )

    def test_cache_nested_cursor_contradicted_rejected(self):
        with tempfile.TemporaryDirectory(prefix="ii_v213_health_") as raw:
            tmp = Path(raw)
            bad_id = _valid_cache_doc()
            bad_id["source_health"]["latest_returned_id"] = "999"
            self.assertIsNone(mod.cached_is_fresh(self._write(tmp, bad_id), FIXED_NOW))
            bad_time = _valid_cache_doc()
            bad_time["source_health"]["latest_returned_time"] = COMMIT_DATE
            self.assertIsNone(mod.cached_is_fresh(self._write(tmp, bad_time), FIXED_NOW))

    def test_cache_cursor_wrong_type_or_missing_flattened_rejected(self):
        with tempfile.TemporaryDirectory(prefix="ii_v213_health_") as raw:
            tmp = Path(raw)
            for scope, key, value in (
                ("source_health", "latest_returned_id", 2097815176838017066),
                ("source_health", "latest_returned_time", 1786000000),
                (None, "sync_latest_returned_id", 2097815176838017066),
                (None, "sync_latest_returned_time", 1786000000),
            ):
                document = _valid_cache_doc()
                target = document["source_health"] if scope else document
                target[key] = value
                out = self._write(tmp, document)
                self.assertIsNone(
                    mod.cached_is_fresh(out, FIXED_NOW),
                    f"wrong-type cursor {scope or 'root'}/{key} must be rejected",
                )
            for key in ("sync_latest_returned_id", "sync_latest_returned_time"):
                document = _valid_cache_doc()
                del document[key]
                out = self._write(tmp, document)
                self.assertIsNone(
                    mod.cached_is_fresh(out, FIXED_NOW),
                    f"missing flattened cursor {key} must be rejected",
                )

    def test_cache_missing_direct_status_rejected(self):
        with tempfile.TemporaryDirectory(prefix="ii_v213_health_") as raw:
            tmp = Path(raw)
            document = _valid_cache_doc()
            del document["source_health"]["direct_status"]
            out = self._write(tmp, document)
            self.assertIsNone(mod.cached_is_fresh(out, FIXED_NOW))

    def test_cache_wrong_verification_source_rejected(self):
        with tempfile.TemporaryDirectory(prefix="ii_v213_health_") as raw:
            tmp = Path(raw)
            document = _valid_cache_doc()
            document["source_health"]["verification_source"] = "x_public_profile"
            out = self._write(tmp, document)
            self.assertIsNone(mod.cached_is_fresh(out, FIXED_NOW))


class MainRefusalTests(unittest.TestCase):
    def _cache(self, tmp: Path, document: dict[str, Any]) -> tuple[Path, bytes]:
        out = tmp / "out.json"
        out.write_text(json.dumps(document, indent=2), encoding="utf-8")
        return out, out.read_bytes()

    def test_main_refuses_before_replacing_prior_output(self):
        with tempfile.TemporaryDirectory(prefix="ii_v213_health_") as raw:
            tmp = Path(raw)
            document = _valid_cache_doc("sentinel")
            for key in ("source_health_admitted", "source_health_reason",
                        "verification_scope"):
                document.pop(key, None)
            out, before = self._cache(tmp, document)
            code, _stdout, exc = _main(tmp, [], _failing_fetcher)
            self.assertIsNone(code)
            self.assertIsInstance(exc, mod.PublicSourceError)
            self.assertEqual(out.read_bytes(), before)
            self.assertFalse(out.with_name(out.name + ".tmp").exists())

    def test_main_no_fallback_to_flagged_cache(self):
        with tempfile.TemporaryDirectory(prefix="ii_v213_health_") as raw:
            tmp = Path(raw)
            document = _valid_cache_doc("sentinel")
            document["latest_available_verified"] = False
            out, before = self._cache(tmp, document)
            code, stdout, exc = _main(tmp, [], _failing_fetcher)
            self.assertIsNone(code)
            self.assertIsInstance(exc, mod.PublicSourceError)
            self.assertNotIn("FRESH_CACHE", stdout)
            self.assertEqual(out.read_bytes(), before)

    def test_main_no_fallback_to_forged_cache(self):
        with tempfile.TemporaryDirectory(prefix="ii_v213_health_") as raw:
            tmp = Path(raw)
            failed = _build(_failed_sync())
            _forge_admission(failed)
            out, before = self._cache(tmp, failed)
            code, stdout, exc = _main(tmp, [], _failing_fetcher)
            self.assertIsNone(code)
            self.assertIsInstance(exc, mod.PublicSourceError)
            self.assertNotIn("FRESH_CACHE", stdout)
            self.assertEqual(out.read_bytes(), before)

    def test_main_fallback_only_to_qualified_fresh_cache_preserves_bytes(self):
        with tempfile.TemporaryDirectory(prefix="ii_v213_health_") as raw:
            tmp = Path(raw)
            out, before = self._cache(tmp, _valid_cache_doc("sentinel"))
            code, stdout, exc = _main(tmp, [], _failing_fetcher)
            self.assertEqual(code, 0)
            self.assertIsNone(exc)
            self.assertIn("FRESH_CACHE", stdout)
            self.assertEqual(out.read_bytes(), before)

    def test_main_enforce_refuses_fallback(self):
        with tempfile.TemporaryDirectory(prefix="ii_v213_health_") as raw:
            tmp = Path(raw)
            out, before = self._cache(tmp, _valid_cache_doc("sentinel"))
            code, stdout, exc = _main(tmp, ["--enforce"], _failing_fetcher)
            self.assertIsNone(code)
            self.assertIsInstance(exc, mod.PublicSourceError)
            self.assertNotIn("FRESH_CACHE", stdout)
            self.assertEqual(out.read_bytes(), before)

    def test_main_live_success_writes_qualified_document(self):
        with tempfile.TemporaryDirectory(prefix="ii_v213_health_") as raw:
            tmp = Path(raw)
            code, _stdout, exc = _main(
                tmp, [], _fetch_doc(_positive_sync())
            )
            self.assertEqual(code, 0)
            self.assertIsNone(exc)
            out = tmp / "out.json"
            self.assertTrue(out.exists())
            document = json.loads(out.read_text(encoding="utf-8"))
            self.assertTrue(document["latest_available_verified"])
            self.assertTrue(document["source_health_admitted"])
            self.assertEqual(
                document["source_health_reason"],
                "ADMITTED_REVIEWED_FALLBACK_SHAPE",
            )
            self.assertEqual(document["verification_scope"], mod.VERIFICATION_SCOPE)
            self.assertEqual(
                document["source_health"]["latest_returned_id"], LAST_TWEET_ID
            )
            self.assertEqual(
                document["sync_latest_returned_id"], LAST_TWEET_ID
            )
            self.assertEqual(document["retrieved_at"], NOW_ISO)

    def test_main_failed_health_refuses_live_write(self):
        with tempfile.TemporaryDirectory(prefix="ii_v213_health_") as raw:
            tmp = Path(raw)
            code, _stdout, exc = _main(tmp, [], _fetch_doc(_failed_sync()))
            self.assertIsNone(code)
            self.assertIsInstance(exc, mod.PublicSourceError)
            self.assertFalse((tmp / "out.json").exists())

    def test_main_failed_live_health_preserves_valid_cache_bytes(self):
        with tempfile.TemporaryDirectory(prefix="ii_v213_health_") as raw:
            tmp = Path(raw)
            out, before = self._cache(tmp, _valid_cache_doc("sentinel"))
            code, stdout, exc = _main(tmp, [], _fetch_doc(_failed_sync()))
            self.assertIsNone(code)
            self.assertIsInstance(exc, mod.PublicSourceError)
            self.assertNotIn("FRESH_CACHE", stdout)
            self.assertEqual(out.read_bytes(), before)

    def test_main_malformed_source_health_preserves_valid_cache_bytes(self):
        with tempfile.TemporaryDirectory(prefix="ii_v213_health_") as raw:
            tmp = Path(raw)
            out, before = self._cache(tmp, _valid_cache_doc("sentinel"))
            code, stdout, exc = _main(
                tmp, [], _fetch_doc(_positive_sync(health_override="stale_unverified"))
            )
            self.assertIsNone(code)
            self.assertIsInstance(exc, mod.PublicSourceError)
            self.assertNotIn("FRESH_CACHE", stdout)
            self.assertEqual(out.read_bytes(), before)

    def test_main_malformed_live_sync_must_not_be_masked_as_transport_failure(self):
        """DEFECT REGRESSION: an unparseable (non-JSON) canonical
        sync_state.json is invalid live EVIDENCE about the canonical
        archive, not a transport failure. main() currently routes it through
        the transport_error path and serves the qualified cache, masking the
        invalid evidence. It must refuse (raise) and leave the cache bytes
        untouched."""
        with tempfile.TemporaryDirectory(prefix="ii_v213_health_") as raw:
            tmp = Path(raw)
            out, before = self._cache(tmp, _valid_cache_doc("sentinel"))
            payloads = _payloads(b"not-json")
            code, stdout, exc = _main(tmp, [], lambda url: payloads[url])
            self.assertIsNone(code)
            self.assertIsInstance(exc, mod.PublicSourceError)
            # Pin the boundary: invalid live evidence is NOT the transport
            # subtype, so no cache fallback is even eligible.
            self.assertNotIsInstance(exc, mod.PublicSourceTransportError)
            self.assertNotIn("FRESH_CACHE", stdout)
            self.assertEqual(out.read_bytes(), before)

    def test_main_malformed_live_response_must_not_be_masked_as_transport_failure(self):
        """A non-dict repository metadata response is invalid live evidence,
        not a transport failure: main must refuse despite a qualified cache
        and leave the cache bytes untouched."""
        with tempfile.TemporaryDirectory(prefix="ii_v213_health_") as raw:
            tmp = Path(raw)
            out, before = self._cache(tmp, _valid_cache_doc("sentinel"))
            payloads = _payloads(json.dumps(_positive_sync()).encode("utf-8"))
            payloads[f"{mod.API}/repos/{mod.REPOSITORIES[0][0]}"] = ["not", "a", "dict"]
            code, stdout, exc = _main(tmp, [], lambda url: payloads[url])
            self.assertIsNone(code)
            self.assertIsInstance(exc, mod.PublicSourceError)
            self.assertNotIsInstance(exc, mod.PublicSourceTransportError)
            self.assertNotIn("FRESH_CACHE", stdout)
            self.assertEqual(out.read_bytes(), before)


class ApiJsonBoundaryTests(unittest.TestCase):
    """api_json error classification with a fully mocked urlopen:
    acquisition/network errors (timeout/URLError/OSError) map to
    PublicSourceTransportError, the ONLY class main() treats as transport
    (cache fallback). Malformed JSON/UTF-8, oversized bodies and schema
    errors stay plain, non-transport PublicSourceError.

    No network and no credentials: urlopen is fully mocked and
    GITHUB_TOKEN is cleared only inside this mock context.
    """

    URL = "https://api.github.com/repos/yan-labs/serenity-aleabitoreddit"

    def _call(self, urlopen_mock: unittest.mock.MagicMock) -> Any:
        with unittest.mock.patch.dict(os.environ, {"GITHUB_TOKEN": ""}), \
                unittest.mock.patch.object(
                    mod.urllib.request, "urlopen", urlopen_mock
                ):
            try:
                return mod.api_json(self.URL)
            except mod.PublicSourceError as exc:
                return exc

    @staticmethod
    def _ok_response(body: bytes) -> unittest.mock.MagicMock:
        response = unittest.mock.MagicMock()
        response.read.return_value = body
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        return unittest.mock.MagicMock(return_value=response)

    def test_transport_is_strict_subclass(self):
        self.assertTrue(
            issubclass(mod.PublicSourceTransportError, mod.PublicSourceError)
        )

    def test_timeout_is_transport_subtype(self):
        for error in (TimeoutError("timed out"), socket.timeout("timed out")):
            with self.subTest(error=type(error).__name__):
                result = self._call(
                    unittest.mock.MagicMock(side_effect=error)
                )
                self.assertIsInstance(result, mod.PublicSourceTransportError)

    def test_urlerror_and_oserror_are_transport_subtype(self):
        for error in (
            mod.urllib.error.URLError("dns down"),
            OSError("connection reset"),
        ):
            with self.subTest(error=type(error).__name__):
                result = self._call(
                    unittest.mock.MagicMock(side_effect=error)
                )
                self.assertIsInstance(result, mod.PublicSourceTransportError)

    def test_malformed_json_is_not_transport(self):
        result = self._call(self._ok_response(b"not-json"))
        self.assertIsInstance(result, mod.PublicSourceError)
        self.assertNotIsInstance(result, mod.PublicSourceTransportError)

    def test_invalid_utf8_is_not_transport(self):
        result = self._call(self._ok_response(b"\xff\xfe\xfa{"))
        self.assertIsInstance(result, mod.PublicSourceError)
        self.assertNotIsInstance(result, mod.PublicSourceTransportError)

    def test_oversized_body_is_not_transport(self):
        result = self._call(
            self._ok_response(b"{" + b"0" * (4 * 1024 * 1024))
        )
        self.assertIsInstance(result, mod.PublicSourceError)
        self.assertNotIsInstance(result, mod.PublicSourceTransportError)
        self.assertIn("too large", str(result))

    def test_valid_json_returns_payload(self):
        result = self._call(self._ok_response(b'{"ok": true}'))
        self.assertEqual(result, {"ok": True})


class CanonicalFirstOrderingTests(unittest.TestCase):
    """Canonical-first ordering contract (post-fix regressions).

    The single canonical repository specification is validated BEFORE any
    fetch, and the canonical archive is fetched and health-evaluated BEFORE
    any auxiliary repository, regardless of REPOSITORIES tuple order.  An
    unadmitted or malformed canonical therefore cannot be masked by a later
    auxiliary transport error into an (incorrect) FRESH_CACHE fallback.

    Synthetic clock + fake fetchers only.  These do NOT replace the
    historical governance repro (audit-runtime/astra-qwen-20260912), which
    proved the PRE-fix ordering via its auxiliary-call assumption and is
    preserved as historical evidence, not a post-fix acceptance test.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._tmp_path = Path(self._tmp.name)
        self._patchers: list[Any] = []

    def tearDown(self) -> None:
        for patcher in reversed(self._patchers):
            patcher.stop()
        self._tmp.cleanup()

    def _patch_repositories(self, repositories: list[tuple[str, bool]]) -> None:
        patcher = unittest.mock.patch.object(mod, "REPOSITORIES", repositories)
        patcher.start()
        self._patchers.append(patcher)

    def _aux_calls(self, calls: list[str]) -> list[str]:
        canonical_repo = [r for r, c in mod.REPOSITORIES if c][0]
        prefix = f"{mod.API}/repos/{canonical_repo}"
        return [c for c in calls if not (c == prefix or c.startswith(prefix + "/"))]

    def test_failed_canonical_with_aux_transport_error_main_refuses_no_fresh_cache(self):
        # Confirmed repro B: failed canonical health + auxiliary transport
        # error must refuse, not serve the older qualified cache.
        out = self._tmp_path / "out.json"
        out.write_text(json.dumps(_build(_positive_sync())))
        before = out.read_bytes()
        fetcher, calls = _ordering_fetcher(
            json.dumps(_failed_sync()).encode("utf-8"), aux_transport=True
        )
        code, stdout, exc = _main(self._tmp_path, [], fetcher)
        self.assertIsNone(code)
        self.assertIsInstance(exc, mod.PublicSourceError)
        # Non-transport live rejection: the observed failed canonical health
        # must not be misclassified as a transport failure.
        self.assertNotIsInstance(exc, mod.PublicSourceTransportError)
        self.assertNotIn("FRESH_CACHE", stdout)
        self.assertEqual(out.read_bytes(), before)
        # The auxiliary transport trap was never armed: auxiliaries were
        # never fetched.
        self.assertEqual(self._aux_calls(calls), [])
        self.assertTrue(calls)

    def test_canonical_moved_behind_auxiliary_still_validated_first(self):
        reordered = [e for e in mod.REPOSITORIES if not e[1]] + [
            e for e in mod.REPOSITORIES if e[1]
        ]
        self.assertFalse(reordered[0][1])
        self._patch_repositories(reordered)
        fetcher, calls = _ordering_fetcher(
            json.dumps(_failed_sync()).encode("utf-8"), aux_transport=True
        )
        document = _build_with_fetcher(fetcher)
        self.assertFalse(document["latest_available_verified"])
        # The _failed_sync() shape (status stale_unverified) is pinned by
        # the script's own self_test to UNKNOWN_STATUS.
        self.assertEqual(document["source_health_reason"], "UNKNOWN_STATUS")
        # First request is the canonical archive despite tuple order.
        canonical_repo = [r for r, c in mod.REPOSITORIES if c][0]
        prefix = f"{mod.API}/repos/{canonical_repo}"
        self.assertTrue(calls[0] == prefix or calls[0].startswith(prefix + "/"))
        # Auxiliaries never fetched; unadmitted document carries only the
        # actually-acquired canonical row.
        self.assertEqual(self._aux_calls(calls), [])
        self.assertEqual(
            [r["repository"] for r in document["repositories"]], [canonical_repo]
        )

    def test_malformed_canonical_stops_before_auxiliary(self):
        fetcher, calls = _ordering_fetcher(b"not-json")
        with self.assertRaises(mod.PublicSourceError) as ctx:
            _build_with_fetcher(fetcher)
        self.assertNotIsInstance(ctx.exception, mod.PublicSourceTransportError)
        # Only the canonical archive was acquired before the malformed
        # sync_state stopped the build.
        self.assertTrue(calls)
        self.assertEqual(self._aux_calls(calls), [])

    def test_healthy_canonical_fetches_all_configured_repositories(self):
        fetcher, calls = _ordering_fetcher(
            json.dumps(_positive_sync()).encode("utf-8")
        )
        document = _build_with_fetcher(fetcher)
        self.assertTrue(document["latest_available_verified"])
        expected = [repo for repo, _c in mod.REPOSITORIES]
        self.assertEqual([r["repository"] for r in document["repositories"]], expected)
        # Canonical (repo+commit+sync) plus two URLs per auxiliary.
        self.assertEqual(len(calls), 2 * len(expected) + 1)
        for repo in expected:
            prefix = f"{mod.API}/repos/{repo}"
            self.assertTrue(
                any(c == prefix or c.startswith(prefix + "/") for c in calls),
                repo,
            )

    def test_missing_canonical_config_refuses_before_any_fetch(self):
        self._patch_repositories([(r, False) for r, _c in mod.REPOSITORIES])
        fetcher, calls = _bare_recording_fetcher()
        with self.assertRaises(mod.PublicSourceError):
            _build_with_fetcher(fetcher)
        self.assertEqual(calls, [])

    def test_duplicate_canonical_config_refuses_before_any_fetch(self):
        entries = list(mod.REPOSITORIES)
        for index, (repo, is_canonical) in enumerate(entries):
            if not is_canonical:
                entries[index] = (repo, True)
                break
        self._patch_repositories(entries)
        fetcher, calls = _bare_recording_fetcher()
        with self.assertRaises(mod.PublicSourceError):
            _build_with_fetcher(fetcher)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    if sys.executable != str(PY312) and PY312.exists():
        raise SystemExit(
            f"rerun with pinned CPython: {PY312} -m unittest "
            "tests.test_v213_public_source_health -v"
        )
    unittest.main(verbosity=2)
