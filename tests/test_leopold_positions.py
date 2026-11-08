"""Leopold 13F lead layer: periods, amendments, CUSIP map, options, 13D/G events and currency (V16). No network."""
from __future__ import annotations

import json
import re
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import leopold_positions as leopold  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "leopold"
Q1 = FIXTURES / "info_table_q1_trimmed.xml"
Q2 = FIXTURES / "info_table_q2_trimmed.xml"
NOW = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
ACC_Q1, ACC_Q2, ACC_A = "0002045724-26-000008", "0000935836-26-000418", "0000935836-26-000999"
ACC_SHAZ, ACC_CORZ = "0000935836-26-000500", "0000919574-26-004796"
INDEX = {"sandisk": "SNDK", "micron technology": "MU", "sharonai": "SHAZ", "core scientific": "CORZ",
         "bloom energy": "BE", "widget works": "WDGT"}


def folder(accession: str) -> str:
    return leopold.folder_url(accession)


def make_fetch(filings, tables, extras=None, primary=None, documents=None):
    """filings: rows (form, accession, filed, period); tables: accession -> bytes; extras: url -> bytes;
    documents: accession -> primaryDocument name."""
    recent = {"form": [f[0] for f in filings], "accessionNumber": [f[1] for f in filings],
              "filingDate": [f[2] for f in filings], "reportDate": [f[3] for f in filings]}
    if documents:
        recent["primaryDocument"] = [documents.get(f[1], "") for f in filings]
    files = {leopold.SUBMISSIONS: json.dumps({"filings": {"recent": recent}}).encode()}
    for accession, raw in tables.items():
        files[folder(accession) + "index.json"] = json.dumps({"directory": {"item": [
            {"name": "primary_doc.xml"}, {"name": "form13fInfoTable.xml"}]}}).encode()
        files[folder(accession) + "form13fInfoTable.xml"] = raw
    for accession, raw in (primary or {}).items():
        files[folder(accession) + "primary_doc.xml"] = raw
    files.update(extras or {})

    def fetch(url: str) -> bytes:
        if url not in files:
            raise KeyError(url)
        return files[url]
    return fetch


def events_files():
    return {folder(ACC_SHAZ) + "primary_doc.xml": (FIXTURES / "sharonai_13da.xml").read_bytes(),
            folder(ACC_CORZ) + "primary_doc.xml": (FIXTURES / "corescientific_13da.xml").read_bytes()}


BASE = [("SCHEDULE 13D/A", ACC_SHAZ, "2026-09-17", "2026-09-15"), ("SCHEDULE 13D/A", ACC_CORZ, "2026-08-04", "2026-07-15"),
        ("13F-HR", ACC_Q2, "2026-08-14", "2026-06-30"), ("13F-HR", ACC_Q1, "2026-05-18", "2026-03-31")]


def base_build(**kwargs):
    fetch = make_fetch(BASE, {ACC_Q1: Q1.read_bytes(), ACC_Q2: Q2.read_bytes()}, events_files())
    return leopold.build(fetch, INDEX, NOW, **kwargs)


def by_ticker(document):
    return {p["ticker"] or p["cusip"]: p for p in document["positions"]}


