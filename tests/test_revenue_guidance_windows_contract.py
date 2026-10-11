"""Windows substrate checks that precede native work, plus the retained close graph.

_lazy_bind is a failing sentinel in every test, so reaching native binding is a
failure. Owners are built with the private secret on an in-memory lease; the module
custody globals are patched and restored per test. No DLL, handle or syscall is
used, and no native custody, ACL or ABI property is qualified here (G3).
"""
from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import revenue_guidance_storage as storage
import revenue_guidance_windows as windows

GUID = "{01234567-89ab-cdef-0123-456789abcdef}"
OTHER_GUID = "{fedcba98-7654-3210-fedc-ba9876543210}"
Fault = windows.StorageValidationFault


def context(state="READY"):
    lease = storage.NativeStorageLease.__new__(storage.NativeStorageLease)
    lease.anchor = SimpleNamespace(volume_guid=GUID, bootstrap_id="synthetic-bootstrap", state_required=True)
    lease._initialize_custody(storage.NativeLimits())
    lease._state = state
    return lease


def owned(ctx, slot=0, *, submitted=True, value=0x1234, status=windows.STATUS_SUCCESS, parent=None):
    owner = windows.OwnedHandle(ctx, _secret=windows.OwnedHandle)
    owner._slot = owner._serial = slot
    owner._charged = True
    owner._request = SimpleNamespace(submitted=submitted, final_status=status, out_handle=SimpleNamespace(value=value),
                                     parent=parent, lease_context=ctx, owned_handle=owner)
    ctx._owned_handles[slot] = owner
    return owner


def native_api(result):
    close = mock.Mock(return_value=result)
    return SimpleNamespace(kernel32=SimpleNamespace(CloseHandle=close), HANDLE=lambda value: value), close


class _IsolatedDomain(unittest.TestCase):
    def setUp(self):
        self.bind = self.enterContext(mock.patch.object(
            windows, "_lazy_bind", side_effect=AssertionError("native binding reached")))
        self.enterContext(mock.patch.object(windows, "_poisoned", False))
        self.enterContext(mock.patch.object(windows, "_unsettled_close_owner", None))
        self.enterContext(mock.patch.object(windows, "_quarantine_record", None))
        # Independent origin custody belongs to the provisioner, not this module.
        self.enterContext(mock.patch.object(windows, "_origin_custody_unresolved", return_value=False))

    def tearDown(self):
        self.bind.assert_not_called()


class ComponentNameTests(_IsolatedDomain):
    def test_admitted_components(self):
        for name in ("journal.dat", "coordination.lock", "b1", "control", "enroll-" + "0" * 32,
                     "COM10", "LPT0", "CONSOLE", "x.y", "a" * 255):
            with self.subTest(name=name):
                windows._validate_component(name)

    def test_refused_components(self):
        for name in ("", ".", "..", "a.", "a ", "a/b", "a\\b", "a:b", "a*b", "a?b", 'a"b', "a<b", "a>b",
                     "a|b", "a\0b", "a\x01b", "a\x1fb", "a\x7fb", "a\x9fb", "CON", "con.txt", "Prn", "AUX.log",
                     "NUL", "COM1", "lpt9.txt", "COM\u00b9", "LPT\u00b3", "a" * 256, "\ud800", 7, b"journal", None):
            with self.subTest(name=repr(name)):
                with self.assertRaises(Fault):
                    windows._validate_component(name)

    def test_control_filenames_are_not_namespace_operands(self):
        for name in ("journal.dat", "JOURNAL.DAT", "Coordination.Lock"):
            with self.subTest(name=name):
                with self.assertRaises(Fault):
                    windows._namespace_name(name)
        windows._namespace_name("receipts.json")


