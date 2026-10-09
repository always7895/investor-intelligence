"""SYNTHETIC_G9_NOT_GENUINE: seven private issuers, fake time, no network.

Only owned TemporaryDirectory state is writable. This is not issuer admission.
"""
from __future__ import annotations

from collections import Counter
from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import socket
import tempfile
from unittest import mock

from tests import nbis_synthetic_sources as f

updater, overlay, verify, guidance = f.updater, f.overlay, f.verify, f.guidance
ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "config/revenue-guidance-extraction-profiles-v1.json"
REGISTRY = ROOT / "config/revenue-guidance-v1.json"
BOOTSTRAP = ROOT / "tests/fixtures/revenue-guidance-autoupdate/bootstrap-registry.json"
SYMS = ("ZQA", "ZQB", "ZQC", "ZQD", "ZQE", "ZQF", "ZQG")
MARKER = "SYNTHETIC_G9_NOT_GENUINE"
D = "2026-03-01"


def at(k):
    return datetime(2026, 3, 2, 12, tzinfo=timezone.utc) + timedelta(minutes=k)


def cik(i):
    return 9100001 + i


def acc(i, n):
    return f"{cik(i):010d}-26-{n:06d}"


def host(sym):
    return "ir." + sym.lower() + ".synthetic-g9.example"


def ir_url(sym):
    return f"https://{host(sym)}/news/2026/{sym.lower()}-results/default.aspx"


def later(channel, day, identity, label):
    return dict(channel=channel, date=day, id=identity, label=label, disposition="RESULTS_RELEASE")


def settled():
    return [{"key": f"0000000000-00-{i:06d}", "date": "2026-01-01"} for i in range(256)]


