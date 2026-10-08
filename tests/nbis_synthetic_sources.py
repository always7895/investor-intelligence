"""SYNTHETIC_G4_NOT_GENUINE: deterministic NBIS inputs, never network evidence.

XHTML_IXBRL_SHAPED_SYNTHETIC statements are deliberately NOT representative of
real plain-HTML NBIS exhibits. All stores are owned TemporaryDirectory roots.
Tracked policy is read-only; this generator does not enable NBIS.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import revenue_guidance as guidance  # noqa: E402
import revenue_guidance_auto_verify as verify  # noqa: E402
import revenue_guidance_autoupdate as updater  # noqa: E402
import revenue_guidance_overlay as overlay  # noqa: E402

MARKER = "<!-- SYNTHETIC_G4_NOT_GENUINE -->"
SHAPE = "XHTML_IXBRL_SHAPED_SYNTHETIC"
COMPANY = "Nebius Group N.V."
SUBMISSIONS = "https://data.sec.gov/submissions/CIK0001513845.json"
ARCHIVES = "https://www.sec.gov/Archives/edgar/data/1513845/"
PROFILE_PATH = ROOT / "config/revenue-guidance-extraction-profiles-v1.json"
ORDINAL = {1: "first", 2: "second", 3: "third", 4: "fourth"}
MONTH_END = {1: ("March", 31), 2: ("June", 30), 3: ("September", 30), 4: ("December", 31)}
DURATION = {1: "Three", 2: "Six", 3: "Nine", 4: "Twelve"}
GAAP = "These unaudited condensed consolidated financial statements are prepared in accordance with U.S. GAAP."
CONTINUING = ("Revenues in the unaudited condensed consolidated statements of operations "
              "are revenues from continuing operations for all periods presented.")
HEADING = "Unaudited Condensed Consolidated Statements of Operations"
UNITS = "(in millions of U.S. dollars, except share and per share data)"
FILLER = "Neutral synthetic spacer. " * 180
BASELINE_REFERENCE_URL = ARCHIVES + "000000000031000305/tm3100305d1_ex99-2.htm"


def tracked():
    return json.loads(PROFILE_PATH.read_bytes())


def profile():
    return copy.deepcopy(next(p for p in tracked()["profiles"] if p["symbol"] == "NBIS"))


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def html(identity, body, xhtml=False):
    ns = ' xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"' if xhtml else ""
    return (f'<html{ns}><head><title>synthetic-g4-{identity}</title></head><body>'
            + MARKER + f"<!-- {identity} -->" + body + "</body></html>\n").encode("utf-8")


def fy_block(year):
    return (f"On track to achieve $7.2B–$7.6B revenue in {year} and $9.0B–$9.9B ARR. "
            "Nebius Group N.V.'s consolidated revenue guidance is prepared in accordance with U.S. GAAP.")


class Package:
    def __init__(self, accession, filed, year, quarter, shown, ytd=None, original=None, reaffirm=None):
        self.accession, self.filed, self.year, self.quarter = accession, filed, year, quarter
        self.shown, self.ytd, self.original, self.reaffirm = shown, ytd, original, reaffirm
        self.base = ARCHIVES + accession.replace("-", "") + "/"
        self.stem = f"tm{accession[11:13]}{int(accession[-6:]):05d}d1"
        self.names = [self.stem + suffix for suffix in ("_6k.htm", "_ex99-1.htm", "_ex99-2.htm")]
        self.title = f"Nebius reports {ORDINAL[quarter]} quarter {year} financial results"
        slug = "synthetic-g4-" + self.title.lower().replace(" ", "-")
        self.ir = "https://group.nebius.com/newsroom/" + slug
        self.wire = "https://www.nasdaq.com/press-release/" + slug

    def table(self):
        month, day = MONTH_END[self.quarter]
        headings = [f"Three months ended {month} {day}"]
        numbers = [self.shown]
        if self.ytd is not None:
            headings.append(f"{DURATION[self.quarter]} months ended {month} {day}")
            numbers.append(self.ytd)
        def row(cells, tag):
            return "<tr>" + "".join(f"<{tag}>{c}</{tag}>" for c in cells) + "</tr>"
        return ("<table>" + row(["Period"] + headings, "th")
                + row(["Year"] + [str(self.year)] * len(numbers), "th")
                + row(["Revenues"] + numbers, "td") + "</table>")

    def links(self, absolute=False):
        return "".join(f'<a href="{self.base if absolute else ""}{n}">Exhibit {i}</a>'
                       for i, n in enumerate(self.names[1:], 1))

    def documents(self):
        report = f"financial results for the {ORDINAL[self.quarter]} quarter of {self.year}"
        form = html(self.accession + "-form", f"<p>{COMPANY} FORM 6-K</p><p>{report}</p>" + self.links())
        statement = html(self.accession + "-statement", f"<p>{COMPANY} {SHAPE}</p>"
                         f"<p>Financial Highlights</p><p>Consolidated results</p>"
                         f"<p>{UNITS}</p>" + self.table() + f"<p>{FILLER}</p><p>{GAAP}</p>"
                         f"<p>{CONTINUING}</p><p>{HEADING}</p>"
                         f"<p>{UNITS}</p>" + self.table() + "<p>&#160;</p>", xhtml=True)
        letter_body = f"<p>{COMPANY}</p><p>Dear shareholders</p>"
        if self.original:
            letter_body += f"<p>{self.original} Guidance update</p><p>{fy_block(self.original)}</p>"
        if self.reaffirm:
            letter_body += ("<p>Financial model proving itself as we scale</p>"
                            f"<p>We are reaffirming our full-year {self.reaffirm} guidance across all metrics.</p>")
        elif self.original:
            letter_body += (f"<p>Consolidated revenue for the {ORDINAL[self.quarter]} quarter of {self.year} "
                            f"was ${self.shown.replace(',', '')} million.</p>")
        letter = html(self.accession + "-letter", letter_body)
        result = {self.base + n: raw for n, raw in zip(self.names, (form, statement, letter))}
        result[self.base + "index.json"] = encoded({"_synthetic": MARKER, "accession": self.accession,
                                                    "directory": {"item": [{"name": n} for n in self.names]}})
        for channel, url in (("ir", self.ir), ("wire", self.wire)):
            result[url] = html(self.accession + "-" + channel,
                               f"<p>{COMPANY}</p><p>{self.title}</p>" + self.links(absolute=True))
        return result


def z_packages():
    # The older Q1 filing is before 'since'; MP7 must request its index, unlike the control.
    return [Package("0000000000-32-000105", "2032-02-19", 2031, 4, "1,444.4", "5,111.0", original=2032),
            Package("0000000000-31-000305", "2031-11-13", 2031, 3, "1,333.3", "3,666.6"),
            Package("0000000000-31-000205", "2031-08-13", 2031, 2, "1,222.2", "2,333.3"),
            Package("0000000000-31-000105", "2031-05-14", 2031, 1, "1,111.1"),
            Package("0000000000-31-000104", "2031-05-13", 2031, 1, "1,111.1")]


def r_packages():
    return [Package("0000000000-34-000205", "2034-08-13", 2034, 2, "1,822.2", "3,533.3", reaffirm=2034),
            Package("0000000000-34-000105", "2034-05-14", 2034, 1, "1,711.1", original=2034),
            Package("0000000000-34-000004", "2034-02-19", 2033, 4, "1,644.4", "5,711.0"),
            Package("0000000000-33-000305", "2033-11-13", 2033, 3, "1,533.3", "4,066.6")]


def baseline(reference_package, raw, now):
    """Small synthetic predecessor; numbers are not inherited by the builder."""
    p = reference_package
    document_id = "SYNTHETIC-G4-BASELINE"
    q = p.quarter
    start = f"{p.year}-{3 * q - 2:02d}-01"
    end = f"{p.year}-{3 * q:02d}-{MONTH_END[q][1]:02d}"
    nq, ny = (q + 1, p.year) if q < 4 else (1, p.year + 1)
    intervals = []
    for step in range(4):
        fq = (nq - 1 + step) % 4 + 1
        fy = ny + (nq - 1 + step) // 4
        intervals.append({"fiscal_label": f"Q{fq} FY{fy % 100:02d}",
                          "start": f"{fy}-{3 * fq - 2:02d}-01",
                          "end": f"{fy}-{3 * fq:02d}-{MONTH_END[fq][1]:02d}",
                          "calendar_document_id": document_id, "calendar_locator": "synthetic-g4-calendar"})
    claim = {"id": "SYNTHETIC-G4-BASELINE-CLAIM", "document_id": document_id,
             "locator": "synthetic-g4-baseline", "passage": "Synthetic group revenue guidance: USD 1777.7 million.",
             "metric": "REVENUE", "assertion_kind": "COMPANY_GUIDANCE", "currency": "USD",
             "unit_multiplier": 1, "amount": 1777700000.0, "original_representation": "POINT",
             "scope": "COMPANY", "scope_label": "Company", "accounting_basis": "GAAP",
             "fiscal_label": f"Q{nq} FY{ny % 100:02d}", "period_kind": "QUARTER",
             "period_start": f"{ny}-{nq * 3 - 2:02d}-01", "period_end": f"{ny}-{nq * 3:02d}-{MONTH_END[nq][1]:02d}"}
    return {"symbol": "NBIS", "company_name": COMPANY, "status": "GUIDANCE", "reason": None,
            "url_prefixes": [ARCHIVES], "documents": [{"id": document_id, "issuer": "NBIS", "publisher": COMPANY,
            "title": "Synthetic G4 baseline", "source_kind": "SEC_6K_EXHIBIT", "url": p.base + p.names[2],
            "published_date": p.filed, "retrieved_at": now, "sha256": hashlib.sha256(raw).hexdigest(),
            "byte_size": len(raw), "lineage_id": document_id}], "claims": [claim],
            "reported_quarters": [{"fiscal_label": f"Q{q} FY{p.year % 100:02d}", "start": start, "end": end,
            "revenue": float(p.shown.replace(",", "")) * 1000000, "currency": "USD", "scope": "COMPANY",
            "accounting_basis": "GAAP", "document_id": document_id, "locator": "synthetic-g4-baseline"}],
            "forward_intervals": intervals, "fy_reconciliation": None, "reviewed_later_documents": [],
            "release_channels": {"sec_cik": 1513845, "wire_symbol": "NBIS", "wire_names": ["Nebius"],
            "ir": {"kind": "NEWSROOM_HTML", "url": "https://group.nebius.com/newsroom"},
            "ir_guidance_release_title": p.title}}


class FixtureTransport:
    """No connector exists: every request is an exact in-memory lookup plus real URL policy."""
    replay = False

    def __init__(self, bodies):
        self.bodies, self.requests = bodies, []

    def get(self, url, selected, symbol):
        self.requests.append(url)
        kind = updater.url_rule(url, selected)
        if symbol != "NBIS" or url not in self.bodies:
            raise AssertionError("UNEXPECTED_SYNTHETIC_REQUEST " + url)
        return self.bodies[url], updater.CONTENT_TYPES[kind][0]


class Scenario:
    def __init__(self, mode="Z"):
        self.mode = mode
        self.packages = z_packages() if mode == "Z" else r_packages()
        self.now = "2032-02-19T23:00:00Z" if mode == "Z" else "2034-08-13T23:00:00Z"
        self.moment = datetime.strptime(self.now, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        self.clock = lambda: self.moment
        self.profile = profile()
        self.bodies = {url: raw for p in self.packages for url, raw in p.documents().items()}
        self.bodies[SUBMISSIONS] = encoded({"_synthetic": MARKER, "cik": 1513845, "filings": {"recent": {
            "accessionNumber": [p.accession for p in self.packages],
            "form": ["6-K"] * len(self.packages), "filingDate": [p.filed for p in self.packages],
            "reportDate": [f"{p.year}-{p.quarter * 3:02d}-{MONTH_END[p.quarter][1]:02d}" for p in self.packages],
            "primaryDocument": [p.names[0] for p in self.packages]}}})
        ref = self.packages[1]
        self.baseline = baseline(ref, self.bodies[ref.base + ref.names[2]], self.now)
        current = self.packages[0]
        def item(p, channel):
            return {"id": getattr(p, channel), "date": p.filed, "title": p.title}
        material = [{"channel": "SEC_SUBMISSIONS", "id": p.accession, "date": p.filed,
                     "label": "6-K", "disposition": "POSSIBLY_RELEVANT"} for p in self.packages[:2]]
        material += [{"channel": channel, "id": getattr(p, attr), "date": p.filed,
                      "label": p.title, "disposition": "POSSIBLY_RELEVANT"}
                     for p, channel, attr in ((current, "ISSUER_IR", "ir"),
                     (current, "WIRE_PRESS_RELEASES", "wire"), (ref, "WIRE_PRESS_RELEASES", "wire"))]
        self.lead = {"accession": current.accession, "filed": current.filed,
                     "ir_item": item(current, "ir"), "wire_item": item(current, "wire"), "later_documents": material}
        self.transport = FixtureTransport(self.bodies)
        self._temp = None

    def __enter__(self):
        self._temp = tempfile.TemporaryDirectory(prefix="synthetic-g4-")
        self.root = Path(self._temp.name) / "state"
        return self

    def __exit__(self, *args):
        self._temp.cleanup()

    def plan(self, captures=None):
        self.event, self.captures = updater.plan_nbis_event(
            self.transport, self.root, self.profile, self.lead, self.now[:10], self.clock,
            {"bytes": 0, "store": 0}, captures=captures)
        return self.event, self.captures

    def loaded(self):
        return {k: overlay.load_capture(self.root, v) for k, v in self.captures.items()}

    def build(self):
        return verify.build_successor(self.profile, overlay.predecessor_view(self.baseline, self.baseline),
                                      self.event, self.loaded(), self.now)

    def expected_requests(self):
        rows = [SUBMISSIONS]
        for p in self.packages[:4]:
            rows += [p.base + "index.json"] + [p.base + n for n in sorted(p.names)]
        return rows + [self.packages[1].wire, self.packages[0].ir, self.packages[0].wire]