class CusipMapTests(unittest.TestCase):
    def test_every_fixture_cusip_is_mapped_with_provenance(self):
        cusip_map = leopold.load_cusip_map()
        rows = leopold.parse_info_table(Q1.read_bytes()) + leopold.parse_info_table(Q2.read_bytes())
        for row in rows:
            self.assertIn(row["cusip"], cusip_map)
        for cusip, entry in cusip_map.items():
            self.assertTrue(entry["issuer"] and entry["verification"] and "note" in entry, cusip)
            if entry["ticker"] is None:
                self.assertTrue(entry["reason"], cusip)
        self.assertEqual(len(cusip_map), 34)

    def test_match_route(self):
        cusip_map = leopold.load_cusip_map()
        self.assertEqual(leopold.resolve_ticker("ANY NAME", "80004C200", {}, cusip_map), ("SNDK", "CUSIP_MAP"))
        self.assertEqual(leopold.resolve_ticker("VANECK ETF TRUST", "92189F676", {"vaneck etf trust": "XYZ"}, cusip_map), (None, "NONE"))
        self.assertEqual(leopold.resolve_ticker("WIDGET WORKS INC", "000000000", INDEX, cusip_map), ("WDGT", "NAME"))
        self.assertEqual(leopold.resolve_ticker("NO SUCH CO", "000000000", INDEX, cusip_map), (None, "NONE"))
        self.assertEqual(leopold.match_ticker("MICRON TECHNOLOGY INC", INDEX), "MU")


class CurrencyTests(unittest.TestCase):
    def test_schema_two_factors(self):
        document = base_build()
        positions = by_ticker(document)
        self.assertEqual(document["schema_version"], 2)
        self.assertEqual(document["filing"]["period"], "2026-06-30")
        self.assertEqual(positions["SNDK"]["currency_factor"], 0.25)
        self.assertEqual(positions["SNDK"]["currency_reason"], ["REGIME_SALP-2026-07-30-BOOK-SALE"])
        self.assertEqual(positions["MU"]["currency_factor"], 0.25)
        shaz = positions["SHAZ"]  # event dated 2026-09-15 is after the regime: the regime factor is not applied
        self.assertEqual(shaz["currency_factor"], min(1.0, 8070950 / 5396127))
        self.assertEqual(shaz["currency_reason"], ["EVENT_SCHEDULE 13D/A_2026-09-17"])
        corz = positions["CORZ"]  # event dated 2026-07-15 is before the regime: both factors apply
        self.assertAlmostEqual(corz["currency_factor"], min(1.0, 14089395 / 26008473) * 0.25, places=12)
        self.assertEqual(corz["currency_reason"], ["REGIME_SALP-2026-07-30-BOOK-SALE", "EVENT_SCHEDULE 13D/A_2026-08-04"])
        self.assertEqual(corz["post_period_event"]["shares"], 14089395.0)
        self.assertEqual(corz["post_period_event"]["event_date"], "2026-07-15")
        self.assertEqual(document["regime"], {"id": "SALP-2026-07-30-BOOK-SALE", "applies": True, "factor": 0.25, "review_overdue": False})
        self.assertFalse(document["regime_review_overdue"])
        self.assertIn("SALP-2026-07-30-BOOK-SALE", document["caveat"])

    def test_events_list(self):
        events = base_build()["events"]
        self.assertEqual([e["accession"] for e in events], [ACC_SHAZ, ACC_CORZ])
        shaz = events[0]
        self.assertEqual((shaz["form"], shaz["filed"], shaz["event_date"], shaz["cusip"], shaz["ticker"], shaz["shares"],
                          shaz["percent_of_class"]), ("SCHEDULE 13D/A", "2026-09-17", "2026-09-15", "778920306", "SHAZ", 8070950.0, 21.1))
        self.assertEqual(events[1]["subject"], "Core Scientific, Inc.")
        self.assertEqual(events[1]["percent_of_class"], 4.4)

    def test_regime_off_when_period_reaches_event_date(self):
        regime = json.loads((ROOT / "config" / "leopold-regime-events-v1.json").read_text(encoding="utf-8"))["events"]
        regime[0] = dict(regime[0], date="2026-06-30", superseded_by_13f_period_on_or_after="2026-06-30")
        document = base_build(regime_events=regime)
        self.assertFalse(document["regime"]["applies"])
        self.assertEqual(document["regime"]["factor"], 1.0)
        self.assertEqual(by_ticker(document)["SNDK"]["currency_factor"], 1.0)
        self.assertEqual(by_ticker(document)["SNDK"]["currency_reason"], [])

    def test_regime_config_shape(self):
        event = leopold.load_regime_events()[0]
        self.assertEqual((event["factor"], event["date"], event["review_by"], event["primary_confirmation"]), (0.25, "2026-07-30", "2026-11-20", None))
        self.assertEqual(event["lineage"], "PRESS_ONE_LINEAGE")
        self.assertEqual(len(event["re_reports"]), 2)
        self.assertEqual(len(event["originator_urls_not_read"]), 1)
        self.assertTrue(all("cnbc.com" not in url for url in event["re_reports"]))

    def test_review_overdue_still_applies(self):
        fetch = make_fetch(BASE, {ACC_Q1: Q1.read_bytes(), ACC_Q2: Q2.read_bytes()}, events_files())
        document = leopold.build(fetch, INDEX, datetime(2026, 11, 21, tzinfo=timezone.utc))
        self.assertTrue(document["regime_review_overdue"] and document["regime"]["review_overdue"] and document["regime"]["applies"])
        self.assertEqual(by_ticker(document)["SNDK"]["currency_factor"], 0.25)

    def test_small_book(self):
        tiny = re.sub(rb"<(?:ns1:)?value>\d+<", lambda m: m.group(0)[:m.group(0).index(b">") + 1] + b"1000<", Q2.read_bytes())
        fetch = make_fetch(BASE[2:], {ACC_Q1: Q1.read_bytes(), ACC_Q2: tiny})
        document = leopold.build(fetch, INDEX, NOW, regime_events=[])
        self.assertEqual(by_ticker(document)["SNDK"]["currency_factor"], 0.25)
        self.assertEqual(by_ticker(document)["SNDK"]["currency_reason"], ["SMALL_BOOK"])
        self.assertIsNone(document["regime"])

    def test_unknown_event_shares_leave_factor_unchanged(self):
        extras = events_files()
        extras[folder(ACC_SHAZ) + "primary_doc.xml"] = re.sub(rb"<aggregateAmountOwned>.*?</aggregateAmountOwned>", b"", extras[folder(ACC_SHAZ) + "primary_doc.xml"])
        fetch = make_fetch(BASE, {ACC_Q1: Q1.read_bytes(), ACC_Q2: Q2.read_bytes()}, extras)
        shaz = by_ticker(leopold.build(fetch, INDEX, NOW))["SHAZ"]
        self.assertEqual(shaz["currency_factor"], 0.25)
        self.assertEqual(shaz["currency_reason"], ["REGIME_SALP-2026-07-30-BOOK-SALE", "EVENT_SHARES_UNKNOWN"])


