"""Exact objects.json key-set tests for scripts/publish_sealed_snapshot.py main() (offline, no KV, no provider reads).

PB.main always gets --snapshot-root <tmp>/snapshots and never --live-clock; the five lazy providers are replaced by
recording fakes, so no repository cache is read and the key set depends on constants only. The expected key lists are
written here as literals on purpose: expectations derived only from the publisher's own constants would let a
constant mutation pass. Each row compares a literal designed from the code; the comment above each row cites the
lines it was designed from."""
from __future__ import annotations

import contextlib
import hashlib
import json
import socket
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import publish_sealed_snapshot as publisher  # noqa: E402

CLOCK_NAMES = ("LIVE_NOW", "LIVE_STAMP", "EVALUATED_AT", "GENERATED_AT", "CLAIMED_AT", "PROMOTED_AT",
               "PUBLISHED_DATA_AS_OF")
LAZY_NAMES = ("lazy_identity_bodies", "lazy_market_bodies", "lazy_options_coverage_body", "lazy_price_bodies",
              "lazy_bottleneck_v3_body")
EXPECTED_BODY_KEYS = [
    "v21:top20:latest", "scores:latest", "source_views:latest", "source_plan:latest", "reports:latest",
    "reports:morning:latest", "reports:evening:latest", "last_successful_pipeline_timestamp",
    "v212:top20-report:latest", "v213:top20-report:latest", "v213:source-federation:latest",
    "v213:source-independence:latest", "v213:activation-claim", "v213:macro-industry:latest",
]
EXPECTED_15 = EXPECTED_BODY_KEYS + ["v213:snapshot-seal:v1"]
FIELDS_F = ("exit_code", "prefix_ok", "unprefixed", "suffixes", "blob_keys", "count", "lazy_objects", "top20_state",
            "top20_reason", "calls", "coverage_arg", "blob_bodies")
FIELDS_0 = ("object_keys", "macro_key", "seal_key", "blob_prefix", "coverage_key", "bottleneck_key", "doc_15_keys",
            "expected_len")
B_ID = '{"synthetic":"identity"}'
B_Q = '{"synthetic":"quotes"}'
B_O = '{"synthetic":"options","note":"合成"}'
B_C = '{"synthetic":"coverage"}'
B_P = '{"synthetic":"prices"}'
B_B = '{"synthetic":"bottleneck"}'
B_SAME = '{"synthetic":"one body under two names"}'


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def diff_fields(names, got, want):
    fields = [name for name, a, b in zip(names, got, want) if a != b]
    if len(got) != len(want):
        fields.append("arity")
    return "DIFF_FIELDS=" + ",".join(fields)


class Recorder:
    """Stands in for one lazy provider: counts calls, remembers the arguments, returns a fixed dict."""

    def __init__(self, returns):
        self.returns = dict(returns)
        self.calls = []

    def __call__(self, first, now):
        self.calls.append((first, now))
        return dict(self.returns)


