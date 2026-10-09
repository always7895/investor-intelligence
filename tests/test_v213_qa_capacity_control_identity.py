"""Finite deterministic synthetic tests for the PURE identity foundation
(Gate B, slice GB-S1).

These tests exercise only the new pure module `v213_qa_capacity_control_identity`.
They use unittest style, synthetic values, and side-effect guards to prove the
public APIs are pure and side-effect free. No child/native runner is started,
no port is opened, no canonical path reserved, no real authority artifact
generated. The existing 12-test inert-launcher refusal suite is run separately
in the same focused invocation and must remain unmodified.
"""
import ast
import contextlib
import hashlib
import io
import sys
import unittest
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))
import v213_qa_capacity_control_identity as CI  # noqa: E402


def accepted_mapping():
    return {
        "source_head": "6922278ac865727fdcdded96535f94aaaabeb8b3",
        "harness_sha256": "ef6bef33bd510a9f3dc155145ae895749c512670d14c91eaa8ed782f7f024324",
        "request_sha256": "1fa1910c8db0dda712d6997717e7c5519c22de9465222dd302e96456bcc3f7b0",
        "run_plan_sha256": "3e36a3be4b1a4e5d42d3dd6927cf4e160aa26ea72a011df73a9ce6fbc304866d",
    }


class TestGitCommitValidator(unittest.TestCase):
    def test_valid_40hex_returns_same_string(self):
        v = "6922278ac865727fdcdded96535f94aaaabeb8b3"
        self.assertIs(CI.validate_git_commit(v), v)

    def test_all_zero_40hex_ok(self):
        self.assertEqual(CI.validate_git_commit("0" * 40), "0" * 40)

    def test_wrong_length_short(self):
        with self.assertRaises(CI.IdentityValidationError):
            CI.validate_git_commit("a" * 39)

    def test_wrong_length_long(self):
        with self.assertRaises(CI.IdentityValidationError):
            CI.validate_git_commit("a" * 41)

    def test_64hex_rejected_for_git(self):
        with self.assertRaises(CI.IdentityValidationError):
            CI.validate_git_commit("a" * 64)

    def test_uppercase_fails(self):
        with self.assertRaises(CI.IdentityValidationError):
            CI.validate_git_commit("A" * 40)

    def test_mixed_case_fails(self):
        with self.assertRaises(CI.IdentityValidationError):
            CI.validate_git_commit("a" * 39 + "A")

    def test_leading_whitespace_fails(self):
        with self.assertRaises(CI.IdentityValidationError):
            CI.validate_git_commit(" " + "a" * 39)

    def test_trailing_whitespace_fails(self):
        with self.assertRaises(CI.IdentityValidationError):
            CI.validate_git_commit("a" * 40 + " ")

    def test_unicode_non_ascii_fails(self):
        with self.assertRaises(CI.IdentityValidationError):
            CI.validate_git_commit("\u0100" + "a" * 39)

    def test_non_hex_char_fails(self):
        with self.assertRaises(CI.IdentityValidationError):
            CI.validate_git_commit("g" * 40)

    def test_bool_fails(self):
        with self.assertRaises(CI.IdentityValidationError):
            CI.validate_git_commit(True)

    def test_none_fails(self):
        with self.assertRaises(CI.IdentityValidationError):
            CI.validate_git_commit(None)

    def test_int_fails(self):
        with self.assertRaises(CI.IdentityValidationError):
            CI.validate_git_commit(1234567890)

    def test_float_fails(self):
        with self.assertRaises(CI.IdentityValidationError):
            CI.validate_git_commit(1.0)

    def test_bytes_fails(self):
        with self.assertRaises(CI.IdentityValidationError):
            CI.validate_git_commit(b"a" * 40)

    def test_str_subclass_fails(self):
        class Sub(str):
            pass
        with self.assertRaises(CI.IdentityValidationError):
            CI.validate_git_commit(Sub("a" * 40))

    def test_error_is_valueerror_derived(self):
        self.assertTrue(issubclass(CI.IdentityValidationError, ValueError))


