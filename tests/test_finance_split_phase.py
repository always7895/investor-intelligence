"""FINANCE-SPLIT-03-R1 operating/financing fields, the deep-report presentation and PRODUCER-CLOCK-03 (synthetic only).

The legacy `phase` stays the admission gate byte for byte; the seven additive fields are display only. Signal dates,
values and SEC rows are test data, not research. No network, subprocess or file write.
"""
from __future__ import annotations

import copy
import unittest

from tests.test_company_deep_report import CONFIG, FACTS, ROTATION, TODAY, cdr
from tests.test_thesis_phase import STORY, sig, tp

LEGACY_KEYS = ["as_of", "scope", "phase", "engine_lifecycle", "shortage_relieved", "extreme_valuation_crowding",
               "dilution_overhang", "preference_rank", "constraint_families", "relief_families", "capture_families",
               "reasons", "supporting_signal_ids", "context_only_signal_ids", "expired_signal_ids", "next_review_at",
               "authorship"]
NEW_KEYS = ["operating_phase", "operating_reasons", "operating_supporting_signal_ids", "financing_status",
            "financing_reason_codes", "financing_supporting_signal_ids", "known_financing_entry_blocked"]
OVERHANG_REASON = "dilution overhang: equity capture at risk"
COMMERCIAL_REASON = "constraint confirmed and company capture visible before consensus"
CHAIN_IDS = ["COMPANY_PRICING-2025-05-01-issuer", "LEAD_TIME-2025-01-10-gov_regulator", "PRICE-2025-03-01-utility_buyer"]
UNCONFIRMED = "；知悉時間覆蓋未確認（不假設零；不代表論點失效）"


def financing(result):
    return {key: result[key] for key in ("financing_status", "financing_reason_codes", "financing_supporting_signal_ids",
                                         "known_financing_entry_blocked")}


def operating(result):
    return (result["operating_phase"], result["operating_reasons"], result["operating_supporting_signal_ids"])