class KeysetCase(unittest.TestCase):
    def setUp(self):
        self.saved = {name: getattr(publisher, name) for name in CLOCK_NAMES}

        def refuse_network(*args, **kwargs):
            raise AssertionError("guard: network must never be used")

        self.patchers = [mock.patch.object(socket, "create_connection", side_effect=refuse_network),
                         mock.patch.object(socket, "getaddrinfo", side_effect=refuse_network)]
        for patcher in self.patchers:
            patcher.start()
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name).resolve()
        self.snapshots = self.base / "snapshots"
        self.assertEqual(self.snapshots.is_relative_to(ROOT.resolve()), False)

    def tearDown(self):
        for patcher in reversed(self.patchers):
            patcher.stop()
        for name, value in self.saved.items():
            setattr(publisher, name, value)
        self.tmp.cleanup()

    def run_pb(self, argv, returns=None):
        """One publisher.main(argv) with the five lazy providers faked; never raises, never asserts."""
        fakes = {name: Recorder((returns or {}).get(name, {})) for name in LAZY_NAMES}
        buffer = StringIO()
        exit_code = 0
        with contextlib.ExitStack() as stack:
            for name, fake in fakes.items():
                stack.enter_context(mock.patch.object(publisher, name, fake))
            try:
                with redirect_stdout(buffer):
                    publisher.main(argv)
            except (Exception, SystemExit) as error:  # noqa: BLE001 - the class name is the row's observation
                exit_code = type(error).__name__
        try:
            summary = json.loads(buffer.getvalue())
        except ValueError:
            summary = {}
        run_dir = self.snapshots / summary["run_id"] if "run_id" in summary else None
        try:
            objects = json.loads((run_dir / "objects.json").read_bytes().decode("utf-8"))
        except (OSError, ValueError, TypeError):
            objects = {}
        run_id = summary.get("run_id", "")
        prefix = "snapshot:" + run_id + ":"
        keys = list(objects)
        blob_keys = tuple(sorted(key for key in keys if key.startswith("blob:v1:")))
        coverage = fakes["lazy_options_coverage_body"].calls
        return {
            "exit_code": exit_code,
            "prefix_ok": run_id.startswith("20260915T120000Z-"),
            "unprefixed": tuple(sorted(key for key in keys if not key.startswith(prefix) and not key.startswith("blob:v1:"))),
            "suffixes": tuple(sorted(key[len(prefix):] for key in keys if key.startswith(prefix))),
            "blob_keys": blob_keys,
            "count": len(keys),
            "lazy_objects": summary.get("lazy_objects"),
            "top20_state": summary.get("top20_state"),
            "top20_reason": summary.get("top20_reason"),
            "calls": tuple(len(fakes[name].calls) for name in LAZY_NAMES),
            "coverage_arg": coverage[0][0] if coverage else None,
            "blob_bodies": tuple(sorted(objects[key] for key in blob_keys)),
            "_objects": objects, "_run_dir": run_dir, "_run_id": run_id, "_prefix": prefix,
        }

    def row_f(self, seen):
        return tuple(seen[name] for name in FIELDS_F)

    def chain_checks(self, seen, lazy_bodies):
        """Preconditions placed after a row's main assertEqual (SR/PB lines in the row comments below)."""
        objects, prefix, run_dir = seen["_objects"], seen["_prefix"], seen["_run_dir"]
        order = [prefix + name for name in EXPECTED_BODY_KEYS] + [prefix + "v213:snapshot-seal:v1"]
        self.assertEqual(list(objects)[:len(order)], order)
        seal = json.loads(objects[prefix + "v213:snapshot-seal:v1"])
        names = list(EXPECTED_BODY_KEYS)
        lazy_names = sorted(lazy_bodies)
        self.assertEqual(list(seal["objects"]), names + lazy_names)
        rows = [(name, seal["objects"][name]["sha256"], seal["objects"][name]["utf8_bytes"]) for name in seal["objects"]]
        bodies = [objects[prefix + name] for name in names] + [lazy_bodies[name] for name in lazy_names]
        self.assertEqual(rows, [(name, sha(body), len(body.encode("utf-8")))
                                for name, body in zip(names + lazy_names, bodies)])
        pointer = json.loads((run_dir / "pointer.raw.json").read_bytes().decode("utf-8"))
        self.assertEqual((pointer["run_id"], pointer["seal_sha256"]),
                         (run_dir.name, sha(objects[prefix + "v213:snapshot-seal:v1"])))
        return seal


