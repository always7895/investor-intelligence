#!/usr/bin/env python3
"""Fail closed until a reviewed free public option-quote provider is selected."""
from __future__ import annotations

import copy
import json
import re
import tomllib
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
CANDIDATES_PATH = ROOT / "config" / "public-options-provider-candidates.json"
DEVELOPMENT_PATH = ROOT / "config" / "public-options-development-provider.json"
RUNTIME_POLICY_PATH = ROOT / "config" / "runtime-policy.json"
WRANGLER_PATH = ROOT / "cloud" / "wrangler.toml"
BUILDER_PATH = ROOT / "scripts" / "build_line_public_options.py"

REQUIRED_PROVIDER_FIELDS = {
    "id",
    "name",
    "authority",
    "jurisdictions",
    "data_roles",
    "official_url",
    "rights_evidence_url",
    "rights_status",
    "automated_access_allowed",
    "rights_reviewed_at",
    "review_notes",
    "adapter_status",
    "runtime_enabled",
    "line_quote_eligible",
}
ALLOWED_RIGHTS_STATUSES = {
    "review_before_enable",
    "reviewed_public_access",
    "automated_access_prohibited",
}
ALLOWED_ADAPTER_STATUSES = {
    "not_implemented",
    "candidate_implemented",  # local-only code; never satisfies the runtime reviewed gate
    "adapter_reviewed",
    "not_permitted",
}
AUTOMATION_PROHIBITED_PROVIDER_IDS = {
    "cboe_public_options_market_data",
    "marketdata_app_free_forever",
    "occ_public_market_data",
    "tradier_broker_market_data_api",
}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# Optional-while-disabled fields (L-RIGHTS): REQUIRED, and fully validated, before a provider may be enabled. No value is inserted
# into the catalog by this module; real scope and review window come only from an actual rights review.
OPTIONAL_PROVIDER_FIELDS = {"admitted_scopes", "review_valid_through"}
SCOPE_KEYS = {"jurisdiction", "venue", "instrument_kind", "quote_basis", "publication_scope"}
ALLOWED_INSTRUMENT_KINDS = {"equity_option"}  # only real equity-option quotes; EOD/theoretical/settlement are never upgraded
ALLOWED_QUOTE_BASES = {"delayed"}
ALLOWED_PUBLICATION_SCOPES = {"public_line_quote"}
VENUE_RE = re.compile(r"^[A-Z0-9][A-Z0-9_.-]{0,31}$")
IDENTITY_FIELDS = ("provider_id", "jurisdiction", "venue", "instrument_kind", "quote_basis", "publication_scope")
OPTION_RIGHTS_NOT_ADMITTED = "OPTION_RIGHTS_NOT_ADMITTED"
OPTION_RIGHTS_UNAVAILABLE_ZH = "期權報價未取得公開散布權利准入（OPTION_RIGHTS_NOT_ADMITTED）；僅限本機研究，不公開顯示。"


class PublicOptionsProviderError(ValueError):
    """Raised when public option-provider configuration cannot be audited."""


def _object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise
    except json.JSONDecodeError as exc:
        raise PublicOptionsProviderError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise PublicOptionsProviderError(f"Expected an object in {path}")
    return value


def _safe_https(value: Any) -> bool:
    try:
        parsed = urlsplit(str(value or ""))
        port = parsed.port
    except ValueError:
        return False
    return bool(
        parsed.scheme.casefold() == "https"
        and parsed.hostname
        and not parsed.username
        and not parsed.password
        and port in (None, 443)
    )


def _review_date(value: Any) -> bool:
    if not isinstance(value, str) or not DATE_RE.fullmatch(value):
        return False
    try:
        return date.fromisoformat(value) <= datetime.now(timezone.utc).date()
    except ValueError:
        return False