class OperatingFinancingFieldTests(unittest.TestCase):
    def setUp(self):
        self.policy = tp.load_policy()

    def phase(self, signals, when, policy=None, **kwargs):
        return tp.assess_phase(signals, when, policy=policy or self.policy, **kwargs)

    def test_fields_are_additive_after_the_legacy_keys_and_mirror_the_unblocked_chain(self):
        for when in ("2025-01-20", "2025-03-05", "2025-05-15", "2025-08-05", "2025-10-03", "2025-10-20", "2026-02-05"):
            with self.subTest(when=when):
                result = self.phase(STORY, when)
                self.assertEqual(list(result), LEGACY_KEYS + NEW_KEYS)
                self.assertNotIn("withheld_signal_ids", result)  # T11-F1A stays inert: the engine emits no list
                self.assertEqual(result["operating_phase"], result["phase"])
                self.assertEqual(result["operating_reasons"], [r for r in result["reasons"] if r != OVERHANG_REASON])
                self.assertEqual(result["operating_supporting_signal_ids"], result["supporting_signal_ids"])
                self.assertEqual(financing(result), {
                    "financing_status": "UNKNOWN",
                    "financing_reason_codes": ["DILUTION_NO_APPLICABLE_OBSERVATION", "ATM_CAPACITY_NO_APPLICABLE_OBSERVATION"],
                    "financing_supporting_signal_ids": [], "known_financing_entry_blocked": None})

    def test_dilution_entry_block_keeps_legacy_broken_and_shows_the_operating_chain(self):
        result = self.phase(STORY[:3] + [sig("DILUTION", "2025-05-12", "issuer", value=25)], "2025-05-15")
        self.assertEqual((result["phase"], result["reasons"], result["supporting_signal_ids"], result["dilution_overhang"]),
                         ("BROKEN", ["falsifier active: DILUTION"], ["DILUTION-2025-05-12-issuer"], False))
        self.assertEqual(result["next_review_at"], "2026-11-13")  # 2025-05-12 + 550 days: the legacy schedule is untouched
        self.assertEqual(operating(result), ("COMMERCIAL_VALIDATION", [COMMERCIAL_REASON], CHAIN_IDS))
        self.assertEqual(financing(result), {
            "financing_status": "ENTRY_BLOCK_OBSERVED",
            "financing_reason_codes": ["DILUTION_ENTRY_BLOCK_OBSERVED", "ATM_CAPACITY_NO_APPLICABLE_OBSERVATION"],
            "financing_supporting_signal_ids": ["DILUTION-2025-05-12-issuer"], "known_financing_entry_blocked": True})

    def test_overhang_with_one_kind_unknown_is_not_a_false_clear(self):
        result = self.phase(STORY[:3] + [sig("DILUTION", "2025-05-12", "issuer", value=8)], "2025-05-15")
        self.assertEqual((result["phase"], result["reasons"]), ("COMMERCIAL_VALIDATION", [COMMERCIAL_REASON, OVERHANG_REASON]))
        self.assertEqual(operating(result), ("COMMERCIAL_VALIDATION", [COMMERCIAL_REASON], CHAIN_IDS))
        self.assertEqual(financing(result), {
            "financing_status": "OVERHANG_OBSERVED",
            "financing_reason_codes": ["DILUTION_OVERHANG_OBSERVED", "ATM_CAPACITY_NO_APPLICABLE_OBSERVATION"],
            "financing_supporting_signal_ids": ["DILUTION-2025-05-12-issuer"], "known_financing_entry_blocked": None})

    def test_false_only_when_both_supplied_observations_are_below_the_entry_block(self):
        rows = [
            ((8, 0), "OVERHANG_OBSERVED", ["DILUTION_OVERHANG_OBSERVED", "ATM_CAPACITY_BELOW_OVERHANG_OBSERVED"]),
            ((2, 1), "BELOW_OVERHANG_OBSERVED", ["DILUTION_BELOW_OVERHANG_OBSERVED", "ATM_CAPACITY_BELOW_OVERHANG_OBSERVED"]),
        ]
        for (dilution, atm), status, codes in rows:
            with self.subTest(dilution=dilution, atm=atm):
                signals = STORY[:3] + [sig("DILUTION", "2025-05-12", "issuer", value=dilution),
                                       sig("ATM_CAPACITY", "2025-05-12", "issuer", value=atm)]
                result = self.phase(signals, "2025-05-15")
                self.assertEqual(result["phase"], "COMMERCIAL_VALIDATION")
                self.assertEqual(financing(result), {
                    "financing_status": status, "financing_reason_codes": codes,
                    "financing_supporting_signal_ids": ["ATM_CAPACITY-2025-05-12-issuer", "DILUTION-2025-05-12-issuer"],
                    "known_financing_entry_blocked": False})

    def test_thesis_killer_stays_an_operating_falsifier_beside_an_atm_block(self):
        signals = STORY[:3] + [sig("ATM_CAPACITY", "2025-05-05", "issuer", value=55), sig("THESIS_KILLER", "2025-05-10", "issuer")]
        result = self.phase(signals, "2025-05-15")
        self.assertEqual((result["phase"], result["reasons"], result["supporting_signal_ids"]),
                         ("BROKEN", ["falsifier active: ATM_CAPACITY, THESIS_KILLER"],
                          ["ATM_CAPACITY-2025-05-05-issuer", "THESIS_KILLER-2025-05-10-issuer"]))
        self.assertEqual(operating(result), ("BROKEN", ["falsifier active: THESIS_KILLER"], ["THESIS_KILLER-2025-05-10-issuer"]))
        self.assertEqual(financing(result), {
            "financing_status": "ENTRY_BLOCK_OBSERVED",
            "financing_reason_codes": ["DILUTION_NO_APPLICABLE_OBSERVATION", "ATM_CAPACITY_ENTRY_BLOCK_OBSERVED"],
            "financing_supporting_signal_ids": ["ATM_CAPACITY-2025-05-05-issuer"], "known_financing_entry_blocked": True})

    def test_latest_date_group_conflict_invalid_and_no_fallback_to_older_rows(self):
        rows = [
            ("conflict", [sig("DILUTION", "2025-05-12", "issuer", value=8, sid="d-a"),
                          sig("DILUTION", "2025-05-12", "issuer", value=9, sid="d-b")],
             "COMMERCIAL_VALIDATION", "UNKNOWN", ["DILUTION_LATEST_VALUE_CONFLICT", "ATM_CAPACITY_NO_APPLICABLE_OBSERVATION"], []),
            ("no-fallback", [sig("DILUTION", "2025-05-01", "issuer", value=25, sid="d-old"),
                             sig("DILUTION", "2025-05-12", "issuer", value=8, sid="d-new")],
             "COMMERCIAL_VALIDATION", "OVERHANG_OBSERVED", ["DILUTION_OVERHANG_OBSERVED", "ATM_CAPACITY_NO_APPLICABLE_OBSERVATION"],
             ["d-new"]),
            ("missing-value", [sig("DILUTION", "2025-05-12", "issuer", sid="d-none")],
             "COMMERCIAL_VALIDATION", "UNKNOWN", ["DILUTION_LATEST_VALUE_INVALID", "ATM_CAPACITY_NO_APPLICABLE_OBSERVATION"], []),
            ("negative-atm", [sig("ATM_CAPACITY", "2025-05-12", "issuer", value=-1, sid="a-neg")],
             "COMMERCIAL_VALIDATION", "UNKNOWN", ["DILUTION_NO_APPLICABLE_OBSERVATION", "ATM_CAPACITY_LATEST_VALUE_INVALID"], []),
            ("infinite", [sig("DILUTION", "2025-05-12", "issuer", value=float("inf"), sid="d-inf")],
             "BROKEN", "UNKNOWN", ["DILUTION_LATEST_VALUE_INVALID", "ATM_CAPACITY_NO_APPLICABLE_OBSERVATION"], []),
        ]
        for name, extra, legacy, status, codes, support in rows:
            with self.subTest(row=name):
                result = self.phase(STORY[:3] + extra, "2025-05-15")
                self.assertEqual(result["phase"], legacy)
                self.assertEqual(result["operating_phase"], "COMMERCIAL_VALIDATION")
                self.assertEqual(financing(result), {"financing_status": status, "financing_reason_codes": codes,
                                                     "financing_supporting_signal_ids": support,
                                                     "known_financing_entry_blocked": None})

    def test_industry_scope_financing_is_not_applicable_and_never_broken(self):
        signals = STORY + [sig("DILUTION", "2025-09-30", "issuer", value=25), sig("THESIS_KILLER", "2025-09-30", "issuer")]
        result = self.phase(signals, "2025-10-03", scope="industry")
        self.assertEqual((result["phase"], result["operating_phase"]), ("EARLY_VALIDATION", "EARLY_VALIDATION"))
        self.assertEqual(financing(result), {"financing_status": "NA", "financing_reason_codes": ["FINANCING_NOT_APPLICABLE"],
                                             "financing_supporting_signal_ids": [], "known_financing_entry_blocked": None})

    def test_custom_policy_threshold_gaps_touch_only_the_new_fields(self):
        blocked = STORY[:3] + [sig("DILUTION", "2025-05-12", "issuer", value=25)]
        for name, edit in (("missing", lambda limits: limits.pop("relief_families")),
                           ("boolean", lambda limits: limits.__setitem__("confirmed_constraint_families", True)),
                           ("non-finite", lambda limits: limits.__setitem__("holder_crowding_pct", float("nan")))):
            with self.subTest(threshold=name):
                policy = copy.deepcopy(self.policy)
                edit(policy["thresholds"])
                result = self.phase(blocked, "2025-05-15", policy=policy)
                self.assertEqual((result["phase"], result["reasons"]), ("BROKEN", ["falsifier active: DILUTION"]))
                if name == "non-finite":  # not reached: no holder value exists, so the chain never reads it
                    self.assertEqual(operating(result), ("COMMERCIAL_VALIDATION", [COMMERCIAL_REASON], CHAIN_IDS))
                else:
                    self.assertEqual(operating(result), (None, ["OPERATING_POLICY_THRESHOLD_UNAVAILABLE"], []))
        policy = copy.deepcopy(self.policy)
        del policy["thresholds"]["relief_families"]
        with self.assertRaises(KeyError):  # without a block the chain IS the legacy lookup; its error still propagates
            self.phase(STORY[:3], "2025-05-15", policy=policy)
        policy = copy.deepcopy(self.policy)
        policy["thresholds"]["dilution_overhang_pct"] = True
        result = self.phase(STORY[:3] + [sig("DILUTION", "2025-05-12", "issuer", value=8)], "2025-05-15", policy=policy)
        self.assertTrue(result["dilution_overhang"])  # legacy comparison unchanged (True compares as 1)
        self.assertEqual(financing(result), {
            "financing_status": "UNKNOWN",
            "financing_reason_codes": ["DILUTION_POLICY_THRESHOLD_UNAVAILABLE", "ATM_CAPACITY_NO_APPLICABLE_OBSERVATION"],
            "financing_supporting_signal_ids": [], "known_financing_entry_blocked": None})


