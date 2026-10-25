"""V12 I1 identity shadow focused tests; synthetic fixtures only, no real-source claims."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "scripts" / "v213_identity_search_shadow.py"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.v213_identity_search_shadow import normalize_query, resolve_query  # noqa: E402


def nvda(us=True):
    return {
        "company_id": "syn-co-nvda",
        "security_id": "syn-sec-nvda-us" if us else "syn-sec-nvda-adr",
        "exchange": "NASDAQ" if us else "NYSE",
        "ticker": "NVDA",
        "canonical_name_zh_tw": "輝達" if us else None,
        "aliases": ["NVIDIA", "nvidia", "NvIdIa"] if us else [],
        "name_authority": "official_issuer_chinese" if us else None,
        "name_source": "synthetic-fixture" if us else None,
    }


def rec(cid, sid, exch, tick, canon=None, aliases=None, auth=None, src=None):
    return {
        "company_id": cid, "security_id": sid, "exchange": exch, "ticker": tick,
        "canonical_name_zh_tw": canon, "aliases": aliases or [],
        "name_authority": auth, "name_source": src,
    }


class TestIdentityShadow(unittest.TestCase):
    def test_normalization_aliases(self):
        records = [nvda()]
        for q in ("NVIDIA", "nvidia", "NvIdIa", "NVDA", "輝達", "ＮＶＤＡ", "  NVDA  "):
            with self.subTest(q=q):
                r = resolve_query(q, records)
                self.assertEqual(r["status"], "MATCH")
                self.assertFalse(r["AMBIGUOUS"])
                self.assertEqual(r["candidates"][0]["security_id"], "syn-sec-nvda-us")
        self.assertEqual(normalize_query("ＮＶＤＡ"), "nvda")
        self.assertEqual(normalize_query("  N   V   I   D   I   A "), "n v i d i a")
        with self.subTest("leading zero preserved"):
            lr = [rec("c", "s0", "HKEX", "00700")]
            self.assertEqual(resolve_query("00700", lr)["status"], "MATCH")
            self.assertEqual(resolve_query("700", lr)["status"], "NOT_FOUND")
        with self.subTest("punctuation distinctions"):
            pr = [rec("c", "s1", "NASDAQ", "BRK.A")]
            self.assertEqual(resolve_query("BRK.A", pr)["status"], "MATCH")
            self.assertEqual(resolve_query("BRK-A", pr)["status"], "NOT_FOUND")

    def test_collisions_and_filter(self):
        dual = [nvda(True), nvda(False)]
        r = resolve_query("NVDA", dual)
        self.assertEqual(r["status"], "AMBIGUOUS")
        self.assertTrue(r["AMBIGUOUS"])
        self.assertEqual(len(r["candidates"]), 2)
        names = {c["security_id"]: c["name"] for c in r["candidates"]}
        self.assertIsNone(names["syn-sec-nvda-adr"])
        self.assertEqual(names["syn-sec-nvda-us"], "輝達")
        self.assertEqual(resolve_query("NVDA", dual, exchange="NASDAQ")["status"], "MATCH")
        self.assertEqual(resolve_query("NVDA", dual, exchange="NYSE")["status"], "MATCH")
        no_pref = [rec("cA", "sA", "EX1", "ZZZ"), rec("cB", "sB", "EX2", "YYY", aliases=["ZZZ"])]
        rp = resolve_query("ZZZ", no_pref)
        self.assertEqual(rp["status"], "AMBIGUOUS")
        self.assertEqual(len(rp["candidates"]), 2)

    def test_invalid_inputs(self):
        good = nvda()
        def bad(mut):
            r = json.loads(json.dumps(good)); mut(r); return [r]
        cases = {
            "llm authority": lambda r: r.update(name_authority="llm"),
            "dict authority": lambda r: r.update(name_authority={}),
            "padded id": lambda r: r.update(company_id=" co "),
            "blank id": lambda r: r.update(security_id="   "),
            "blank source": lambda r: r.update(name_source="   "),
            "canonical absent with authority": lambda r: r.update(canonical_name_zh_tw=None),
        }
        for label, mut in cases.items():
            with self.subTest(label):
                with self.assertRaises(ValueError):
                    resolve_query("NVDA", bad(mut))
        with self.subTest("duplicate security_id"):
            with self.assertRaises(ValueError):
                resolve_query("NVDA", [nvda(True), nvda(True)])
        with self.subTest("duplicate venue-ticker"):
            a = nvda(True); b = json.loads(json.dumps(a)); b["security_id"] = "other"
            with self.assertRaises(ValueError):
                resolve_query("NVDA", [a, b])
        with self.subTest("non-str query"):
            with self.assertRaises(ValueError):
                resolve_query(123, [nvda()])
        with self.subTest("records not list"):
            with self.assertRaises(ValueError):
                resolve_query("NVDA", nvda())
        for ch in ("\x00", "\u202e"):
            with self.subTest(repr(ch)):
                with self.assertRaises(ValueError):
                    normalize_query("NVDA" + ch)

    def test_cli(self):
        def run(payload_text):
            with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
                f.write(payload_text); path = f.name
            try:
                return subprocess.run([sys.executable, str(SRC), path], capture_output=True, text=True, timeout=10)
            finally:
                Path(path).unlink(missing_ok=True)
        with self.subTest("valid match"):
            proc = run(json.dumps({"query": "NVDA", "records": [nvda()]}))
            self.assertEqual(proc.returncode, 0)
            out = json.loads(proc.stdout)
            self.assertEqual(out["status"], "MATCH")
            self.assertTrue(out["shadow_only"])
            self.assertFalse(out["production_authorized"])
        with self.subTest("malformed json failclosed"):
            proc = run("{not valid json")
            self.assertEqual(proc.returncode, 2)
            out = json.loads(proc.stdout)
            self.assertEqual(out["status"], "INVALID")
            self.assertEqual(out["candidates"], [])
        with self.subTest("duplicate keys failclosed"):
            proc = run('{"query":"NVDA","query":"NVDA","records":[]}')
            self.assertEqual(proc.returncode, 2)
            self.assertEqual(json.loads(proc.stdout)["status"], "INVALID")
        with self.subTest("deep nesting failclosed"):
            proc = run("[" * 2000 + "0" + "]" * 2000)
            self.assertEqual(proc.returncode, 2)
            out = json.loads(proc.stdout)
            self.assertEqual(out["status"], "INVALID")
            self.assertFalse(out["production_authorized"])
            self.assertEqual(proc.stderr, "")


if __name__ == "__main__":
    unittest.main()