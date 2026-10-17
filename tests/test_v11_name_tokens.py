"""V11 W5: leading-word name lookup. The producer side of the token shards (word folding, bucket hash, shard layout), their
sealing as lazy objects and the refresh's rebuild rule. Synthetic feeds and temporary directories only; no network.
The Worker half is cloud/test/v11-name-lookup.test.ts; its VECTORS table (between the VECTORS-BEGIN and VECTORS-END markers) is the
single list of shared word-folding vectors, asserted there against the Worker and here against the producer."""
from __future__ import annotations

import contextlib
import io
import json
import re
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_identity_shards as shards  # noqa: E402
import fetch_live_public_snapshot as live  # noqa: E402
import publish_sealed_snapshot as publisher  # noqa: E402
from tests.test_identity_batch04 import NOW, build_document  # noqa: E402

WORKER_TEST = (ROOT / "cloud/test/v11-name-lookup.test.ts").read_text(encoding="utf-8")
# [input, words, tokenized name ("" when the first word is not Latin), bucket or null]; the table is plain JSON inside the TypeScript file.
TABLE = re.search(r"// VECTORS-BEGIN.*?\nconst VECTORS[^=]*= (\[.*?\n\]);\n// VECTORS-END", WORKER_TEST, re.S)
VECTORS = json.loads(TABLE.group(1)) if TABLE else []
STAMP = "2026-10-13T04:14:46Z"


def row(symbol, venue, name, native=None, zh=None, market="US"):
    """The shape of a retained identity row (build() output): symbol, venue, market, country, name, native name, class, currency,
    feed index, [Chinese name, source] or None."""
    return [symbol, venue, market, "Synthetic", name, native, "COMMON_STOCK", "USD", 0, zh]


class WordFoldingTests(unittest.TestCase):
    def test_the_workers_vector_table_is_the_producers_output(self):
        self.assertGreaterEqual(len(VECTORS), 20)
        self.assertEqual(shards.TOKEN_BUCKETS, 8)  # the Worker's TOKEN_BUCKETS and the seal whitelist tok:[0-7]
        for text, words, name, bucket in VECTORS:
            self.assertEqual(shards.name_tokens(text), words, text)
            self.assertEqual(shards.leading_name(text), name, text)
            if name:
                self.assertEqual(shards.token_bucket(words[0]), bucket, text)
            else:
                self.assertIsNone(bucket)

    def test_hand_written_expectations(self):
        self.assertEqual(shards.name_tokens("Astera Labs, Inc. - Common Stock"), ["astera", "labs", "inc", "common", "stock"])
        self.assertEqual(shards.name_tokens("Lowe's Companies"), ["lowe", "s", "companies"])
        self.assertEqual(shards.name_tokens("Ｓｉｖｅｒｓ"), ["sivers"])  # full-width folds
        self.assertEqual(shards.name_tokens("a_b-c"), ["a", "b", "c"])
        self.assertEqual(shards.leading_name("  Sivers   Semiconductors "), "sivers semiconductors")
        # Only a Latin-script first word is indexed: Chinese, Korean and Greek names keep exact-name lookups only.
        for text in ("台積電", "삼성전자", "Σίγμα Corp", "", "---"):
            self.assertEqual(shards.leading_name(text), "", text)
        self.assertEqual(shards.leading_name("3M Company"), "3m company")

    def test_bucket_is_the_name_hash_of_the_first_word(self):
        self.assertEqual(shards.token_bucket("abc"), 440920331 % shards.TOKEN_BUCKETS)  # same FNV-1a as the exact-name shards
        for word in ("sivers", "micron", "alphabet", "global", "toyota"):
            self.assertIn(shards.token_bucket(word), range(shards.TOKEN_BUCKETS))