class DeepReportPresentationTests(unittest.TestCase):
    def report(self, facts=FACTS):
        return cdr.build_report("SYN", "0000000001", facts=facts, submissions={"sic": "3674"}, business=None,
                                rotation=ROTATION, rotation_config=CONFIG, today=TODAY)

    def test_phase_section_shows_gate_operating_and_financing_apart(self):
        text = {s["title"]: s["text"] for s in self.report()["sections"]}
        self.assertEqual(text["資料階段"], (
            "舊版准入狀態：商業驗證（公司開始獲利）；營運階段：商業驗證（公司開始獲利）；"
            "融資觀察：觀察到稀釋疑慮；無法確定是否達准入阻擋門檻；舊版稀釋疑慮旗標（與融資觀察分開計算）" + UNCONFIRMED
            + "；下次檢查 2026-11-12；訊號家族（吃緊來源：BLS 生產者物價、SEC 公司申報；公司捕捉：SEC 公司申報；緩解：無）"))
        self.assertTrue(text["所屬產業訊號"].startswith("合成半導體："))
        self.assertTrue(text["所屬產業訊號"].endswith(UNCONFIRMED))
        self.assertEqual(text["證偽條件"], (
            "營運警示條件：RPO 年增降至 -10% 以下；毛利率年減 1 個百分點以上；存貨成長超過營收 10 個百分點；所屬產業 PPI 年增降至 -3% 以下。"
            "融資准入阻擋條件（舊版准入狀態）：稀釋後股數年增 20% 以上。以上為觀察條件，不是交易指令"))

    def test_finance_only_block_is_never_shown_as_a_failed_thesis(self):
        facts = copy.deepcopy(FACTS)
        facts["facts"]["us-gaap"]["WeightedAverageNumberOfDilutedSharesOutstanding"]["units"]["shares"][0]["val"] = 130
        report = self.report(facts)
        self.assertEqual((report["phase"]["phase"], report["phase"]["operating_phase"]), ("BROKEN", "COMMERCIAL_VALIDATION"))
        text = {s["title"]: s["text"] for s in report["sections"]}
        self.assertEqual(text["資料階段"], (
            "舊版准入狀態：受阻（可能含融資條件，不等同營運論點失效）；營運階段：商業驗證（公司開始獲利）；"
            "融資觀察：觀察到達准入阻擋門檻的融資條件" + UNCONFIRMED
            + "；下次檢查 2028-01-01；訊號家族（吃緊來源：BLS 生產者物價、SEC 公司申報；公司捕捉：SEC 公司申報；緩解：無）"))
        self.assertFalse(any("已失效" in s["text"] for s in report["sections"]))
        self.assertTrue(all(len(s["text"]) <= 700 for s in report["sections"]))

    def test_presentation_reads_malformed_or_old_fields_as_unknown(self):
        unknown_financing = "未知或不完整（無法確定是否受阻，不推定無融資風險）"
        rows = [
            (None, "未知", "未知", unknown_financing),
            ({"phase": "BROKEN"}, "受阻（可能含融資條件，不等同營運論點失效）", "未知", unknown_financing),
            ({"phase": "toString", "operating_phase": "__proto__"}, "未知", "未知", unknown_financing),
            ({"phase": "BROKEN", "operating_phase": None, "operating_reasons": ["OPERATING_POLICY_THRESHOLD_UNAVAILABLE"],
              "scope": "company", "financing_status": "UNKNOWN", "known_financing_entry_blocked": None},
             "受阻（可能含融資條件，不等同營運論點失效）", "未知（政策門檻不可用，未推論）", unknown_financing),
            ({"phase": "BROKEN", "operating_phase": "BROKEN", "scope": "company", "financing_status": "ENTRY_BLOCK_OBSERVED",
              "known_financing_entry_blocked": True},
             "受阻（可能含融資條件，不等同營運論點失效）", "營運證偽訊號成立", "觀察到達准入阻擋門檻的融資條件"),
            ({"phase": "COMMERCIAL_VALIDATION", "operating_phase": "COMMERCIAL_VALIDATION", "scope": "company",
              "financing_status": "BELOW_OVERHANG_OBSERVED", "known_financing_entry_blocked": False},
             "商業驗證（公司開始獲利）", "商業驗證（公司開始獲利）", "僅已提供觀察未達准入阻擋門檻（非進場許可、非安全證明、非完整融資覆蓋）"),
            ({"phase": "EARLY_VALIDATION", "operating_phase": "EARLY_VALIDATION", "scope": "company",
              "financing_status": "ENTRY_BLOCK_OBSERVED", "known_financing_entry_blocked": False},
             "驗證中（雙來源確認）", "驗證中（雙來源確認）", unknown_financing),
            ({"phase": "EARLY_VALIDATION", "operating_phase": "EARLY_VALIDATION", "scope": "company",
              "financing_status": "OVERHANG_OBSERVED", "known_financing_entry_blocked": 0},
             "驗證中（雙來源確認）", "驗證中（雙來源確認）", unknown_financing),
            ({"phase": "EARLY_VALIDATION", "operating_phase": "EARLY_VALIDATION", "scope": "industry",
              "financing_status": "NA", "known_financing_entry_blocked": None},
             "驗證中（雙來源確認）", "驗證中（雙來源確認）", unknown_financing),
        ]
        for phase, legacy, operating_text, financing_text in rows:
            with self.subTest(phase=phase):
                self.assertEqual(cdr._phase_presentation(phase),
                                 f"舊版准入狀態：{legacy}；營運階段：{operating_text}；融資觀察：{financing_text}")

    def test_withheld_notice_never_assumes_zero(self):
        many = [f"s{i}" for i in range(10000)]
        rows = [(None, UNCONFIRMED), ({}, UNCONFIRMED), ({"withheld_signal_ids": None}, UNCONFIRMED),
                ({"withheld_signal_ids": ("a",)}, UNCONFIRMED), ({"withheld_signal_ids": ["a", " "]}, UNCONFIRMED),
                ({"withheld_signal_ids": ["a", 1]}, UNCONFIRMED), ({"withheld_signal_ids": []}, ""),
                ({"withheld_signal_ids": ["a", "a", "b"]},
                 "；時間證據提醒：至少 2 筆訊號未確認截至評估日已知，未計入階段（非完整覆蓋；缺口本身不代表論點失效）"),
                ({"withheld_signal_ids": many},
                 "；時間證據提醒：至少 9999+ 筆訊號未確認截至評估日已知，未計入階段（非完整覆蓋；缺口本身不代表論點失效）")]
        for phase, expected in rows:
            with self.subTest(phase=str(phase)[:60]):
                self.assertEqual(cdr.phase_withheld_notice(phase), expected)


