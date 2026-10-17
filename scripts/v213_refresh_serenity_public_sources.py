#!/usr/bin/env python3
"""Verify latest public Serenity methodology metadata without redistributing posts.

The canonical public-post archive is treated as an author-statement/research-lead
source, never as company-fact authority.  This script records the exact remote
HEAD, commit time and public sync metadata retrieved from GitHub at run time.
Retrieval time never substitutes for the source publication/commit time.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import os
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Mapping

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "cache" / "v213_serenity_public_source_latest.json"
CACHE_MAX_HOURS = 24
API = "https://api.github.com"
REPOSITORIES = (
    ("yan-labs/serenity-aleabitoreddit", True),
    ("muxuuu/serenity-skill", False),
    ("quantskills/skill-serenity-research-model", False),
)


class PublicSourceError(RuntimeError):
    pass


class PublicSourceTransportError(PublicSourceError):
    """Acquisition/network failure only; the sole class eligible for cache fallback."""

# Reviewed positive archive source_health shapes only. Unknown status or
# freshness values are rejected; success enums are never invented.
POSITIVE_HEALTH_STATUSES = {"available_fallback"}
POSITIVE_HEALTH_FRESHNESS = {"new_posts"}
# The single reviewed direct/verification pairing (pinned b32612e): the
# direct X view is stale_unverified while the jina fallback verified new
# posts. Both values must match the reviewed shape exactly.
REVIEWED_DIRECT_STATUS = "stale_unverified"
REVIEWED_VERIFICATION_SOURCE = "x_public_profile+jina_status"
# Exact shared verification scope for live output and cache re-admission.
VERIFICATION_SCOPE = (
    "canonical_archive_head_and_sync_metadata_health_only; "
    "not author_latest_view verification"
)
# Bounded health fields only; free-form payloads (next_action, error, ...)
# are dropped and must not be redistributed. Upstream nests
# latest_returned_id/latest_returned_time INSIDE source_health, never at
# the sync_state root.
HEALTH_FIELDS = (
    "status",
    "direct_status",
    "freshness",
    "verification_source",
    "latest_returned_id",
    "latest_returned_time",
    "checked_time",
)


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_time(value: Any) -> dt.datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PublicSourceError(f"Unable to read JSON: {path}") from exc
    if not isinstance(value, dict):
        raise PublicSourceError(f"Expected JSON object: {path}")
    return value


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="\n", delete=False,
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp",
    ) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def api_json(url: str, timeout: int = 30) -> Any:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "Investor-Intelligence-v2.1.3-public-source-verifier",
        "X-GitHub-Api-Version": "2022-11-28",
        "Cache-Control": "no-cache",
    }
    token = str(os.getenv("GITHUB_TOKEN") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    data: bytes
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read(4 * 1024 * 1024 + 1)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise PublicSourceTransportError(
            f"GitHub API request failed: {url}: {type(exc).__name__}"
        ) from exc
    if len(data) > 4 * 1024 * 1024:
        raise PublicSourceError(f"GitHub API response too large: {url}")
    try:
        return json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PublicSourceError(
            f"GitHub API response is not valid JSON: {url}: {type(exc).__name__}"
        ) from exc


def repository_state(repo: str, canonical: bool, fetcher: Callable[[str], Any] = api_json) -> dict[str, Any]:
    metadata = fetcher(f"{API}/repos/{repo}")
    if not isinstance(metadata, dict):
        raise PublicSourceError(f"Repository metadata shape changed: {repo}")
    branch = str(metadata.get("default_branch") or "main")
    commit = fetcher(f"{API}/repos/{repo}/commits/{branch}")
    if not isinstance(commit, dict):
        raise PublicSourceError(f"Repository commit shape changed: {repo}")
    sha = str(commit.get("sha") or "")
    commit_block = commit.get("commit") if isinstance(commit.get("commit"), dict) else {}
    committer = commit_block.get("committer") if isinstance(commit_block.get("committer"), dict) else {}
    committed_at = str(committer.get("date") or "")
    if len(sha) != 40 or parse_time(committed_at) is None:
        raise PublicSourceError(f"Repository HEAD identity is invalid: {repo}")
    state: dict[str, Any] = {
        "repository": repo,
        "canonical_public_post_archive": canonical,
        "default_branch": branch,
        "head_sha": sha,
        "head_committed_at": committed_at,
        "repository_pushed_at": str(metadata.get("pushed_at") or ""),
        "repository_updated_at": str(metadata.get("updated_at") or ""),
        "license": (
            str((metadata.get("license") or {}).get("spdx_id") or "UNKNOWN")
            if isinstance(metadata.get("license"), dict)
            else "UNKNOWN"
        ),
        "evidence_role": "author_statement_and_research_lead_only" if canonical else "methodology_pattern_only",
        "company_fact_authority": False,
    }
    if canonical:
        sync = fetcher(f"{API}/repos/{repo}/contents/data/sync_state.json?ref={sha}")
        if not isinstance(sync, dict) or not isinstance(sync.get("content"), str):
            raise PublicSourceError("Canonical Serenity sync_state is unavailable")
        try:
            decoded = base64.b64decode(sync["content"]).decode("utf-8-sig")
            sync_doc = json.loads(decoded)
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PublicSourceError("Canonical Serenity sync_state is invalid") from exc
        if not isinstance(sync_doc, dict):
            raise PublicSourceError("Canonical Serenity sync_state is invalid")
        raw_health = sync_doc.get("source_health")
        bounded_health: dict[str, str] = {}
        health_shape = "missing"
        if raw_health is not None:
            health_shape = "malformed"
            if isinstance(raw_health, dict):
                for key in HEALTH_FIELDS:
                    value = raw_health.get(key)
                    if value is None:
                        continue
                    if not isinstance(value, str) or not value.strip():
                        break
                    bounded_health[key] = value.strip()
                else:
                    health_shape = "ok"
        # Upstream nests latest_returned_id/time inside source_health; any
        # root-level cursor fields are ignored and can never override the
        # authoritative nested values.
        state["sync_state"] = {
            "last_tweet_id": str(sync_doc.get("last_tweet_id") or ""),
            "last_update_time": str(sync_doc.get("last_update_time") or ""),
            "latest_returned_id": bounded_health.get("latest_returned_id", ""),
            "latest_returned_time": bounded_health.get("latest_returned_time", ""),
            "source_health": bounded_health,
            "source_health_shape": health_shape,
        }
        if not state["sync_state"]["last_tweet_id"] or parse_time(state["sync_state"]["last_update_time"]) is None:
            raise PublicSourceError("Canonical Serenity sync_state lacks dated public provenance")
    return state


def evaluate_source_health(
    sync_state: Mapping[str, Any],
    now: dt.datetime,
) -> tuple[bool, str, dict[str, str] | None]:
    """Single shared fail-closed admission of reviewed archive source_health.

    Returns (admitted, reason, bounded_health). Used for BOTH live sync
    extraction and cache re-admission so one validator gates both paths. A
    new HEAD commit or retrieval time never renews old health: only the
    exact reviewed status/freshness/direct_status/verification_source
    pairing, the bounded checked_time inside the existing 24h window/skew,
    sync-update ordering, and nested cursor consistency
    (latest_returned_id/time == last_tweet_id/last_update_time) qualify.
    Root-level cursor fields never substitute for nested values.
    """
    shape = str(sync_state.get("source_health_shape") or "missing")
    if shape == "missing":
        return False, "MISSING", None
    if shape == "malformed":
        return False, "MALFORMED", None
    bounded = dict(sync_state.get("source_health") or {})
    if str(bounded.get("status") or "") not in POSITIVE_HEALTH_STATUSES:
        return False, "UNKNOWN_STATUS", bounded
    if str(bounded.get("freshness") or "") not in POSITIVE_HEALTH_FRESHNESS:
        return False, "UNKNOWN_FRESHNESS", bounded
    if str(bounded.get("direct_status") or "") != REVIEWED_DIRECT_STATUS:
        return False, "DIRECT_STATUS_UNREVIEWED", bounded
    if str(bounded.get("verification_source") or "") != REVIEWED_VERIFICATION_SOURCE:
        return False, "VERIFICATION_SOURCE_UNREVIEWED", bounded
    checked = parse_time(bounded.get("checked_time"))
    if checked is None:
        return False, "CHECKED_TIME_UNPARSEABLE", bounded
    checked_utc = checked.astimezone(dt.timezone.utc)
    age_hours = (now - checked_utc).total_seconds() / 3600.0
    if age_hours < -0.1:
        return False, "CHECKED_TIME_FUTURE", bounded
    if age_hours > CACHE_MAX_HOURS:
        return False, "CHECKED_TIME_STALE", bounded
    last_update = parse_time(str(sync_state.get("last_update_time") or ""))
    if last_update is None or checked_utc < last_update.astimezone(dt.timezone.utc):
        return False, "CHECK_TIME_BEFORE_SYNC_UPDATE", bounded
    last_tweet_id = str(sync_state.get("last_tweet_id") or "")
    latest_returned_id = str(sync_state.get("latest_returned_id") or "")
    if not latest_returned_id or latest_returned_id != last_tweet_id:
        return False, "CURSOR_MISMATCH", bounded
    latest_returned_time = parse_time(str(sync_state.get("latest_returned_time") or ""))
    if (
        latest_returned_time is None
        or latest_returned_time.astimezone(dt.timezone.utc)
        != last_update.astimezone(dt.timezone.utc)
    ):
        return False, "CURSOR_MISMATCH", bounded
    return True, "ADMITTED_REVIEWED_FALLBACK_SHAPE", bounded


def cached_is_fresh(path: Path, now: dt.datetime) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        document = read_json(path)
    except PublicSourceError:
        return None
    retrieved = parse_time(document.get("retrieved_at"))
    if retrieved is None:
        return None
    age_hours = (now - retrieved.astimezone(dt.timezone.utc)).total_seconds() / 3600
    if age_hours < -0.1 or age_hours > CACHE_MAX_HOURS:
        return None
    if document.get("latest_available_verified") is not True:
        return None
    # Legacy caches lacking a reviewed health admission must not bypass
    # fresh acquisition; flagged failures are never served. Contract flags
    # are necessary, never sufficient: the actual reviewed health is
    # re-validated below with the same shared live validator.
    if document.get("source_health_admitted") is not True:
        return None
    if str(document.get("verification_scope") or "").strip() != VERIFICATION_SCOPE:
        return None
    if document.get("author_latest_view_verified") is not False:
        return None
    if document.get("company_fact_authority") is not False:
        return None
    admitted, _reason, _bounded = evaluate_source_health(
        normalized_cache_sync_state(document), now
    )
    return document if admitted else None


def normalized_cache_sync_state(document: Mapping[str, Any]) -> dict[str, Any]:
    """Reconstruct the normalized sync_state view from a cached document.

    Canonical sync cursors (canonical_sync_*) plus the bounded NESTED
    source_health cursor fields (source_health.latest_returned_id/time, the
    same authority as the live extraction path) and bounded source_health
    are folded into the same normalized shape the shared live validator
    consumes. Both flattened compatibility fields (sync_latest_returned_*)
    must be present and exactly equal the nested values; missing,
    malformed or contradictory cursor data on either side marks the shape
    malformed so the shared validator refuses. The flattened fields are
    never the authority and never a fallback. Cached booleans are never
    part of this reconstruction.
    """
    health_raw = document.get("source_health")
    bounded_health: dict[str, str] = {}
    health_shape = "missing"
    if health_raw is not None:
        health_shape = "malformed"
        if isinstance(health_raw, dict):
            for key in HEALTH_FIELDS:
                value = health_raw.get(key)
                if value is None:
                    continue
                if not isinstance(value, str) or not value.strip():
                    break
                bounded_health[key] = value.strip()
            else:
                health_shape = "ok"
    # The bounded nested source_health cursor is the only cursor authority;
    # the flattened compatibility fields must both be present and exactly
    # equal it. Any divergence (missing, wrong type, or contradiction on
    # either side) refuses via the malformed shape below.
    nested_id = bounded_health.get("latest_returned_id")
    nested_time = bounded_health.get("latest_returned_time")
    flat_id = document.get("sync_latest_returned_id")
    flat_time = document.get("sync_latest_returned_time")
    if not (
        isinstance(nested_id, str)
        and isinstance(nested_time, str)
        and isinstance(flat_id, str)
        and isinstance(flat_time, str)
        and flat_id == nested_id
        and flat_time == nested_time
    ):
        health_shape = "malformed"
    return {
        "last_tweet_id": str(document.get("canonical_sync_last_tweet_id") or ""),
        "last_update_time": str(document.get("canonical_sync_last_update_time") or ""),
        "latest_returned_id": bounded_health.get("latest_returned_id", ""),
        "latest_returned_time": bounded_health.get("latest_returned_time", ""),
        "source_health": bounded_health,
        "source_health_shape": health_shape,
    }


def assemble_document(
    now: dt.datetime,
    admitted: bool,
    reason: str,
    health: dict[str, str] | None,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Shared live-build document assembly.

    ``rows`` must contain ONLY repositories that were actually acquired.
    An unadmitted canonical archive therefore yields a canonical-only row
    set; auxiliary rows are never fabricated.
    """
    canonical = next(row for row in rows if row["canonical_public_post_archive"])
    return {
        "schema_version": 1,
        "product_version": "2.1.3",
        "retrieved_at": iso(now),
        "latest_available_verified": admitted,
        "verification_scope": VERIFICATION_SCOPE,
        "author_latest_view_verified": False,
        "source_health": health,
        "source_health_admitted": admitted,
        "source_health_reason": reason,
        "sync_latest_returned_id": canonical["sync_state"]["latest_returned_id"],
        "sync_latest_returned_time": canonical["sync_state"]["latest_returned_time"],
        "retrieval_time_is_not_publication_time": True,
        "raw_posts_redistributed": False,
        "company_fact_authority": False,
        "official_serenity_formula_claimed": False,
        "private_method_reproduced": False,
        "repositories": rows,
        "canonical_repository": canonical["repository"],
        "canonical_head_sha": canonical["head_sha"],
        "canonical_head_committed_at": canonical["head_committed_at"],
        "canonical_sync_last_update_time": canonical["sync_state"]["last_update_time"],
        "canonical_sync_last_tweet_id": canonical["sync_state"]["last_tweet_id"],
        "use_boundary": "Public posts provide dated author statements and research leads; company claims still require independent primary and corroborating evidence.",
    }