class SchemaTests(unittest.TestCase):
    OLD_KEYS = {"ticker", "issuer", "cusip", "long_value_usd", "long_shares", "options", "long_weight", "shares_change", "status"}

    def test_schema_one_keys_kept(self):
        document = base_build()
        live = ("schema_version generated_at fund cik authority filing prior_filing long_book_usd positions caveat").split()
        for key in live:
            self.assertIn(key, document)
        for position in document["positions"]:
            self.assertTrue(self.OLD_KEYS <= set(position))
        sndk = by_ticker(document)["SNDK"]
        self.assertEqual((sndk["long_weight"], sndk["status"], sndk["match"]), (round(sndk["long_value_usd"] / document["long_book_usd"], 4), "HELD", "CUSIP_MAP"))
        self.assertEqual(sndk["shares_change"], 2495344.0 - 1140119.0)
        self.assertEqual(document["prior_filing"]["period"], "2026-03-31")

    def test_options_notional(self):
        fetch = make_fetch(BASE[3:], {ACC_Q1: Q1.read_bytes()})
        document = leopold.build(fetch, INDEX, NOW)
        positions = by_ticker(document)
        self.assertEqual(positions["MU"]["put_notional_usd"], 583686168.0)
        self.assertEqual(positions["MU"]["call_notional_usd"], 0.0)
        self.assertEqual(positions["BE"]["call_notional_usd"], 55347665.0)
        self.assertEqual(positions["BE"]["long_weight"], 0.0)
        self.assertEqual(document["options_book"]["put_notional_usd"], 583686168.0 + 494122503.0)
        self.assertEqual(document["options_book"]["call_notional_usd"], 55347665.0)
        self.assertEqual(document["options_book"]["long_usd"], document["long_book_usd"])
        self.assertEqual(positions["MU"]["options"][0]["type"], "PUT")
        self.assertEqual(positions["92189F676"]["match"], "NONE")  # null map entry is final