def clocked_facts():
    """FACTS with SEC filing days: current-quarter rows filed 2026-07-29, year-ago rows 2025-07-30."""
    facts = copy.deepcopy(FACTS)
    for concept in facts["facts"]["us-gaap"].values():
        for rows in concept["units"].values():
            for row in rows:
                row["filed"] = {"2026-06-30": "2026-07-29", "2025-06-30": "2025-07-30"}.get(row["end"], "2026-02-20")
    return facts


def dependency(tag, unit, frame, start, end, value, filed):
    return {"taxonomy": "us-gaap", "tag": tag, "unit": unit, "frame": frame, "start": start, "end": end,
            "value": value, "filed": filed, "accession": "0000000001-26-000001"}


REVENUE = "RevenueFromContractWithCustomerExcludingAssessedTax"
REVENUE_PAIR = [dependency(REVENUE, "USD", "CY2026Q2", "2026-04-01", "2026-06-30", 1000, "2026-07-29"),
                dependency(REVENUE, "USD", "CY2025Q2", "2025-04-01", "2025-06-30", 800, "2025-07-30")]
RPO_PAIR = [dependency("RevenueRemainingPerformanceObligation", "USD", "CY2026Q2I", None, "2026-06-30", 5000, "2026-07-29"),
            dependency("RevenueRemainingPerformanceObligation", "USD", "CY2025Q2I", None, "2025-06-30", 2500, "2025-07-30")]