def _date_value(value: Any) -> date | None:
    if not isinstance(value, str) or not DATE_RE.fullmatch(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _rights_reviewed(provider: dict[str, Any]) -> bool:
    """The ONE definition of a rights-reviewed free public provider, shared by the audit and public admission."""
    return (
        provider.get("rights_status") == "reviewed_public_access"
        and provider.get("automated_access_allowed") is True
        and provider.get("adapter_status") == "adapter_reviewed"
    )


def _scope_findings(label: str, provider: dict[str, Any], *, enabled: bool, today: date) -> list[str]:
    """Exact schema of the optional review_valid_through / admitted_scopes fields. Absent while disabled is fine; required and
    validated when enabled or eligible; validated whenever present."""
    findings: list[str] = []
    if enabled and ("admitted_scopes" not in provider or "review_valid_through" not in provider):
        findings.append(f"{label}: enabled/eligible provider requires admitted_scopes and review_valid_through")
    if "review_valid_through" in provider:
        through = _date_value(provider.get("review_valid_through"))
        reviewed = _date_value(provider.get("rights_reviewed_at"))
        if through is None:
            findings.append(f"{label}: review_valid_through must be a real YYYY-MM-DD date")
        elif reviewed is None or through < reviewed:
            findings.append(f"{label}: review_valid_through must not precede a valid rights_reviewed_at")
        elif enabled and through < today:
            findings.append(f"{label}: review_valid_through has passed for an enabled/eligible provider")
    if "admitted_scopes" in provider:
        scopes = provider.get("admitted_scopes")
        jurisdictions = provider.get("jurisdictions")
        if not isinstance(scopes, list) or not scopes:
            findings.append(f"{label}: admitted_scopes must be a non-empty array")
            return findings
        for entry in scopes:
            if not isinstance(entry, dict) or set(entry) != SCOPE_KEYS or not all(isinstance(entry[key], str) for key in SCOPE_KEYS):
                findings.append(f"{label}: each admitted scope needs exactly the string keys {sorted(SCOPE_KEYS)}")
                continue
            if not isinstance(jurisdictions, list) or entry["jurisdiction"] not in jurisdictions:
                findings.append(f"{label}: scope jurisdiction must be one of the provider jurisdictions")
            if not VENUE_RE.fullmatch(entry["venue"]):
                findings.append(f"{label}: scope venue is malformed")
            if entry["instrument_kind"] not in ALLOWED_INSTRUMENT_KINDS:
                findings.append(f"{label}: scope instrument_kind is not an admissible kind")
            if entry["quote_basis"] not in ALLOWED_QUOTE_BASES:
                findings.append(f"{label}: scope quote_basis is not admissible")
            if entry["publication_scope"] not in ALLOWED_PUBLICATION_SCOPES:
                findings.append(f"{label}: scope publication_scope is not admissible")
    return findings


def audit_public_options_providers(root: Path = ROOT, today: date | None = None) -> tuple[list[str], dict[str, Any]]:
    findings: list[str] = []
    day = today or datetime.now(timezone.utc).date()
    candidates = _object(root / "config" / "public-options-provider-candidates.json")
    development = _object(root / "config" / "public-options-development-provider.json")
    runtime = _object(root / "config" / "runtime-policy.json")
    wrangler = tomllib.loads((root / "cloud" / "wrangler.toml").read_text(encoding="utf-8"))
    builder = (root / "scripts" / "build_line_public_options.py").read_text(encoding="utf-8")

    required_top = {
        "schema_version",
        "purpose",
        "automatic_activation",
        "owner_watchlist_inheritance",
        "ibkr_or_broker_account_fallback",
        "paid_fallback",
        "production_quote_provider_selected",
        "providers",
    }
    unknown_top = sorted(set(candidates).difference(required_top))
    if unknown_top:
        findings.append(
            "public-options-provider-candidates.json: unknown top-level field(s): "
            + ", ".join(unknown_top)
        )
    if candidates.get("schema_version") != 2:
        findings.append("public-options-provider-candidates.json: schema_version must be 2")
    for key in (
        "automatic_activation",
        "owner_watchlist_inheritance",
        "ibkr_or_broker_account_fallback",
        "paid_fallback",
    ):
        if candidates.get(key) is not False:
            findings.append(f"public-options-provider-candidates.json: {key} must be false")
    # production_quote_provider_selected is NOT an always-false flag: it is a strict boolean whose value must equal whether any provider
    # is fully eligible (selected=false with none; selected=true only with at least one). Every other mismatch is a finding below.
    if type(candidates.get("production_quote_provider_selected")) is not bool:
        findings.append("public-options-provider-candidates.json: production_quote_provider_selected must be a boolean")

    providers = candidates.get("providers")
    if not isinstance(providers, list):
        raise PublicOptionsProviderError("public options candidates require a providers array")
    if len(providers) < 8:
        findings.append("public options candidate catalog must contain at least eight providers")

    ids: set[str] = set()
    jurisdictions: set[str] = set()
    authorities: set[str] = set()
    roles: set[str] = set()
    fully_eligible = 0
    attempted_activation = 0
    rejected_count = 0
    pending_count = 0
    reviewed_access_count = 0

    for index, provider in enumerate(providers):
        label = f"providers[{index}]"
        if not isinstance(provider, dict):
            findings.append(f"{label}: provider must be an object")
            continue
        unknown = sorted(set(provider).difference(REQUIRED_PROVIDER_FIELDS | OPTIONAL_PROVIDER_FIELDS))
        missing = sorted(REQUIRED_PROVIDER_FIELDS.difference(provider))
        if unknown:
            findings.append(f"{label}: unknown field(s): {', '.join(unknown)}")
        if missing:
            findings.append(f"{label}: missing field(s): {', '.join(missing)}")

        provider_id = str(provider.get("id") or "").strip()
        if not provider_id:
            findings.append(f"{label}: id is required")
        elif provider_id in ids:
            findings.append(f"{label}: duplicate id {provider_id}")
        ids.add(provider_id)

        authority = str(provider.get("authority") or "").strip()
        if authority:
            authorities.add(authority)
        raw_jurisdictions = provider.get("jurisdictions")
        raw_roles = provider.get("data_roles")
        if not isinstance(raw_jurisdictions, list) or not raw_jurisdictions:
            findings.append(f"{provider_id or label}: jurisdictions cannot be empty")
        else:
            jurisdictions.update(str(item).strip() for item in raw_jurisdictions if str(item).strip())
        if not isinstance(raw_roles, list) or not raw_roles:
            findings.append(f"{provider_id or label}: data_roles cannot be empty")
        else:
            roles.update(str(item).strip() for item in raw_roles if str(item).strip())

        for field in ("official_url", "rights_evidence_url"):
            if not _safe_https(provider.get(field)):
                findings.append(f"{provider_id or label}: {field} must be safe HTTPS")
        review_notes = provider.get("review_notes")
        if not isinstance(review_notes, str) or not review_notes.strip():
            findings.append(f"{provider_id or label}: review_notes are required")

        rights_status = provider.get("rights_status")
        adapter_status = provider.get("adapter_status")
        automation_allowed = provider.get("automated_access_allowed")
        reviewed_at = provider.get("rights_reviewed_at")
        if rights_status not in ALLOWED_RIGHTS_STATUSES:
            findings.append(f"{provider_id or label}: invalid rights_status")
        if adapter_status not in ALLOWED_ADAPTER_STATUSES:
            findings.append(f"{provider_id or label}: invalid adapter_status")
        if automation_allowed is not None and type(automation_allowed) is not bool:
            findings.append(f"{provider_id or label}: automated_access_allowed must be true, false or null")

        if rights_status == "review_before_enable":
            pending_count += 1
            if automation_allowed is not None:
                findings.append(f"{provider_id}: pending rights review requires automated_access_allowed=null")
            if reviewed_at is not None:
                findings.append(f"{provider_id}: pending rights review requires rights_reviewed_at=null")
            if adapter_status == "not_permitted":
                findings.append(f"{provider_id}: pending source cannot be marked not_permitted without a decision")
        elif rights_status == "automated_access_prohibited":
            rejected_count += 1
            if automation_allowed is not False:
                findings.append(f"{provider_id}: prohibited source must set automated_access_allowed=false")
            if not _review_date(reviewed_at):
                findings.append(f"{provider_id}: prohibited source requires a review date")
            if adapter_status != "not_permitted":
                findings.append(f"{provider_id}: prohibited source adapter must be not_permitted")
        elif rights_status == "reviewed_public_access":
            reviewed_access_count += 1
            if automation_allowed is not True:
                findings.append(f"{provider_id}: reviewed public access requires automated_access_allowed=true")
            if not _review_date(reviewed_at):
                findings.append(f"{provider_id}: reviewed public access requires a review date")
            if adapter_status == "not_permitted":
                findings.append(f"{provider_id}: reviewed public access cannot use a not_permitted adapter")

        if provider_id in AUTOMATION_PROHIBITED_PROVIDER_IDS:
            if rights_status != "automated_access_prohibited":
                findings.append(f"{provider_id}: provider is pinned as automation-prohibited")
            if automation_allowed is not False:
                findings.append(f"{provider_id}: pinned provider cannot allow automated access")
            if adapter_status != "not_permitted":
                findings.append(f"{provider_id}: pinned provider cannot receive an executable adapter")

        for field in ("runtime_enabled", "line_quote_eligible"):
            if type(provider.get(field)) is not bool:
                findings.append(f"{provider_id or label}: {field} must be a boolean")
        enabled = provider.get("runtime_enabled") is True
        line_eligible = provider.get("line_quote_eligible") is True
        reviewed = _rights_reviewed(provider)
        if enabled or line_eligible:
            attempted_activation += 1
            if rights_status != "reviewed_public_access":
                findings.append(f"{provider_id}: enabled/eligible provider lacks rights review")
            if automation_allowed is not True:
                findings.append(f"{provider_id}: enabled/eligible provider does not allow automation")
            if adapter_status != "adapter_reviewed":
                findings.append(f"{provider_id}: enabled/eligible provider lacks reviewed adapter")
        if enabled != line_eligible:
            findings.append(
                f"{provider_id}: runtime_enabled and line_quote_eligible must change atomically"
            )
        if enabled and line_eligible and reviewed:
            fully_eligible += 1
        findings.extend(_scope_findings(provider_id or label, provider, enabled=enabled or line_eligible, today=day))

    missing_pinned = sorted(AUTOMATION_PROHIBITED_PROVIDER_IDS.difference(ids))
    if missing_pinned:
        findings.append("automation-prohibited provider decisions were removed from the catalog")
    if len(jurisdictions) < 6:
        findings.append("public options candidates lack jurisdictional diversity")
    if len(authorities) < 8:
        findings.append("public options candidates lack authority diversity")
    if not any("quote" in role for role in roles):
        findings.append("public options candidates lack quote-oriented roles")
    if not any("open_interest" in role for role in roles):
        findings.append("public options candidates lack open-interest roles")

    expected_development = {
        "official_authority": False,
        "rights_status": "unreviewed",
        "production_eligible": False,
        "line_live_fetch_eligible": False,
        "runtime_enabled": False,
        "paid": False,
        "ibkr_or_broker_derived": False,
        "may_be_used_when_current_public_data_enabled": False,
        "may_be_published_as_current": False,
        "replacement_required_before_external_live_options": True,
    }
    for key, expected in expected_development.items():
        if development.get(key) != expected:
            findings.append(f"public-options-development-provider.json: {key} must be {expected!r}")
    if development.get("provider_id") != "yfinance_unreviewed_delayed":
        findings.append("Development provider must be explicitly identified as unreviewed yfinance")

    vars_document = wrangler.get("vars") if isinstance(wrangler.get("vars"), dict) else {}
    current_enabled = str(vars_document.get("CURRENT_PUBLIC_DATA_ENABLED") or "").casefold() == "true"
    if fully_eligible == 0 and current_enabled:
        findings.append(
            "cloud/wrangler.toml: CURRENT_PUBLIC_DATA_ENABLED must remain false without an eligible provider"
        )
    if fully_eligible == 0 and candidates.get("production_quote_provider_selected") is not False:
        findings.append("production_quote_provider_selected must remain false")
    if fully_eligible > 0 and candidates.get("production_quote_provider_selected") is not True:
        findings.append("eligible provider requires explicit production_quote_provider_selected=true")

    if "import yfinance as yf" not in builder:
        findings.append("Public option builder development-provider classification is stale")
    if "fetch_options_ibkr" in builder or "options_service" in builder:
        findings.append("Public option builder must not import broker/provider orchestration")

    line = runtime.get("line") if isinstance(runtime.get("line"), dict) else {}
    data = runtime.get("data") if isinstance(runtime.get("data"), dict) else {}
    if line.get("ibkr_bridge") is not False or line.get("brokerage_connection") is not False:
        findings.append("runtime-policy.json: LINE broker boundary must remain false")
    if data.get("required_sources_must_be_free") is not True:
        findings.append("runtime-policy.json: public option sources must remain free-only")

    summary = {
        "candidate_count": len(providers),
        "authority_count": len(authorities),
        "jurisdiction_count": len(jurisdictions),
        "data_role_count": len(roles),
        "pending_rights_count": pending_count,
        "automation_prohibited_count": rejected_count,
        "reviewed_public_access_count": reviewed_access_count,
        "runtime_enabled_count": sum(
            isinstance(value, dict) and value.get("runtime_enabled") is True for value in providers
        ),
        "line_quote_eligible_count": sum(
            isinstance(value, dict) and value.get("line_quote_eligible") is True for value in providers
        ),
        "attempted_activation_count": attempted_activation,
        "fully_eligible_count": fully_eligible,
        "development_provider": development.get("provider_id"),
        "production_provider_selected": candidates.get("production_quote_provider_selected"),
    }
    return findings, summary


class PublicOptionPolicy:
    """Admission snapshot built by load_public_option_policy from the audited canonical catalog. It holds a DEEP COPY taken at
    construction and provider() returns deep copies, so a caller cannot mutate the cached admission through the accessors, and
    attribute assignment is refused. This is accidental-mutation protection only: in-process Python code can still construct the
    class or monkeypatch the module, and no unforgeability is claimed. Admission never takes a caller-supplied provider map or flag."""

    __slots__ = ("_providers",)

    def __init__(self, providers: dict[str, dict[str, Any]]) -> None:
        object.__setattr__(self, "_providers", copy.deepcopy(providers))

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("PublicOptionPolicy is immutable")

    def provider_ids(self) -> list[str]:
        return sorted(self._providers)

    def provider(self, provider_id: str) -> dict[str, Any] | None:
        found = self._providers.get(provider_id)
        return copy.deepcopy(found) if found is not None else None


def load_public_option_policy(root: Path = ROOT, today: date | None = None) -> PublicOptionPolicy:
    """Providers fully eligible for PUBLIC option display, from the single canonical catalog. Fail closed: any unreadable, invalid,
    unaudited (audit findings), unselected, stale or scope-less state yields an EMPTY policy that admits nothing. No network."""
    try:
        day = today or datetime.now(timezone.utc).date()
        findings, _summary = audit_public_options_providers(root, today=day)
        if findings:
            return PublicOptionPolicy({})
        catalog = _object(root / "config" / "public-options-provider-candidates.json")
        providers = catalog.get("providers")
        if catalog.get("production_quote_provider_selected") is not True or not isinstance(providers, list):
            return PublicOptionPolicy({})
        eligible: dict[str, dict[str, Any]] = {}
        for provider in providers:
            if not isinstance(provider, dict):
                return PublicOptionPolicy({})
            if not (provider.get("runtime_enabled") is True and provider.get("line_quote_eligible") is True and _rights_reviewed(provider)):
                continue
            reviewed = _date_value(provider.get("rights_reviewed_at"))
            through = _date_value(provider.get("review_valid_through"))
            if reviewed is None or through is None or reviewed > day or through < day or through < reviewed:
                continue
            if not (_safe_https(provider.get("official_url")) and _safe_https(provider.get("rights_evidence_url"))):
                continue
            if not isinstance(provider.get("admitted_scopes"), list) or not provider["admitted_scopes"]:
                continue
            eligible[str(provider["id"])] = provider
        return PublicOptionPolicy(eligible)
    except Exception:
        return PublicOptionPolicy({})


def public_option_cycle_admission(cycle: Any, policy: Any) -> str | None:
    """None only when the row's CLAIMED identity (provider_id, jurisdiction, venue, instrument_kind, quote_basis, publication_scope)
    exactly matches an admitted scope of a fully eligible provider of the policy; else OPTION_RIGHTS_NOT_ADMITTED. Rights labels,
    currency, source text and provenance are never identity and never admit. A row cannot self-grant rights."""
    if not isinstance(policy, PublicOptionPolicy) or not isinstance(cycle, dict):
        return OPTION_RIGHTS_NOT_ADMITTED
    claimed: dict[str, str] = {}
    for field in IDENTITY_FIELDS:
        value = cycle.get(field)
        if type(value) is not str or not value:
            return OPTION_RIGHTS_NOT_ADMITTED
        claimed[field] = value
    provider = policy.provider(claimed["provider_id"])
    scopes = provider.get("admitted_scopes") if provider else None
    if not isinstance(scopes, list):
        return OPTION_RIGHTS_NOT_ADMITTED
    for scope in scopes:
        if isinstance(scope, dict) and all(scope.get(key) == claimed[key] for key in SCOPE_KEYS):
            return None
    return OPTION_RIGHTS_NOT_ADMITTED


def main() -> int:
    try:
        findings, summary = audit_public_options_providers()
    except (
        FileNotFoundError,
        json.JSONDecodeError,
        tomllib.TOMLDecodeError,
        PublicOptionsProviderError,
        OSError,
    ) as exc:
        print(f"PUBLIC OPTIONS PROVIDER GATE FAILED\n- {exc}")
        return 1
    if findings:
        print("PUBLIC OPTIONS PROVIDER GATE FAILED")
        for finding in findings:
            print(f"- {finding}")
        return 1
    print("PUBLIC OPTIONS PROVIDER GATE PASSED")
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