class CustodyContextTests(_IsolatedDomain):
    def test_handle_adoption_requires_the_private_secret(self):
        ctx = context()
        for candidate in (None, object(), "OwnedHandle"):
            with self.subTest(candidate=repr(candidate)):
                with self.assertRaises(Fault):
                    windows.OwnedHandle(ctx, _secret=candidate)

    def test_context_must_be_an_actual_guarded_active_lease(self):
        for value in (object(), SimpleNamespace(_guard_thread=None, _lock=None), None):
            with self.subTest(value=type(value).__name__):
                with self.assertRaises(Fault):
                    windows._require_context(value)
        ctx = context()
        with self.assertRaises(Fault):
            windows._require_context(ctx)  # serialization guard not held
        with ctx._serialized():
            self.assertIs(windows._require_context(ctx), ctx)
        for field, value in (("_state", "INITIAL"), ("_state", "FAILED"), ("_closed", True), ("_quarantined", True)):
            with self.subTest(field=field, value=value):
                inactive = context()
                setattr(inactive, field, value)
                with inactive._serialized():
                    with self.assertRaises(Fault):
                        windows._require_context(inactive)

    def test_parent_chain_must_be_same_lease_registered_and_settled(self):
        ctx, other = context(), context()
        foreign = owned(other)
        valid = owned(ctx, 0)
        pending = owned(ctx, 1, status=windows.STATUS_PENDING)
        closed = owned(ctx, 2)
        closed._closed = True
        unregistered = owned(ctx, 3)
        ctx._owned_handles[3] = None
        with ctx._serialized():
            self.assertIs(windows._require_context(ctx, valid), ctx)
            for name, parent in (("foreign", foreign), ("pending", pending), ("closed", closed),
                                 ("unregistered", unregistered), ("not-owned", object())):
                with self.subTest(name):
                    with self.assertRaises(Fault):
                        windows._require_context(ctx, parent)

    def test_open_and_io_entry_points_refuse_before_native_binding(self):
        ctx = context()
        parent = owned(ctx, 0)
        root = f"\\??\\Volume{GUID}\\"
        with ctx._serialized():
            refusals = {
                "root-outside-acquisition": lambda: windows._nt_open(None, root, True, False, ctx),
                "nonbool-flag": lambda: windows._nt_open(parent, "a", 1, False, ctx),
                "namespace-on-file": lambda: windows._nt_open(parent, "a", False, False, ctx, namespace_access=True),
                "invalid-name": lambda: windows._nt_open(parent, "a/b", False, False, ctx),
                "missing-parent": lambda: windows.open_relative(None, "a", True, False, ctx),
                "relative-nonbool": lambda: windows.open_relative(parent, "a", True, 0, ctx),
                "relative-dotdot": lambda: windows.open_relative(parent, "..", True, False, ctx),
                "volume-mismatch": lambda: windows.open_volume_root(OTHER_GUID, ctx),
                "volume-outside-acquisition": lambda: windows.open_volume_root(GUID, ctx),
                "metadata-not-owned": lambda: windows.get_file_metadata(object()),
                "read-not-owned": lambda: windows.read_at(object(), 0, 1),
                "read-negative": lambda: windows.read_at(parent, -1, 1),
                "read-over-cap": lambda: windows.read_at(parent, 0, parent._object_cap + 1),
                "write-text": lambda: windows.write_at(parent, 0, "text"),
                "write-chunk-over-1mib": lambda: windows.write_chunk(parent, 0, b"x" * (windows.IO_CHUNK_BYTES + 1)),
                "flush-not-owned": lambda: windows.flush(object()),
                "create-without-namespace-rights": lambda: windows.create_relative(
                    parent, "a", directory=False, operation=object(), object_cap=1),
            }
            for name, call in refusals.items():
                with self.subTest(name):
                    with self.assertRaises(Fault):
                        call()
            ctx._live_operation = object()
            with self.assertRaises(Fault):
                windows._nt_open(parent, "a", False, True, ctx, create=True, operation=object())
            ctx._live_operation = None
        acquiring = context("ACQUIRING")
        with acquiring._serialized():
            for name, value, write in (("other-volume", f"\\??\\Volume{OTHER_GUID}\\", False), ("writable-root", root, True)):
                with self.subTest(name):
                    with self.assertRaises(Fault):
                        windows._nt_open(None, value, True, write, acquiring)

    def test_relative_open_checks_parent_before_and_leaf_type_links_after_open(self):
        ctx = context()
        parent = owned(ctx, 0)
        leaf = object()
        directory = (7, b"p" * 16, 0, True, False, 0x10, 0, 1)
        cases = {
            "parent-reparse": (directory[:6] + (0xA000000C, 1), None, False),
            "parent-file": (directory[:3] + (False,) + directory[4:], None, False),
            "parent-delete-pending": (directory[:4] + (True,) + directory[5:], None, False),
            "leaf-hardlinked": (directory, (7, b"l" * 16, 3, False, False, 0x20, 0, 2), True),
            "leaf-type": (directory, (7, b"l" * 16, 0, True, False, 0x10, 0, 1), True),
            "leaf-volume": (directory, (8, b"l" * 16, 3, False, False, 0x20, 0, 1), True),
            "leaf-reparse": (directory, (7, b"l" * 16, 3, False, False, 0x420, 0, 1), True),
            "leaf-delete-pending": (directory, (7, b"l" * 16, 3, False, True, 0x20, 0, 1), True),
        }
        for name, (parent_meta, leaf_meta, opened) in cases.items():
            with self.subTest(name):
                metadata = {id(parent): parent_meta, id(leaf): leaf_meta}
                with mock.patch.object(windows, "get_file_metadata", side_effect=lambda h: metadata[id(h)]), \
                        mock.patch.object(windows, "_nt_open", return_value=leaf) as nt_open, ctx._serialized():
                    with self.assertRaises(Fault):
                        windows.open_relative(parent, "leaf.json", False, False, ctx)
                self.assertEqual(nt_open.called, opened)
        metadata = {id(parent): directory, id(leaf): (7, b"l" * 16, 3, False, False, 0x20, 0, 1)}
        with mock.patch.object(windows, "get_file_metadata", side_effect=lambda h: metadata[id(h)]), \
                mock.patch.object(windows, "_nt_open", return_value=leaf), ctx._serialized():
            self.assertIs(windows.open_relative(parent, "leaf.json", False, False, ctx), leaf)