class AmendmentTests(unittest.TestCase):
    def build_with(self, amendment_table: bytes, primary: bytes):
        filings = [("13F-HR/A", ACC_A, "2026-08-20", "2026-06-30")] + BASE[2:]
        fetch = make_fetch(filings, {ACC_Q1: Q1.read_bytes(), ACC_Q2: Q2.read_bytes(), ACC_A: amendment_table},
                           primary={ACC_A: primary})
        return leopold.build(fetch, INDEX, NOW, regime_events=[])

    def test_restatement_replaces_the_table(self):
        only_mu = re.sub(rb"(?s)(<infoTable>(?:(?!</infoTable>).)*?SANDISK.*?</infoTable>)", b"", Q2.read_bytes())
        document = self.build_with(only_mu, (FIXTURES / "13f_amendment_primary_restatement.xml").read_bytes())
        self.assertNotIn("SNDK", by_ticker(document))
        self.assertEqual(document["amendments"], [{"accession": ACC_A, "filed": "2026-08-20", "type": "RESTATEMENT"}])
        self.assertEqual(document["filing"]["accession"], ACC_A)
        self.assertEqual(document["filing"]["period"], "2026-06-30")

    def test_new_holdings_join_as_union_amended_row_wins(self):
        raw = Q2.read_bytes()
        mu = re.search(rb"(?s)<infoTable>(?:(?!</infoTable>).)*?MICRON.*?</infoTable>", raw).group(0)
        amended_mu = mu.replace(b"<sshPrnamt>4828786<", b"<sshPrnamt>1000<")
        extra = mu.replace(b"MICRON TECHNOLOGY INC", b"WIDGET WORKS INC").replace(b"595112103", b"999999998")
        table = raw[:raw.index(b"<infoTable>")] + amended_mu + b"\n" + extra + b"\n</informationTable>\n"
        document = self.build_with(table, (FIXTURES / "13f_amendment_primary_new_holdings.xml").read_bytes())
        positions = by_ticker(document)
        self.assertEqual(positions["MU"]["long_shares"], 1000.0)
        self.assertIn("SNDK", positions)  # untouched rows stay
        self.assertEqual(positions["WDGT"]["match"], "NAME")
        self.assertEqual(document["amendments"][0]["type"], "NEW HOLDINGS")


class EventParserTests(unittest.TestCase):
    def test_xml_and_text_cover_page(self):
        parsed = leopold.parse_event_document((FIXTURES / "corescientific_13da.xml").read_bytes())
        self.assertEqual((parsed["cusip"], parsed["event_date"], parsed["shares"], parsed["percent_of_class"]),
                         ("21874A106", "2026-07-15", 14089395.0, 4.4))
        text = b"<html><body>CUSIP No. 778920306 Date of Event Which Requires Filing of this Statement 09/15/2026 Aggregate Amount Beneficially Owned 8,070,950 Percent of Class 21.1%</body></html>"
        parsed = leopold.parse_event_document(text)
        self.assertEqual((parsed["cusip"], parsed["event_date"], parsed["shares"], parsed["percent_of_class"]),
                         ("778920306", "2026-09-15", 8070950.0, 21.1))
        self.assertIsNone(leopold.parse_event_document(b"nothing here")["shares"])

    def test_events_only_after_newest_period_end(self):
        old = [("SCHEDULE 13G", "0000000000-26-000001", "2026-05-01", "")] + BASE[2:]
        fetch = make_fetch(old, {ACC_Q1: Q1.read_bytes(), ACC_Q2: Q2.read_bytes()})
        self.assertEqual(leopold.build(fetch, INDEX, NOW, regime_events=[])["events"], [])


