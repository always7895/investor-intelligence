#!/usr/bin/env python3
"""Fail closed if the ephemeral manual option calculator gains unsafe capabilities."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = "cloud/src/manual-options.ts"
WORKER = "cloud/src/worker.ts"
DOC = "docs/MANUAL_OPTION_CALCULATOR.md"
TEST = "cloud/test/manual-options.test.ts"


def _read(root: Path, relative: str) -> str:
    path = root / relative
    if not path.is_file():
        raise FileNotFoundError(relative)
    return path.read_text(encoding="utf-8")


def audit_manual_option_calculator(root: Path = ROOT) -> list[str]:
    findings: list[str] = []
    try:
        module = _read(root, MODULE)
        worker = _read(root, WORKER)
        documentation = _read(root, DOC)
        tests = _read(root, TEST)
    except (FileNotFoundError, OSError) as exc:
        return [str(exc)]

    required_module = (
        'export function manualOptionQuoteAnswer(text: string): string | null',
        'export function parseManualOptionInput(text: string)',
        'export function formatManualOptionQuote(input: ManualOptionInput)',
        'USER_SUPPLIED_NOT_VERIFIED',
        '不接受任何持倉、帳戶或個人財務欄位',
        '沒有抓取或驗證行情',
        '不下單',
        '不是推薦',
        'const PRIVATE_FIELDS = new Set',
        'if (ask < bid)',
        'if (dte < 1 || dte > 730)',
    )
    for marker in required_module:
        if marker not in module:
            findings.append(f"{MODULE}: missing required invariant {marker!r}")

    forbidden_module = (
        'fetch(',
        'publicJson',
        'publicText',
        'KVNamespace',
        'putJob',
        'saveConversation',
        'fetch_options_ibkr',
        'options_service',
        'IBKR',
        'LINE_CHANNEL_ACCESS_TOKEN',
        'account_id',
        'portfolio.local',
        'Math.random',
        'Date.now',
        'new Date',
    )
    for marker in forbidden_module:
        if marker in module:
            findings.append(f"{MODULE}: forbidden capability/token {marker!r}")

    required_worker = (
        'import { manualOptionQuoteAnswer } from "./manual-options";',
        'const manualOption = manualOptionQuoteAnswer(text);',
        'if (manualOption !== null)',
        'await rateLimit(env, tenantId, query.intent)',
        'manual_option_calculator: "ephemeral_user_supplied_only"',
        'lineAccessAllowed',
        'source.type !== "user"',
    )
    for marker in required_worker:
        if marker not in worker:
            findings.append(f"{WORKER}: missing required integration {marker!r}")
    rate_limit_index = worker.find('await rateLimit(env, tenantId, query.intent)')
    calculator_index = worker.find('const manualOption = manualOptionQuoteAnswer(text);')
    deterministic_index = worker.find('const deterministic = await deterministicAnswer')
    if not (0 <= rate_limit_index < calculator_index < deterministic_index):
        findings.append(
            f"{WORKER}: manual calculator must run after rate limiting and before model-capable QA"
        )

    for marker in (
        "closed `key=value` schema",
        "not written to public KV",
        "not sent to the local model",
        "USER_SUPPLIED_NOT_VERIFIED",
        "does not fetch or verify a quote",
    ):
        if marker not in documentation:
            findings.append(f"{DOC}: missing required documentation marker {marker!r}")

    for marker in (
        "does not intercept an ordinary public option query",
        "rejects personal holdings and account fields",
        "fails closed on unknown duplicate or missing fields",
        "rejects inverted, non-decimal and unbounded values",
    ):
        if marker not in tests:
            findings.append(f"{TEST}: missing retained regression {marker!r}")
    return findings


def main() -> int:
    findings = audit_manual_option_calculator()
    if findings:
        print("MANUAL OPTION CALCULATOR GATE FAILED")
        for finding in findings:
            print(f"- {finding}")
        return 1
    print(
        "MANUAL OPTION CALCULATOR GATE PASSED: user-supplied, ephemeral, closed-schema, "
        "rate-limited, no fetch, storage, model, broker, holdings or order capability"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