def build(fetcher: Callable[[str], Any] = api_json) -> dict[str, Any]:
    now = utc_now()
    # Fail-closed configuration gate, checked BEFORE any fetch: exactly one
    # canonical public-post archive specification must exist.
    canonical_repos = [repo for repo, is_canonical in REPOSITORIES if is_canonical]
    if len(canonical_repos) != 1:
        raise PublicSourceError("Exactly one canonical public Serenity archive is required")
    canonical_repo = canonical_repos[0]
    # Canonical-first ordering: the canonical archive is always fetched and
    # immediately health-evaluated before any auxiliary repository, regardless
    # of its position in REPOSITORIES.  An observed unadmitted or malformed
    # canonical is therefore never masked by a later auxiliary transport
    # error (which would otherwise be misread as a pure transport failure
    # and trigger cache fallback).
    canonical_row = repository_state(canonical_repo, True, fetcher)
    admitted, reason, health = evaluate_source_health(
        canonical_row["sync_state"], now
    )
    if not admitted:
        # Fail-closed: once the canonical source_health is unadmitted, the
        # auxiliary repositories are never fetched; the unadmitted document
        # carries only the actually-acquired canonical row.
        return assemble_document(now, admitted, reason, health, [canonical_row])
    rows = [canonical_row]
    for repo, is_canonical in REPOSITORIES:
        if repo != canonical_repo:
            rows.append(repository_state(repo, is_canonical, fetcher))
    # Preserve the configured REPOSITORIES row order in the document.
    order = {repo: index for index, (repo, _is_canonical) in enumerate(REPOSITORIES)}
    rows.sort(key=lambda row: order[row["repository"]])
    return assemble_document(now, admitted, reason, health, rows)


