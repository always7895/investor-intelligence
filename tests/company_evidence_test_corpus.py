"""Deterministic synthetic test corpus; NOT REAL RESEARCH EVIDENCE.

Legacy company/numeric tokens preserve existing behavioral test cases only.
No source/audit/cache/network data is read; no writes occur at import.
Receipts here bind synthetic bytes, not authenticated publication or freshness.
"""
import hashlib
import json
from pathlib import Path

MARKER = "SYNTHETIC TEST FIXTURE - NOT REAL RESEARCH EVIDENCE"
DOCUMENTS = (('hitachi-fy2025-results',
  'HITACHI_GROUP_ISSUER',
  'Energy: Performance by Business Segment 25 (*)[ ]: Estimated YoY changes excl. FX impact FY2025 '
  'Key Performance Drivers (YoY) FY2026 Key Performance Drivers (YoY) Power Grids (incl. Hitachi '
  'Energy) By business: Revenue (+) Continued solid demand for transmission equipment and solid '
  'execution of strong order backlog, particularly in large-scale project and product businesses '
  'Profit (+) Profit increase driven by higher revenue bringing volume leverage; Improved revenue '
  'profile; Operational excellence; Solid project execution; Expansion of Lumada business; Lower '
  'IT platform renewal costs By region: Revenue (+) Expansion across all regions primarily in '
  'Europe, North America, and others Hitachi Energy Revenue 19.8 BUSD (YoY: +4.1 BUSD/+26%) Adj. '
  'EBITA 2.64 BUSD (YoY: +1.15 BUSD) Adj. EBITA Margin 13.4% (YoY: +3.9 pts)\n'
  '\n'
  'Consolidated Total Revenue 10,586.7 YoY [YoY excl. FX impact] +8% [+7%]'),
 ('gev-1q2026-results',
  'GE_VERNOVA_ISSUER',
  'We delivered significant growth and margin expansion in the first quarter as we executed our '
  'financial strategy. With robust equipment orders growth in each segment and continued services '
  'strength, our backlog grew to $163 billion, inclusive of Prolec GE\n'
  '\n'
  'Revenue of $9.3B, +16%, +7% organically* led by equipment at Electrification and Power'),
 ('gev-2q2026-transcript',
  'GE_VERNOVA_ISSUER',
  "Welcome to GE Vernova's Second Quarter 2026 Earnings Call. I'm joined today by our CEO, Scott "
  'Strazik, and CFO, Ken Parks.\n'
  '\n'
  'Electrification fixture introduction.\n'
  '\n'
  'In the second quarter, we booked orders of $24.2 billion, an 88% increase year-over-year\n'
  '\n'
  'Our services backlog grew approximately $10 billion or 12% year-over-year to $88 billion, led '
  'by Power.\n'
  '\n'
  'Electrification fixture conclusion.'),
 ('hitachi-energy-financial-outlook',
  'HITACHI_GROUP_ISSUER',
  'Revenues CAGR Target 2021-2024 12-15% Actual 21%'))

PROPOSALS = ({'claim_id': 'SYNTHETIC-1',
  'company_id': 'SYNTHETIC_ENTITY',
  'exact_passage': 'Hitachi Energy Revenue 19.8 BUSD (YoY: +4.1 BUSD/+26%) Adj. EBITA 2.64 BUSD '
                   '(YoY: +1.15 BUSD) Adj. EBITA Margin 13.4% (YoY: +3.9 pts)',
  'legal_entity': 'Synthetic test entity, not a real research claim',
  'metric': 'fixture_metric',
  'passage_context': 'Energy: Performance by Business Segment 25 (*)[ ]: Estimated YoY changes '
                     'excl. FX impact FY2025 Key Performance Drivers (YoY) FY2026 Key Performance '
                     'Drivers (YoY) Power Grids (incl. Hitachi Energy) By business: Revenue (+) '
                     'Continued solid demand for transmission equipment and solid execution of '
                     'strong order backlog, particularly in large-scale project and product '
                     'businesses Profit (+) Profit increase driven by higher revenue bringing '
                     'volume leverage; Improved revenue profile; Operational excellence; Solid '
                     'project execution; Expansion of Lumada business; Lower IT platform renewal '
                     'costs By region: Revenue (+) Expansion across all regions primarily in '
                     'Europe, North America, and others Hitachi Energy Revenue 19.8 BUSD (YoY: '
                     '+4.1 BUSD/+26%) Adj. EBITA 2.64 BUSD (YoY: +1.15 BUSD) Adj. EBITA Margin '
                     '13.4% (YoY: +3.9 pts)',
  'source_id': 'hitachi-fy2025-results'},
 {'claim_id': 'SYNTHETIC-2',
  'company_id': 'SYNTHETIC_ENTITY',
  'exact_passage': 'With robust equipment orders growth in each segment and continued services '
                   'strength, our backlog grew to $163 billion, inclusive of Prolec GE',
  'legal_entity': 'Synthetic test entity, not a real research claim',
  'metric': 'fixture_metric',
  'passage_context': 'We delivered significant growth and margin expansion in the first quarter as '
                     'we executed our financial strategy. With robust equipment orders growth in '
                     'each segment and continued services strength, our backlog grew to $163 '
                     'billion, inclusive of Prolec GE',
  'source_id': 'gev-1q2026-results'})


def build_corpus(root):
    """Write only into the caller's empty test directory; return two Paths."""
    root = Path(root)
    if not root.is_dir() or any(root.iterdir()):
        raise ValueError("EMPTY_FIXTURE_DIR_REQUIRED")

    def write(name, raw):
        with (root / name).open("xb") as stream:
            stream.write(raw)
        return hashlib.sha256(raw).hexdigest()

    def json_bytes(value):
        return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                           allow_nan=False, indent=2) + "\n").encode("utf-8")

    sources = []
    for source_id, lineage, content in DOCUMENTS:
        raw = (MARKER + "\n\n" + content + "\n").encode("utf-8")
        name = source_id + ".md"
        digest = write(name, raw)
        sources.append({"id": source_id,
                        "source_url": "https://example.com/synthetic/" + name,
                        "text_file": name, "text_sha256": digest,
                        "text_bytes": len(raw), "lineage_id": lineage,
                        "rights": "NOT_REVIEWED", "runtime_admitted": False})
    receipt = json_bytes({"synthetic_fixture": True, "purpose": MARKER,
                          "runtime_admitted": False})
    digest = write("synthetic-receipt.json", receipt)
    manifest = {"schema_version": 1, "scope": "PUBLIC_RESEARCH_INPUT_NOT_ADMITTED",
                "assembled_at": "2000-01-01T00:00:00Z", "record_count": 4,
                "sources": sources,
                "source_receipts": [{"file": "synthetic-receipt.json", "sha256": digest}]}
    write("research-sources.json", json_bytes(manifest))
    write("synthetic-proposals.json", json_bytes({"schema_version": 1,
          "scope": "COMPANY_EVIDENCE_RESEARCH_V1_PROPOSALS", "proposals": PROPOSALS}))
    return root / "research-sources.json", root / "synthetic-proposals.json"