class TokenShardLayoutTests(unittest.TestCase):
    def test_rows_buckets_order_and_exclusions(self):
        records = [
            row("SIVE", "NASDAQ STOCKHOLM", "Sivers Semiconductors", market="SWEDEN"),
            row("MU", "NASDAQ", "Micron Technology, Inc. - Common Stock", zh=["美光", "ZHWIKI"]),
            row("6159", "TSE", "MICRON MACHINERY CO.,LTD.", market="JAPAN"),
            row("2330", "TWSE", "台灣積體電路製造股份有限公司", native="台積電", zh=["台積電", "TWSE"], market="TAIWAN"),
            row("TSM", "NYSE", "Taiwan Semiconductor Manufacturing Company Ltd.", zh=["台積電", "ZHWIKI"]),
            row("005930", "KRX", "삼성전자", native="삼성전자", market="KOREA"),
            row("VOLV B", "NASDAQ STOCKHOLM", "Volvo B", market="SWEDEN"),
            # A contradictory variant of one key and a repeated equal row: one token row for the key.
            row("ACME", "NASDAQ", "Acme Orbit"), row("ACME", "NASDAQ", "Acme Variant"), row("ACME", "NASDAQ", "Acme Orbit"),
            row("NATV", "NASDAQ", "Plain Name", native="Native Label"),
        ]
        document = shards.build_token_shards(records, STAMP)
        flat = sorted(item for shard in document.values() for item in shard["rows"])
        self.assertEqual(flat, sorted([
            ["sivers semiconductors", "S", "SIVE", "NASDAQ STOCKHOLM"],
            ["micron technology inc common stock", "M", "MU", "NASDAQ"],
            ["micron machinery co ltd", "6", "6159", "TSE"],
            ["taiwan semiconductor manufacturing company ltd", "T", "TSM", "NYSE"],
            ["volvo b", "V", "VOLV B", "NASDAQ STOCKHOLM"],
            ["acme orbit", "A", "ACME", "NASDAQ"],
            ["acme variant", "A", "ACME", "NASDAQ"],
            ["plain name", "N", "NATV", "NASDAQ"],
            ["native label", "N", "NATV", "NASDAQ"],
        ]))
        for bucket, shard in document.items():
            self.assertEqual(set(shard), {"schema", "kind", "bucket", "generated_at", "rows"})
            self.assertEqual((shard["schema"], shard["kind"], shard["generated_at"]), (shards.SCHEMA, "token", STAMP))
            self.assertIn(bucket, [str(index) for index in range(shards.TOKEN_BUCKETS)])
            self.assertEqual(shard["rows"], sorted(shard["rows"]))
            for name, symbol_bucket, symbol, venue in shard["rows"]:
                self.assertEqual(str(shards.token_bucket(name.split(" ", 1)[0])), bucket)
                self.assertEqual(symbol_bucket, shards.symbol_bucket(symbol))
                self.assertTrue(name and all(isinstance(item, str) for item in (name, symbol_bucket, symbol, venue)))
        self.assertFalse(any("台" in name or "삼성" in name or "美光" in name for shard in document.values() for name, *_ in shard["rows"]))

    def test_every_latin_name_of_the_builder_output_is_indexed_and_resolves_back(self):
        document = build_document()
        self.assertTrue(0 < len(document["token_shards"]) <= shards.TOKEN_BUCKETS)
        variants: dict[tuple[str, str], set[str]] = {}  # every retained variant of a key, so contradictory ones are all indexed
        for shard in document["symbol_shards"].values():
            for item in shard["rows"]:
                variants.setdefault((item[0], item[1]), set()).update({shards.leading_name(item[4]), shards.leading_name(item[5] or "")} - {""})
        indexed: dict[tuple[str, str], set[str]] = {}
        for shard in document["token_shards"].values():
            for name, symbol_bucket, symbol, venue in shard["rows"]:
                self.assertEqual(symbol_bucket, shards.symbol_bucket(symbol))
                indexed.setdefault((symbol, venue), set()).add(name)
        self.assertIn(("SIVE", "NASDAQ STOCKHOLM"), indexed)
        self.assertEqual(indexed, {key: names for key, names in variants.items() if names})