class RetainedCloseGraphTests(_IsolatedDomain):
    def test_settled_domain_status_and_hold_return_without_waiting(self):
        self.assertEqual(windows.native_custody_status(), "SETTLED")
        with mock.patch.object(windows._custody_hold_event, "wait", side_effect=AssertionError("waited")):
            self.assertIsNone(windows.hold_unresolved_native_custody())
        windows._check_poison()

    def test_uncertain_cleanup_retains_the_first_live_registered_owner_once(self):
        ctx, other = context(), context()
        first, second = owned(ctx, 0), owned(ctx, 1)
        windows._retain_uncertain_cleanup(ctx)
        self.assertIs(windows._unsettled_close_owner, first)
        self.assertTrue(windows._poisoned)
        self.assertEqual(windows.native_custody_status(), "UNRESOLVED")
        self.assertTrue(windows.context_custody_unresolved(ctx))
        self.assertFalse(windows.context_custody_unresolved(other))
        windows._retain_uncertain_cleanup(ctx)
        self.assertIs(windows._unsettled_close_owner, first)
        with self.assertRaises(windows.StorageUnavailableError) as raised:
            windows._check_poison()
        self.assertIn("NATIVE_CUSTODY_UNRESOLVED", str(raised.exception))
        api, close = native_api(1)
        with self.assertRaises(storage.StorageLeaseError) as refused:
            second._close_internal(api)
        self.assertIs(refused.exception, ctx._cleanup_failure)
        close.assert_not_called()
        self.assertFalse(second._closed)
        self.assertFalse(second._close_attempted)

    def test_unsubmitted_empty_or_released_owners_are_not_retained(self):
        ctx = context()
        owned(ctx, 0, submitted=False)
        owned(ctx, 1, value=0)
        owned(ctx, 2, value=0xFFFFFFFFFFFFFFFF)
        owned(ctx, 3)._closed = True
        owned(ctx, 4)._active_released = True
        windows._retain_uncertain_cleanup(ctx)
        self.assertIsNone(windows._unsettled_close_owner)
        self.assertFalse(windows._poisoned)
        self.assertEqual(windows.native_custody_status(), "SETTLED")

    def test_failed_native_close_stays_unresolved_and_is_attempted_once(self):
        ctx = context()
        owner = owned(ctx, 0)
        api, close = native_api(0)
        with self.assertRaises(windows.StorageUnavailableError) as raised:
            owner._close_internal(api)
        close.assert_called_once_with(0x1234)
        self.assertIs(owner.close_error, raised.exception)
        self.assertIs(windows._unsettled_close_owner, owner)
        self.assertEqual(windows.native_custody_status(), "UNRESOLVED")
        self.assertFalse(owner._closed)
        self.assertFalse(owner._active_released)
        with self.assertRaises(storage.StorageLeaseError):
            owner._close_internal(api)
        close.assert_called_once_with(0x1234)

    def test_confirmed_native_close_alone_releases_custody(self):
        ctx = context()
        owner = owned(ctx, 0)
        api, close = native_api(1)
        owner._close_internal(api)
        close.assert_called_once_with(0x1234)
        self.assertTrue(owner._closed and owner._active_released and owner._evidence.close_confirmed)
        self.assertIsNone(windows._unsettled_close_owner)
        self.assertEqual(windows.native_custody_status(), "SETTLED")
        owner._close_internal(api)
        close.assert_called_once_with(0x1234)

    def test_live_descendant_blocks_ancestor_close(self):
        ctx = context()
        ancestor = owned(ctx, 0)
        owned(ctx, 1, parent=ancestor)
        api, close = native_api(1)
        with self.assertRaises(Fault):
            ancestor._close_internal(api)
        close.assert_not_called()
        self.assertFalse(ancestor._close_attempted)

    def test_pending_request_record_poisons_only_its_own_context(self):
        ctx, other = context(), context()
        owner = owned(ctx, 0)
        record = SimpleNamespace(submitted=True, final_status=windows.STATUS_PENDING, lease_context=ctx)
        with mock.patch.object(windows, "_quarantine_record", record):
            self.assertEqual(windows.native_custody_status(), "UNRESOLVED")
            self.assertTrue(windows._retains_context(ctx))
            self.assertFalse(windows._retains_context(other))
            api, close = native_api(1)
            with self.assertRaises(windows.StorageUnavailableError) as refused:
                owner._close_internal(api)
            self.assertIs(refused.exception, ctx._pending_failure)
            close.assert_not_called()
            with self.assertRaises(windows.StorageUnavailableError) as raised:
                windows._check_poison()
            self.assertIn("PENDING_IO_UNRESOLVED", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
