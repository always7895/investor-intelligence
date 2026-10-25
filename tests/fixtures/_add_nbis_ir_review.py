"""One-shot writer tool (ORDERS-V3-01 r6): record the writer review of the NBIS newsroom AGM item on the official
IR channel (the same event the wire item 0001104659-26-101076 already documents as reviewed). The item's title
carries the result word "results" (meeting outcomes), so the collector classifies it POSSIBLY_RELEVANT and the
receipt stays REVIEW_REQUIRED until this reviewed_later_documents entry exists. Registry entry keeps the 14:26:45Z
review time of its sibling entries; the r2 fixture keeps its 10:35:58Z times."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NBIS_IR_ITEM = "https://group.nebius.com/newsroom/nebius-group-n-v-announces-results-of-its-annual-general-meeting-2026"


def entry(revised_at: str) -> str:
    return (
        ',\n    {\n     "id": "%s",\n     "disposition": "REVIEWED_IRRELEVANT",\n     "reviewed_at": "%s",\n'
        '     "note": "newsroom item: results of the annual general meeting (same event as reviewed wire item '
        '0001104659-26-101076); no revenue or guidance statement"\n    }' % (NBIS_IR_ITEM, revised_at)
    )


def patch(path: Path, reviewed_at: str, anchor_id: str) -> None:
    text = path.read_text(encoding="utf-8")
    m = re.search(r'"id": "%s",\s*"disposition": "REVIEWED_IRRELEVANT",\s*"reviewed_at": "[^"]*",\s*"note": "[^"]*"\s*\}'
                  % re.escape(anchor_id), text)
    assert m, f"{path.name}: no {anchor_id} reviewed entry"
    text = text[: m.end()] + entry(reviewed_at) + text[m.end():]
    json.loads(text)
    path.write_text(text, encoding="utf-8")
    print(f"patched {path.name}")


# Anchor on each file's existing NBIS 6-K closing review (present in both, unique in each).
patch(ROOT / "config" / "revenue-guidance-v1.json", "2026-09-28T14:26:45Z", "0001104659-26-105749")
patch(ROOT / "tests" / "fixtures" / "revenue-guidance-issuers-r2.json", "2026-09-28T10:35:58Z", "0001104659-26-105749")
print("ok")
