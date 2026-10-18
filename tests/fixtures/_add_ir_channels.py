"""One-shot writer tool (ORDERS-V3-01 r6): add the reviewed official-IR channel fields to the registry and the
r2 fixture (9 issuers, from _archive/lane-orders-v3/verify/ir-channels.json), plus the CRWV reviewed IR item.
Text-level insertion: the surrounding formatting is preserved, and both files are re-parsed as JSON at the end.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

IR = {
    "NVDA": ("Q4_PRESS_RELEASES", "https://investor.nvidia.com/feed/PressRelease.svc/GetPressReleaseList",
             "NVIDIA Announces Financial Results for Second Quarter Fiscal 2027"),
    "CRWV": ("Q4_PRESS_RELEASES", "https://investors.coreweave.com/feed/PressRelease.svc/GetPressReleaseList",
             "CoreWeave Reports Strong Second Quarter 2026 Results"),
    "LITE": ("Q4_PRESS_RELEASES", "https://investor.lumentum.com/feed/PressRelease.svc/GetPressReleaseList",
             "Lumentum Announces Fourth Quarter and Full Fiscal Year 2026 Results"),
    "CRDO": ("Q4_PRESS_RELEASES", "https://investors.credosemi.com/feed/PressRelease.svc/GetPressReleaseList",
             "Credo Technology Group Holding Ltd Reports First Quarter of Fiscal Year 2027 Financial Results"),
    "MU": ("Q4_PRESS_RELEASES", "https://investors.micron.com/feed/PressRelease.svc/GetPressReleaseList",
           "Micron Technology, Inc. Reports Record Results for the Third Quarter of Fiscal 2026"),
    "BE": ("Q4_PRESS_RELEASES", "https://investor.bloomenergy.com/feed/PressRelease.svc/GetPressReleaseList",
           "Bloom Energy Reports Record Second Quarter 2026 Financial Results and Raises Full Year 2026 Guidance"),
    "AMD": ("RSS", "https://ir.amd.com/news-events/press-releases/rss",
            "AMD Reports Second Quarter 2026 Financial Results"),
    "MRVL": ("RSS", "https://investor.marvell.com/news-events/press-releases/rss",
             "Marvell Technology, Inc. Reports Second Quarter of Fiscal Year 2027 Financial Results"),
    "NBIS": ("NEWSROOM_HTML", "https://group.nebius.com/newsroom",
             "Nebius reports second quarter 2026 financial results"),
}

CRWV_REVIEW = (
    ',\n    {\n     "id": "https://investors.coreweave.com/news/2026/'
    'CoreWeave-Continues-to-Contract-New-Compute-Capacity-at-Higher-Prices/default.aspx",\n'
    '     "disposition": "REVIEWED_IRRELEVANT",\n     "reviewed_at": "2026-09-28T14:45:00Z",\n'
    '     "note": "contract pricing and commitments since June 30; no revenue guidance statement or change"\n    }'
)


def patch(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    for sym, (kind, url, title) in IR.items():
        m = re.search(r'"wire_symbol": "%s",\s*"wire_names": \[[^]]*\]' % re.escape(sym), text)
        assert m, f"{path.name}: no release_channels block for {sym}"
        insert = (',\n    "ir": {\n     "kind": "%s",\n     "url": "%s"\n    },\n'
                  '    "ir_guidance_release_title": "%s"' % (kind, url, title))
        text = text[: m.end()] + insert + text[m.end():]
    # The CRWV reviewed IR item (id = the IR item URL captured in ir-live-2026-09-28.txt).
    m = re.search(r'"id": "0001769628-26-000432",\s*"disposition": "REVIEWED_IRRELEVANT",\s*'
                  r'"reviewed_at": "[^"]*",\s*"note": "[^"]*"\s*\}', text)
    assert m, f"{path.name}: no CRWV last reviewed entry"
    text = text[: m.end()] + CRWV_REVIEW + text[m.end():]
    json.loads(text)  # must stay valid JSON
    path.write_text(text, encoding="utf-8")
    print(f"patched {path}")


patch(ROOT / "config" / "revenue-guidance-v1.json")
patch(ROOT / "tests" / "fixtures" / "revenue-guidance-issuers-r2.json")
print("ok")
