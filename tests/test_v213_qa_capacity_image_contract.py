"""V11-01 image contract step-1 positive/structural tests; pure in-memory (no PE exec/ctypes/native/compiler/network/filesystem); raw_pe+expected adapted from the v11-01 audit fixture (pure parts, never run)."""
import dataclasses
import hashlib
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.v213_qa_capacity_image_contract import (  # noqa: E402
    AUTHORIZES_EXECUTION, ContractError, OperationClass, Phase,
    ImagePlan, ComparisonResult, ActorRole, ActorRequirement,
    RangeCategory, actor_requirements, operation_classification,
    parse_raw_pe, compare_image, NATIVE_OPERATIONS)

PREFERRED = 0x140000000


def raw_pe(dynamic=False):
    raw = bytearray(5120)
    raw[:2] = b'MZ'
    struct.pack_into('<I', raw, 0x3C, 0x80)
    raw[0x80:0x84] = b'PE\0\0'
    struct.pack_into('<HHIIIHH', raw, 0x84, 0x8664, 2, 0, 0, 0, 240, 0x22)
    o = 0x98
    struct.pack_into('<H', raw, o, 0x20B)
    struct.pack_into('<III', raw, o + 4, 512, 512, 0)
    struct.pack_into('<IIQ', raw, o + 16, 0x1000, 0x1000, PREFERRED)
    struct.pack_into('<IIHHHHHH', raw, o + 32, 4096, 512, 6, 0, 0, 0, 6, 0)
    struct.pack_into('<II', raw, o + 56, 0x3000, 0x1000)
    struct.pack_into('<HH', raw, o + 68, 3, 0x100 | (0x40 if dynamic else 0))
    struct.pack_into('<QQQQ', raw, o + 72, 0x100000, 0x1000, 0x100000, 0x1000)
    struct.pack_into('<II', raw, o + 104, 0, 16)
    struct.pack_into('<II', raw, o + 112 + 5 * 8, 0x2000, 12)
    for at, name, va, rp, chars in ((o + 240, b'.text', 0x1000, 0x1000, 0x60000020),
                                    (o + 280, b'.reloc', 0x2000, 0x1200, 0x40000040)):
        struct.pack_into('<8sIIIIIIHHI', raw, at, name, 0x1000, va, 512, rp, 0, 0, 0, 0, chars)
    raw[0x1000:0x1002] = b'\xeb\xfe'
    struct.pack_into('<Q', raw, 0x1008, 0x140001234)
    struct.pack_into('<IIHH', raw, 0x1200, 0x1000, 12, 0xA008, 0)
    return bytes(raw)


def expected(raw, base, relocated):
    b = bytearray(0x3000)
    b[:0x1200] = raw[:0x1200]
    b[0x2000:0x2200] = raw[0x1200:0x1400]
    if relocated:
        struct.pack_into('<Q', b, 0x1008, (0x140001234 + base - PREFERRED) & ((1 << 64) - 1))
    return bytes(b)


def raw_pe_multi():
    raw = bytearray(raw_pe())
    struct.pack_into('<II', raw, 0x98 + 112 + 5 * 8, 0x2000, 16)
    struct.pack_into('<IIHHHH', raw, 0x1200, 0x1000, 16, 0xA008, 0xA018, 0, 0)
    struct.pack_into('<Q', raw, 0x1018, 0x140001234)
    return bytes(raw)


# ---- negative-case helpers + data (source frozen; offsets from the v11-01 fixture) ----
# COFF 0x84, characteristics 0x96, optional 0x98, section table 0x188, relocation RAW 0x1200

def _mut_fmt(raw, fmt, off, vals):
    r = bytearray(raw)
    struct.pack_into(fmt, r, off, *vals)
    return bytes(r)

def _mut_bytes(raw, off, data):
    r = bytearray(raw)
    r[off:off + len(data)] = data
    return bytes(r)

def _build_mem(raw, base, relocated):
    return bytearray(expected(raw, base, relocated))

def _expect_contract(fn):
    try:
        fn()
    except ContractError:
        return
    raise AssertionError("expected ContractError, none raised")