class TestSha256Validator(unittest.TestCase):
    def test_valid_64hex_returns_same_string(self):
        v = "ef6bef33bd510a9f3dc155145ae895749c512670d14c91eaa8ed782f7f024324"
        self.assertIs(CI.validate_sha256(v), v)

    def test_40hex_rejected_for_sha256(self):
        with self.assertRaises(CI.IdentityValidationError):
            CI.validate_sha256("a" * 40)

    def test_wrong_length_63(self):
        with self.assertRaises(CI.IdentityValidationError):
            CI.validate_sha256("a" * 63)

    def test_wrong_length_65(self):
        with self.assertRaises(CI.IdentityValidationError):
            CI.validate_sha256("a" * 65)

    def test_uppercase_fails(self):
        with self.assertRaises(CI.IdentityValidationError):
            CI.validate_sha256("A" * 64)

    def test_whitespace_fails(self):
        with self.assertRaises(CI.IdentityValidationError):
            CI.validate_sha256("a" * 64 + " ")

    def test_non_hex_fails(self):
        with self.assertRaises(CI.IdentityValidationError):
            CI.validate_sha256("f" * 63 + "z")

    def test_bool_none_int_fail(self):
        for bad in (True, None, 5):
            with self.subTest(bad=bad):
                with self.assertRaises(CI.IdentityValidationError):
                    CI.validate_sha256(bad)

    def test_bytes_fail(self):
        with self.assertRaises(CI.IdentityValidationError):
            CI.validate_sha256(b"a" * 64)

    def test_str_subclass_fails(self):
        class Sub(str):
            pass
        with self.assertRaises(CI.IdentityValidationError):
            CI.validate_sha256(Sub("a" * 64))


class TestControllerIdentityRecord(unittest.TestCase):
    def test_exact_accepted_claims_immutable_copied_record(self):
        rec = CI.validate_controller_identity_mapping(accepted_mapping())
        self.assertIsInstance(rec, CI.ControllerIdentity)
        self.assertEqual(rec.source_head, "6922278ac865727fdcdded96535f94aaaabeb8b3")
        self.assertEqual(rec.harness_sha256, "ef6bef33bd510a9f3dc155145ae895749c512670d14c91eaa8ed782f7f024324")
        self.assertEqual(rec.request_sha256, "1fa1910c8db0dda712d6997717e7c5519c22de9465222dd302e96456bcc3f7b0")
        self.assertEqual(rec.run_plan_sha256, "3e36a3be4b1a4e5d42d3dd6927cf4e160aa26ea72a011df73a9ce6fbc304866d")
        # Fresh copy, not the constant object, but equal to it.
        self.assertIsNot(rec, CI.ACCEPTED_CONTROLLER_IDENTITY)
        self.assertEqual(rec, CI.ACCEPTED_CONTROLLER_IDENTITY)

    def test_input_mapping_mutation_cannot_change_record(self):
        m = accepted_mapping()
        rec = CI.validate_controller_identity_mapping(m)
        # Mutate the caller mapping after validation.
        m["source_head"] = "a" * 40
        m["harness_sha256"] = "b" * 64
        self.assertEqual(rec.source_head, "6922278ac865727fdcdded96535f94aaaabeb8b3")
        self.assertEqual(rec.harness_sha256, "ef6bef33bd510a9f3dc155145ae895749c512670d14c91eaa8ed782f7f024324")

    def test_frozen_fields_reject_reassignment(self):
        rec = CI.validate_controller_identity_mapping(accepted_mapping())
        with self.assertRaises(AttributeError):
            rec.source_head = "a" * 40
        with self.assertRaises(AttributeError):
            rec.harness_sha256 = "b" * 64

    def test_each_field_changed_independently_shape_valid_wrong_value_fails(self):
        cases = {
            "source_head": "a" * 40,          # valid 40hex, wrong value
            "harness_sha256": "a" * 64,       # valid 64hex, wrong value
            "request_sha256": "b" * 64,       # valid 64hex, wrong value
            "run_plan_sha256": "c" * 64,      # valid 64hex, wrong value
        }
        for field, wrong in cases.items():
            m = accepted_mapping()
            m[field] = wrong
            with self.subTest(field=field):
                with self.assertRaises(CI.IdentityValidationError):
                    CI.validate_controller_identity_mapping(m)

    def test_field_shape_invalid_fails(self):
        m = accepted_mapping()
        m["source_head"] = "a" * 39           # wrong length for git
        with self.assertRaises(CI.IdentityValidationError):
            CI.validate_controller_identity_mapping(m)
        m = accepted_mapping()
        m["harness_sha256"] = "A" * 64        # uppercase
        with self.assertRaises(CI.IdentityValidationError):
            CI.validate_controller_identity_mapping(m)

    def test_missing_field_fails(self):
        for field in ("source_head", "harness_sha256", "request_sha256", "run_plan_sha256"):
            m = accepted_mapping()
            del m[field]
            with self.subTest(field=field):
                with self.assertRaises(CI.IdentityValidationError):
                    CI.validate_controller_identity_mapping(m)

    def test_extra_field_fails(self):
        m = accepted_mapping()
        m["window_id"] = "W-1"
        with self.assertRaises(CI.IdentityValidationError):
            CI.validate_controller_identity_mapping(m)

    def test_wrong_mapping_types_fail(self):
        good = accepted_mapping()
        bads = [
            list(good.items()),
            tuple(good.values()),
            bytes(good["source_head"], "ascii"),
            "not-a-dict",
            42,
            None,
        ]
        for bad in bads:
            with self.subTest(bad=type(bad).__name__):
                with self.assertRaises(CI.IdentityValidationError):
                    CI.validate_controller_identity_mapping(bad)

    def test_dict_subclass_rejected(self):
        class Sub(dict):
            pass
        with self.assertRaises(CI.IdentityValidationError):
            CI.validate_controller_identity_mapping(Sub(accepted_mapping()))

    def test_no_narrowing_widening_of_runner_authority_schema(self):
        # The new 4-field record must NOT imply the accepted runner authority
        # schema (task_id/fixup_sha/window_id/run_namespace/...). None of those
        # keys are part of this record's field set.
        rec = CI.validate_controller_identity_mapping(accepted_mapping())
        fields = set(rec.__dataclass_fields__)
        self.assertEqual(fields, {"source_head", "harness_sha256",
                                  "request_sha256", "run_plan_sha256"})
        runner_keys = {"task_id", "fixup_sha", "authorized_source_sha",
                       "window_id", "run_namespace", "valid_from_epoch_s",
                       "valid_until_epoch_s", "operator"}
        self.assertEqual(fields & runner_keys, set())

    def test_no_caller_override_of_expected_pins(self):
        # A caller cannot retarget the production expected pins; a wrong
        # pinned value always fails even when the mapping is otherwise exact.
        m = accepted_mapping()
        m["source_head"] = "0" * 40
        with self.assertRaises(CI.IdentityValidationError):
            CI.validate_controller_identity_mapping(m)


