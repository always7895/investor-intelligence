#!/usr/bin/env python3
"""Run offline-safe tests in a repository checkout or clean release ZIP.

Repository mode executes the complete suite. Distribution mode executes only
package-compatible tests and never assumes ``.git``, ``.github`` or ``state``
exists. Missing optional live providers are replaced by fail-closed import
stubs; a test cannot silently perform network/provider activity through them.
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

DISTRIBUTION_SAFE_PATTERNS = (
    "test_actions_storage_policy_gate.py",
    "test_active_scan.py",
    "test_attribution.py",
    "test_authoritative_source_catalog.py",
    "test_build_line_public_options.py",
    "test_dependency_lock_renderer.py",
    "test_derive_tenant_hash.py",
    "test_delivery_bundle.py",
    "test_final_cleanup_gate.py",
    "test_final_distribution_scripts.py",
    "test_free_only_runtime.py",
    "test_generate_public_briefing.py",
    "test_ibkr_readonly.py",
    "test_kv_namespace_isolation_gate.py",
    "test_line_public_options_closed_dto.py",
    "test_local_research_config.py",
    "test_manual_option_calculator_gate.py",
    "test_options.py",
    "test_options_service.py",
    "test_phase8_fault_injection_gate.py",
    "test_privacy_cost_policy.py",
    "test_public_artifact_closed_schema.py",
    "test_public_options_provider_gate.py",
    "test_public_symbol_admission.py",
    "test_release_candidate_gate.py",
    "test_replayed_authoritative_adapters.py",
    "test_report.py",
    "test_schedule_planner.py",
    "test_scoring.py",
    "test_secure_public_fetch_canonical.py",
    "test_security_check.py",
    "test_source_claim_coverage_gate.py",
    "test_source_diversity_gate.py",
    "test_source_health.py",
    "test_source_ingestion_boundaries.py",
    "test_source_observation.py",
    "test_source_registry.py",
    "test_staged_gleif_ecb_adapters.py",
    "test_sync_to_kv.py",
    "test_validate_kv_namespace_ids.py",
)


class OfflineProviderUnavailable(RuntimeError):
    pass


def _install_yfinance_stub() -> None:
    if importlib.util.find_spec("yfinance") is not None:
        return
    module = types.ModuleType("yfinance")

    class Ticker:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            raise OfflineProviderUnavailable(
                "yfinance is unavailable in offline unit tests; live fallback was not called"
            )

    module.Ticker = Ticker  # type: ignore[attr-defined]
    sys.modules["yfinance"] = module


def _install_pandas_stub() -> None:
    if importlib.util.find_spec("pandas") is not None:
        return
    sys.modules["pandas"] = types.ModuleType("pandas")


def _install_requests_stub() -> None:
    if importlib.util.find_spec("requests") is not None:
        return

    requests_module = types.ModuleType("requests")
    adapters_module = types.ModuleType("requests.adapters")

    class Headers(dict[str, str]):
        pass

    class Session:
        def __init__(self) -> None:
            self.headers: Headers = Headers()

        def mount(self, *_args: Any, **_kwargs: Any) -> None:
            return None

        def request(self, *_args: Any, **_kwargs: Any) -> Any:
            raise OfflineProviderUnavailable(
                "requests is unavailable in offline unit tests; live HTTP was not called"
            )

    class HTTPAdapter:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

    def unavailable(*_args: Any, **_kwargs: Any) -> Any:
        raise OfflineProviderUnavailable(
            "requests is unavailable in offline unit tests; live HTTP was not called"
        )

    requests_module.Session = Session  # type: ignore[attr-defined]
    requests_module.get = unavailable  # type: ignore[attr-defined]
    requests_module.post = unavailable  # type: ignore[attr-defined]
    requests_module.request = unavailable  # type: ignore[attr-defined]
    adapters_module.HTTPAdapter = HTTPAdapter  # type: ignore[attr-defined]
    requests_module.adapters = adapters_module  # type: ignore[attr-defined]
    sys.modules["requests"] = requests_module
    sys.modules["requests.adapters"] = adapters_module


def _install_urllib3_stub() -> None:
    if importlib.util.find_spec("urllib3") is not None:
        return

    urllib3_module = types.ModuleType("urllib3")
    util_module = types.ModuleType("urllib3.util")
    retry_module = types.ModuleType("urllib3.util.retry")
    exceptions_module = types.ModuleType("urllib3.exceptions")

    class Retry:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

    class InsecureRequestWarning(Warning):
        pass

    def disable_warnings(*_args: Any, **_kwargs: Any) -> None:
        return None

    retry_module.Retry = Retry  # type: ignore[attr-defined]
    exceptions_module.InsecureRequestWarning = InsecureRequestWarning  # type: ignore[attr-defined]
    urllib3_module.disable_warnings = disable_warnings  # type: ignore[attr-defined]
    urllib3_module.exceptions = exceptions_module  # type: ignore[attr-defined]
    urllib3_module.util = util_module  # type: ignore[attr-defined]
    util_module.retry = retry_module  # type: ignore[attr-defined]
    sys.modules["urllib3"] = urllib3_module
    sys.modules["urllib3.exceptions"] = exceptions_module
    sys.modules["urllib3.util"] = util_module
    sys.modules["urllib3.util.retry"] = retry_module


def install_optional_dependency_stubs() -> None:
    _install_yfinance_stub()
    _install_pandas_stub()
    _install_requests_stub()
    _install_urllib3_stub()


def _distribution_suite(loader: unittest.TestLoader) -> unittest.TestSuite:
    suite = unittest.TestSuite()
    for pattern in DISTRIBUTION_SAFE_PATTERNS:
        path = ROOT / "tests" / pattern
        if not path.is_file():
            raise FileNotFoundError(f"Distribution-safe test is missing: {pattern}")
        suite.addTests(loader.discover(str(ROOT / "tests"), pattern=pattern))
    return suite


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--repository", action="store_true")
    mode.add_argument("--distribution", action="store_true")
    args = parser.parse_args()

    install_optional_dependency_stubs()
    repository_available = (ROOT / ".git").exists() and (ROOT / ".github" / "workflows").is_dir()
    distribution_mode = args.distribution or (not args.repository and not repository_available)

    loader = unittest.TestLoader()
    if distribution_mode:
        print("OFFLINE TEST MODE: FINAL DISTRIBUTION (repository-only metadata gates excluded)")
        suite = _distribution_suite(loader)
    else:
        print("OFFLINE TEST MODE: COMPLETE REPOSITORY")
        suite = loader.discover(str(ROOT / "tests"), pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