ACC_F4 = "0000935836-26-000700"
SNDK_CUSIP = "80004C200"


def info_table(rows):
    """rows: (issuer, cusip, value, shares, prn_type or None, put_call or None) in the SEC informationTable schema."""
    parts = ['<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">']
    for issuer, cusip, value, shares, kind, put_call in rows:
        parts.append(f"<infoTable><nameOfIssuer>{issuer}</nameOfIssuer><titleOfClass>COM</titleOfClass><cusip>{cusip}</cusip>"
                     f"<value>{value}</value><shrsOrPrnAmt><sshPrnamt>{shares}</sshPrnamt>"
                     + (f"<sshPrnamtType>{kind}</sshPrnamtType>" if kind else "") + "</shrsOrPrnAmt>"
                     + (f"<putCall>{put_call}</putCall>" if put_call else "") + "</infoTable>")
    return ("".join(parts) + "</informationTable>").encode()


def cover(entries=None, value=None, omitted="false", amendment=None):
    amend = f"<amendmentInfo><amendmentType>{amendment}</amendmentType></amendmentInfo>" if amendment else ""
    summary = ("<summaryPage>" + (f"<tableEntryTotal>{entries}</tableEntryTotal>" if entries is not None else "")
               + (f"<tableValueTotal>{value}</tableValueTotal>" if value is not None else "") + "</summaryPage>")
    return (f'<edgarSubmission xmlns="http://www.sec.gov/edgar/thirteenffiler"><formData><coverPage>'
            f"<isConfidentialOmitted>{omitted}</isConfidentialOmitted>{amend}</coverPage>{summary}</formData></edgarSubmission>").encode()


def two_period_build(q1_rows, q2_rows, primary=None, cusip_map=None, regime_events=None):
    fetch = make_fetch(BASE[2:], {ACC_Q1: info_table(q1_rows), ACC_Q2: info_table(q2_rows)}, primary=primary)
    return leopold.build(fetch, INDEX, NOW, cusip_map=cusip_map, regime_events=[] if regime_events is None else regime_events)


class SharesAndPrincipalTests(unittest.TestCase):  # L1
    def test_two_rows_of_one_cusip_in_both_periods_change_zero(self):
        rows = [("SANDISK CORP", SNDK_CUSIP, 1000, 100, "SH", None), ("SANDISK CORP", SNDK_CUSIP, 3000, 300, "SH", None)]
        sndk = by_ticker(two_period_build(rows, rows))["SNDK"]
        self.assertEqual((sndk["long_shares"], sndk["prior_shares"], sndk["shares_change"], sndk["status"]), (400.0, 400.0, 0.0, "HELD"))

    def test_prior_shares_sum_over_every_cusip_of_the_item(self):
        a, b = "000000000", "999999998"  # two valid CUSIPs, one issuer name
        rows = [("WIDGET WORKS INC", a, 1000, 100, "SH", None), ("WIDGET WORKS INC", b, 3000, 300, "SH", None)]
        item = by_ticker(two_period_build(rows, rows, cusip_map={}))["WDGT"]
        self.assertEqual((item["cusips"], item["prior_shares"], item["shares_change"]), ([a, b], 400.0, 0.0))

    def test_prn_rows_never_count_as_shares(self):
        prior = [("SANDISK CORP", SNDK_CUSIP, 1000, 100, "SH", None)]
        now_rows = prior + [("SANDISK CORP", SNDK_CUSIP, 5000000, 5000000, "PRN", None)]
        sndk = by_ticker(two_period_build(prior, now_rows))["SNDK"]
        self.assertEqual((sndk["long_shares"], sndk["shares_change"]), (100.0, 0.0))
        self.assertEqual((sndk["long_value_usd"], sndk["principal_usd"]), (5001000.0, 5000000.0))
        both = by_ticker(two_period_build(now_rows, now_rows))["SNDK"]
        self.assertEqual((both["prior_shares"], both["shares_change"]), (100.0, 0.0))

    def test_rows_without_a_type_count_as_shares_and_options_do_not(self):
        rows = leopold.parse_info_table(info_table([("A", "000000000", 1, 5, None, None), ("B", "000000000", 1, 5, "PRN", None),
                                                    ("C", "000000000", 1, 5, "SH", "Put")]))
        self.assertEqual([leopold.counts_as_shares(row) for row in rows], [True, False, False])
        self.assertEqual(rows[0]["prn_type"], "SH")


