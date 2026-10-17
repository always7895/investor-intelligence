"""S3E2A synthetic custody creation contract (pure stdlib, non-authorizing).

Offline pure synthetic input validator. Positive results mean
synthetic ordering/field checks pass; nothing here authorizes execution, retry,
cleanup, or proves OS custody. Tokens are synthetic labels, not OS handles.
"""
import re
import unicodedata

EVENT_ORDER = (
    "RESERVATION", "JOB_READY", "ATTRIBUTES_READY", "CREATE_ADMITTED",
    "CREATE_RETURNED", "MEMBERSHIP_OBSERVED", "ATTRIBUTE_STORAGE_RELEASED", "CUSTODY_RETAINED",
)
COMMON_FIELDS = frozenset({"type", "now_ns"})
EVENT_FIELDS = {
    "RESERVATION": frozenset({"run_id", "candidate_sha256", "deadline_ns", "synthetic"}),
    "JOB_READY": frozenset({"job_token", "inherit", "kill_on_close", "breakaway"}),
    "ATTRIBUTES_READY": frozenset({"executable", "cwd", "flags", "inherit_handles", "job_list", "stdio"}),
    "CREATE_ADMITTED": frozenset({"permit_token", "executable", "cwd", "flags", "inherit_handles", "job_list", "handle_list"}),
    "CREATE_RETURNED": frozenset({"success", "process_token", "thread_token", "original_creation_handles", "attributes_kept_alive_through_return"}),
    "MEMBERSHIP_OBSERVED": frozenset({"process_token", "job_token", "in_job", "suspended"}),
    "ATTRIBUTE_STORAGE_RELEASED": frozenset({"after_create_return"}),
    "CUSTODY_RETAINED": frozenset({"process_token", "thread_token", "job_token", "job_inherited", "resumed"}),
}
REQUIRED_FLAGS = 0x00080004
STDIO_KEYS = frozenset({"stdin", "stdout", "stderr"})
MAX_EVENTS = 8
MAX_TOKEN_LEN = 64
MAX_PATH_LEN = 1024
MAX_CLOCK = 2 ** 63 - 1
TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
SHA_RE = re.compile(r"[0-9a-f]{64}\Z")
STATUS_VALID = "SYNTHETIC_CREATION_CONTRACT_VALID"
STATUS_INVALID = "INVALID_TRANSCRIPT"
STATUS_QUARANTINED = "UNQUALIFIED_QUARANTINED"
PERMIT_NOT_ESTABLISHED = "NOT_ESTABLISHED"
PERMIT_SPENT_CLAIMED = "SPENT_CLAIMED"
PERMIT_UNKNOWN = "UNKNOWN"


def _is_token(value):
    return type(value) is str and TOKEN_RE.fullmatch(value) is not None


def _is_sha256(value):
    return type(value) is str and SHA_RE.fullmatch(value) is not None


def _is_clock(value):
    return type(value) is int and 0 <= value <= MAX_CLOCK


def _is_path(value):
    if type(value) is not str or value == "" or len(value) > MAX_PATH_LEN:
        return False
    return not any(unicodedata.category(ch) in ("Cc", "Cf", "Cs") for ch in value)


def _closed_fields(event_type):
    return COMMON_FIELDS | EVENT_FIELDS.get(event_type, frozenset())


def _outcome(status, reason, permit_state):
    return {
        "status": status,
        "reason": reason,
        "synthetic": True,
        "authorizes_execution": False,
        "platform_qualified": False,
        "image_bytes_attested": False,
        "workspace_attested": False,
        "hard_io_timeout_proven": False,
        "cleanup_confirmed": False,
        "retry_authorized": False,
        "permit_state": permit_state,
    }