class ProducerClockTests(unittest.TestCase):
    def provenance(self, facts):
        return cdr.signal_provenance(facts, cdr.extract_metrics(facts, TODAY))

    def test_exact_calendar_rows_give_filing_day_clocks(self):
        result = self.provenance(clocked_facts())
        self.assertEqual(result["RPO"], {"announced_at": "2026-07-29", "dependencies": RPO_PAIR})
        self.assertEqual(result["MARGIN"], {"announced_at": "2026-07-29", "dependencies": [
            dependency("GrossProfit", "USD", "CY2026Q2", "2026-04-01", "2026-06-30", 600, "2026-07-29"),
            dependency("GrossProfit", "USD", "CY2025Q2", "2025-04-01", "2025-06-30", 440, "2025-07-30")] + REVENUE_PAIR})
        self.assertEqual(result["DILUTION"], {"announced_at": "2026-07-29", "dependencies": [
            dependency("WeightedAverageNumberOfDilutedSharesOutstanding", "shares", "CY2026Q2", "2026-04-01", "2026-06-30",
                       106, "2026-07-29"),
            dependency("WeightedAverageNumberOfDilutedSharesOutstanding", "shares", "CY2025Q2", "2025-04-01", "2025-06-30",
                       100, "2025-07-30")]})
        self.assertEqual(result["INVENTORY"]["announced_at"], "2026-07-29")

    def test_rows_without_a_filing_day_stay_unannounced(self):
        self.assertEqual(self.provenance(FACTS), {"RPO": None, "MARGIN": None, "DILUTION": None, "INVENTORY": None})
        report = cdr.build_report("SYN", "0000000001", facts=FACTS, submissions={"sic": "3674"}, business=None,
                                  rotation=ROTATION, rotation_config=CONFIG, today=TODAY)
        self.assertFalse(any("announced_at" in s for s in report["signals"]))

    def test_inconsistent_rows_are_unknown_never_repaired(self):
        rows = []
        early = clocked_facts()
        early["facts"]["us-gaap"]["RevenueRemainingPerformanceObligation"]["units"]["USD"][0]["filed"] = "2026-06-29"
        rows.append(("filed-before-end", early, "RPO"))
        duplicate = clocked_facts()
        rpo = duplicate["facts"]["us-gaap"]["RevenueRemainingPerformanceObligation"]["units"]["USD"]
        rpo.insert(0, dict(rpo[0], val=4999))  # same frame, different value: the legacy last-row pick is order dependent
        rows.append(("same-frame-conflict", duplicate, "RPO"))
        fiscal = clocked_facts()
        fiscal["facts"]["us-gaap"][REVENUE]["units"]["USD"][0]["start"] = "2026-03-29"
        rows.append(("fiscal-start", fiscal, "MARGIN"))
        rows.append(("fiscal-start-inventory", fiscal, "INVENTORY"))
        accession = clocked_facts()
        accession["facts"]["us-gaap"]["WeightedAverageNumberOfDilutedSharesOutstanding"]["units"]["shares"][0]["accn"] = "x"
        rows.append(("accession", accession, "DILUTION"))
        for name, facts, key in rows:
            with self.subTest(row=name):
                self.assertIsNone(self.provenance(facts)[key])
        self.assertIsNotNone(self.provenance(fiscal)["RPO"])  # one inconsistent operand never clears another signal

    def test_signals_carry_the_clock_and_the_legacy_phase_is_unchanged(self):
        facts = clocked_facts()
        clocked = cdr.build_report("SYN", "0000000001", facts=facts, submissions={"sic": "3674"}, business=None,
                                   rotation=ROTATION, rotation_config=CONFIG, today=TODAY)
        plain = cdr.build_report("SYN", "0000000001", facts=FACTS, submissions={"sic": "3674"}, business=None,
                                 rotation=ROTATION, rotation_config=CONFIG, today=TODAY)
        announced = {s["signal_id"]: s.get("announced_at") for s in clocked["signals"]}
        self.assertEqual(announced, {"SYN:RPO": "2026-07-29", "SYN:MARGIN": "2026-07-29", "SYN:DILUTION": "2026-07-29",
                                     "SYN:semis:PRICE": None})
        self.assertEqual(clocked["phase"], plain["phase"])
        self.assertEqual(clocked["sections"], plain["sections"])
        self.assertEqual(set(clocked["signal_provenance"]), {"RPO", "MARGIN", "DILUTION", "INVENTORY"})

    def test_announced_accepts_only_a_complete_consistent_entry(self):
        good = self.provenance(clocked_facts())
        self.assertEqual(cdr._announced(good, "RPO"), {"announced_at": "2026-07-29"})
        tampered = []
        for change in (lambda e: e.__setitem__("announced_at", "2026-07-30"),
                       lambda e: e.__setitem__("extra", 1),
                       lambda e: e["dependencies"].pop(),
                       lambda e: e["dependencies"][0].__setitem__("tag", "Revenues"),
                       lambda e: e["dependencies"][0].__setitem__("unit", "EUR"),
                       lambda e: e["dependencies"].reverse(),
                       lambda e: e["dependencies"][0].__setitem__("frame", "CY2026Q3I")):
            entry = copy.deepcopy(good["RPO"])
            change(entry)
            tampered.append(entry)
        for entry in tampered:
            with self.subTest(entry=str(entry)[:80]):
                self.assertEqual(cdr._announced({"RPO": entry}, "RPO"), {})
        self.assertEqual(cdr._announced(None, "RPO"), {})
        self.assertEqual(cdr._announced(good, "UNKNOWN_KEY"), {})


if __name__ == "__main__":
    unittest.main()
