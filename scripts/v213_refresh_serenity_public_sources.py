#!/usr/bin/env python3
"""Verify latest public Serenity methodology metadata without redistributing posts.

The canonical public-post archive is treated as an author-statement/research-lead
source, never as company-fact authority.  This script records the exact remote
HEAD, commit time and public sync metadata retrieved from GitHub at run time.
Retrieval time never substitutes for the source publication/commit time.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

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
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read(4 * 1024 * 1024 + 1)
            if len(data) > 4 * 1024 * 1024:
                raise PublicSourceError(f"GitHub API response too large: {url}")
            return json.loads(data.decode("utf-8-sig"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise PublicSourceError(f"GitHub API request failed: {url}: {type(exc).__name__}") from exc


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
        import base64
        try:
            decoded = base64.b64decode(sync["content"]).decode("utf-8-sig")
            sync_doc = json.loads(decoded)
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PublicSourceError("Canonical Serenity sync_state is invalid") from exc
        state["sync_state"] = {
            "last_tweet_id": str(sync_doc.get("last_tweet_id") or ""),
            "last_update_time": str(sync_doc.get("last_update_time") or ""),
        }
        if not state["sync_state"]["last_tweet_id"] or parse_time(state["sync_state"]["last_update_time"]) is None:
            raise PublicSourceError("Canonical Serenity sync_state lacks dated public provenance")
    return state


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
    return document


def build(fetcher: Callable[[str], Any] = api_json) -> dict[str, Any]:
    now = utc_now()
    rows = [repository_state(repo, canonical, fetcher) for repo, canonical in REPOSITORIES]
    canonical = [row for row in rows if row["canonical_public_post_archive"]]
    if len(canonical) != 1:
        raise PublicSourceError("Exactly one canonical public Serenity archive is required")
    return {
        "schema_version": 1,
        "product_version": "2.1.3",
        "retrieved_at": iso(now),
        "latest_available_verified": True,
        "retrieval_time_is_not_publication_time": True,
        "raw_posts_redistributed": False,
        "company_fact_authority": False,
        "official_serenity_formula_claimed": False,
        "private_method_reproduced": False,
        "repositories": rows,
        "canonical_repository": canonical[0]["repository"],
        "canonical_head_sha": canonical[0]["head_sha"],
        "canonical_head_committed_at": canonical[0]["head_committed_at"],
        "canonical_sync_last_update_time": canonical[0]["sync_state"]["last_update_time"],
        "canonical_sync_last_tweet_id": canonical[0]["sync_state"]["last_tweet_id"],
        "use_boundary": "Public posts provide dated author statements and research leads; company claims still require independent primary and corroborating evidence.",
    }


def self_test() -> None:
    payloads: dict[str, Any] = {}
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
            import base64
            sync = json.dumps({"last_tweet_id": "123", "last_update_time": "2026-09-03T00:00:00Z"}).encode()
            payloads[f"{API}/repos/{repo}/contents/data/sync_state.json?ref={'a'*40}"] = {
                "content": base64.b64encode(sync).decode()
            }
    document = build(lambda url: payloads[url])
    assert document["latest_available_verified"] is True
    assert document["canonical_head_sha"] == "a" * 40
    assert document["company_fact_authority"] is False
    assert document["raw_posts_redistributed"] is False
    print("V213_SERENITY_PUBLIC_SOURCE_REFRESH_SELF_TEST = PASS")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--enforce", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    now = utc_now()
    try:
        document = build()
        atomic_json(args.output, document)
        source = "LIVE"
    except PublicSourceError:
        cached = cached_is_fresh(args.output, now)
        if cached is None or args.enforce:
            raise
        document = cached
        source = "FRESH_CACHE"
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
