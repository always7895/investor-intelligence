"""G9a designed service rows; SYNTHETIC_G9_NOT_GENUINE, fake clocks only."""
from contextlib import redirect_stdout
from copy import deepcopy
import hashlib
import io
import json
import os
import re
import unittest
from unittest import mock

from tests import g9a_synthetic_issuers as h
from tests import nbis_synthetic_sources as f

A, B, C, D, E, F, G = h.SYMS
ATT = ("ATTEMPTED", "WAITING", "NETWORK_UNAVAILABLE")
CL = ("ATTEMPTED", "WAITING", "CAPTURE_LIMIT")
SK = ("WAITING", None, "RUN_BUDGET")
H4 = "HTTP 404"
SQ = "store quota"
UA = "store accounting unknown (--recount-store)"


class ServiceRows(unittest.TestCase):
    maxDiff = None

    def test_r1_1(self):
        def row():
            conf = json.loads(h.PROFILE.read_bytes())
            changed = deepcopy(conf)
            changed["enabled_symbols"].append(A)
            def gv(c):
                return tuple(n for n, b in (("ENABLED_SYMBOLS", c["enabled_symbols"] != ["NVDA", "MU"]),) if b)
            return (h.updater.PER_ISSUER_REQUESTS, h.updater.PER_RUN_REQUESTS, h.updater.RUN_BUDGET_SECONDS,
                    h.updater.PACING_SECONDS, gv(conf), gv(changed))
        self.assertEqual(f.observe_boundary("R1.1", f.outcome_of(lambda: row())),
                         ("RESULT", (24, 120, 600, 0.5, (), ("ENABLED_SYMBOLS",))))

    def test_r1_2(self):
        def row():
            with h.World(7, 0) as w:
                tracked = json.loads(h.REGISTRY.read_bytes())["issuers"]
                syms = sorted(set(w.records) & {r["symbol"] for r in tracked})
                def ciks(records):
                    return {int(m) for r in records for m in re.findall(r"/Archives/edgar/data/(\d+)/", json.dumps(r))}
                overlap = sorted(ciks(w.records.values()) & ciks(tracked))
                clean = all(not any(x in json.dumps(r).lower() for x in ("1045810", "nvidia", "nvda"))
                            for r in w.records.values())
                return (syms, overlap), clean, w.builder_ok
        self.assertEqual(f.observe_boundary("R1.2", f.outcome_of(lambda: row())),
                         ("RESULT", (([], []), True, True)))

    def test_r1_3(self):
        def row():
            with h.World(7, 0) as w:
                o = w.run(supported=False)
                return (w.summary()["issuers"], len(w.calls), sorted(os.listdir(w.state))) if o[0] == "RESULT" else o
        self.assertEqual(f.observe_boundary("R1.3", f.outcome_of(lambda: row())),
                         ("RESULT", ({}, 0, ["lock"])))

    def test_r1_4(self):
        def row():
            with h.World(7, 0) as w:
                o = w.run()
                if o[0] != "RESULT":
                    return o
                return (tuple((s,) + p for s, p in zip(w.syms, w.p3())), w.req(), w.clock(), w.counts(),
                        json.loads((w.state / "store_usage.json").read_bytes()), w.cur())
        self.assertEqual(f.observe_boundary("R1.4", f.outcome_of(lambda: row())),
                         ("RESULT", (tuple((s,) + ATT for s in h.SYMS), tuple((s, 4) for s in h.SYMS), 13.5,
                                     (9, 21, 21, 0), {"bytes": 21000, "files": 21, "pending": {}}, G)))

    def test_r2_1(self):
        self.assertEqual(f.observe_boundary("R2.1", f.outcome_of(lambda: h.rings()[0])),
                         ("RESULT", [(((A, 4),), (C, D, E, F, G), A),
                                     (((B, 4),), (D, E, F, G, A), B),
                                     (((C, 4),), (E, F, G, A, B), C),
                                     (((D, 4),), (F, G, A, B, C), D),
                                     (((E, 4),), (G, A, B, C, D), E),
                                     (((F, 4),), (A, B, C, D, E), F),
                                     (((G, 4),), (B, C, D, E, F), G),
                                     (((A, 2), (B, 2)), (D, E, F, G), B)]))

    def test_r2_1b(self):
        # Characterization F1; pinned only after the audit-side BASE observation.
        self.assertEqual(f.observe_boundary("R2.1b", f.outcome_of(lambda: h.rings()[1])),
                         ("RESULT", ([(H4, 3)] * 6 + [("RUN_REQUEST_BUDGET", 3), (H4, 3)], True, True)))

    def test_r2_2(self):
        def row():
            with h.World(7, 0) as w:
                o1 = w.run(1, crash=B)
                req1, cur1 = w.req(), w.cur()
                o2 = w.run(2, crash=B)
                final = tuple(tuple(w.last(s)[k] for k in ("outcome", "reason", "detail")) for s in w.syms)
                return o1, req1, cur1, o2, w.req(), w.cur(), final
        self.assertEqual(f.observe_boundary("R2.2", f.outcome_of(lambda: row())),
                         ("RESULT", (("RAISED", "_Sentinel", ""), ((A, 4), (B, 1)), B,
                                     ("RAISED", "_Sentinel", ""), ((C, 4), (D, 4), (E, 4), (F, 4), (G, 4), (A, 2), (B, 1)), B,
                                     (("WAITING", "NETWORK_UNAVAILABLE", H4),
                                      ("WAITING", "EVENT_DETECTED", "results filing detected")) +
                                     (("WAITING", "NETWORK_UNAVAILABLE", H4),) * 5)))

    def test_r3_1(self):
        def row():
            with h.World(7, 7) as w:
                o = w.run(retry503=True)
                return (len(w.calls), w.req(), w.p3(), w.detail(F), w.detail(A), w.cur(), w.clock(),
                        max(n for s, n in w.req())) if o[0] == "RESULT" else o
        self.assertEqual(f.observe_boundary("R3.1", f.outcome_of(lambda: row())),
                         ("RESULT", (120, ((A, 22), (B, 22), (C, 22), (D, 22), (E, 22), (F, 10)),
                                     (ATT,) * 6 + (SK,), ("RUN_REQUEST_BUDGET", 5), (H4, 10), F, 59.5, 22)))

    def test_r3_2(self):
        def row():
            with h.World(3, 7, 1) as w:
                o = w.run(retry503=True)
                return (w.req(), w.p3(), tuple(w.detail(s) for s in w.syms), len(w.calls), w.cur(), w.clock()) if o[0] == "RESULT" else o
        self.assertEqual(f.observe_boundary("R3.2", f.outcome_of(lambda: row())),
                         ("RESULT", (((A, 24), (B, 24), (C, 24)), (ATT,) * 3,
                                     (("ISSUER_REQUEST_BUDGET", 12),) * 3, 72, C, 35.5)))

    def test_r3_3(self):
        def row():
            with h.World(2, 3) as w:
                o = w.run(latency=100)
                return ([t for t, s, kind in w.calls], len(w.calls), w.p3(),
                        (w.detail(A)[0], tuple(sorted(w.last(A)["captures"]))), w.cur(), w.clock()) if o[0] == "RESULT" else o
        self.assertEqual(f.observe_boundary("R3.3", f.outcome_of(lambda: row())),
                         ("RESULT", ([0.0, 100.0, 200.0, 300.0, 400.0, 500.0], 6, (ATT, SK),
                                     ("RUN_BUDGET", ("exhibit", "index", "package:d1.htm", "package:d2.htm", "submissions")), A, 600.0)))

    def test_r3_4(self):
        def row():
            with h.World(2, 0) as w:
                o = w.run(patches={"CYCLE_CAPTURE_BYTES": 4000})
                return (w.req(), w.p3(), w.detail(B), tuple(sorted(w.last(B)["captures"])),
                        sum(p.stat().st_size for p in w.raw()), w.cur()) if o[0] == "RESULT" else o
        self.assertEqual(f.observe_boundary("R3.4", f.outcome_of(lambda: row())),
                         ("RESULT", (((A, 4), (B, 2)), (ATT, CL), ("RUN_CAPTURE_BUDGET", 1), ("submissions",), 4000, B)))

    def test_r4_1(self):
        def row():
            with h.World(3, 0) as w:
                o1 = w.run(1)
                size, count = sum(p.stat().st_size for p in w.raw()), len(w.raw())
                o2 = w.run(2, patches={"STORE_QUOTA_BYTES": 9000})
                if o1[0] != "RESULT" or o2[0] != "RESULT":
                    return o1, o2
                return (len(w.calls), w.p3(), tuple(w.detail(s)[0] for s in w.syms),
                        (size, sum(p.stat().st_size for p in w.raw())), (count, len(w.raw())), w.cur())
        self.assertEqual(f.observe_boundary("R4.1", f.outcome_of(lambda: row())),
                         ("RESULT", (0, (CL,) * 3, (SQ,) * 3, (9000, 9000), (9, 9), C)))

    def test_r4_2(self):
        def row():
            with h.World(3, 0) as w:
                o1 = w.run(1)
                with mock.patch.object(h, "MARKER", h.MARKER + " R2"):
                    o2 = w.run(2, patches={"STORE_QUOTA_BYTES": 9001})
                return (w.req(), tuple(w.detail(s)[0] for s in w.syms), sum(p.stat().st_size for p in w.raw()),
                        len(w.raw())) if o1[0] == o2[0] == "RESULT" else (o1, o2)
        self.assertEqual(f.observe_boundary("R4.2", f.outcome_of(lambda: row())),
                         ("RESULT", (((A, 1),), (SQ,) * 3, 9000, 9)))

    def test_r4_3(self):
        def row():
            with h.World(3, 0) as w:
                o1 = w.run(1)
                (w.state / "store_usage.json").unlink()
                o2 = w.run(2)
                run2 = ((w.summary().get("store_accounting"), len(w.calls), tuple(w.detail(s)[0] for s in w.syms),
                         tuple(len(w.pg()["detections"][s]["documents"]) for s in w.syms))
                        if o2[0] == "RESULT" else o2)
                out = io.StringIO()
                with redirect_stdout(out):
                    main = f.outcome_of(lambda: h.updater.main(["--state-root", str(w.state), "--recount-store"]))
                recount = json.loads(out.getvalue())
                o3 = w.run(3)
                run3 = (w.req(), tuple(w.detail(s)[0] for s in w.syms)) if o3[0] == "RESULT" else o3
                return (run2, (main[1], tuple(recount[k] for k in ("bytes", "files", "status"))), run3) if o1[0] == main[0] == "RESULT" else (o1, main, o3)
        self.assertEqual(f.observe_boundary("R4.3", f.outcome_of(lambda: row())),
                         ("RESULT", (("UNKNOWN", 0, (UA,) * 3, (2, 2, 2)),
                                     (0, (9000, 9, "RECOUNTED")), (((A, 2), (B, 2), (C, 2)), (H4,) * 3))))

    def test_r5_1(self):
        def row():
            with h.World(1, 0) as w:
                control = w.run()
                if control[0] != "RESULT":
                    return control
                chain = list(reversed(w.walk()))
                s0, s1 = (p.stat().st_size for p, gen in chain[:2])
            variants = []
            for limit in (s0, s0 - 1):
                with h.World(1, 0) as w, mock.patch.object(h.overlay, "MAX_GENERATION_BYTES", limit):
                    o = w.run()
                    pointer = w.pointer()
                    status = "ABSENT" if pointer is None else "OK" if pointer["sha256"] == hashlib.sha256(
                        (w.state / "generations" / (pointer["generation_id"] + ".json")).read_bytes()).hexdigest() else "BAD"
                    variants.append((o, w.counts()[0], status, len(w.calls),
                                     tuple(sorted(str(p.relative_to(w.state)) for p in w.state.rglob("*.tmp-*")))))
            return variants[0], variants[1], s1 > s0
        self.assertEqual(f.observe_boundary("R5.1", f.outcome_of(lambda: row())),
                         ("RESULT", ((("RAISED", "SystemicFailure", "PUBLISH GENERATION_TOO_LARGE"), 1, "OK", 0, ()),
                                     (("RAISED", "SystemicFailure", "PUBLISH GENERATION_TOO_LARGE"), 0, "ABSENT", 0, ()), True)))


if __name__ == "__main__":
    unittest.main()
