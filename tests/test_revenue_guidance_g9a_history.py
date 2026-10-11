"""G9a BASE-pinned history characterization; not correctness claims."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import unittest

from tests import g9a_synthetic_issuers as h
from tests import nbis_synthetic_sources as f

A, B, C, D, E, F, G = h.SYMS


class HistoryRows(unittest.TestCase):
    maxDiff = None

    def test_r6_1(self):
        def row():
            with h.World(7, 0) as w:
                previous, queue, pointer = {}, None, None
                trace, sizes_ok = [], True
                for k in range(1, 11):
                    if k == 6:
                        w.ghost(2)
                    o = w.run(k)
                    if o[0] != "RESULT":
                        trace.append(o)
                        continue
                    current = {p.relative_to(w.state).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                               for name in ("captures", "segments", "generations") for p in w.files(name)}
                    new = set(current) - set(previous)
                    raw = sum(p.startswith("captures/") and not p.endswith(".json") for p in new)
                    meta = sum(p.startswith("captures/") and p.endswith(".json") for p in new)
                    gen = sum(p.startswith("generations/") for p in new)
                    seg = sum(p.startswith("segments/") for p in new)
                    changed = sum(current.get(p) != digest for p, digest in previous.items())
                    q = (w.state / "queue.json").read_bytes()
                    p = (w.state / "current.json").read_bytes()
                    trace.append((raw, meta, gen, seg, changed, q == queue, p == pointer))
                    sizes_ok &= gen <= 9 and all(p.stat().st_size < 262144 for p in w.files("generations"))
                    previous, queue, pointer = current, q, p
                chain = w.walk()
                complete = len(chain) == 13 and {p for p, gen in chain} == set(w.files("generations"))
                def detected(gen):
                    return any(a["event_key"] == h.acc(0, 1) and a["reason"] == "EVENT_DETECTED"
                               for a in gen["issuers"].get(A, {}).get("open", []))
                finding = sum(detected(gen) for p, gen in chain), detected(w.pg())
                return trace, sizes_ok, complete, finding
        self.assertEqual(f.observe_boundary("R6.1", f.outcome_of(lambda: row())),
                         ("RESULT", ([(21, 21, 9, 0, 0, False, False)] + [(0, 0, 0, 0, 0, True, True)] * 4 +
                                     [(0, 0, 3, 0, 0, True, False), (0, 0, 1, 0, 0, True, False)] +
                                     [(0, 0, 0, 0, 0, True, True)] * 3, True, True, (1, False))))

    def test_r6_4(self):
        def row():
            with h.World(3, 0) as w:
                control = w.run(1)
                if control[0] != "RESULT":
                    return control
                pointer = w.pointer()
                gen = deepcopy(w.pg())
                when = datetime(2026, 3, 2, 12, 30, tzinfo=timezone.utc)
                gen.update(generation_id=h.updater._new_generation_id(lambda: when),
                           parent={k: pointer[k] for k in ("generation_id", "sha256")},
                           created_at="2026-03-02T12:30:00Z")
                gen["issuers"][B]["index"]["settled"] = h.settled()
                h.overlay.publish_generation(w.state, gen, pointer)
                w.ghost(1)
                trace = []
                for hour in (13, 14):
                    o = w.run(instant=datetime(2026, 3, 2, hour, tzinfo=timezone.utc))
                    trace.append((o[0], w.summary()["issuers"].get(B) if o[0] == "RESULT" else o, w.req(), w.cur(),
                                  w.last(B)["reason"], len(w.pg()["issuers"][B]["index"]["settled"]), w.counts()[0]))
                return trace[0], trace[1]
        # G9a F3 fixed: the overflow refuses B alone (entry unchanged, nothing recorded) and every run completes.
        blocked = {"action": "BLOCKED", "reason": "SETTLED_OVERFLOW"}
        self.assertEqual(f.observe_boundary("R6.4", f.outcome_of(lambda: row())),
                         ("RESULT", (("RESULT", blocked, ((A, 2), (B, 1), (C, 2)), C, "EVENT_DETECTED", 256, 8),
                                     ("RESULT", blocked, ((A, 2), (B, 1), (C, 2)), C, "EVENT_DETECTED", 256, 8))))

    def test_r6_5(self):
        def row():
            with h.World(1, 0) as w:
                event = {"accession": h.acc(0, 1), "filed": "2026-03-01", "periodic": {}, "calendar": None,
                         "allocation_sources": [], "ir_item": None, "wire_item": None, "later_documents": []}
                attempt = {"event_key": h.acc(0, 1), "attempted_at": "2026-03-02T12:00:00Z",
                           "predecessor_sha256": h.overlay.record_sha256(w.records[A]), "event": event,
                           "captures": {}, "outcome": "VERIFIED", "reason": "VERIFIED", "detail": "",
                           "record_sha256": h.overlay.record_sha256(w.records[A]), "record": w.records[A], "decisions": []}
                entry = {"head": None, "sealed": 0, "open": [attempt],
                         "index": {"verified": [{"segment": None, "position": 0}], "truncated": False, "settled": h.settled()}}
                entries, readable, original = {A: entry}, {A}, deepcopy(entry)
                o = f.outcome_of(lambda: h.updater.reverify(w.root, {A: w.profs[A]}, {A: w.records[A]},
                                                            entries, readable, False, "2026-03-02T12:00:00Z"))
                return o, entries[A] == original, sorted(readable)
        # G9a F4 fixed: no raw StateError; the history is carried unchanged and leaves the readable set.
        self.assertEqual(f.observe_boundary("R6.5", f.outcome_of(lambda: row())),
                         ("RESULT", (("RESULT", None), True, [])))


if __name__ == "__main__":
    unittest.main()