def self_test() -> None:
    payloads: dict[str, Any] = {}
    checked = iso(utc_now())
    for repo, canonical in REPOSITORIES:
        payloads[f"{API}/repos/{repo}"] = {
            "default_branch": "main", "pushed_at": "2026-09-03T00:00:00Z",
            "updated_at": "2026-09-03T00:00:00Z", "license": {"spdx_id": "MIT"},
        }
        payloads[f"{API}/repos/{repo}/commits/main"] = {
            "sha": ("a" if canonical else "b") * 40,
            "commit": {"committer": {"date": "2026-09-03T00:00:00Z"}},
        }
        if canonical:
            # Reviewed observed positive fallback shape (pinned b32612e);
            # free-form health payloads must be dropped as unbounded.
            sync = json.dumps({
                "last_tweet_id": "123",
                "last_update_time": "2026-09-03T00:00:00Z",
                "source_health": {
                    "status": "available_fallback",
                    "direct_status": "stale_unverified",
                    "freshness": "new_posts",
                    "verification_source": "x_public_profile+jina_status",
                    "latest_returned_id": "123",
                    "latest_returned_time": "2026-09-03T00:00:00Z",
                    "checked_time": checked,
                    "next_action": "free-form payload must not be preserved",
                },
            }).encode()
            payloads[f"{API}/repos/{repo}/contents/data/sync_state.json?ref={'a'*40}"] = {
                "content": base64.b64encode(sync).decode()
            }
    document = build(lambda url: payloads[url])
    assert document["latest_available_verified"] is True
    assert document["source_health_admitted"] is True
    assert document["source_health_reason"] == "ADMITTED_REVIEWED_FALLBACK_SHAPE"
    assert document["source_health"]["status"] == "available_fallback"
    assert document["source_health"]["direct_status"] == REVIEWED_DIRECT_STATUS
    assert document["source_health"]["verification_source"] == REVIEWED_VERIFICATION_SOURCE
    assert document["source_health"]["latest_returned_id"] == "123"
    assert document["sync_latest_returned_id"] == "123"
    assert document["canonical_sync_last_tweet_id"] == "123"
    assert "next_action" not in document["source_health"]
    assert document["author_latest_view_verified"] is False
    assert document["verification_scope"] == VERIFICATION_SCOPE
    assert document["canonical_head_sha"] == "a" * 40
    assert document["company_fact_authority"] is False
    assert document["raw_posts_redistributed"] is False
    # Observed failure-only commit shape must not be admitted.
    admitted, reason, _ = evaluate_source_health({
        "last_tweet_id": "123",
        "last_update_time": "2026-09-03T00:00:00Z",
        "latest_returned_id": "",
        "latest_returned_time": "",
        "source_health": {
            "status": "stale_unverified",
            "direct_status": "stale_unverified",
            "freshness": "unverified",
            "checked_time": checked,
        },
        "source_health_shape": "ok",
    }, utc_now())
    assert admitted is False and reason == "UNKNOWN_STATUS"
    print("V213_SERENITY_PUBLIC_SOURCE_REFRESH_SELF_TEST = PASS")