def validate_creation_transcript(events):
    """Validate bounded synthetic claims. Never issue an OS capability or permit."""
    if type(events) is not list or not 1 <= len(events) <= MAX_EVENTS:
        return _outcome(STATUS_INVALID, "invalid event container", PERMIT_UNKNOWN)
    spent = False
    previous = None
    deadline = None
    job = None
    attrs = None
    stdio_tokens = set()
    permit = None
    process = None
    thread = None

    def bad(reason):
        return _outcome(STATUS_QUARANTINED if spent else STATUS_INVALID,
                        reason, PERMIT_SPENT_CLAIMED if spent else PERMIT_UNKNOWN)

    for index, event in enumerate(events):
        kind = EVENT_ORDER[index]
        keys = _closed_fields(kind)
        if (type(event) is not dict or len(event) != len(keys)
                or any(type(k) is not str for k in event) or set(event) != keys
                or type(event["type"]) is not str or event["type"] != kind):
            return bad("invalid event schema or order")
        now = event["now_ns"]
        if not _is_clock(now) or (previous is not None and now < previous):
            return bad("invalid monotonic coordinate")
        previous = now
        if kind == "RESERVATION":
            if (not _is_token(event["run_id"]) or not _is_sha256(event["candidate_sha256"])
                    or not _is_clock(event["deadline_ns"]) or event["synthetic"] is not True):
                return bad("invalid reservation claims")
            deadline = event["deadline_ns"]
        elif kind == "JOB_READY":
            if (not _is_token(event["job_token"]) or event["inherit"] is not False
                    or event["kill_on_close"] is not True or event["breakaway"] is not False):
                return bad("invalid job claims")
            job = event["job_token"]
        elif kind == "ATTRIBUTES_READY":
            io = event["stdio"]
            if (not _is_path(event["executable"]) or not _is_path(event["cwd"])
                    or type(event["flags"]) is not int or event["flags"] != REQUIRED_FLAGS
                    or type(event["inherit_handles"]) is not bool
                    or type(event["job_list"]) is not list or len(event["job_list"]) != 1
                    or type(event["job_list"][0]) is not str or event["job_list"][0] != job
                    or type(io) is not dict or len(io) not in (0, 3)):
                return bad("invalid creation attributes")
            if io:
                if (any(type(k) is not str for k in io) or set(io) != STDIO_KEYS
                        or any(not _is_token(v) for v in io.values())
                        or io["stdin"] in (io["stdout"], io["stderr"])):
                    return bad("invalid stdio roles")
            stdio_tokens = set(io.values())
            if job in stdio_tokens or event["inherit_handles"] is not bool(io):
                return bad("invalid inheritance claims")
            attrs = event
        elif kind == "CREATE_ADMITTED":
            # Structurally present admission with an expired clock is uncertain,
            # even if another call-field claim is malformed. Never report none.
            if now >= deadline:
                return _outcome(STATUS_QUARANTINED, "expired admission claim", PERMIT_UNKNOWN)
            handles = event["handle_list"]
            if (not _is_token(event["permit_token"])
                    or event["permit_token"] in stdio_tokens | {job}
                    or type(event["flags"]) is not int
                    or type(event["inherit_handles"]) is not bool
                    or type(event["job_list"]) is not list or len(event["job_list"]) != 1
                    or type(event["job_list"][0]) is not str or event["job_list"][0] != job
                    or type(handles) is not list or len(handles) > 3
                    or any(not _is_token(h) for h in handles)):
                return bad("invalid admission claims")
            for key in ("executable", "cwd", "flags", "inherit_handles", "job_list"):
                if type(event[key]) is not type(attrs[key]) or event[key] != attrs[key]:
                    return bad("admitted call mismatch")
            if len(set(handles)) != len(handles) or set(handles) != stdio_tokens:
                return bad("inherited handle list mismatch")
            permit = event["permit_token"]
            spent = True
        elif kind == "CREATE_RETURNED":
            if type(event["success"]) is not bool or type(event["attributes_kept_alive_through_return"]) is not bool:
                return bad("invalid creation return claims")
            if event["success"] is False:
                if (event["process_token"] is not None or event["thread_token"] is not None
                        or event["original_creation_handles"] is not False):
                    return bad("invalid failed creation claims")
                return bad("create returned failure")
            process, thread = event["process_token"], event["thread_token"]
            if (not _is_token(process) or not _is_token(thread) or process == thread
                    or process in stdio_tokens | {job, permit}
                    or thread in stdio_tokens | {job, permit}
                    or event["original_creation_handles"] is not True
                    or event["attributes_kept_alive_through_return"] is not True):
                return bad("invalid original custody claims")
        elif kind == "MEMBERSHIP_OBSERVED":
            if (type(event["process_token"]) is not str or event["process_token"] != process
                    or type(event["job_token"]) is not str or event["job_token"] != job
                    or event["in_job"] is not True or event["suspended"] is not True):
                return bad("invalid membership claims")
        elif kind == "ATTRIBUTE_STORAGE_RELEASED":
            if event["after_create_return"] is not True:
                return bad("invalid attribute lifetime claims")
        elif kind == "CUSTODY_RETAINED":
            if (any(type(event[k]) is not str for k in ("process_token", "thread_token", "job_token"))
                    or event["process_token"] != process or event["thread_token"] != thread
                    or event["job_token"] != job or event["job_inherited"] is not False
                    or event["resumed"] is not False):
                return bad("invalid final custody claims")
        if now >= deadline:
            return _outcome(STATUS_QUARANTINED, "expired forward event",
                            PERMIT_SPENT_CLAIMED if spent else PERMIT_UNKNOWN)
    if len(events) != MAX_EVENTS:
        return _outcome(STATUS_QUARANTINED if spent else STATUS_INVALID,
                        "incomplete transcript", PERMIT_SPENT_CLAIMED if spent else PERMIT_NOT_ESTABLISHED)
    return _outcome(STATUS_VALID, "synthetic ordering validated", PERMIT_SPENT_CLAIMED)
