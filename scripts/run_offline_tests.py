#!/usr/bin/env python3
"""Run the repository unit suite without downloading optional live providers.

Only absent optional packages are stubbed. Every stub fails closed if a test
attempts a live network/provider operation, while import-time policy and parser
tests remain available on a clean runner.
"""
from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


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
    module = types.ModuleType("pandas")
    sys.modules["pandas"] = module


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


def main() -> int:
    install_optional_dependency_stubs()
    loader = unittest.TestLoader()
    suite = loader.discover(str(ROOT / "tests"), pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
