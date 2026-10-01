"""Pure strict synthetic image contract (V11-01): RAW-derived range comparison only.

Limitations: not actual loaded-memory attestation; loader-mutated ImageBase header is
intentionally NOT normalized (no mutable masks), so dynamic observed memory rejects."""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
import struct
import hashlib

AUTHORIZES_EXECUTION = False
IMAGE_BYTES_ATTESTED = False
WORKSPACE_ATTESTED = False
HARD_IO_TIMEOUT_PROVEN = False

# Architecture-matrix native API inventory. Membership is NOT permission:
# every listed operation remains NOT_ACCEPTABLE under the strict profile.
NATIVE_OPERATIONS = frozenset({
    "CreateFileW", "NtQueryInformationFile", "WriteFile", "ReadFile",
    "FlushFileBuffers", "CloseHandle",
    "CreateProcessW", "CreateJobObjectW", "NtQueryInformationProcess",
    "TerminateJobObject",
    "GetThreadContext", "ReadProcessMemory", "VirtualQueryEx",
    "NtCreateThreadEx", "NtGdiQueryInfo",
    "CreatePipeW", "CancelSynchronousIo", "ResumeThread",
    "MoveFileExW", "ReleaseFileLease", "ResumePi",
})

SYNTHETIC_RAW_DERIVED_RANGE_COMPARISON_ONLY = (
    "SYNTHETIC_RAW_DERIVED_RANGE_COMPARISON_ONLY: not actual loaded-memory attestation")


class ContractError(ValueError):
    """Explicit contract/profile failure; never a silent pass."""


class RangeCategory(Enum):
    IMMUTABLE_EXPECTED = "IMMUTABLE_EXPECTED"
    ZERO_FILL_EXPECTED = "ZERO_FILL_EXPECTED"
    RELOCATION_NORMALIZED = "RELOCATION_NORMALIZED"
    LOADER_MUTABLE = "LOADER_MUTABLE"                # defined, never accepted
    UNVERIFIABLE_FAIL_CLOSED = "UNVERIFIABLE_FAIL_CLOSED"  # defined, never accepted


class Phase(Enum):
    PREFERRED_UNRELOCATED = "PREFERRED_UNRELOCATED"
    RELOCATED = "RELOCATED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ByteRange:
    offset: int
    length: int
    category: RangeCategory


@dataclass(frozen=True)
class ImagePlan:
    raw_sha256: str
    size_of_image: int
    preferred_base: int
    ranges: tuple[ByteRange, ...]
    authorizes_execution: bool = field(default=False, init=False)
    image_bytes_attested: bool = field(default=False, init=False)
    workspace_attested: bool = field(default=False, init=False)
    hard_io_timeout_proven: bool = field(default=False, init=False)


@dataclass(frozen=True)
class ComparisonResult:
    raw_sha256: str
    preferred_base: int
    actual_base: int
    phase: str
    match: bool
    counterexample: bool
    scope: str = SYNTHETIC_RAW_DERIVED_RANGE_COMPARISON_ONLY
    authorizes_execution: bool = field(default=False, init=False)
    image_bytes_attested: bool = field(default=False, init=False)
    workspace_attested: bool = field(default=False, init=False)
    hard_io_timeout_proven: bool = field(default=False, init=False)


class ActorRole(Enum):
    PI = "PI"
    TABBY = "TABBY"
    RUNNER = "RUNNER"


@dataclass(frozen=True)
class ActorRequirement:
    role: ActorRole
    predicate: str


