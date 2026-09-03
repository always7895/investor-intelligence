[CmdletBinding()]
param([string]$ProjectRoot = '')
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Set-StrictMode -Version Latest

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
}
$ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

$v4Path = Join-Path $ProjectRoot 'scripts\v213_source_independence_gate_v4.py'
if (-not (Test-Path -LiteralPath $v4Path -PathType Leaf)) {
    throw 'Final v4 source-independence gate is missing.'
}
$v4Text = Get-Content -LiteralPath $v4Path -Raw -Encoding utf8
foreach ($marker in @(
    'MIN_HIGH_CONFIDENCE_MARKET_PROVIDERS = 2',
    'MARKET_HARD_MAX_AGE_DAYS = 7.0',
    'MARKET_HIGH_CONFIDENCE_FRESHEST_MAX_AGE_DAYS = 4.0',
    'MARKET_COMPARABLE_PROVIDER_MAX_LAG_DAYS = 3.0',
    'worker_degradation_schema_compatible=true'
)) {
    if (-not $v4Text.Contains($marker)) { throw "Final v4 source gate marker is missing: $marker" }
}

$entrypoint = @'
#!/usr/bin/env python3
"""Compatibility entrypoint for the final v2.1.3 source-independence gate.

The implementation lives in ``v213_source_independence_gate_v4.py``. This stable
path is retained because existing launchers and qualification scripts invoke the
v3 filename.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

V4_PATH = Path(__file__).resolve().with_name("v213_source_independence_gate_v4.py")
if not V4_PATH.is_file():
    raise RuntimeError(f"Missing final source-independence implementation: {V4_PATH}")
spec = importlib.util.spec_from_file_location(
    "investor_intelligence_v213_source_gate_v4_entrypoint",
    V4_PATH,
)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Unable to load final source-independence gate: {V4_PATH}")
v4 = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = v4
spec.loader.exec_module(v4)

if __name__ == "__main__":
    if "--wrapper-self-test" in sys.argv:
        v4.self_test()
        raise SystemExit(0)
    raise SystemExit(v4.gate.main())
'@
$entryPath = Join-Path $ProjectRoot 'scripts\v213_source_independence_gate_v3.py'
[IO.File]::WriteAllText($entryPath, ($entrypoint.TrimStart() + "`n"), $utf8NoBom)

$policyPath = Join-Path $ProjectRoot 'config\v213-serenity-evidence-freshness-policy.json'
if (-not (Test-Path -LiteralPath $policyPath -PathType Leaf)) {
    throw 'Serenity evidence freshness policy is missing.'
}
$policy = Get-Content -LiteralPath $policyPath -Raw -Encoding utf8 | ConvertFrom-Json
$policy.schema_version = 1
$policy.product_version = '2.1.3'
$policy.policy_id = 'v213-serenity-fresh-independent-evidence-v2'
$policy.description_en = 'Final v2.1.3 candidates require recent dated company evidence and fresh comparable independently operated market corroboration. Retrieval time never substitutes for publication/as-of time; Yahoo remains compatibility calculation only.'
$policy.description_zh_TW = 'v2.1.3 最終候選必須使用具日期且仍在有效期間的公司證據，以及新鮮、可比較、彼此獨立營運的市場交叉驗證。檢索時間不得取代發布／資料截至時間；Yahoo 僅保留相容性計算角色。'
$policy.activation_snapshot_max_age_hours = 2
$policy.clock_skew_tolerance_minutes = 5
$policy.market_observation_max_age_days = 7
if ($null -eq $policy.PSObject.Properties['market_high_confidence_freshest_max_age_days']) {
    $policy | Add-Member -NotePropertyName market_high_confidence_freshest_max_age_days -NotePropertyValue 4
} else { $policy.market_high_confidence_freshest_max_age_days = 4 }
if ($null -eq $policy.PSObject.Properties['market_comparable_provider_max_lag_days']) {
    $policy | Add-Member -NotePropertyName market_comparable_provider_max_lag_days -NotePropertyValue 3
} else { $policy.market_comparable_provider_max_lag_days = 3 }
if ($null -eq $policy.PSObject.Properties['minimum_independent_market_providers_for_high_confidence']) {
    $policy | Add-Member -NotePropertyName minimum_independent_market_providers_for_high_confidence -NotePropertyValue 2
} else { $policy.minimum_independent_market_providers_for_high_confidence = 2 }
$policy.macro_observation_max_age_days = 45
$policy.current_state_claim_max_age_days = 135
$policy.structural_claim_max_age_days = 550
$policy.minimum_claim_source_families_per_ticker = 2
$policy.minimum_claim_source_domains_per_ticker = 2
$policy.minimum_claim_primary_sources_per_ticker = 1
$policy.minimum_sensitive_advantage_source_units = 2
$policy.minimum_sensitive_advantage_domains = 2
$policy.minimum_claim_dated_evidence_ratio = 0.8
foreach ($name in @(
    'market_data_is_company_claim_evidence','official_macro_is_company_claim_evidence',
    'same_registrable_domain_is_independent','same_publisher_family_is_independent',
    'syndicated_duplicate_is_independent','conflicting_sources_are_averaged',
    'stale_live_market_observation_is_publishable','undated_sensitive_advantage_is_publishable',
    'single_source_positive_advantage_is_publishable'
)) {
    if ($null -eq $policy.PSObject.Properties[$name]) {
        $policy | Add-Member -NotePropertyName $name -NotePropertyValue $false
    } else { $policy.$name = $false }
}
foreach ($name in @(
    'fresh_non_primary_corroborator_required_for_positive_advantage',
    'retrieval_timestamp_cannot_substitute_publication_date',
    'latest_available_evidence_must_be_selected',
    'comparable_market_metric_basis_required_for_high_confidence'
)) {
    if ($null -eq $policy.PSObject.Properties[$name]) {
        $policy | Add-Member -NotePropertyName $name -NotePropertyValue $true
    } else { $policy.$name = $true }
}
$policy.sensitive_advantage_factors = @(
    'demand_wave','chokepoint','pricing_power','replacement_friction','tam_capture'
)
$policy.required_release_properties = @(
    'fresh_same_run_snapshot',
    'fresh_market_observations_only',
    'latest_available_publication_or_as_of_selected',
    'retrieval_time_never_substitutes_for_publication_time',
    'two_claim_source_families_per_ticker',
    'two_claim_source_domains_per_ticker',
    'one_primary_claim_source_per_ticker',
    'fresh_non_primary_corroborator_for_positive_advantages',
    'two_fresh_comparable_market_providers_for_high_confidence',
    'same_metric_basis_for_return_comparison',
    'source_conflicts_preserved_not_averaged',
    'stale_and_unavailable_sources_disclosed'
)
[IO.File]::WriteAllText(
    $policyPath,
    (($policy | ConvertTo-Json -Depth 12) + "`n"),
    $utf8NoBom
)

$verified = Get-Content -LiteralPath $policyPath -Raw -Encoding utf8 | ConvertFrom-Json
if (
    [double]$verified.current_state_claim_max_age_days -gt 135 -or
    [double]$verified.market_observation_max_age_days -gt 7 -or
    [double]$verified.market_high_confidence_freshest_max_age_days -gt 4 -or
    [double]$verified.market_comparable_provider_max_lag_days -gt 3 -or
    [int]$verified.minimum_independent_market_providers_for_high_confidence -lt 2 -or
    $verified.latest_available_evidence_must_be_selected -ne $true -or
    $verified.retrieval_timestamp_cannot_substitute_publication_date -ne $true
) {
    throw 'Normalized latest-data policy failed readback validation.'
}
Write-Host 'V213_FINAL_SOURCE_GATE_NORMALIZATION = PASS; entrypoint=v3_to_v4; current_claim_max_days=135; market_hard_max_days=7; freshest_high_confidence_days=4; comparable_lag_days=3; high_confidence_market_providers=2; latest_available_required=true' -ForegroundColor Green