class CusipCheckTests(unittest.TestCase):  # L2
    def test_shipped_map_validates_and_a_flipped_digit_fails(self):
        for key in leopold.load_cusip_map():
            self.assertTrue(leopold.valid_cusip(key), key)
        self.assertTrue(leopold.valid_cusip("037833100") and leopold.valid_cusip("80004c200") and leopold.valid_cusip("000000000"))
        self.assertFalse(leopold.valid_cusip("037833101") or leopold.valid_cusip("80004C201"))
        self.assertFalse(any(leopold.valid_cusip(c) for c in ("", "12345", "03783310A", "0378331000")))

    def test_bad_map_key_raises(self):
        import tempfile
        raw = json.loads((ROOT / "config" / "leopold-cusip-map-v1.json").read_text(encoding="utf-8"))
        raw["entries"]["80004C201"] = raw["entries"].pop(SNDK_CUSIP)
        with tempfile.TemporaryDirectory() as folder_name:
            path = Path(folder_name) / "map.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaises(ValueError) as caught:
                leopold.load_cusip_map(path)
        self.assertEqual(str(caught.exception), "LEOPOLD_CUSIP_MAP_INVALID: 80004C201")

    def test_bad_row_stays_unresolved_counts_in_the_book_and_is_reported(self):
        rows = [("SANDISK CORP", "80004C201", 1000, 10, "SH", None), ("MICRON TECHNOLOGY INC", "595112103", 3000, 30, "SH", None)]
        document = two_period_build(rows, rows)
        bad = by_ticker(document)["80004C201"]
        self.assertEqual((bad["ticker"], bad["match"]), (None, "NONE"))
        self.assertEqual((document["filing"]["invalid_cusips"], document["long_book_usd"]), (1, 4000.0))
        self.assertEqual(bad["long_weight"], 0.25)