_ACTOR_REQUIREMENTS = {
    ActorRole.PI: (
        ActorRequirement(ActorRole.PI, "retained original process PID/birth/path observation"),
        ActorRequirement(ActorRole.PI, "exit observation"),
        ActorRequirement(ActorRole.PI, "foreign clients; no historical bytes"),
    ),
    ActorRole.TABBY: (
        ActorRequirement(ActorRole.TABBY, "retained listener/service"),
        ActorRequirement(ActorRole.TABBY, "GPU UUID"),
        ActorRequirement(ActorRole.TABBY, "exact served+active model/context"),
        ActorRequirement(ActorRole.TABBY, "foreign clients; never contained"),
    ),
    ActorRole.RUNNER: (
        ActorRequirement(ActorRole.RUNNER, "fresh artifact RAW+FileId+root/ancestor retained objects"),
        ActorRequirement(ActorRole.RUNNER, "original returned process/thread custody"),
        ActorRequirement(ActorRole.RUNNER, "creation-time JOB_LIST; initial suspension"),
        ActorRequirement(ActorRole.RUNNER, "pre-resume range proof; exactly one resume"),
    ),
}
_ACTOR_REQUIREMENTS = MappingProxyType(_ACTOR_REQUIREMENTS)


def actor_requirements(role) -> tuple[ActorRequirement, ...]:
    if not isinstance(role, ActorRole):
        raise ContractError("actor role must be an ActorRole enum member")
    return _ACTOR_REQUIREMENTS[role]


class OperationClass(Enum):
    INTRINSICALLY_BOUNDED = "INTRINSICALLY_BOUNDED"   # pure parse/hash/range work only
    NOT_ACCEPTABLE = "NOT_ACCEPTABLE"                 # all native + unknown, currently


_BOUNDED_OPS = frozenset({
    "parse_raw_pe", "canonical_sha256", "range_arithmetic", "comparison_partition"})


def operation_classification(name) -> OperationClass:
    if type(name) is not str:
        raise ContractError("operation name must be a builtin str")
    if name in _BOUNDED_OPS:
        return OperationClass.INTRINSICALLY_BOUNDED
    return OperationClass.NOT_ACCEPTABLE


def _parse_headers(raw: bytes) -> dict:
    """Strict pure header parse; malformed bytes -> ContractError, never struct.error."""
    if type(raw) is not bytes:
        raise ContractError("raw must be builtin bytes")
    n = len(raw)
    if n > 16 * 1024 * 1024 or n < 64:
        raise ContractError("raw length out of bounds")

    def _u(off: int, fmt: str) -> tuple:
        try:
            return struct.unpack_from(fmt, raw, off)
        except struct.error as exc:
            raise ContractError(f"header extent unsafe at {off}: {exc}")

    def _ok(cond: bool, msg: str) -> None:
        if not cond:
            raise ContractError(msg)

    _ok(raw[0:2] == b"MZ", "missing MZ")
    (e_lfanew,) = _u(0x3C, "<I")
    _ok(64 <= e_lfanew and e_lfanew + 24 <= n, "e_lfanew/COFF extent unsafe")
    (machine, nsec, _ts, _sym, _nsym, _optsize, _chars) = _u(e_lfanew + 4, "<HHIIIHH")
    _ok(raw[e_lfanew:e_lfanew + 4] == b"PE\x00\x00", "missing PE signature")
    _ok(machine == 0x8664, "machine must be AMD64")
    _ok(1 <= nsec <= 96, "section count out of range")
    _ok(_optsize == 240, "optional header size must be 240")
    _ok(_chars & 0x0002, "executable flag required")
    _ok(not _chars & 0x2000, "DLL characteristic forbidden")
    opt = e_lfanew + 24
    _ok(opt + 240 <= n, "optional header extent unsafe")
    (magic,) = _u(opt, "<H")
    _ok(magic == 0x20B, "optional header magic must be 0x20B")
    (nrdirs,) = _u(opt + 108, "<I")
    _ok(nrdirs == 16, "data directory count must be 16")
    (imagebase,) = _u(opt + 24, "<Q")
    _ok(imagebase != 0 and imagebase % 65536 == 0, "image base must be nonzero and 64KiB aligned")
    (sizeofimage,) = _u(opt + 56, "<I")
    _ok(0 < sizeofimage <= 64 * 1024 * 1024, "SizeOfImage out of bounds")
    (sizeofheaders,) = _u(opt + 60, "<I")
    _ok(sizeofheaders > 0 and sizeofheaders % 4096 == 0 and sizeofheaders <= n, "SizeOfHeaders invalid")
    (secalign,) = _u(opt + 32, "<I")
    _ok(secalign == 4096, "SectionAlignment must be 4096")
    (filealign,) = _u(opt + 36, "<I")
    _ok(filealign == 512, "FileAlignment must be 512")
    (entry,) = _u(opt + 16, "<I")
    (relva, relsize) = _u(opt + 112 + 5 * 8, "<II")
    if _chars & 0x0001 and relva != 0:
        raise ContractError("RELOCS_STRIPPED contradicts nonzero relocation directory")
    for i in range(16):
        if i == 5:
            continue
        (rva, size) = _u(opt + 112 + i * 8, "<II")
        _ok(rva == 0 and size == 0, f"data directory {i} must be zeroed")
    sectab = opt + 240
    _ok(sectab + 40 * nsec <= n, "section table extent unsafe")
    _ok(sizeofheaders >= sectab, "SizeOfHeaders below section table end")
    return {
        "section_table_offset": sectab,
        "section_count": nsec,
        "size_of_image": sizeofimage,
        "size_of_headers": sizeofheaders,
        "entry_rva": entry,
        "preferred_base": imagebase,
        "image_extent": imagebase + sizeofimage,
        "relocation_rva": relva,
        "relocation_size": relsize,
    }