class TestMappingKeyTypes(unittest.TestCase):
    """Regressions for non-string mapping keys: exact built-in str key-type
    validation must fire BEFORE set/sort/diagnostics, with constant error text
    that never calls repr of untrusted keys. All produce
    IdentityValidationError (ValueError-derived), never TypeError."""

    def _expect_key_error(self, m):
        with self.assertRaises(CI.IdentityValidationError):
            CI.validate_controller_identity_mapping(m)

    def test_int_key_fails(self):
        m = accepted_mapping()
        m[1] = "x"
        self._expect_key_error(m)

    def test_none_key_fails(self):
        m = accepted_mapping()
        m[None] = "x"
        self._expect_key_error(m)

    def test_bool_key_fails(self):
        m = accepted_mapping()
        m[True] = "x"
        self._expect_key_error(m)

    def test_tuple_key_fails(self):
        m = accepted_mapping()
        m[("a",)] = "x"
        self._expect_key_error(m)

    def test_mixed_keys_counterexample_fails(self):
        # Exact Astra counterexample: accepted mapping plus keys 1 and None.
        # Old code raised TypeError at sorted(unknown); must be ValueError-derived.
        m = accepted_mapping()
        m[1] = "x"
        m[None] = "y"
        self._expect_key_error(m)

    def test_str_subclass_key_fails(self):
        class Sub(str):
            pass
        m = accepted_mapping()
        # Genuinely NEW subclass key (not equal to any existing built-in key),
        # so the dict actually holds a Sub instance and the key-type check fires.
        # All accepted values are retained.
        m[Sub("extra")] = "x"
        with self.assertRaises(CI.IdentityValidationError) as ctx:
            CI.validate_controller_identity_mapping(m)
        self.assertEqual(
            str(ctx.exception), "identity mapping keys must be exact built-in str")

    def test_custom_hashable_repr_sentinel_zero_repr(self):
        class ReprSentinel:
            def __init__(self):
                self.repr_calls = 0

            def __hash__(self):
                return 987654

            def __eq__(self, other):
                return False

            def __repr__(self):
                self.repr_calls += 1
                return "UNTRUSTED_REPR"

        sent = ReprSentinel()
        m = accepted_mapping()
        m[sent] = "x"
        try:
            CI.validate_controller_identity_mapping(m)
            self.fail("expected IdentityValidationError")
        except CI.IdentityValidationError as e:
            self.assertNotIn("UNTRUSTED_REPR", str(e))
        self.assertEqual(sent.repr_calls, 0)

    def test_all_bad_keys_zero_side_effects(self):
        with SideEffectGuard() as g:
            for bad_key in (1, None, True, ("a",), object()):
                m = accepted_mapping()
                m[bad_key] = "x"
                with self.assertRaises(CI.IdentityValidationError):
                    CI.validate_controller_identity_mapping(m)
            g.assert_zero_calls()