class ReconciliationTests(unittest.TestCase):  # L3
    ROWS = [("SANDISK CORP", SNDK_CUSIP, 6000000, 100, "SH", None), ("MICRON TECHNOLOGY INC", "595112103", 4000000, 50, "SH", None)]

    def run_with(self, cover_xml, regime_events=None):
        return two_period_build(self.ROWS, self.ROWS, primary={ACC_Q2: cover_xml}, regime_events=regime_events)

    def test_reconciled_table(self):
        document = self.run_with(cover(2, 10000000))
        self.assertEqual(document["filing"]["reconciliation"], {"entries_ok": True, "value_ok": True, "confidential_omitted": False, "status": "RECON_OK"})
        self.assertEqual(by_ticker(document)["SNDK"]["currency_reason"], [])
        self.assertEqual(by_ticker(document)["SNDK"]["currency_factor"], 1.0)
        self.assertEqual(self.run_with(cover(2, 10040000))["filing"]["reconciliation"]["status"], "RECON_OK")  # inside 0.5 %

    def test_thousands_table_is_a_mismatch_and_halves_the_factor(self):
        document = self.run_with(cover(2, 10000000000))
        self.assertEqual(document["filing"]["reconciliation"], {"entries_ok": True, "value_ok": False, "confidential_omitted": False, "status": "RECON_MISMATCH"})
        sndk = by_ticker(document)["SNDK"]
        self.assertEqual((sndk["currency_factor"], sndk["currency_reason"]), (0.5, ["RECON_MISMATCH"]))

    def test_mismatch_comes_after_regime_and_event_entries_and_stacks(self):
        document = self.run_with(cover(3, 10000000), regime_events=leopold.load_regime_events())
        sndk = by_ticker(document)["SNDK"]
        self.assertEqual(sndk["currency_reason"], ["REGIME_SALP-2026-07-30-BOOK-SALE", "RECON_MISMATCH"])
        self.assertEqual(sndk["currency_factor"], 0.25 * 0.5)
        self.assertEqual(document["filing"]["reconciliation"]["entries_ok"], False)

    def test_short_table_is_a_mismatch(self):
        self.assertEqual(self.run_with(cover(2, 12000000))["filing"]["reconciliation"]["status"], "RECON_MISMATCH")

    def test_omitted_flag_is_labelled_only(self):
        document = self.run_with(cover(2, 10000000, omitted="true"))
        self.assertEqual(document["filing"]["reconciliation"]["status"], "CONFIDENTIAL_OMITTED")
        self.assertTrue(document["filing"]["reconciliation"]["confidential_omitted"])
        self.assertEqual(by_ticker(document)["SNDK"]["currency_reason"], [])

    def test_unreadable_or_incomplete_cover_is_unknown_and_never_raises(self):
        for raw in (b"<not xml", cover(), cover(2), cover(2, 0)):
            document = self.run_with(raw)
            self.assertEqual(document["filing"]["reconciliation"]["status"], "RECON_UNKNOWN", raw)
            self.assertEqual(by_ticker(document)["SNDK"]["currency_reason"], [])
        self.assertEqual(two_period_build(self.ROWS, self.ROWS)["filing"]["reconciliation"]["status"], "RECON_UNKNOWN")  # cover absent

    def test_each_filing_is_compared_with_its_own_cover(self):
        extra = [("WIDGET WORKS INC", "999999998", 500000, 5, "SH", None)]
        filings = [("13F-HR/A", ACC_A, "2026-08-20", "2026-06-30")] + BASE[2:]
        tables = {ACC_Q1: info_table(self.ROWS), ACC_Q2: info_table(self.ROWS), ACC_A: info_table(extra)}
        fetch = make_fetch(filings, tables, primary={ACC_Q2: cover(2, 10000000), ACC_A: cover(1, 500000, amendment="NEW HOLDINGS")})
        document = leopold.build(fetch, INDEX, NOW, regime_events=[])
        self.assertEqual(document["filing"]["reconciliation"]["status"], "RECON_OK")  # the union (3 rows) is never held against one cover
        self.assertIn("WDGT", by_ticker(document))
        bad = make_fetch(filings, tables, primary={ACC_Q2: cover(2, 10000000), ACC_A: cover(1, 9000000, amendment="NEW HOLDINGS")})
        self.assertEqual(leopold.build(bad, INDEX, NOW, regime_events=[])["filing"]["reconciliation"]["status"], "RECON_MISMATCH")
        old = dict(tables, **{ACC_Q2: info_table([("OLD", "000000000", 1, 1, "SH", None)]), ACC_A: info_table(self.ROWS)})
        restated = make_fetch(filings, old, primary={ACC_Q2: cover(5, 77), ACC_A: cover(2, 10000000, amendment="RESTATEMENT")})
        self.assertEqual(leopold.build(restated, INDEX, NOW, regime_events=[])["filing"]["reconciliation"]["status"], "RECON_OK")  # superseded cover ignored