def _parse_sections(raw: bytes, h: dict) -> tuple:
    """Strict pure section-table parse; returns (sections, byte_ranges), both immutable."""
    base, size = h["preferred_base"], h["size_of_image"]
    if base + size > 2**64:
        raise ContractError("image extent exceeds uint64")
    if h["size_of_headers"] < h["section_table_offset"] + 40 * h["section_count"]:
        raise ContractError("SizeOfHeaders below section table end")
    if (h["relocation_rva"] == 0) != (h["relocation_size"] == 0):
        raise ContractError("relocation rva/size pairing invalid")
    n = len(raw)
    off = h["section_table_offset"]
    sects, extents, ends = [], [], []
    rva = h["size_of_headers"]
    for _ in range(h["section_count"]):
        try:
            (_name, vsize, srva, rsize, rp, relptr, lineptr, nrel, nlines, chars) = \
                struct.unpack_from("<8sIIIIIIHHI", raw, off)
        except struct.error as exc:
            raise ContractError(f"section extent unsafe at {off}: {exc}")
        if not (vsize > 0 and vsize % 4096 == 0 and vsize >= rsize):
            raise ContractError("virtual size invalid")
        if chars & ~0xE00000E0:
            raise ContractError("unknown or discardable section flags")
        if not chars & 0x40000000:
            raise ContractError("section READ flag required")
        if chars & 0x80000000 and chars & 0x20000000:
            raise ContractError("WRITE+EXECUTE section refused")
        kinds = (chars & 0x20) + (chars & 0x40) + (chars & 0x80)
        if kinds != 0x20 and kinds != 0x40 and kinds != 0x80:
            raise ContractError("exactly one content kind required")
        if (rsize > 0) != bool(chars & 0x60):
            raise ContractError("content kind inconsistent with raw size")
        if srva != rva:
            raise ContractError("section RVA not contiguous")
        if rsize % 512 != 0:
            raise ContractError("raw size not 512-multiple")
        if rsize > 0:
            if rp < h["size_of_headers"] or rp % 512 != 0 or rp + rsize > n:
                raise ContractError("initialized raw extent invalid")
            extents.append((rp, rp + rsize))
        elif rp != 0:
            raise ContractError("pure bss raw pointer must be 0")
        if relptr != 0 or lineptr != 0 or nrel != 0 or nlines != 0:
            raise ContractError("relocation/linenumber pointers unsupported")
        ends.append(srva + vsize)
        sects.append((srva, vsize, rp, rsize, chars))
        rva = ends[-1]
        off += 40
    if rva != size:
        raise ContractError("final section end != SizeOfImage")
    for i in range(len(extents)):
        for j in range(i + 1, len(extents)):
            a, b = extents[i], extents[j]
            if a[0] < b[1] and b[0] < a[1]:
                raise ContractError("initialized raw extents overlap")
    if max([h["size_of_headers"]] + [e[1] for e in extents]) != n:
        raise ContractError("raw overlay beyond mapped sections")
    entry = h["entry_rva"]
    if not any(srva <= entry < srva + rsize and c & 0x20000000 for srva, _v, _rp, rsize, c in sects if rsize > 0):
        raise ContractError("entrypoint not in initialized executable section")
    ranges = [ByteRange(0, h["size_of_headers"], RangeCategory.IMMUTABLE_EXPECTED)]
    for srva, vsize, _rp, rsize, _c in sects:
        if rsize > 0:
            ranges.append(ByteRange(srva, rsize, RangeCategory.IMMUTABLE_EXPECTED))
        if vsize > rsize:
            ranges.append(ByteRange(srva + rsize, vsize - rsize, RangeCategory.ZERO_FILL_EXPECTED))
    for i in range(len(ranges)):
        if ranges[i].offset != (ranges[i - 1].offset + ranges[i - 1].length if i else 0):
            raise ContractError("ranges not contiguous")
    if ranges[-1].offset + ranges[-1].length != size:
        raise ContractError("partition must end at SizeOfImage")
    return tuple(sects), tuple(ranges)