class TestBytesSha256Verifier(unittest.TestCase):
    # Fixed known literal + its fixed known digest (deterministic).
    LITERAL = b"The quick brown fox jumps over the lazy dog"
    DIGEST = "d7a8fbb307d7809469ca9abcb0082e4f8d5651e46d3cdb762d02d0bf37c9e592"

    def test_success_known_literal_fixed_digest(self):
        self.assertEqual(CI.verify_bytes_sha256(self.LITERAL, self.DIGEST), self.DIGEST)

    def test_independent_hashlib_cross_check(self):
        self.assertEqual(hashlib.sha256(self.LITERAL).hexdigest(), self.DIGEST)

    def test_single_byte_mutation_fails(self):
        mutated = self.LITERAL[:-1] + bytes([self.LITERAL[-1] ^ 1])
        with self.assertRaises(CI.IdentityValidationError):
            CI.verify_bytes_sha256(mutated, self.DIGEST)

    def test_newline_mutation_fails(self):
        with self.assertRaises(CI.IdentityValidationError):
            CI.verify_bytes_sha256(self.LITERAL + b"\n", self.DIGEST)

    def test_bom_mutation_fails(self):
        with self.assertRaises(CI.IdentityValidationError):
            CI.verify_bytes_sha256(b"\xef\xbb\xbf" + self.LITERAL, self.DIGEST)

    def test_wrong_digest_fails(self):
        with self.assertRaises(CI.IdentityValidationError):
            CI.verify_bytes_sha256(self.LITERAL, "a" * 64)

    def test_non_bytes_types_fail(self):
        for bad in (
            bytearray(self.LITERAL),
            memoryview(self.LITERAL),
            self.LITERAL.decode("ascii"),
            list(self.LITERAL),
            None,
        ):
            with self.subTest(bad=type(bad).__name__):
                with self.assertRaises(CI.IdentityValidationError):
                    CI.verify_bytes_sha256(bad, self.DIGEST)

    def test_malformed_expected_digest_fails(self):
        for bad in ("a" * 63, "A" * 64, "a" * 40, "a" * 64 + " ", True, None):
            with self.subTest(bad=bad):
                with self.assertRaises(CI.IdentityValidationError):
                    CI.verify_bytes_sha256(self.LITERAL, bad)


class SideEffectGuard:
    """Patch process/socket/filesystem/time side effects with mocks; verify
    ZERO calls. Original objects are restored on exit."""

    TARGETS = (
        ("subprocess", "Popen"), ("subprocess", "run"), ("subprocess", "call"),
        ("socket", "socket"), ("socket", "create_connection"),
        ("os", "open"), ("os", "mkdir"), ("os", "remove"), ("os", "unlink"),
        ("os", "getenv"), ("os", "listdir"),
        ("pathlib", "Path.mkdir"), ("pathlib", "Path.open"),
        ("pathlib", "Path.read_text"), ("pathlib", "Path.write_text"),
        ("time", "sleep"), ("time", "time"),
    )

    def __enter__(self):
        self._saved = []
        for mod_name, attr in self.TARGETS:
            mod = __import__(mod_name, fromlist=[attr])
            obj = mod
            for part in attr.split(".")[:-1]:
                obj = getattr(obj, part)
            leaf = attr.split(".")[-1]
            if not hasattr(obj, leaf):
                continue
            self._saved.append((obj, leaf, getattr(obj, leaf)))
            setattr(obj, leaf, mock.Mock(name=f"{mod_name}.{attr}"))
        return self

    def __exit__(self, *exc):
        for obj, leaf, orig in self._saved:
            setattr(obj, leaf, orig)

    def assert_zero_calls(self):
        for obj, leaf, _orig in self._saved:
            m = getattr(obj, leaf)
            if m.called:
                raise AssertionError(f"side effect {leaf} was called")