class Form34Tests(unittest.TestCase):  # L4
    def build_with(self, raw, name="xslF345X05/wk-form4_1.xml", form="4"):
        filings = [(form, ACC_F4, "2026-09-02", "")] + BASE[2:]
        files = {folder(ACC_F4) + "wk-form4_1.xml": raw} if raw is not None else {}
        fetch = make_fetch(filings, {ACC_Q1: Q1.read_bytes(), ACC_Q2: Q2.read_bytes()}, files, documents={ACC_F4: name})
        return leopold.build(fetch, INDEX, NOW)

    def fixture(self, name):
        return (FIXTURES / name).read_bytes()

    def test_sale_lowers_with_the_newest_row_and_replaces_the_regime_discount(self):
        sndk = by_ticker(self.build_with(self.fixture("form4_sale.xml")))["SNDK"]
        self.assertEqual(sndk["currency_reason"], ["EVENT_4_2026-09-02"])
        self.assertEqual(sndk["currency_factor"], 1000000 / 2495344)
        event = sndk["post_period_event"]
        self.assertEqual((event["form"], event["ticker"], event["cusip"], event["event_date"], event["shares"]), ("4", "SNDK", None, "2026-09-01", 1000000.0))

    def test_purchase_caps_at_one(self):
        sndk = by_ticker(self.build_with(self.fixture("form4_purchase.xml")))["SNDK"]
        self.assertEqual((sndk["currency_factor"], sndk["currency_reason"]), (1.0, ["EVENT_4_2026-09-02"]))

    def test_exercise_only_filing_is_unknown_and_keeps_the_regime(self):
        sndk = by_ticker(self.build_with(self.fixture("form4_exercise_only.xml")))["SNDK"]
        self.assertEqual((sndk["currency_factor"], sndk["currency_reason"]), (0.25, ["REGIME_SALP-2026-07-30-BOOK-SALE", "EVENT_SHARES_UNKNOWN"]))

    def test_foreign_owner_and_malformed_or_missing_documents_are_ignored(self):
        for raw in (self.fixture("form4_foreign_owner.xml"), b"<ownershipDocument><broken", None):
            document = self.build_with(raw)
            self.assertEqual(document["events"], [])
            self.assertEqual(by_ticker(document)["SNDK"]["currency_reason"], ["REGIME_SALP-2026-07-30-BOOK-SALE"])

    def test_owner_cik_compares_as_an_integer(self):
        raw = self.fixture("form4_sale.xml").replace(b"0002045724", b"2045724")
        self.assertEqual(len(self.build_with(raw)["events"]), 1)

    def test_conflicting_natures_use_the_direct_figure_else_unknown(self):
        rows = leopold.parse_ownership_document(self.fixture("form4_sale.xml"))["transactions"]
        self.assertEqual(leopold.form_34_event_shares([dict(rows[0], nature="D"), dict(rows[1], nature="I", owned_after=42.0)]), (1500000.0, "2026-08-31"))
        self.assertEqual(leopold.form_34_event_shares([dict(rows[0], nature="I"), dict(rows[1], nature="")]), (None, None))
        self.assertEqual(leopold.form_34_event_shares([dict(rows[0], nature="I"), dict(rows[1], nature="I")]), (1000000.0, "2026-09-01"))

    def test_only_form_3_and_4_and_at_most_twenty_are_fetched(self):
        calls = []
        filings = ([("4", f"0000935836-26-{900 + n:06d}", f"2026-09-{(n % 27) + 1:02d}", "") for n in range(25)]
                   + [("144", "0000935836-26-000800", "2026-09-05", "")] + BASE[2:])
        inner = make_fetch(filings, {ACC_Q1: Q1.read_bytes(), ACC_Q2: Q2.read_bytes()}, documents={f[1]: "x.xml" for f in filings})

        def fetch(url):
            calls.append(url)
            return inner(url)
        leopold.build(fetch, INDEX, NOW)
        self.assertEqual(sum(1 for url in calls if url.endswith("/x.xml")), 20)
        self.assertFalse(any("000800" in url for url in calls))


if __name__ == "__main__":
    unittest.main()