class TestV213ImageContractStep1(unittest.TestCase):
    def test_preferred_and_zero_delta_relocated_pass(self):
        raw = raw_pe()
        for phase in (Phase.PREFERRED_UNRELOCATED.value, Phase.RELOCATED.value):
            r = compare_image(raw, expected(raw, PREFERRED, False), PREFERRED, phase)
            self.assertEqual((r.raw_sha256, r.preferred_base, r.actual_base, r.phase),
                             (hashlib.sha256(raw).hexdigest(), PREFERRED, PREFERRED, phase))
            self.assertEqual((r.match, r.counterexample), (True, False))

    def test_relocated_positive_delta(self):
        raw = raw_pe()
        base = PREFERRED + 0x100000
        r = compare_image(raw, expected(raw, base, True), base, Phase.RELOCATED.value)
        self.assertEqual((r.match, r.counterexample), (True, False))

    def test_relocated_negative_delta(self):
        raw = raw_pe()
        base = PREFERRED - 0x100000
        r = compare_image(raw, expected(raw, base, True), base, Phase.RELOCATED.value)
        self.assertEqual((r.match, r.counterexample), (True, False))

    def test_multiple_dir64_targets_same_section(self):
        raw = raw_pe_multi()
        plan = parse_raw_pe(raw)
        self.assertEqual([x.offset for x in plan.ranges if x.category is RangeCategory.RELOCATION_NORMALIZED],
                         [0x1008, 0x1018])
        b = bytearray(expected(raw, PREFERRED + 0x100000, True))
        struct.pack_into('<Q', b, 0x1018, PREFERRED + 0x1234 + 0x100000)
        r = compare_image(raw, bytes(b), PREFERRED + 0x100000, Phase.RELOCATED.value)
        self.assertEqual((r.match, r.counterexample), (True, False))

    def test_whole_raw_hash_and_complete_contiguous_coverage(self):
        raw = raw_pe()
        plan = parse_raw_pe(raw)
        self.assertEqual(plan.raw_sha256, hashlib.sha256(raw).hexdigest())
        self.assertEqual((plan.size_of_image, plan.preferred_base), (0x3000, PREFERRED))
        pos = 0
        for rg in plan.ranges:
            self.assertEqual((rg.offset, rg.length > 0), (pos, True))
            pos = rg.offset + rg.length
        self.assertEqual(pos, plan.size_of_image)
        self.assertEqual({RangeCategory.IMMUTABLE_EXPECTED, RangeCategory.RELOCATION_NORMALIZED,
                          RangeCategory.ZERO_FILL_EXPECTED}, {rg.category for rg in plan.ranges})

    def test_plan_result_flags_false_and_nonoverridable(self):
        plan = ImagePlan("s", 0x3000, PREFERRED, ())
        r = ComparisonResult("s", PREFERRED, PREFERRED, "PREFERRED_UNRELOCATED", True, False)
        names = ("authorizes_execution", "image_bytes_attested", "workspace_attested", "hard_io_timeout_proven")
        for obj, args in ((plan, (plan.raw_sha256, plan.size_of_image, plan.preferred_base, plan.ranges)),
                          (r, (r.raw_sha256, r.preferred_base, r.actual_base, r.phase, True, False))):
            self.assertTrue(all(not getattr(obj, n) for n in names))
            with self.assertRaises(TypeError):
                type(obj)(*args, authorizes_execution=True)
        self.assertFalse(AUTHORIZES_EXECUTION)

    def test_typed_actor_requirements_and_default_deny_native(self):
        for bad in (None, "PI", 1):
            with self.assertRaises(ContractError):
                actor_requirements(bad)
        for role in (ActorRole.PI, ActorRole.TABBY, ActorRole.RUNNER):
            reqs = actor_requirements(role)
            self.assertTrue(all(isinstance(x, ActorRequirement) and x.role is role for x in reqs))
        self.assertIs(operation_classification("parse_raw_pe"), OperationClass.INTRINSICALLY_BOUNDED)
        for name in ("native_open", "process_write", "unknown_op"):
            self.assertIs(operation_classification(name), OperationClass.NOT_ACCEPTABLE)
        with self.assertRaises(ContractError):
            operation_classification(65)

    # ---- step2 negative cases: data-driven factory (setattr before unittest.main) ----
    def _neg_parse(self, fmt, off, vals):
        raw = _mut_fmt(raw_pe(), fmt, off, vals)
        _expect_contract(lambda: parse_raw_pe(raw))

    def test_negative_mz(self):
        self._neg_parse("<2s", 0, (b"QZ",))

    def test_negative_pe_sig(self):
        self._neg_parse("<4s", 0x80, (b"XX\x00\x00",))

    def test_negative_machine(self):
        self._neg_parse("<H", 0x84, (0x014C,))

    def test_negative_sections0(self):
        self._neg_parse("<H", 0x86, (0,))

    def test_negative_sections97(self):
        self._neg_parse("<H", 0x86, (97,))

    def test_negative_optsize(self):
        self._neg_parse("<H", 0x94, (20,))

    def test_negative_magic(self):
        self._neg_parse("<H", 0x98, (0x10B,))

    def test_negative_dirs_count(self):
        self._neg_parse("<I", 0x98 + 108, (15,))

    def test_negative_base_align(self):
        self._neg_parse("<Q", 0x98 + 24, (PREFERRED + 1,))

    def test_negative_size_of_image(self):
        self._neg_parse("<I", 0x98 + 56, (64 * 1024 * 1024 + 1,))

    def test_negative_headers_align(self):
        self._neg_parse("<I", 0x98 + 60, (0x1004,))

    def test_negative_sec_align(self):
        self._neg_parse("<I", 0x98 + 32, (0x2000,))

    def test_negative_file_align(self):
        self._neg_parse("<I", 0x98 + 36, (0x400,))

    def test_negative_headers_extent(self):
        _expect_contract(lambda: parse_raw_pe(raw_pe()[:0x1C8]))

    def test_negative_raw_extent(self):
        raw = _mut_fmt(raw_pe(), '<I', 0x188 + 20, (0x100000,))
        with self.assertRaisesRegex(ContractError, 'initialized raw extent invalid'):
            parse_raw_pe(raw)

    def test_negative_virtual0(self):
        raw = _mut_fmt(raw_pe(), '<I', 0x188 + 8, (0,))
        with self.assertRaisesRegex(ContractError, 'virtual size invalid'):
            parse_raw_pe(raw)

    def test_negative_raw_gt_virtual(self):
        raw = _mut_fmt(raw_pe(), '<I', 0x188 + 16, (0x1200,))
        with self.assertRaisesRegex(ContractError, 'virtual size invalid'):
            parse_raw_pe(raw)

    def test_negative_rva_gap(self):
        raw = _mut_fmt(raw_pe(), '<I', 0x188 + 40 + 12, (0x3000,))
        with self.assertRaisesRegex(ContractError, 'section RVA not contiguous'):
            parse_raw_pe(raw)

    def test_negative_raw_overlap(self):
        raw = _mut_fmt(raw_pe(), '<I', 0x188 + 20, (0x1200,))
        with self.assertRaisesRegex(ContractError, 'initialized raw extents overlap'):
            parse_raw_pe(raw)

    def test_negative_entry_zero_tail(self):
        self._neg_parse("<I", 0x98 + 16, (0x1400,))

    def test_negative_overlay(self):
        _expect_contract(lambda: parse_raw_pe(raw_pe() + b"\x00" * 0x200))

    def test_negative_import_dir(self):
        raw = _mut_fmt(raw_pe(), '<II', 0x98 + 112 + 1 * 8, (0x1000, 16))
        with self.assertRaisesRegex(ContractError, 'data directory 1 must be zeroed'):
            parse_raw_pe(raw)

    def test_negative_iat_dir(self):
        raw = _mut_fmt(raw_pe(), '<II', 0x98 + 112 + 12 * 8, (0x1000, 16))
        with self.assertRaisesRegex(ContractError, 'data directory 12 must be zeroed'):
            parse_raw_pe(raw)

    def test_negative_clr_dir(self):
        raw = _mut_fmt(raw_pe(), '<II', 0x98 + 112 + 14 * 8, (0x1000, 16))
        with self.assertRaisesRegex(ContractError, 'data directory 14 must be zeroed'):
            parse_raw_pe(raw)

    def test_negative_tls_dir(self):
        raw = _mut_fmt(raw_pe(), '<II', 0x98 + 112 + 9 * 8, (0x1000, 16))
        with self.assertRaisesRegex(ContractError, 'data directory 9 must be zeroed'):
            parse_raw_pe(raw)

    def test_negative_loadconfig_dir(self):
        raw = _mut_fmt(raw_pe(), '<II', 0x98 + 112 + 10 * 8, (0x1000, 16))
        with self.assertRaisesRegex(ContractError, 'data directory 10 must be zeroed'):
            parse_raw_pe(raw)

    def test_negative_relocs_stripped(self):
        self._neg_parse("<H", 0x96, (0x23,))

    def test_negative_sec_discardable(self):
        raw = _mut_fmt(raw_pe(), '<I', 0x188 + 36, (0x62000020,))
        with self.assertRaisesRegex(ContractError, 'unknown or discardable'):
            parse_raw_pe(raw)

    def test_negative_sec_bss_with_raw(self):
        raw = _mut_fmt(raw_pe(), '<I', 0x188 + 36, (0x40000080,))
        with self.assertRaisesRegex(ContractError, 'content kind inconsistent'):
            parse_raw_pe(raw)

    def test_negative_sec_wx(self):
        raw = _mut_fmt(raw_pe(), '<I', 0x188 + 36, (0xE0000020,))
        with self.assertRaisesRegex(ContractError, 'WRITE\\+EXECUTE'):
            parse_raw_pe(raw)

    def test_negative_sec_unknownbit(self):
        raw = _mut_fmt(raw_pe(), '<I', 0x188 + 36, (0x60000220,))
        with self.assertRaisesRegex(ContractError, 'unknown or discardable'):
            parse_raw_pe(raw)

    def test_negative_reloc_bad_block(self):
        self._neg_parse("<I", 0x1204, (6,))

    def test_negative_reloc_bad_type(self):
        raw = _mut_fmt(raw_pe(), '<H', 0x1208, (0x3008,))
        with self.assertRaisesRegex(ContractError, 'only DIR64 relocation type supported'):
            parse_raw_pe(raw)

    def test_negative_reloc_dup_target(self):
        raw = _mut_fmt(raw_pe(), '<H', 0x120A, (0xA008,))
        with self.assertRaisesRegex(ContractError, 'duplicate relocation target'):
            parse_raw_pe(raw)

    def test_negative_reloc_overlap_target(self):
        raw = _mut_fmt(raw_pe(), '<H', 0x120A, (0xA00C,))
        with self.assertRaisesRegex(ContractError, 'overlapping relocation targets'):
            parse_raw_pe(raw)

    def test_negative_reloc_oob(self):
        self._neg_parse("<I", 0x98 + 112 + 5 * 8 + 4, (0x1000,))

    def test_negative_reloc_metadata_target(self):
        raw = _mut_fmt(raw_pe(), '<I', 0x1200, (0x2000,))
        raw = _mut_fmt(raw, '<H', 0x1208, (0xA000,))
        with self.assertRaisesRegex(ContractError, 'relocation target overlaps metadata'):
            parse_raw_pe(raw)

    def test_negative_reloc_zerofill_target(self):
        raw = _mut_fmt(raw_pe(), '<H', 0x1208, (0xA300,))
        with self.assertRaisesRegex(ContractError, 'relocation target not in initialized section'):
            parse_raw_pe(raw)

    def _neg_mem(self, off, data):
        raw = raw_pe()
        mem = _build_mem(raw, PREFERRED, False)
        mem[off:off + len(data)] = data
        _expect_contract(lambda: compare_image(raw, bytes(mem), PREFERRED, Phase.PREFERRED_UNRELOCATED.value))

    def test_negative_mem_header(self):
        self._neg_mem(0x08, b"\xFF")

    def test_negative_mem_text(self):
        self._neg_mem(0x1000, b"\xFF")

    def test_negative_mem_zero(self):
        self._neg_mem(0x1400, b"\xFF")

    def test_negative_mem_reloc(self):
        self._neg_mem(0x2004, b"\xFF")

    def test_negative_mem_writable(self):
        raw = _mut_fmt(raw_pe(), '<I', 0x188 + 40 + 36, (0xC0000040,))
        mem = bytearray(expected(raw, PREFERRED, False))
        self.assertTrue(compare_image(raw, bytes(mem), PREFERRED, 'PREFERRED_UNRELOCATED').match)
        mem[0x2100] ^= 1
        with self.assertRaisesRegex(ContractError, 'observed image mismatch'):
            compare_image(raw, bytes(mem), PREFERRED, 'PREFERRED_UNRELOCATED')

    def test_negative_phase_preferred_nonpreferred(self):
        raw = raw_pe()
        base = PREFERRED + 0x100000
        _expect_contract(lambda: compare_image(raw, expected(raw, base, True), base, Phase.PREFERRED_UNRELOCATED.value))

    def test_negative_base_bool(self):
        raw = raw_pe()
        _expect_contract(lambda: compare_image(raw, expected(raw, PREFERRED, False), True, Phase.PREFERRED_UNRELOCATED.value))

    def test_negative_base_float(self):
        raw = raw_pe()
        _expect_contract(lambda: compare_image(raw, expected(raw, PREFERRED, False), float(PREFERRED), Phase.PREFERRED_UNRELOCATED.value))

    def test_negative_observed_bytearray(self):
        raw = raw_pe()
        _expect_contract(lambda: compare_image(raw, bytearray(expected(raw, PREFERRED, False)), PREFERRED, Phase.PREFERRED_UNRELOCATED.value))

    def test_negative_phase_int(self):
        raw = raw_pe()
        _expect_contract(lambda: compare_image(raw, expected(raw, PREFERRED, False), PREFERRED, 1))

    def test_negative_phase_str_subclass(self):
        raw = raw_pe()
        class _S(str):
            pass
        _expect_contract(lambda: compare_image(raw, expected(raw, PREFERRED, False), PREFERRED, _S("PREFERRED_UNRELOCATED")))

    def test_negative_imagebase_header_mutated(self):
        raw = raw_pe()
        base = PREFERRED + 0x100000
        mem = _build_mem(raw, base, True)
        struct.pack_into("<Q", mem, 0xB0, base)
        _expect_contract(lambda: compare_image(raw, bytes(mem), base, Phase.RELOCATED.value))

    def test_negative_native_inventory_default_deny(self):
        for name in NATIVE_OPERATIONS:
            self.assertIs(operation_classification(name), OperationClass.NOT_ACCEPTABLE)
        plan = ImagePlan('s', 0x3000, PREFERRED, ())
        with self.assertRaises(ValueError):
            dataclasses.replace(plan, authorizes_execution=True)


    def test_negative_raw_cap(self):
        with self.assertRaisesRegex(ContractError, 'raw length out of bounds'):
            parse_raw_pe(b'x' * (16 * 1024 * 1024 + 1))

    def test_negative_observed_short(self):
        raw = raw_pe()
        with self.assertRaisesRegex(ContractError, 'observed length'):
            compare_image(raw, expected(raw, PREFERRED, False)[:-1], PREFERRED, 'PREFERRED_UNRELOCATED')

    def test_negative_raw_bytes_subclass(self):
        class Bytes(bytes):
            pass
        with self.assertRaisesRegex(ContractError, 'raw must be builtin bytes'):
            parse_raw_pe(Bytes(raw_pe()))

    def test_negative_base_int_subclass(self):
        class Int(int):
            pass
        raw = raw_pe()
        with self.assertRaisesRegex(ContractError, 'actual base must be builtin int'):
            compare_image(raw, expected(raw, PREFERRED, False), Int(PREFERRED), 'PREFERRED_UNRELOCATED')


if __name__ == "__main__":
    unittest.main()