def _parse_relocations(raw: bytes, h: dict, sections: tuple) -> tuple:
    """Strict pure DIR64 relocation parse; returns sorted immutable tuple of target RVAs."""
    rva, size = h["relocation_rva"], h["relocation_size"]
    if rva == 0 and size == 0:
        return ()
    sects = [s for s in sections if s[3] > 0]
    if not any(s[0] <= rva and rva + size <= s[0] + s[3] for s in sects):
        raise ContractError("relocation directory not in one initialized section")
    sect = next(s for s in sects if s[0] <= rva and rva + size <= s[0] + s[3])
    roff = sect[2] + (rva - sect[0])
    rend = roff + size
    if roff < h["size_of_headers"] or rend > len(raw) or rva + size > h["size_of_image"]:
        raise ContractError("relocation directory out of bounds")
    if size % 4 != 0:
        raise ContractError("relocation size not 4-multiple")
    off, targets, nent = roff, [], 0
    while off < rend:
        try:
            (page, bsize) = struct.unpack_from("<II", raw, off)
        except struct.error as exc:
            raise ContractError(f"relocation block extent unsafe at {off}: {exc}")
        if off + 8 > rend:
            raise ContractError("relocation block extent unsafe")
        if bsize < 8 or bsize % 4 != 0 or off + bsize > rend:
            raise ContractError("relocation block size invalid")
        if page % 4096 != 0 or page >= h["size_of_image"]:
            raise ContractError("relocation page RVA invalid")
        n = (bsize - 8) // 2
        nent += n
        if nent > 65536:
            raise ContractError("relocation entry count exceeds 65536")
        try:
            words = struct.unpack_from(f"<{n}H" if n else "<0H", raw, off + 8)
        except struct.error as exc:
            raise ContractError(f"relocation entry extent unsafe at {off + 8}: {exc}")
        for w in words:
            t = w >> 12
            if t == 0:
                continue
            if t != 10:
                raise ContractError("only DIR64 relocation type supported")
            targets.append(page + (w & 0xFFF))
        off += bsize
    targets.sort()
    for i in range(1, len(targets)):
        if targets[i] == targets[i - 1]:
            raise ContractError("duplicate relocation target")
        if targets[i] < targets[i - 1] + 8:
            raise ContractError("overlapping relocation targets")
    for t in targets:
        if not any(s[0] <= t and t + 8 <= s[0] + s[3] for s in sects):
            raise ContractError("relocation target not in initialized section")
        if t < rva + size and t + 8 > rva:
            raise ContractError("relocation target overlaps metadata")
    return tuple(targets)


