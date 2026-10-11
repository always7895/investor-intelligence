"""G2-33 caller tests: the fixed same-host PUBLIC stage reader and the publisher's --guidance-machine seam.

Claim (verification-matrix-03f G2-33; docs/REVENUE_GUIDANCE_AUTOUPDATE.md item 8): the publisher CLI checks the fixed
staged original bytes against independently supplied digests and the mutual binding, then puts BOTH original objects
into the one existing generic seal; it does not rerun the lazy ranking/model/path loader or restore a witness, and the
default CLI stays ordinary.

Two real callers run over the genuine frozen AUTO bundle (tests/fixtures/revenue-guidance-machine-auto-functional.json;
the NBIS AUTO bundle is the foreign pair). Both are read at test time, so a fixture regeneration needs no edit here:
* revenue_guidance_machine.read_staged_bundle (B lines 346-381) with the module attribute PUBLIC_STAGE_ROOT (line 40)
  redirected to a TemporaryDirectory for each call only;
* publish_sealed_snapshot.main (lines 1022-1053 and 1085-1089) through
  tests/fixtures/make_revenue_guidance_f06_replay.run_publisher (pinned clocks, socket guard, macro rotation input
  absent), and the script entry (lines 1145-1151) through runpy in this process.
tests/test_revenue_guidance_f06_replay.py already pins the sealed wire layout and seven CLI refusals (zero report or
binding digest, swapped digests, binding + b" ", binding absent, upper-case export name, all three operands without
--guidance-machine); those rows are not repeated here.

Links, reparse points and the lstat/fstat identity are tested as the code checks them: a second hard link is a real
link in the temporary directory; the reparse attribute (0x400), is_symlink() and the identity fields are test-side
fakes on a Path-subclass root (pathlib.with_segments keeps the class through .parents and "/") and on os.fstat for one
call, because a real symlink or junction would need a privilege or a process-token change. Stage-directory inventory,
the PowerShell exporter and native custody belong to G2-30/G2-31/G2-32 and G3: nothing here is native or live evidence.
"""
from __future__ import annotations

import contextlib
import hashlib
import inspect
import io
import json
import os
from pathlib import Path
import runpy
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "fixtures"))
sys.path.insert(0, str(ROOT / "scripts"))

import make_revenue_guidance_f06_replay as f06  # noqa: E402
import publish_sealed_snapshot as publisher  # noqa: E402
import revenue_guidance_machine as machine  # noqa: E402
import revenue_guidance_overlay as overlay  # noqa: E402

SCRIPT = ROOT / "scripts" / "publish_sealed_snapshot.py"
NBIS_FIXTURE = ROOT / "tests" / "fixtures" / "revenue-guidance-machine-nbis-auto-functional.json"
FIXED_STAGE_ROOT = machine.PUBLIC_STAGE_ROOT  # captured at import, before any test redirects it
# Literal on purpose: a constant mutation in the product must not move the expectation with it.
REPORT_KEY = "v213:bottleneck-top20:v3"
BINDING_KEY = "v213:revenue-guidance-binding:v1"
REPORT_CAP = 1900000
BINDING_CAP = 64000
EXPORT = "MACHINE_EXPORT_UNAVAILABLE"
INPUTS = "MACHINE_INPUTS_UNAVAILABLE"
ADMITTED = "ADMITTED"
REPARSE_POINT = 0x400  # FILE_ATTRIBUTE_REPARSE_POINT
TOKEN = "5a" * 16
OTHER_TOKEN = "c3" * 16
BODY = TOKEN + ".body.txt"
BINDING = TOKEN + ".binding.json"
# The 13 OBJECT_KEYS and the macro overview (tests/test_publish_sealed_snapshot_keyset.py EXPECTED_BODY_KEYS), then
# the two lazy guidance objects in sorted order (publish_sealed_snapshot.build_seal).
EAGER = ["v21:top20:latest", "scores:latest", "source_views:latest", "source_plan:latest", "reports:latest",
         "reports:morning:latest", "reports:evening:latest", "last_successful_pipeline_timestamp",
         "v212:top20-report:latest", "v213:top20-report:latest", "v213:source-federation:latest",
         "v213:source-independence:latest", "v213:activation-claim", "v213:macro-industry:latest"]
LAZY = [REPORT_KEY, BINDING_KEY]
# Builders the staged path must never reach: the lazy families, the v3 rebuild, the order-forecast model, the machine
# resolver/serializers and the effective-input path loader.
FORBIDDEN = (
    (publisher, ("lazy_identity_bodies", "lazy_market_bodies", "lazy_options_coverage_body", "lazy_price_bodies",
                 "lazy_bottleneck_v3_body", "captured_bottleneck_v3_body", "_with_order_forecast")),
    (machine, ("resolve_machine_inputs", "require_machine_inputs", "make_machine_envelope", "make_public_binding")),
    (overlay, ("load_effective_inputs",)),
)
# Native host/session/storage modules: the publisher must not import any of them (no witness restoration).
NATIVE_MODULES = ("revenue_guidance_host", "revenue_guidance_bootstrap", "revenue_guidance_provisioner",
                  "revenue_guidance_enroll", "revenue_guidance_storage", "revenue_guidance_windows")
OMIT = object()
_PLATFORM_PATH = type(Path())


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def fixture_bundle(path: Path) -> tuple[bytes, bytes]:
    document = json.loads(path.read_text(encoding="utf-8"))
    return document["report"].encode("utf-8"), document["binding"].encode("utf-8")