def main(fetcher: Callable[[str], Any] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--enforce", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    now = utc_now()
    document: dict[str, Any] | None = None
    source = ""
    transport_error: PublicSourceTransportError | None = None
    live_rejection: PublicSourceError | None = None
    try:
        document = build(fetcher if fetcher is not None else api_json)
    except PublicSourceTransportError as exc:
        transport_error = exc
    except PublicSourceError:
        # Invalid live evidence (malformed sync/health/schema) is a refusal,
        # never a transport failure: do not fall back to the cache.
        raise
    if document is not None and document["latest_available_verified"] is not True:
        # Fail-closed: an archive whose source_health is not admitted must
        # not replace prior output.
        live_rejection = PublicSourceError(
            f"Canonical archive source_health not admitted: "
            f"{document['source_health_reason']}"
        )
        document = None
    if document is None:
        # Explicitly observed unadmitted live health forbids falling back to
        # an older cache: refuse before any write, preserving prior bytes.
        # Only a transport-level failure may fall back, and only to a cache
        # that passes the same shared validator (read-only: never rewritten).
        if live_rejection is not None:
            raise live_rejection
        cached = None if args.enforce else cached_is_fresh(args.output, now)
        if cached is None:
            raise transport_error if transport_error is not None else PublicSourceError(
                "public source refresh unavailable"
            )
        document = cached
        source = "FRESH_CACHE"
    else:
        source = "LIVE"
    if source == "LIVE":
        # Read-only cache fallback must never rewrite prior output bytes.
        atomic_json(args.output, document)
    print(
        "V213_SERENITY_PUBLIC_SOURCE_REFRESH = PASS; "
        f"source={source}; canonical={document['canonical_repository']}; "
        f"head={document['canonical_head_sha']}; retrieved_at={document['retrieved_at']}; "
        "company_fact_authority=false",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PublicSourceError as exc:
        print(f"V213_SERENITY_PUBLIC_SOURCE_REFRESH = FAIL; {exc}", file=__import__('sys').stderr, flush=True)
        raise SystemExit(1)