def put(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def padded(body):
    raw = body.encode("utf-8") if isinstance(body, str) else json.dumps(body).encode("utf-8")
    if len(raw) > 1000:
        raise ValueError("synthetic connector body exceeds 1000 bytes")
    return raw.ljust(1000, b" ")


class FakeClock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value

    def sleep(self, seconds):
        self.value += seconds


class Response:
    def __init__(self, status, body, ctype, retry=False):
        self.status, self.body = status, body
        self.headers = {"content-type": ctype}
        if retry:
            self.headers["retry-after"] = "0"

    def read(self, n):
        body, self.body = self.body, b""
        return body

    def close(self):
        pass


class World:
    def __init__(self, n, k_pkg, periodic=0):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.state = self.root / "state"
        self.syms = SYMS[:n]
        self.k_pkg, self.periodic = k_pkg, periodic
        self.profiles = self.root / "profiles.json"
        self.registry = self.root / "registry.json"
        self.approval = self.root / "approval.json"
        self.receipts = self.root / "receipts.json"
        tracked = json.loads(PROFILE.read_bytes())
        original = next(p for p in tracked["profiles"] if p["symbol"] == "NVDA")
        profiles = []
        bootstrap = json.loads(BOOTSTRAP.read_bytes())
        record = next(r for r in bootstrap["issuers"] if r["symbol"] == "NVDA")
        records, receipt_rows = [], {}
        for i, sym in enumerate(self.syms):
            prof = deepcopy(original)
            prof.update(symbol=sym, profile_id="G9A-" + sym, cik=cik(i), company_name=sym, ir_host=host(sym))
            prof["release"]["exhibit_name_pattern"] = r"^pr\.htm$"
            prof["ir_page_pattern"] = "^https://" + re.escape(host(sym)) + r"/news/20[0-9]{2}/[A-Za-z0-9-]{1,160}/default\.aspx$"
            title_pattern = sym + "\u00c9 Announces Financial Results for (?P<q>First|Second|Third|Fourth) Quarter (?:and )?Fiscal (?P<fy>[0-9]{4})"
            prof["ir_title_pattern"] = prof["wire_title_pattern"] = title_pattern
            profiles.append(prof)
            raw = json.dumps(record)
            for old, new in (("0001045810", f"{cik(i):010d}"), ("1045810", str(cik(i))),
                             ("investor.nvidia.com", host(sym)), ("NVDA", sym), ("nvda", sym.lower()),
                             ("NVIDIA", sym), ("nvidia", sym.lower())):
                raw = raw.replace(old, new)
            records.append(json.loads(raw))
            receipt_rows[sym] = [{"checked_at": "2026-03-02T11:00:00Z",
                                  "guidance_document_id": f"{sym}-{cik(i):010d}-25-000228",
                                  "later_documents": [later("SEC_SUBMISSIONS", D, acc(i, 1), "8-K items 2.02,9.01"),
                                                      later("ISSUER_IR", D, ir_url(sym), sym + "\u00c9 Announces Financial Results for First Quarter Fiscal 2027")]}]
        put(self.profiles, dict(tracked, profiles=profiles, enabled_symbols=list(self.syms)))
        put(self.registry, {"schema": bootstrap["schema"], "version": bootstrap["version"], "issuers": records})
        self.approval.write_text('{"schema": "test-baseline-approval"}', encoding="utf-8")
        put(self.receipts, {"schema": guidance.RELEASE_CHECKS_SCHEMA, "issuers": receipt_rows})
        self.profs = verify.validate_profiles(json.loads(self.profiles.read_bytes()))
        parsed = guidance.parse_registry(self.registry.read_bytes())
        if set(self.profs) != set(self.syms) or parsed["status"] != "OK":
            raise ValueError("synthetic builder validation: " + repr(parsed.get("error")))
        self.records = {r["symbol"]: r for r in records}
        self.builder_ok = all(guidance.guidance_reference(r)["conflict"] is False and
                              guidance.guidance_reference(r)["document_id"] == receipt_rows[sym][0]["guidance_document_id"]
                              for sym, r in self.records.items())
        if not self.builder_ok:
            raise ValueError("synthetic builder reference conflict")
        self.calls, self.outcomes = [], []
        self.clock = FakeClock()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.tmp.cleanup()

    def payload(self, i, kind, name):
        sym = self.syms[i]
        if kind == "SUB":
            rows = [(acc(i, 1), "8-K", D, "2026-02-28", "pr.htm", "2.02,9.01")]
            if self.periodic:
                rows += [(acc(i, 10), "10-K", "2026-02-20", "2025-12-31", "k.htm", ""),
                         (acc(i, 11), "10-Q", "2026-02-25", "2025-12-31", "q.htm", "")]
            recent = {key: [r[j] for r in rows] for j, key in enumerate(
                ("accessionNumber", "form", "filingDate", "reportDate", "primaryDocument", "items"))}
            return padded({"cik": cik(i), "filings": {"recent": recent}, "marker": MARKER}), "application/json"
        if kind == "INDEX":
            names = ["pr.htm"] + [f"d{j}.htm" for j in range(1, self.k_pkg + 1)]
            return padded({"directory": {"item": [{"name": n} for n in names]}, "marker": MARKER + " " + sym}), "application/json"
        return padded(f"<html><body><p>{MARKER} {sym} {name}</p></body></html>"), "text/html"

    def run(self, k=1, *, instant=None, supported=True, retry503=False, latency=0, crash=None, patches=None):
        self.calls, seen = [], set()
        self.clock = FakeClock()

        def connector(h, address, path, headers, timeout):
            if h == "data.sec.gov":
                i, kind = int(re.fullmatch(r"/submissions/CIK([0-9]{10})\.json", path)[1]) - 9100001, "SUB"
            elif h == "www.sec.gov":
                i = int(path.split("/")[4]) - 9100001
                kind = "INDEX" if path.endswith("/index.json") else "DOC"
            else:
                i, kind = [host(sym) for sym in self.syms].index(h), "IR"
            sym = self.syms[i]
            self.calls.append((self.clock(), sym, kind))
            self.clock.sleep(latency)
            if sym == crash:
                raise f._Sentinel()
            url = (h, path)
            retry = retry503 and url not in seen
            seen.add(url)
            raw, ctype = self.payload(i, kind, path.rsplit("/", 1)[-1])
            return Response(503 if retry else 404 if kind == "IR" else 200, raw, ctype, retry)

        transport = updater.Transport({"User-Agent": "G9A-SYNTHETIC"}, connector=connector,
                                      resolver=lambda h: ["162.159.140.1"], sleep=self.clock.sleep, monotonic=self.clock)
        fixed = instant or at(k)
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(socket, "create_connection", side_effect=AssertionError("NO_NETWORK")))
            stack.enter_context(mock.patch.object(socket, "getaddrinfo", side_effect=AssertionError("NO_NETWORK")))
            if supported:
                stack.enter_context(mock.patch.object(overlay, "SUPPORTED_AUTO", tuple(self.syms)))
            for name, value in (patches or {}).items():
                stack.enter_context(mock.patch.object(updater, name, value))
            result = f.outcome_of(lambda: updater.run(self.state, transport, lambda: fixed, self.profiles,
                                                     self.registry, self.approval, self.receipts))
        self.outcomes.append(result)
        return result

    def summary(self):
        return self.outcomes[-1][1] if self.outcomes[-1][0] == "RESULT" else self.outcomes[-1]

    def req(self):
        return tuple(Counter(sym for _, sym, _ in self.calls).items())

    def pointer(self):
        p = self.state / "current.json"
        return json.loads(p.read_bytes()) if p.exists() else None

    def pg(self):
        p = self.pointer()
        return json.loads((self.state / "generations" / (p["generation_id"] + ".json")).read_bytes())

    def cur(self):
        p = self.state / "queue.json"
        return json.loads(p.read_bytes())["last_served"] if p.exists() else None

    def last(self, sym):
        return self.pg()["issuers"][sym]["open"][-1]

    def detail(self, sym):
        a = self.last(sym)
        return a["detail"], len(a["captures"])

    def p3(self):
        rows = self.summary()["issuers"]
        return tuple((rows[s]["action"], rows[s].get("outcome"), rows[s]["reason"]) for s in self.syms)

    def files(self, directory):
        p = self.state / directory
        return sorted(x for x in p.rglob("*") if x.is_file()) if p.exists() else []

    def raw(self):
        return [p for p in self.files("captures") if p.suffix != ".json"]

    def counts(self):
        captures = self.files("captures")
        return len(self.files("generations")), len(self.raw()), len(captures) - len(self.raw()), len(self.files("segments"))

    def walk(self):
        p, generations = self.pointer(), []
        while p:
            path = self.state / "generations" / (p["generation_id"] + ".json")
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != p["sha256"]:
                raise ValueError("parent digest mismatch")
            gen = json.loads(raw)
            generations.append((path, gen))
            p = gen["parent"]
        return generations

    def ghost(self, i, j=1):
        rows = json.loads(self.receipts.read_bytes())
        rows["issuers"][self.syms[i]][0]["later_documents"].append(
            later("SEC_SUBMISSIONS", "2026-02-27", acc(i, 900000 + j), "8-K items 2.02,9.01"))
        put(self.receipts, rows)


def rings():
    with World(7, 0) as w:
        trace, waits, keys, generations = [], [], [], []
        for k in range(1, 9):
            outcome = w.run(k, patches={"PER_RUN_REQUESTS": 4})
            if outcome[0] != "RESULT":
                trace.append(outcome)
                continue
            skips = tuple(s for s, entry in w.summary()["issuers"].items()
                          if entry == {"action": "WAITING", "reason": "RUN_BUDGET"})
            trace.append((w.req(), skips, w.cur()))
            waits.append(w.detail("ZQA"))
            keys.append(tuple(sorted(w.last("ZQA")["captures"])))
            generations.append(w.counts()[0])
        return trace, (waits, len(keys) == 8 and all(k == keys[0] for k in keys),
                       len(generations) == 8 and generations == sorted(generations))