def rebind(binding: bytes, **changes) -> bytes:
    """The binding document with top-level fields replaced, compact UTF-8 (as PublicBundleByteBoundTests.rebound)."""
    document = json.loads(binding.decode("utf-8"))
    document.update(changes)
    return json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def stage(root: Path, report: bytes | None, binding: bytes | None, token: str = TOKEN) -> Path:
    """The same-owner PUBLIC export files read_staged_bundle opens (None: that member is absent)."""
    root.mkdir(parents=True, exist_ok=True)
    for suffix, raw in ((".body.txt", report), (".binding.json", binding)):
        if raw is not None:
            (root / (token + suffix)).write_bytes(raw)
    return root


def inventory(root: Path):
    """Names and bytes of everything directly in the stage (None for a directory entry or an absent stage)."""
    try:
        return {path.name: (path.read_bytes() if path.is_file() else None) for path in sorted(root.iterdir())}
    except (FileNotFoundError, NotADirectoryError):
        return None


def cli(base: Path, token, report_sha, binding_sha, *, machine_flag: bool = True) -> list[str]:
    """Publisher arguments in the MACHINE_CARRIED shape of f06.machine_argv; OMIT leaves an operand out."""
    argv = ["--guidance-machine"] if machine_flag else []
    for option, value in (("--guidance-public-token", token), ("--guidance-report-sha256", report_sha),
                          ("--guidance-binding-sha256", binding_sha)):
        if value is not OMIT:
            argv += [option, value]
    return argv + ["--top20-bundle", str(base / "absent-top20-bundle.json"), "--top20-insufficient",
                   f06.TOP20_REASON, "--snapshot-root", str(base / "snapshots")]


def sealed_run(base: Path, summary: dict) -> tuple[bytes, bytes]:
    run_dir = base / "snapshots" / summary["run_id"]
    return (run_dir / "objects.json").read_bytes(), (run_dir / "pointer.raw.json").read_bytes()


class Hex(str):
    """A str subclass: the reader requires exact str operands."""


class StatView:
    """A real stat result with chosen fields replaced; every other field is the real one."""

    def __init__(self, real, **override):
        self._real = real
        self._override = override

    def __getattr__(self, name):
        override = self.__dict__["_override"]
        if name in override:
            return override[name]
        return getattr(self.__dict__["_real"], name)


class HandleProxy:
    """The reader's real open handle (its real descriptor goes to os.fstat); read() can shorten the bytes it returns
    or run an action right after the read (an append through a second handle)."""

    def __init__(self, handle, *, shorten=False, after_read=None):
        self._handle, self._shorten, self._after_read = handle, shorten, after_read

    def fileno(self):
        return self._handle.fileno()

    def read(self, size=-1):
        data = self._handle.read(size)
        if self._after_read is not None:
            self._after_read()
        return data[:-1] if self._shorten else data

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self._handle.close()
        return False


class Forbidden:
    """Stands in for a builder the staged path must never call; counts and refuses every call."""

    def __init__(self, name):
        self.name, self.calls = name, 0

    def __call__(self, *args, **kwargs):
        self.calls += 1
        raise AssertionError(self.name + " ran on the staged-bundle path")


def hooked_root(root: Path, *, on_lstat=None, on_symlink=None, on_open=None) -> Path:
    """``root`` as a platform Path subclass. Every path the reader derives from it keeps the class (pathlib
    with_segments: .parents and "/"), so lstat/is_symlink/open consult the hooks; the real files stay underneath."""

    class HookedPath(_PLATFORM_PATH):
        def lstat(self):
            real = os.lstat(self)
            return real if on_lstat is None else on_lstat(self, real)

        def is_symlink(self):
            real = os.path.islink(self)
            return real if on_symlink is None else on_symlink(self, real)

        def open(self, *args, **kwargs):
            def real_open():
                return _PLATFORM_PATH.open(self, *args, **kwargs)
            return real_open() if on_open is None else on_open(self, real_open)

    return HookedPath(root)


def trap_root(root: Path) -> Path:
    """``root`` as a Path subclass whose every file-system query fails the test (AssertionError is not one of the
    reader's handled exceptions, so it propagates instead of becoming a typed refusal)."""

    class TrapPath(_PLATFORM_PATH):
        def stat(self, *args, **kwargs):
            raise AssertionError("the stage was touched for a refused token")

        def lstat(self):
            raise AssertionError("the stage was touched for a refused token")

        def is_symlink(self):
            raise AssertionError("the stage was touched for a refused token")

        def open(self, *args, **kwargs):
            raise AssertionError("the stage was touched for a refused token")

    return TrapPath(root)


@contextlib.contextmanager
def native_imports_refused():
    """A fresh import of a native host/storage module raises ImportError for the duration (sys.modules entry None);
    the previous entries are restored exactly afterwards."""
    absent = object()
    saved = {name: sys.modules.get(name, absent) for name in NATIVE_MODULES}
    for name in NATIVE_MODULES:
        sys.modules[name] = None
    try:
        yield
    finally:
        for name, value in saved.items():
            if value is absent:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = value


class StageCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report, cls.binding = f06.producer_bundle()
        cls.nbis_report, cls.nbis_binding = fixture_bundle(NBIS_FIXTURE)
        cls.digests = (sha(cls.report), sha(cls.binding))

    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="ii-g2-33-")
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.assertFalse(self.base.is_relative_to(ROOT.resolve()))
        self.root = self.base / "guidance-public-exports"
        self.enterContext(f06.offline())

    def tearDown(self):
        self.assertEqual(machine.PUBLIC_STAGE_ROOT, FIXED_STAGE_ROOT)  # every redirect was undone

    def read(self, root, token, report_sha, binding_sha):
        with mock.patch.object(machine, "PUBLIC_STAGE_ROOT", root):
            return machine.read_staged_bundle(token, report_sha, binding_sha)

    def outcome(self, root, token, report_sha, binding_sha):
        try:
            result = self.read(root, token, report_sha, binding_sha)
        except machine.MachinePublicationBlocked as error:
            return error.reason
        self.assertEqual(list(result), [REPORT_KEY, BINDING_KEY])
        return ADMITTED

    def text(self, report, binding):
        return {REPORT_KEY: report.decode("utf-8"), BINDING_KEY: binding.decode("utf-8")}


class StagedBundleReaderTests(StageCase):
    """read_staged_bundle called directly with the module's fixed root redirected to a temporary stage."""

    # B 40, 346-350: one fixed module location, three operands, the token is the only name selector and is checked
    # before any file-system query (the trap root fails the test on any query).
    def test_the_stage_location_is_fixed_and_a_token_is_checked_before_any_file_system_query(self):
        self.assertEqual(FIXED_STAGE_ROOT,
                         Path(machine.__file__).resolve().parents[1] / "state" / "guidance-public-exports")
        self.assertEqual(FIXED_STAGE_ROOT, ROOT / "state" / "guidance-public-exports")
        self.assertEqual(list(inspect.signature(machine.read_staged_bundle).parameters),
                         ["token", "expected_report_sha", "expected_binding_sha"])
        self.assertEqual((machine.REPORT_BYTES, machine.BINDING_BYTES, machine.REPORT_KEY, machine.BINDING_KEY),
                         (REPORT_CAP, BINDING_CAP, REPORT_KEY, BINDING_KEY))
        trap = trap_root(self.root)
        bad = {
            "none": None, "int": 0x5A, "bytes": TOKEN.encode("ascii"), "str_subclass": Hex(TOKEN),
            "path": Path(TOKEN), "empty": "", "31_hex": TOKEN[:-1], "33_hex": TOKEN + "0",
            "upper_case": TOKEN.upper(), "non_hex": "g" + TOKEN[1:], "trailing_newline": TOKEN + "\n",
            "leading_space": " " + TOKEN[1:], "parent_escape": "../" + TOKEN[3:], "drive": "C:/" + TOKEN[3:],
            "separator": TOKEN[:16] + "/" + TOKEN[17:], "fullwidth_digits": "\uff10" * 32,
            "nul": TOKEN[:-1] + "\x00", "with_suffix": TOKEN + ".body.txt",
        }
        for name, token in bad.items():
            with self.subTest(token=name):
                self.assertEqual(self.outcome(trap, token, *self.digests), EXPORT)
        # Control: the trap is live; a well-formed token reaches the file system and fails the test.
        with self.assertRaises(AssertionError):
            self.outcome(trap, TOKEN, *self.digests)

    # B 356-377: exactly the token's two members are read and returned as their original text; other stage members
    # (another token's pair, a manifest naming that pair's digests, a partial copy, a directory) are never consulted,
    # and nothing in the stage is created, changed or removed.
    def test_the_genuine_pair_is_returned_as_its_exact_original_text_and_the_stage_is_left_as_found(self):
        stage(self.root, self.report, self.binding)
        stage(self.root, self.nbis_report, self.nbis_binding, OTHER_TOKEN)
        nbis_digests = (sha(self.nbis_report), sha(self.nbis_binding))
        (self.root / (TOKEN + ".manifest.json")).write_bytes(json.dumps(
            {"report_sha256": nbis_digests[0], "binding_sha256": nbis_digests[1]}).encode("utf-8"))
        (self.root / (BODY + ".partial")).write_bytes(self.nbis_report[:100])
        (self.root / (TOKEN + ".d")).mkdir()
        found = inventory(self.root)
        first = self.read(self.root, TOKEN, *self.digests)
        self.assertEqual(first, self.text(self.report, self.binding))
        self.assertEqual(list(first), [REPORT_KEY, BINDING_KEY])
        second = self.read(self.root, TOKEN, *self.digests)
        self.assertEqual(second, first)
        self.assertIsNot(second, first)
        self.assertEqual(self.read(self.root, OTHER_TOKEN, *nbis_digests),
                         self.text(self.nbis_report, self.nbis_binding))
        # Digests are operands, never stage data: the manifest's digests neither select nor certify the TOKEN pair.
        self.assertEqual(self.outcome(self.root, TOKEN, *nbis_digests), INPUTS)
        self.assertEqual(inventory(self.root), found)

    # B 352-359 and 380-381: an absent stage or ancestor, an absent member, a member of the wrong type or a pair that
    # exists only under another token is an OSError/ValueError and ends as the fixed export reason.
    def test_absent_or_wrong_type_members_are_export_unavailable(self):
        report, binding = self.report, self.binding

        def directory_member(root, name):
            (root / name).mkdir()
            return root

        def file_instead_of_stage(path):
            path.write_bytes(report)
            return path

        cases = {
            "body_absent": lambda base: stage(base / "s", None, binding),
            "binding_absent": lambda base: stage(base / "s", report, None),
            "both_absent": lambda base: stage(base / "s", None, None),
            "pair_only_under_another_token": lambda base: stage(base / "s", report, binding, OTHER_TOKEN),
            "stage_absent": lambda base: base / "s",
            "stage_parent_absent": lambda base: base / "absent" / "s",
            "stage_is_a_file": lambda base: file_instead_of_stage(base / "s"),
            "body_is_a_directory": lambda base: directory_member(stage(base / "s", None, binding), BODY),
            "binding_is_a_directory": lambda base: directory_member(stage(base / "s", report, None), BINDING),
        }
        control = stage(self.base / "control" / "s", report, binding)
        self.assertEqual(self.outcome(control, TOKEN, *self.digests), ADMITTED)
        for name, build in cases.items():
            with self.subTest(case=name):
                case_base = self.base / name
                case_base.mkdir()
                root = build(case_base)
                found = inventory(root)
                self.assertEqual(self.outcome(root, TOKEN, *self.digests), EXPORT)
                self.assertEqual(inventory(root), found)

    # B 357-362 and 372-373: each member must be non-empty and within its own cap (body 1900000, binding 64000) by
    # lstat size BEFORE it is opened; exactly-at-cap members are read whole. The over-cap and empty rows carry
    # digests (and a re-bound binding) that would satisfy validate_public_bundle, so only the stage check refuses
    # them with the export reason (a widened cap would end as MACHINE_INPUTS_UNAVAILABLE instead).
    def test_member_byte_caps_are_inclusive_and_refused_before_the_member_is_opened(self):
        at_cap = self.report + b" " * (REPORT_CAP - len(self.report))
        over = at_cap + b" "
        binding_at_cap = self.binding + b" " * (BINDING_CAP - len(self.binding))
        self.assertEqual((len(at_cap), len(over), len(binding_at_cap)), (REPORT_CAP, REPORT_CAP + 1, BINDING_CAP))
        cases = {  # name: (body bytes, binding bytes, outcome, members opened)
            "genuine": (self.report, self.binding, ADMITTED, [BODY, BINDING]),
            "body_at_cap": (at_cap, rebind(self.binding, report_sha256=sha(at_cap)), ADMITTED, [BODY, BINDING]),
            "body_over_cap": (over, rebind(self.binding, report_sha256=sha(over)), EXPORT, []),
            "binding_at_cap": (self.report, binding_at_cap, ADMITTED, [BODY, BINDING]),
            "binding_over_cap": (self.report, binding_at_cap + b" ", EXPORT, [BODY]),
            "body_empty": (b"", rebind(self.binding, report_sha256=sha(b"")), EXPORT, []),
            "binding_empty": (self.report, b"", EXPORT, [BODY]),
        }
        for name, (body, binding, expected, expected_opened) in cases.items():
            with self.subTest(case=name):
                root = stage(self.base / name, body, binding)
                opened = []

                def on_open(path, real_open, opened=opened):
                    opened.append(path.name)
                    return real_open()

                got = self.outcome(hooked_root(root, on_open=on_open), TOKEN, sha(body), sha(binding))
                self.assertEqual((got, opened), (expected, expected_opened))
                if expected == ADMITTED:
                    self.assertEqual(self.read(root, TOKEN, sha(body), sha(binding)), self.text(body, binding))

    # B 376 -> 292-296: both expected digests must be exact lower-case SHA-256 str values of the staged bytes; the
    # validation reason (MACHINE_INPUTS_UNAVAILABLE) passes through the reader unchanged (378-379).
    def test_supplied_digests_must_be_exact_lowercase_sha256_of_the_staged_bytes(self):
        stage(self.root, self.report, self.binding)
        r, b = self.digests
        self.assertEqual(self.outcome(self.root, TOKEN, r, b), ADMITTED)
        cases = {
            "report_zero": ("0" * 64, b), "binding_zero": (r, "0" * 64), "swapped": (b, r), "both_report": (r, r),
            "report_upper": (r.upper(), b), "binding_upper": (r, b.upper()), "report_leading_space": (" " + r, b),
            "report_trailing_newline": (r + "\n", b), "report_63": (r[:-1], b), "report_65": (r + "0", b),
            "report_none": (None, b), "binding_none": (r, None), "report_bytes": (r.encode("ascii"), b),
            "report_str_subclass": (Hex(r), b), "binding_str_subclass": (r, Hex(b)),
            "report_of_the_text_with_bom": (sha(b"\xef\xbb\xbf" + self.report), b),
        }
        for name, (report_sha, binding_sha) in cases.items():
            with self.subTest(case=name):
                self.assertEqual(self.outcome(self.root, TOKEN, report_sha, binding_sha), INPUTS)

    # B 376 -> 297-343: with BOTH outer digests exact for the staged bytes, a tampered, foreign, re-pointed, edited,
    # duplicate-key or non-UTF-8 member still fails the report<->binding<->envelope binding.
    def test_tampered_or_foreign_members_fail_the_mutual_binding_under_exact_digests(self):
        report, binding = self.report, self.binding
        document = json.loads(binding.decode("utf-8"))
        symbol, pin = next((key, value) for key, value in document["issuers"].items()
                           if value["disposition"] != "CURATED")
        self.assertTrue(pin["identity"])
        field = sorted(pin["identity"])[0]
        edited_pin = {**pin, "identity": {**pin["identity"], field: "tampered-" + str(pin["identity"][field])}}
        edited = rebind(binding, issuers={**document["issuers"], symbol: edited_pin})
        self.assertTrue(binding.startswith(b"{"))
        duplicate = b'{"schema":"revenue-guidance-public-binding-v1",' + binding[1:]
        extended = report + b" "
        not_utf8 = b"\xff" + report
        not_utf8_binding = rebind(binding, report_sha256=sha(not_utf8))
        repointed = rebind(self.nbis_binding, report_sha256=sha(report))
        cases = {  # name: (body bytes, binding bytes, report digest, binding digest)
            "body_extended_under_the_original_digest": (extended, binding, sha(report), sha(binding)),
            "body_extended_under_a_rebound_digest": (extended, binding, sha(extended), sha(binding)),
            "foreign_binding": (report, self.nbis_binding, sha(report), sha(self.nbis_binding)),
            "foreign_binding_repointed_at_the_report": (report, repointed, sha(report), sha(repointed)),
            "foreign_report": (self.nbis_report, binding, sha(self.nbis_report), sha(binding)),
            "issuer_identity_edited": (report, edited, sha(report), sha(edited)),
            "duplicate_binding_key": (report, duplicate, sha(report), sha(duplicate)),
            "binding_not_utf8": (report, b"\xff" + binding, sha(report), sha(b"\xff" + binding)),
            "body_not_utf8": (not_utf8, not_utf8_binding, sha(not_utf8), sha(not_utf8_binding)),
        }
        control = stage(self.base / "control", report, binding)
        self.assertEqual(self.outcome(control, TOKEN, sha(report), sha(binding)), ADMITTED)
        for name, (body, bound, report_sha, binding_sha) in cases.items():
            with self.subTest(case=name):
                root = stage(self.base / name, body, bound)
                self.assertEqual(self.outcome(root, TOKEN, report_sha, binding_sha), INPUTS)

    # B 352-355 (every ancestor from the anchor down to the stage root) and 359-362 (each member): a symlink or the
    # reparse attribute anywhere on the chain, or a second link on a member, refuses before that member is opened.
    # Fakes on a hooked root (see module docstring); a real second link is the next test.
    def test_reparse_points_symlinks_and_second_links_are_refused_before_the_member_is_opened(self):
        stage(self.root, self.report, self.binding)
        chain = [*reversed(self.root.parents), self.root]
        self.assertEqual((str(chain[0]), chain[-1]), (self.root.anchor, self.root))

        def attempt(*, reparse=None, symlink=None, linked=None, viewed=None):
            examined, opened = [], []

            def on_lstat(path, real):
                examined.append(str(path))
                if str(path) == reparse:
                    return StatView(real, st_file_attributes=getattr(real, "st_file_attributes", 0) | REPARSE_POINT)
                if str(path) == linked:
                    return StatView(real, st_nlink=2)
                if str(path) == viewed:
                    return StatView(real)  # pass-through control for the fake
                return real

            def on_symlink(path, real):
                return True if str(path) == symlink else real

            def on_open(path, real_open):
                opened.append(path.name)
                return real_open()

            root = hooked_root(self.root, on_lstat=on_lstat, on_symlink=on_symlink, on_open=on_open)
            got = self.outcome(root, TOKEN, *self.digests)
            target = reparse or symlink or linked or viewed
            return got, opened, target is not None and target in examined

        self.assertEqual(attempt(), (ADMITTED, [BODY, BINDING], False))
        self.assertEqual(attempt(reparse=str(self.base / "unrelated")), (ADMITTED, [BODY, BINDING], False))
        for path in (chain[0], self.root, self.root / BODY, self.root / BINDING):
            with self.subTest(control=str(path)):
                self.assertEqual(attempt(viewed=str(path)), (ADMITTED, [BODY, BINDING], True))
        for index, ancestor in enumerate(chain):
            for kind in ("reparse", "symlink"):
                with self.subTest(ancestor=index, kind=kind):
                    self.assertEqual(attempt(**{kind: str(ancestor)}), (EXPORT, [], True))
        for member, opened_before in ((BODY, []), (BINDING, [BODY])):
            for kind in ("reparse", "symlink", "linked"):
                with self.subTest(member=member, kind=kind):
                    self.assertEqual(attempt(**{kind: str(self.root / member)}), (EXPORT, opened_before, True))

    # B 361: a real second hard link (created in the temporary directory, no privilege) refuses either member; once
    # the extra link is removed the same bytes are admitted again.
    def test_a_real_second_hard_link_is_refused_until_it_is_removed(self):
        stage(self.root, self.report, self.binding)
        for name in (BODY, BINDING):
            with self.subTest(member=name):
                member, extra = self.root / name, self.base / ("second-link-" + name)
                os.link(member, extra)
                try:
                    self.assertEqual(member.stat().st_nlink, 2)
                    self.assertEqual(self.outcome(self.root, TOKEN, *self.digests), EXPORT)
                finally:
                    os.unlink(extra)
                self.assertEqual(member.stat().st_nlink, 1)
                self.assertEqual(self.read(self.root, TOKEN, *self.digests), self.text(self.report, self.binding))

    # B 359 and 363-373: (ino, dev, size, mtime_ns) of the lstat before the open must equal the opened handle's
    # fstat before and after the read, and the bytes read must be exactly the lstat size. Each identity field is
    # changed alone on either side (fakes), then real races: a byte-identical replacement before the open, an
    # append before the open, an append through a second handle during the read, and a short read.
    def test_member_identity_must_hold_from_lstat_through_the_read(self):
        real_fstat = os.fstat

        def append_one_byte(path):
            with open(path, "ab") as extra:
                extra.write(b" ")

        def replace_with_identical_bytes(path):
            twin = self.base / "identical-twin"
            twin.write_bytes(path.read_bytes())
            os.replace(twin, path)

        def attempt(member=None, *, lstat_field=None, fstat_field=None, before_open=None, wrap=None):
            stage(self.root, self.report, self.binding)  # a fresh genuine pair for every row
            state = {"open": None, "fstat": 0, "fired": []}

            def changed(real, field):  # field "" keeps every value: the pass-through control for the fake itself
                return StatView(real, **({field: getattr(real, field) + 1} if field else {}))

            def on_lstat(path, real):
                if lstat_field is not None and path.name == member:
                    state["fired"].append("lstat")
                    return changed(real, lstat_field)
                return real

            def on_open(path, real_open):
                state["open"], state["fstat"] = path.name, 0
                plain = Path(os.fspath(path))
                if before_open is not None and path.name == member:
                    before_open(plain)
                    state["fired"].append("before_open")
                handle = real_open()
                if wrap is not None and path.name == member:
                    state["fired"].append("wrap")
                    return wrap(handle, plain)
                return handle

            def fstat(fd):
                result = real_fstat(fd)
                if fstat_field is not None and state["open"] == member:
                    state["fstat"] += 1
                    if state["fstat"] == 2:  # the reader's post-read fstat (B 366)
                        state["fired"].append("fstat")
                        return changed(result, fstat_field)
                return result

            root = hooked_root(self.root, on_lstat=on_lstat, on_open=on_open)
            with mock.patch.object(machine.os, "fstat", fstat):
                got = self.outcome(root, TOKEN, *self.digests)
            return got, state["fired"]

        def shorten(handle, path):
            return HandleProxy(handle, shorten=True)

        def grow(handle, path):
            return HandleProxy(handle, after_read=lambda: append_one_byte(path))

        self.assertEqual(attempt(), (ADMITTED, []))
        for member in (BODY, BINDING):
            # Controls: the stat view, the fstat fake and the handle proxy alone change nothing (a broken fake would
            # raise AttributeError, which the reader also maps to the export reason, so the rows below need these).
            with self.subTest(member=member, control="fakes_pass_through"):
                self.assertEqual(attempt(member, lstat_field=""), (ADMITTED, ["lstat"]))
                self.assertEqual(attempt(member, fstat_field=""), (ADMITTED, ["fstat"]))
                self.assertEqual(attempt(member, wrap=lambda handle, path: HandleProxy(handle)), (ADMITTED, ["wrap"]))
            for field in ("st_ino", "st_dev", "st_size", "st_mtime_ns"):
                with self.subTest(member=member, lstat=field):
                    self.assertEqual(attempt(member, lstat_field=field), (EXPORT, ["lstat"]))
                with self.subTest(member=member, fstat=field):
                    self.assertEqual(attempt(member, fstat_field=field), (EXPORT, ["fstat"]))
            with self.subTest(member=member, race="identical_replacement_before_open"):
                self.assertEqual(attempt(member, before_open=replace_with_identical_bytes), (EXPORT, ["before_open"]))
            with self.subTest(member=member, race="append_before_open"):
                self.assertEqual(attempt(member, before_open=append_one_byte), (EXPORT, ["before_open"]))
            with self.subTest(member=member, race="append_during_read"):
                self.assertEqual(attempt(member, wrap=grow), (EXPORT, ["wrap"]))
            with self.subTest(member=member, race="short_read"):
                self.assertEqual(attempt(member, wrap=shorten), (EXPORT, ["wrap"]))
        self.assertEqual(attempt(), (ADMITTED, []))