class KeysetRows(KeysetCase):
    # KS-0: the constants behind the key set. PB 106-112 (13 OBJECT_KEYS), 55 MACRO_KEY, 92 SEAL_KEY, 95 prefix,
    # 882 COVERAGE_KEY, 99 BOTTLENECK_V3_KEY, header docstring line 12 ("15 store keys: 14 bodies + seal").
    def test_KS_0_constants(self):
        got = (tuple(publisher.OBJECT_KEYS), publisher.MACRO_KEY, publisher.SEAL_KEY, publisher.LAZY_BLOB_PREFIX,
               publisher.COVERAGE_KEY, publisher.BOTTLENECK_V3_KEY, "15 store keys" in publisher.__doc__,
               len(EXPECTED_15))
        want = (tuple(EXPECTED_BODY_KEYS[:13]), "v213:macro-industry:latest", "v213:snapshot-seal:v1", "blob:v1:",
                "v213:options-coverage:v1", "v213:bottleneck-top20:v3", True, 15)
        self.assertEqual(got, want, diff_fields(FIELDS_0, got, want))

    # KS-1 golden path: no carry (1069-1075), no lazy flag (1076-1088), so objects = 13 OBJECT_KEYS + MACRO_KEY under
    # snapshot:<run_id>: (1093-1094) + the seal (1095) = 15 keys, no blob key (1096-1097 loop over an empty dict).
    # run_id is the golden stamp 20260915T120000Z-<suffix> (342, 58). Summary has no lazy_objects (1123) and no
    # top20_state (1125).
    def test_KS_1_golden_key_set(self):
        seen = self.run_pb(["--snapshot-root", str(self.snapshots)])
        got = self.row_f(seen)
        want = (0, True, (), tuple(sorted(EXPECTED_15)), (), 15, None, None, None, (0, 0, 0, 0, 0), None, ())
        self.assertEqual(got, want, diff_fields(FIELDS_F, got, want))
        self.chain_checks(seen, {})
        names = tuple(sorted(path.name for path in seen["_run_dir"].iterdir()))
        # PB 1098-1103 and 1135: objects, pointer, projection (golden path has a Top20) and summary.
        self.assertEqual(names, ("objects.json", "pointer.raw.json", "seven-field-projection.json", "summary.json"))

    # KS-2 INSUFFICIENT carry (1070-1074, 366-367 forced reason returns before any bundle read): same 15 keys; the
    # summary carries top20_state/top20_reason (1125-1130); no Top20 projection file (1102 needs meta["top20"]).
    def test_KS_2_insufficient_carry_key_set(self):
        argv = ["--top20-bundle", str(self.base / "absent.json"), "--top20-insufficient", "TOP20_KEYSET_PROBE",
                "--snapshot-root", str(self.snapshots)]
        seen = self.run_pb(argv)
        got = self.row_f(seen)
        want = (0, True, (), tuple(sorted(EXPECTED_15)), (), 15, None, "INSUFFICIENT", "TOP20_KEYSET_PROBE",
                (0, 0, 0, 0, 0), None, ())
        self.assertEqual(got, want, diff_fields(FIELDS_F, got, want))
        self.chain_checks(seen, {})
        names = tuple(sorted(path.name for path in seen["_run_dir"].iterdir()))
        self.assertEqual(names, ("objects.json", "pointer.raw.json", "summary.json"))

    # KS-3 all lazy families (1077-1088): identity, market (+ coverage computed from the options body just built,
    # 1082), prices, bottleneck. Lazy objects are stored ONLY as blob:v1:<sha256(body)> (95, 1096-1097); their names
    # appear only in the seal manifest, sorted (991-992). 15 + 6 = 21 keys; summary lazy_objects = 6 (1123-1124).
    def test_KS_3_all_lazy_families(self):
        lazy = {"v213:identity:v2:sym:A": B_ID, "v213:quotes:v1": B_Q, "v213:options:v2": B_O,
                publisher.COVERAGE_KEY: B_C, "v213:prices:v1:US": B_P, publisher.BOTTLENECK_V3_KEY: B_B}
        returns = {"lazy_identity_bodies": {"v213:identity:v2:sym:A": B_ID},
                   "lazy_market_bodies": {"v213:quotes:v1": B_Q, "v213:options:v2": B_O},
                   "lazy_options_coverage_body": {publisher.COVERAGE_KEY: B_C},
                   "lazy_price_bodies": {"v213:prices:v1:US": B_P},
                   "lazy_bottleneck_v3_body": {publisher.BOTTLENECK_V3_KEY: B_B}}
        argv = ["--identity-shards", "x", "--market-observations", "x", "--price-shards", "x", "--bottleneck-v3", "x",
                "--snapshot-root", str(self.snapshots)]
        seen = self.run_pb(argv, returns)
        blobs = tuple(sorted("blob:v1:" + sha(body) for body in (B_ID, B_Q, B_O, B_C, B_P, B_B)))
        got = self.row_f(seen)
        want = (0, True, (), tuple(sorted(EXPECTED_15)), blobs, 21, 6, None, None, (1, 1, 1, 1, 1), B_O,
                tuple(sorted((B_ID, B_Q, B_O, B_C, B_P, B_B))))
        self.assertEqual(got, want, diff_fields(FIELDS_F, got, want))
        prefix = seen["_prefix"]
        keys = list(seen["_objects"])
        order = [prefix + name for name in EXPECTED_15]
        order_tail = ["blob:v1:" + sha(body) for body in (B_ID, B_Q, B_O, B_C, B_P, B_B)]
        self.assertEqual(keys, order + order_tail)
        self.chain_checks(seen, lazy)
        under_prefix = [prefix + name for name in lazy if prefix + name in seen["_objects"]]
        self.assertEqual(under_prefix, [])
        self.assertEqual(len(B_O.encode("utf-8")) > len(B_O), True)

    # KS-4 content-addressed dedup (1096-1097): two names with one body make ONE blob key, while the seal still lists
    # both names (989-992). 15 + 1 = 16 keys, lazy_objects counts the two names (1124).
    def test_KS_4_equal_bodies_share_one_blob(self):
        returns = {"lazy_identity_bodies": {"v213:identity:v2:sym:A": B_SAME},
                   "lazy_bottleneck_v3_body": {publisher.BOTTLENECK_V3_KEY: B_SAME}}
        argv = ["--identity-shards", "x", "--bottleneck-v3", "x", "--snapshot-root", str(self.snapshots)]
        seen = self.run_pb(argv, returns)
        got = self.row_f(seen)
        want = (0, True, (), tuple(sorted(EXPECTED_15)), ("blob:v1:" + sha(B_SAME),), 16, 2, None, None,
                (1, 0, 0, 0, 1), None, (B_SAME,))
        self.assertEqual(got, want, diff_fields(FIELDS_F, got, want))
        lazy = {"v213:identity:v2:sym:A": B_SAME, "v213:bottleneck-top20:v3": B_SAME}
        seal = self.chain_checks(seen, lazy)
        shas = [seal["objects"][name]["sha256"] for name in ("v213:bottleneck-top20:v3", "v213:identity:v2:sym:A")]
        self.assertEqual(shas, [sha(B_SAME), sha(B_SAME)])


if __name__ == "__main__":
    unittest.main()