def parse_raw_pe(raw: bytes) -> ImagePlan:
    """Parse headers/sections/relocations; split spans at DIR64 targets; return ImagePlan."""
    h = _parse_headers(raw)
    sections, ranges = _parse_sections(raw, h)
    targets = _parse_relocations(raw, h, sections)
    out = []
    for r in ranges:
        hits = sorted(t for t in targets if r.offset <= t < r.offset + r.length)
        if not hits:
            out.append(r)
            continue
        cur = r.offset
        for t in hits:
            if t - cur > 0:
                out.append(ByteRange(cur, t - cur, r.category))
            cat = RangeCategory.RELOCATION_NORMALIZED if r.category is RangeCategory.IMMUTABLE_EXPECTED else r.category
            out.append(ByteRange(t, 8, cat))
            cur = t + 8
        if r.offset + r.length - cur > 0:
            out.append(ByteRange(cur, r.offset + r.length - cur, r.category))
    if len(out) > 131072:
        raise ContractError("range span count exceeds cap")
    pos = 0
    for r in out:
        if r.offset != pos:
            raise ContractError("output ranges not adjacent from 0")
        pos = r.offset + r.length
    if pos != h["size_of_image"]:
        raise ContractError("partition must end at SizeOfImage")
    return ImagePlan(hashlib.sha256(raw).hexdigest(), h["size_of_image"], h["preferred_base"], tuple(out))


def compare_image(raw: bytes, observed: bytes, actual_base: int, phase: str) -> ComparisonResult:
    """Reparse raw (never a caller plan); compare observed in <=64KiB chunks; fail-closed."""
    if type(observed) is not bytes:
        raise ContractError("observed must be builtin bytes")
    if type(actual_base) is not int:
        raise ContractError("actual base must be builtin int")
    if type(phase) is not str or phase not in ("PREFERRED_UNRELOCATED", "RELOCATED"):
        raise ContractError("phase must be exact PREFERRED_UNRELOCATED or RELOCATED")
    plan = parse_raw_pe(raw)
    h = _parse_headers(raw)
    sections, _ = _parse_sections(raw, h)
    targets = _parse_relocations(raw, h, sections)
    size = plan.size_of_image
    if len(observed) != size:
        raise ContractError("observed length != SizeOfImage")
    if actual_base <= 0 or actual_base % 4096 != 0 or actual_base + size > 2**64:
        raise ContractError("actual base invalid")
    if phase == "PREFERRED_UNRELOCATED" and actual_base != plan.preferred_base:
        raise ContractError("preferred phase requires actual == preferred")
    if phase == "RELOCATED" and not targets and actual_base != plan.preferred_base:
        raise ContractError("relocated phase with base change requires nonempty targets")
    base = plan.preferred_base
    expected = bytearray(size)
    expected[0:h["size_of_headers"]] = raw[0:h["size_of_headers"]]
    for srva, vsize, rp, rsize, _c in sections:
        if rsize > 0:
            expected[srva:srva + rsize] = raw[rp:rp + rsize]
    if phase == "RELOCATED":
        delta = actual_base - base
        for t in targets:
            cv = int.from_bytes(expected[t:t + 8], "little")
            expected[t:t + 8] = ((cv + delta) & ((1 << 64) - 1)).to_bytes(8, "little")
    for off in range(0, size, 65536):
        if observed[off:off + 65536] != expected[off:off + 65536]:
            raise ContractError("observed image mismatch")
    return ComparisonResult(hashlib.sha256(raw).hexdigest(), base, actual_base, phase, True, False)