class PublisherStagedBundleCallerTests(StageCase):
    """publish_sealed_snapshot.main and its script entry over the same temporary stage."""

    @contextlib.contextmanager
    def guarded(self, *also_forbidden):
        """Forbidden builders, refused native imports and a spy that forwards to the real read_staged_bundle."""
        sentinels = []
        with contextlib.ExitStack() as stack:
            for module, names in (*FORBIDDEN, *also_forbidden):
                for name in names:
                    sentinel = Forbidden(f"{module.__name__}.{name}")
                    sentinels.append(sentinel)
                    stack.enter_context(mock.patch.object(module, name, sentinel))
            spy = mock.MagicMock(side_effect=machine.read_staged_bundle)
            stack.enter_context(mock.patch.object(machine, "read_staged_bundle", spy))
            stack.enter_context(native_imports_refused())
            yield spy
        self.assertEqual([sentinel.name for sentinel in sentinels if sentinel.calls], [])

    # PB 1047-1050, 1085-1089, 988-1006: the machine run seals exactly the ordinary run's eager bodies plus the two
    # staged originals as content-addressed blobs, in the same seal manifest extended by two rows; --bottleneck-v3
    # cannot displace them and nothing is rebuilt (forbidden builders, native imports refused); the stage is unchanged.
    def test_machine_cli_adds_only_the_two_original_objects_to_the_ordinary_generic_seal(self):
        stage(self.root, self.report, self.binding)
        stage(self.root, self.nbis_report, self.nbis_binding, OTHER_TOKEN)
        (self.root / (TOKEN + ".manifest.json")).write_bytes(json.dumps(
            {"report_sha256": sha(self.nbis_report), "binding_sha256": sha(self.nbis_binding)}).encode("utf-8"))
        found = inventory(self.root)
        r, b = self.digests
        plans = {
            "ordinary": (self.base / "ordinary", cli(self.base / "ordinary", OMIT, OMIT, OMIT, machine_flag=False)),
            "machine": (self.base / "machine", cli(self.base / "machine", TOKEN, r, b)),
            # --bottleneck-v3 names an absent path: the staged pair takes precedence and no v3 body is rebuilt.
            "machine_v3": (self.base / "machine-v3", cli(self.base / "machine-v3", TOKEN, r, b)
                           + ["--bottleneck-v3", str(self.base / "absent-v3.json")]),
        }
        runs = {}
        for name, (base, argv) in plans.items():
            with self.guarded() as spy:
                summary = f06.run_publisher(argv, self.root)
            runs[name] = (summary, list(spy.call_args_list), *sealed_run(base, summary))
        (o_sum, o_calls, o_raw, o_ptr), (m_sum, m_calls, m_raw, m_ptr), (v_sum, v_calls, v_raw, v_ptr) = (
            runs["ordinary"], runs["machine"], runs["machine_v3"])
        self.assertEqual((o_calls, m_calls, v_calls), ([], [mock.call(TOKEN, r, b)], [mock.call(TOKEN, r, b)]))
        run_id = o_sum["run_id"]
        self.assertEqual((m_sum["run_id"], v_sum["run_id"]), (run_id, run_id))
        self.assertEqual(("lazy_objects" in o_sum, m_sum.get("lazy_objects"), v_sum.get("lazy_objects")),
                         (False, 2, 2))
        o_obj, m_obj = json.loads(o_raw.decode("utf-8")), json.loads(m_raw.decode("utf-8"))
        seal_key = f"snapshot:{run_id}:v213:snapshot-seal:v1"
        blobs = {"blob:v1:" + r: self.report, "blob:v1:" + b: self.binding}
        self.assertEqual(set(m_obj) - set(o_obj), set(blobs))
        self.assertEqual(set(o_obj) - set(m_obj), set())
        self.assertEqual({key: value for key, value in m_obj.items() if key != seal_key and key not in blobs},
                         {key: value for key, value in o_obj.items() if key != seal_key})
        for key, raw in blobs.items():
            self.assertEqual(m_obj[key].encode("utf-8"), raw)
        o_seal, m_seal = json.loads(o_obj[seal_key]), json.loads(m_obj[seal_key])
        self.assertEqual((list(o_seal["objects"]), list(m_seal["objects"])), (EAGER, EAGER + LAZY))
        self.assertEqual(m_seal, {**o_seal, "objects": {
            **o_seal["objects"], REPORT_KEY: {"sha256": r, "utf8_bytes": len(self.report)},
            BINDING_KEY: {"sha256": b, "utf8_bytes": len(self.binding)}}})
        o_pointer, m_pointer = json.loads(o_ptr.decode("utf-8")), json.loads(m_ptr.decode("utf-8"))
        self.assertEqual((o_pointer["seal_sha256"], m_pointer["seal_sha256"]),
                         (sha(o_obj[seal_key].encode("utf-8")), sha(m_obj[seal_key].encode("utf-8"))))
        self.assertEqual({key: value for key, value in m_pointer.items() if key != "seal_sha256"},
                         {key: value for key, value in o_pointer.items() if key != "seal_sha256"})
        self.assertEqual((o_sum["seal_sha256"], m_sum["seal_sha256"]),
                         (o_pointer["seal_sha256"], m_pointer["seal_sha256"]))
        self.assertEqual((v_raw, v_ptr), (m_raw, m_ptr))  # byte-identical sealed run with --bottleneck-v3 present
        self.assertEqual(inventory(self.root), found)

    # PB 1048-1050: the publisher hands the reader its three operands unchanged, positionally and in the declared
    # order (token, report digest, binding digest). The real reader refuses a swapped pair before main() returns, so
    # here the spy answers the genuine text itself and the order is compared at the seam; the second row passes the
    # two digests swapped on the command line, which must reach the reader still swapped (no re-sorting or pairing).
    def test_machine_cli_passes_the_operands_to_the_reader_unchanged_and_in_declared_order(self):
        stage(self.root, self.report, self.binding)
        found = inventory(self.root)
        r, b = self.digests
        self.assertNotEqual(r, b)
        for name, (report_sha, binding_sha) in {"declared": (r, b), "swapped_on_the_command_line": (b, r)}.items():
            with self.subTest(case=name):
                base = self.base / name
                with self.guarded() as spy:
                    spy.side_effect = None
                    spy.return_value = self.text(self.report, self.binding)
                    summary = f06.run_publisher(cli(base, TOKEN, report_sha, binding_sha), self.root)
                self.assertEqual(spy.call_args_list, [mock.call(TOKEN, report_sha, binding_sha)])
                self.assertEqual(summary.get("lazy_objects"), 2)
        self.assertEqual(inventory(self.root), found)

    # PB 1045-1053: every refusal is the fixed typed reason raised before carry_state/build_bodies, so no run
    # directory exists and the stage is unchanged. Token problems end as the export reason, digest and binding
    # problems as the inputs reason; any single guidance operand without --guidance-machine is refused without
    # reading the stage (the three-operand row is in tests/test_revenue_guidance_f06_replay.py).
    def test_machine_cli_refusals_happen_before_any_build_or_run_directory(self):
        r, b = self.digests
        zero = "0" * 64
        extended = self.report + b" "
        repointed = rebind(self.nbis_binding, report_sha256=r)
        over = self.report + b" " * (REPORT_CAP + 1 - len(self.report))
        over_binding = rebind(self.binding, report_sha256=sha(over))
        manifest = json.dumps({"report_sha256": r, "binding_sha256": b}).encode("utf-8")
        genuine = (self.report, self.binding, TOKEN, None)
        cases = {  # name: ((body, binding, staged token, manifest), (token, report sha, binding sha, flag), reason)
            "token_omitted": (genuine, (OMIT, r, b, True), EXPORT),
            "token_empty": (genuine, ("", r, b, True), EXPORT),
            "token_31_hex": (genuine, (TOKEN[:-1], r, b, True), EXPORT),
            "token_parent_escape": (genuine, ("../" + TOKEN[3:], r, b, True), EXPORT),
            "report_digest_omitted": (genuine, (TOKEN, OMIT, b, True), INPUTS),
            "binding_digest_omitted": (genuine, (TOKEN, r, OMIT, True), INPUTS),
            "both_digests_omitted": (genuine, (TOKEN, OMIT, OMIT, True), INPUTS),
            "report_digest_upper_case": (genuine, (TOKEN, r.upper(), b, True), INPUTS),
            "stage_manifest_is_not_a_digest_source": ((self.report, self.binding, TOKEN, manifest),
                                                      (TOKEN, zero, zero, True), INPUTS),
            "body_extended_under_a_rebound_digest": ((extended, self.binding, TOKEN, None),
                                                     (TOKEN, sha(extended), b, True), INPUTS),
            "foreign_binding_under_its_own_digest": ((self.report, self.nbis_binding, TOKEN, None),
                                                     (TOKEN, r, sha(self.nbis_binding), True), INPUTS),
            "foreign_binding_repointed_at_the_report": ((self.report, repointed, TOKEN, None),
                                                        (TOKEN, r, sha(repointed), True), INPUTS),
            "body_absent": ((None, self.binding, TOKEN, None), (TOKEN, r, b, True), EXPORT),
            "pair_only_under_another_token": ((self.report, self.binding, OTHER_TOKEN, None),
                                              (TOKEN, r, b, True), EXPORT),
            "body_over_cap": ((over, over_binding, TOKEN, None), (TOKEN, sha(over), sha(over_binding), True), EXPORT),
            "body_empty": ((b"", self.binding, TOKEN, None), (TOKEN, sha(b""), b, True), EXPORT),
            "token_alone_without_machine": (genuine, (TOKEN, OMIT, OMIT, False), INPUTS),
            "report_digest_alone_without_machine": (genuine, (OMIT, r, OMIT, False), INPUTS),
            "binding_digest_alone_without_machine": (genuine, (OMIT, OMIT, b, False), INPUTS),
        }
        for name, ((body, binding, staged_token, extra), (token, report_sha, binding_sha, flag), reason) in (
                cases.items()):
            with self.subTest(case=name):
                base = self.base / name
                root = stage(base / "guidance-public-exports", body, binding, staged_token)
                if extra is not None:
                    (root / (TOKEN + ".manifest.json")).write_bytes(extra)
                found = inventory(root)
                with self.guarded((publisher, ("carry_state", "build_bodies"))) as spy:
                    with self.assertRaises(machine.MachinePublicationBlocked) as raised:
                        f06.run_publisher(cli(base, token, report_sha, binding_sha, machine_flag=flag), root)
                self.assertEqual((raised.exception.reason, spy.call_count), (reason, 1 if flag else 0))
                self.assertFalse((base / "snapshots").exists())
                self.assertEqual(inventory(root), found)

    # PB 1145-1151: the script entry prints only the fixed reason on stdout and exits 2; no traceback, stage path or
    # token reaches stdout or stderr, and no run directory is written (runpy runs the file as __main__ in-process).
    def test_script_entry_prints_only_the_fixed_reason_and_exits_2(self):
        stage(self.root, self.report, self.binding)
        r, b = self.digests
        for name, (token, report_sha, reason) in {"digest_mismatch": (TOKEN, "0" * 64, INPUTS),
                                                   "export_absent": (OTHER_TOKEN, r, EXPORT)}.items():
            with self.subTest(case=name):
                base = self.base / name
                out, err = io.StringIO(), io.StringIO()
                saved_path = list(sys.path)
                try:
                    with mock.patch.object(machine, "PUBLIC_STAGE_ROOT", self.root), \
                            mock.patch.object(sys, "argv", [str(SCRIPT), *cli(base, token, report_sha, b)]), \
                            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
                            self.assertRaises(SystemExit) as raised:
                        runpy.run_path(str(SCRIPT), run_name="__main__")
                finally:
                    sys.path[:] = saved_path
                self.assertEqual((raised.exception.code, out.getvalue()), (2, reason + "\n"))
                for text in (str(self.base), TOKEN, OTHER_TOKEN, "Traceback"):
                    self.assertNotIn(text, err.getvalue())
                self.assertFalse((base / "snapshots").exists())


if __name__ == "__main__":
    unittest.main()