class SealingTests(unittest.TestCase):
    def lazy(self, document, now=None):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "identity.json"
            path.write_bytes(shards.dumps(document).encode("utf-8"))
            return publisher.lazy_identity_bodies(path, now or NOW)

    def test_token_shards_are_sealed_as_lazy_objects_next_to_the_v2_shards(self):
        document = build_document()
        lazy = self.lazy(document)
        tokens = {key for key in lazy if ":tok:" in key}
        self.assertEqual(tokens, {f"v213:identity:v2:tok:{bucket}" for bucket in document["token_shards"]})
        self.assertEqual(len(lazy), len(document["symbol_shards"]) + len(document["name_shards"]) + len(document["token_shards"]))
        for key in tokens:
            self.assertTrue(live.LAZY_KEY.fullmatch(key), key)
            self.assertEqual(json.loads(lazy[key])["kind"], "token")
        self.assertIn("v213:identity:v2:sym:S", lazy)

    def test_a_document_without_token_shards_seals_exactly_what_it_sealed_before(self):
        document = build_document()
        legacy = {key: value for key, value in document.items() if key != "token_shards"}
        lazy = self.lazy(legacy)
        self.assertFalse(any(":tok:" in key for key in lazy))
        self.assertEqual(len(lazy), len(document["symbol_shards"]) + len(document["name_shards"]))

    def test_a_bucket_outside_the_worker_whitelist_seals_no_identity_at_all(self):
        document = build_document()
        document["token_shards"] = {**document["token_shards"], "8": {"schema": shards.SCHEMA, "kind": "token", "bucket": "8",
                                                                      "generated_at": document["generated_at"], "rows": []}}
        self.assertEqual(self.lazy(document), {})
        document["token_shards"] = ["not", "a", "mapping"]
        self.assertEqual(self.lazy(document), {})

    def test_the_live_fetch_whitelist_mirrors_the_worker_keys(self):
        for good in ("v213:identity:v2:tok:0", "v213:identity:v2:tok:7", "v213:identity:v2:name:15", "v213:identity:v2:sym:A"):
            self.assertTrue(live.LAZY_KEY.fullmatch(good), good)
        for bad in ("v213:identity:v2:tok:8", "v213:identity:v2:tok:10", "v213:identity:v2:tok:A", "v213:identity:v2:tok:", "v213:identity:v3:tok:1"):
            self.assertFalse(live.LAZY_KEY.fullmatch(bad), bad)

    def test_the_whole_lazy_key_whitelist_fits_the_seals_key_budget(self):
        seal = (ROOT / "cloud/src/v213/snapshot-seal.ts").read_text(encoding="utf-8")
        limit = int(re.search(r"const MAX_LAZY_KEYS = (\d+);", seal).group(1))
        # Every key the whitelist can admit: 37 symbol buckets (A-Z, 0-9, _), 16 name, TOKEN_BUCKETS token, quotes:v1, options v1 and v2,
        # options-coverage, bottleneck-top20, revenue-guidance-binding and the 8 price markets. 16 token shards would give 83.
        possible = 37 + 16 + shards.TOKEN_BUCKETS + 1 + 2 + 1 + 1 + 1 + 8
        self.assertEqual(possible, 75)
        self.assertLessEqual(possible, limit)


class RefreshRuleTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="v11-tokens-")
        self.addCleanup(temp.cleanup)
        self.output = Path(temp.name) / "out" / "identity_shards_latest.json"
        patcher = mock.patch.object(shards, "load_zh_names", return_value=({}, None))
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_main(self, document, hours=24):
        build = mock.Mock(return_value=document)
        out = io.StringIO()
        with mock.patch.object(shards, "build", build), contextlib.redirect_stdout(out):
            code = shards.main(["--output", str(self.output), "--if-older-than-hours", str(hours)])
        return code, json.loads(out.getvalue().splitlines()[0]), build.call_count

    def test_the_producer_cli_writes_token_shards_and_reports_them(self):
        document = build_document()
        code, summary, calls = self.run_main(document)
        self.assertEqual((code, calls, summary["status"], summary["token_shards"]), (0, 1, "OK", len(document["token_shards"])))
        self.assertEqual(json.loads(self.output.read_bytes())["token_shards"], document["token_shards"])
        self.assertLess(summary["largest_shard_bytes"], 1_900_000)

    def test_a_fresh_file_built_before_the_token_shards_is_rebuilt_and_a_fresh_one_with_them_is_skipped(self):
        fresh = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        document = dict(build_document(), generated_at=fresh)
        old = {key: value for key, value in document.items() if key != "token_shards"}
        self.output.parent.mkdir(parents=True)
        self.output.write_text(shards.dumps(old), encoding="utf-8")
        code, summary, calls = self.run_main(document)
        self.assertEqual((code, calls, summary["status"]), (0, 1, "OK"))
        self.assertIn("token_shards", json.loads(self.output.read_bytes()))
        code, summary, calls = self.run_main(document)
        self.assertEqual((code, calls, summary["status"]), (0, 0, "SKIPPED_FRESH"))


if __name__ == "__main__":
    unittest.main()