class TestPurityAndSideEffects(unittest.TestCase):
    def _imported_module_names(self):
        src = Path(CI.__file__).read_text(encoding="utf-8")
        tree = ast.parse(src)
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    names.add(a.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    names.add(node.module.split(".")[0])
        return names

    def test_only_pure_stdlib_imports(self):
        self.assertEqual(self._imported_module_names(), {"hashlib", "dataclasses"})

    def test_no_forbidden_capability_in_code(self):
        # AST-based: with only hashlib/dataclasses imported, no process/network/
        # file/time/env/Win32/Git capability can be referenced in CODE. Docstrings
        # may name capabilities (to document their absence) without triggering
        # this check, so this is robust to the required purity docstring.
        src = Path(CI.__file__).read_text(encoding="utf-8")
        tree = ast.parse(src)
        self.assertEqual(self._imported_module_names(), {"hashlib", "dataclasses"})
        forbidden_modules = {"os", "subprocess", "socket", "ctypes", "time",
                             "shutil", "signal", "multiprocessing", "asyncio",
                             "urllib", "requests", "http", "ssl", "git"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                base = node
                while isinstance(base, ast.Attribute):
                    base = base.value
                if isinstance(base, ast.Name) and base.id in forbidden_modules:
                    self.fail(f"forbidden module reference in code: {base.id}")
        for node in tree.body:
            if isinstance(node, ast.If):
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Name) and sub.id == "__name__":
                        self.fail("module-level __name__ guard present")
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.assertNotIn(node.name, {"main", "run"})
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        self.assertNotIn(t.id, {"ACCEPTED", "_DRAFT_ACCEPTED"})

    def test_no_cli_activation_or_mutable_switch(self):
        self.assertFalse(hasattr(CI, "main"))
        self.assertFalse(hasattr(CI, "_DRAFT_ACCEPTED"))
        self.assertFalse(hasattr(CI, "run"))

    def test_public_apis_pure_zero_side_effects(self):
        with SideEffectGuard() as g:
            CI.validate_git_commit("6922278ac865727fdcdded96535f94aaaabeb8b3")
            CI.validate_sha256("ef6bef33bd510a9f3dc155145ae895749c512670d14c91eaa8ed782f7f024324")
            CI.validate_controller_identity_mapping(accepted_mapping())
            with self.assertRaises(CI.IdentityValidationError):
                CI.validate_git_commit("a" * 39)
            with self.assertRaises(CI.IdentityValidationError):
                CI.validate_controller_identity_mapping(
                    {**accepted_mapping(), "window_id": "W"})
            CI.verify_bytes_sha256(
                b"The quick brown fox jumps over the lazy dog",
                "d7a8fbb307d7809469ca9abcb0082e4f8d5651e46d3cdb762d02d0bf37c9e592")
            with self.assertRaises(CI.IdentityValidationError):
                CI.verify_bytes_sha256(b"x", "a" * 64)
            g.assert_zero_calls()

    def test_no_env_clock_git_on_public_paths(self):
        with mock.patch("os.getenv", side_effect=AssertionError("env used")) as getenv, \
             mock.patch("time.time", side_effect=AssertionError("clock used")) as tm, \
             mock.patch("subprocess.run", side_effect=AssertionError("git used")) as srun:
            CI.validate_controller_identity_mapping(accepted_mapping())
            CI.verify_bytes_sha256(
                b"The quick brown fox jumps over the lazy dog",
                "d7a8fbb307d7809469ca9abcb0082e4f8d5651e46d3cdb762d02d0bf37c9e592")
            getenv.assert_not_called()
            tm.assert_not_called()
            srun.assert_not_called()


if __name__ == "__main__":
    unittest.main()