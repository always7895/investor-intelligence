#!/usr/bin/env python3
"""Local data_report text for one forward premise assessment (contract C2).

Renders either the side-by-side disclosure of two SUPPORTED values or the
withheld text with unresolved premises. Pure and import-inert; no I/O, clock,
conversion, ratio, growth, scoring, Top20 order field or publication.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import hashlib
import json

if __package__:
    from .v213_forward_premises_shadow import ForwardPremiseAssessment
else:
    from v213_forward_premises_shadow import ForwardPremiseAssessment

TITLE = "前瞻指引對照 / Guidance beside reported baseline"
WITHHELD = "無可靠公開預估"
NOTICE = "此為揭露值並列，非預測、成長率或評分；未取得發布資格。"
REVISED = "基準值在同一 SEC 文件內曾有不同申報值；採用 cutoff 前最新一次申報，仍須附註核對。"
# Same per-section ceiling as company_financial_products._product (UTF-16 units).
MAX_SECTION_UNITS = 4400


class ForwardRenderError(ValueError):
    """Fixed non-data-echoing render error."""


def _number(value: object) -> str:
    if type(value) is bool or type(value) not in (int, float, str):
        raise ForwardRenderError("FORWARD_RENDER_INVALID")
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise ForwardRenderError("FORWARD_RENDER_INVALID") from None
    if not number.is_finite():
        raise ForwardRenderError("FORWARD_RENDER_INVALID")
    return format(number, ",")


def _date(value: object) -> str:
    text = str(value)
    return text[:10] if len(text) >= 10 else text


def render_forward_comparison_block(assessment: object) -> str:
    """Return one data_report section; unresolved premises always withhold values."""
    if type(assessment) is not ForwardPremiseAssessment:
        raise ForwardRenderError("FORWARD_RENDER_INVALID")
    if not assessment.comparison_ready:
        unresolved = [
            f"{name}（{'、'.join(reasons) if reasons else state}）"
            for name, state, reasons in assessment.premise_states
            if name != "CONSUMER_ADMISSION" and state not in ("RESOLVED", "NOT_APPLICABLE_AGGREGATE_METRIC")
        ]
        lines = [TITLE, WITHHELD, "未解決前提：" + "；".join(unresolved)]
    else:
        base = dict(assessment.baseline_view)
        ahead = dict(assessment.forward_view)
        lines = [
            TITLE,
            (f"公司指引 {ahead['period']} 營收：{_number(ahead['value'])} {ahead['unit']} {ahead['currency']}"
             f"（{ahead['basis']}，{ahead['scope']}；{ahead['independent_evidence_families']} 個獨立來源；"
             f"主張 {ahead['claim_id']}）"),
            (f"已申報基準 {_date(base['period_start'])}～{_date(base['period_end'])} 營收：{_number(base['value'])} "
             f"{base['currency']}（us-gaap:{base['tag']}；accession {base['accession']}；申報 {_date(base['filed'])}；"
             f"CIK {base['cik']}）"),
        ]
        if "BASELINE_REVISED_WITHIN_DOCUMENT" in assessment.limitations:
            lines.append(REVISED)
        lines.append(NOTICE)
    text = "\n".join(lines)
    if len(text.encode("utf-16-le")) // 2 > MAX_SECTION_UNITS:
        raise ForwardRenderError("FORWARD_RENDER_TOO_LARGE")
    return text

def build_forward_comparison_artifact(assessment: object) -> dict:
    """Contract C2b (option C): one digest-bound local artifact; data_report is untouched."""
    text = render_forward_comparison_block(assessment)
    body = {
        "schema_version": 1,
        "kind": "FORWARD_COMPARISON_LOCAL_ARTIFACT",
        "audience": "OPERATOR_LOCAL_ONLY",
        "publication_eligible": False,
        "assessment": assessment.to_dict(),
        "text": text,
    }
    canonical = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {**body, "sha256": hashlib.sha256(canonical).hexdigest()}
