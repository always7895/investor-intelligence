#!/usr/bin/env python3
"""Bootstrap load guard: candidate/transaction fixture suite.

Stdlib unittest + TemporaryDirectory. Each test owns synthetic temp-only
project/global settings, policy, and state dir. Exact-path deny traps on
builtins.open / io.open / os.open / os.replace for the real runtime-root and
home settings paths are installed BEFORE the helper is loaded. No actual
real-settings IO; no count/version table.
"""
from __future__ import annotations

import builtins
import copy
import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# Real settings paths (deny targets; never read/hashed in tests).
_RUNTIME_SETTINGS = "D:/Investor-Intelligence-LINE-Pi/.pi/settings.json"
_HOME_SETTINGS = str(Path.home() / ".pi" / "agent" / "settings.json")


def _normalize_path(value):
    """Pure lexical path normalization for Path/str/bytes: absolute
    normalization, Windows slash/backslash and case equivalence (also for
    Windows drive strings on non-Windows CI). Integer file descriptors are
    ignored (returned as None). No real path resolve/stat/read."""
    if isinstance(value, int):
        return None  # integer file descriptor, not a path string
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError:
            return None
    if not isinstance(value, str):
        value = str(value)
    value = value.strip()
    if not value:
        return None
    import ntpath
    # Standard Windows lexical path routines (consistent on all hosts):
    # make absolute, collapse . / .., normalize separators.
    value = ntpath.abspath(value)
    # Lowercase for Windows case equivalence.
    value = value.lower()
    return value


_DENY_PATHS = {_normalize_path(_RUNTIME_SETTINGS), _normalize_path(_HOME_SETTINGS)}

# Helper source path (explicit; imported via file path).
_HELPER_SOURCE = Path(__file__).resolve().parents[1] / "scripts" / "pi_bootstrap_load_guard.py"


def _deny_open(original):
    def _guarded(file, *args, **kwargs):
        if _normalize_path(file) in _DENY_PATHS:
            raise AssertionError(f"real settings path accessed: {file}")
        return original(file, *args, **kwargs)
    return _guarded


def _deny_os_open(original):
    def _guarded(file, *args, **kwargs):
        if _normalize_path(file) in _DENY_PATHS:
            raise AssertionError(f"real settings path accessed: {file}")
        return original(file, *args, **kwargs)
    return _guarded


def _deny_os_replace(original):
    def _guarded(src, dst, *args, **kwargs):
        if _normalize_path(src) in _DENY_PATHS or _normalize_path(dst) in _DENY_PATHS:
            raise AssertionError(f"real settings path replace: {src} -> {dst}")
        return original(src, dst, *args, **kwargs)
    return _guarded


class BootstrapLoadGuardCandidateTests(unittest.TestCase):
    def setUp(self):
        # Install exact-path deny traps BEFORE loading the helper. Register
        # addCleanup immediately after EACH start so a setUp failure cleans up.
        self._p_open = mock.patch("builtins.open", _deny_open(builtins.open))
        self._p_open.start()
        self.addCleanup(self._p_open.stop)
        self._p_io = mock.patch("io.open", _deny_open(io.open))
        self._p_io.start()
        self.addCleanup(self._p_io.stop)
        self._p_os_open = mock.patch("os.open", _deny_os_open(os.open))
        self._p_os_open.start()
        self.addCleanup(self._p_os_open.stop)
        self._p_os_replace = mock.patch("os.replace", _deny_os_replace(os.replace))
        self._p_os_replace.start()
        self.addCleanup(self._p_os_replace.stop)
        # Import only the current helper from source via explicit file path.
        spec = importlib.util.spec_from_file_location("blg_under_test", _HELPER_SOURCE)
        self.blg = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.blg)
        # Synthetic project/global files, policy, state dir.
        self._tmpdir = tempfile.TemporaryDirectory(prefix="blg-cand-")
        self.addCleanup(self._tmpdir.cleanup)
        base = Path(self._tmpdir.name)
        self.state_dir = base / "state"
        self.state_dir.mkdir()
        self.policy = {
            "profiles": {
                "bootstrap": {
                    "global": {"extensions": ["!global-ext"], "skills": ["!global-skill"]},
                    "project": {"extensions": ["!proj-ext"], "skills": ["!proj-skill"]},
                }
            },
            "package_policy": {"approved": {}},
        }
        # Synthetic project/global JSON files + documents (temp-only IO).
        self.documents = {
            "project": {
                "defaultProvider": "openai-codex",
                "packages": ["npm:pi-web-access"],
                "skills": ["original-skill"],
            },
            "global": {
                "theme": "dark",
                "packages": ["git:github.com/NVlabs/SoL-Pi"],
                "extensions": ["original-ext"],
            },
        }
        self.targets = {}
        for name, doc in self.documents.items():
            path = base / f"{name}-settings.json"
            path.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
            self.targets[name] = path

    def test_candidate_preserves_unrelated_key_and_does_not_mutate_input(self):
        documents = {
            "project": {
                "defaultProvider": "openai-codex",
                "packages": ["npm:pi-web-access"],
                "skills": ["original-skill"],
            },
            "global": {
                "theme": "dark",
                "packages": ["git:github.com/NVlabs/SoL-Pi"],
                "extensions": ["original-ext"],
            },
        }
        snap_project = copy.deepcopy(documents["project"])
        snap_global = copy.deepcopy(documents["global"])
        candidates = self.blg.build_candidate_documents(documents, self.policy, "bootstrap")
        # Unrelated keys preserved.
        self.assertEqual(candidates["project"]["defaultProvider"], "openai-codex")
        self.assertEqual(candidates["global"]["theme"], "dark")
        # Classified startup arrays replaced by policy.
        self.assertEqual(candidates["project"]["extensions"], ["!proj-ext"])
        self.assertEqual(candidates["project"]["skills"], ["!proj-skill"])
        self.assertEqual(candidates["global"]["extensions"], ["!global-ext"])
        self.assertEqual(candidates["global"]["skills"], ["!global-skill"])
        # Original documents unchanged (deep-copy, no mutation).
        self.assertEqual(documents["project"], snap_project)
        self.assertEqual(documents["global"], snap_global)

    def test_apply_journal_before_write_and_rollback_restores_originals(self):
        # Capture original bytes of both targets.
        originals = {name: path.read_bytes() for name, path in self.targets.items()}
        candidates = self.blg.build_candidate_documents(self.documents, self.policy, "bootstrap")
        encoded = {name: self.blg.encode_json_lf(candidates[name]) for name in self.targets}
        # Recording write callback: at the FIRST target write, assert the
        # journal already exists with both target names, transaction ID, and
        # original/applied hashes. Delegate actual writes to _atomic_write.
        write_calls = {"n": 0}

        def recording_write(path, data):
            write_calls["n"] += 1
            if write_calls["n"] == 1:
                jpath = self.state_dir / "apply-journal.json"
                self.assertTrue(jpath.exists(), "journal must exist before first target write")
                journal = json.loads(jpath.read_text(encoding="utf-8"))
                self.assertIn("project", journal["targets"])
                self.assertIn("global", journal["targets"])
                self.assertTrue(journal.get("transaction_id"))
                for name in self.targets:
                    rec = journal["targets"][name]
                    self.assertIn("original_sha256", rec)
                    self.assertIn("applied_sha256", rec)
            self.blg._atomic_write(path, data)

        self.blg.apply_transaction(
            targets=self.targets,
            documents=self.documents,
            policy=self.policy,
            state_dir=self.state_dir,
            write=recording_write,
        )
        # Both applied bytes equal encoded candidates.
        for name, path in self.targets.items():
            self.assertEqual(path.read_bytes(), encoded[name])
        # Rollback restores both original byte strings exactly.
        self.blg.rollback_transaction(targets=self.targets, state_dir=self.state_dir)
        for name, path in self.targets.items():
            self.assertEqual(path.read_bytes(), originals[name])
        # Rollback again is idempotent success.
        result = self.blg.rollback_transaction(targets=self.targets, state_dir=self.state_dir)
        self.assertTrue(result.get("rolled_back"))
        for name, path in self.targets.items():
            self.assertEqual(path.read_bytes(), originals[name])

    def test_second_write_failure_propagates_and_restores_originals(self):
        # Capture original bytes of both targets.
        originals = {name: path.read_bytes() for name, path in self.targets.items()}
        write_calls = {"n": 0}

        def failing_write(path, data):
            write_calls["n"] += 1
            if write_calls["n"] == 1:
                # First real TEMP target write.
                self.blg._atomic_write(path, data)
            else:
                # Distinctive OSError on second write.
                raise OSError("injected: second settings write failed")

        with self.assertRaises(OSError) as ctx:
            self.blg.apply_transaction(
                targets=self.targets,
                documents=self.documents,
                policy=self.policy,
                state_dir=self.state_dir,
                write=failing_write,
            )
        # Failure is propagated per current API (not silently success).
        self.assertIn("second settings write failed", str(ctx.exception))
        # Both exact original bytes restored.
        for name, path in self.targets.items():
            self.assertEqual(path.read_bytes(), originals[name])
        # Journal indicates rollback.
        journal = json.loads((self.state_dir / "apply-journal.json").read_text(encoding="utf-8"))
        self.assertEqual(journal.get("status"), "rolled_back")

    def test_third_state_preflight_aborts_before_any_restore(self):
        # Apply normally.
        self.blg.apply_transaction(
            targets=self.targets,
            documents=self.documents,
            policy=self.policy,
            state_dir=self.state_dir,
        )
        # Capture both applied byte strings.
        applied = {name: path.read_bytes() for name, path in self.targets.items()}
        # Externally modify only global TEMP target to distinctive bytes.
        third_state = b"injected: third-state external edit\n"
        self.targets["global"].write_bytes(third_state)
        # Call rollback and require GuardError.
        with self.assertRaises(self.blg.GuardError):
            self.blg.rollback_transaction(targets=self.targets, state_dir=self.state_dir)
        # Project remains applied (zero restores before all-target preflight).
        self.assertEqual(self.targets["project"].read_bytes(), applied["project"])
        # Global third-state bytes unchanged.
        self.assertEqual(self.targets["global"].read_bytes(), third_state)

    def test_interrupted_apply_recovery_restores_originals(self):
        # Capture original bytes of both targets.
        originals = {name: path.read_bytes() for name, path in self.targets.items()}
        # Prepare journal (writes backups + journal BEFORE any settings write).
        self.blg.prepare_transaction(
            targets=self.targets,
            documents=self.documents,
            policy=self.policy,
            state_dir=self.state_dir,
        )
        # Simulate interrupted apply: write only project candidate bytes.
        candidates = self.blg.build_candidate_documents(self.documents, self.policy, "bootstrap")
        self.blg._atomic_write(self.targets["project"], self.blg.encode_json_lf(candidates["project"]))
        # Global stays original.
        self.assertEqual(self.targets["global"].read_bytes(), originals["global"])
        # recover_transaction must restore exact originals and journal rolled_back.
        self.blg.recover_transaction(targets=self.targets, state_dir=self.state_dir)
        for name, path in self.targets.items():
            self.assertEqual(path.read_bytes(), originals[name])
        journal = json.loads((self.state_dir / "apply-journal.json").read_text(encoding="utf-8"))
        self.assertEqual(journal.get("status"), "rolled_back")
        # Repeated recovery idempotent.
        self.blg.recover_transaction(targets=self.targets, state_dir=self.state_dir)
        for name, path in self.targets.items():
            self.assertEqual(path.read_bytes(), originals[name])

    def test_journal_binding_tamper_rejected_before_any_write(self):
        # Apply normally.
        self.blg.apply_transaction(
            targets=self.targets,
            documents=self.documents,
            policy=self.policy,
            state_dir=self.state_dir,
        )
        # Capture all bytes (targets + sentinel).
        applied = {name: path.read_bytes() for name, path in self.targets.items()}
        # Create an OWNED temp sentinel path (never a real path).
        sentinel = Path(self._tmpdir.name) / "sentinel-settings.json"
        sentinel.write_bytes(b"sentinel original\n")
        sentinel_original = sentinel.read_bytes()
        # Tamper the recorded target path in the journal to the sentinel path.
        jpath = self.state_dir / "apply-journal.json"
        journal = json.loads(jpath.read_text(encoding="utf-8"))
        journal["targets"]["project"]["path"] = str(sentinel)
        self.blg._atomic_write(jpath, (json.dumps(journal, indent=1) + "\n").encode("utf-8"))
        # recover/rollback must reject with GuardError before any target/sentinel write.
        with self.assertRaises(self.blg.GuardError):
            self.blg.rollback_transaction(targets=self.targets, state_dir=self.state_dir)
        # Assert all bytes unchanged (targets + sentinel).
        for name, path in self.targets.items():
            self.assertEqual(path.read_bytes(), applied[name])
        self.assertEqual(sentinel.read_bytes(), sentinel_original)

    def test_corrupt_backup_aborts_before_any_restore(self):
        # Apply normally.
        self.blg.apply_transaction(
            targets=self.targets,
            documents=self.documents,
            policy=self.policy,
            state_dir=self.state_dir,
        )
        # Capture both applied byte strings.
        applied = {name: path.read_bytes() for name, path in self.targets.items()}
        # Corrupt global original backup in state_dir.
        backup_copy = self.state_dir / "global-settings.json.orig"
        backup_copy.write_bytes(b"corrupted backup\n")
        # rollback must GuardError before restoring project.
        with self.assertRaises(self.blg.GuardError):
            self.blg.rollback_transaction(targets=self.targets, state_dir=self.state_dir)
        # Both applied targets unchanged.
        for name, path in self.targets.items():
            self.assertEqual(path.read_bytes(), applied[name])

    def test_candidate_deterministic_and_classified_only(self):
        # Fixture documents with nested unrelated keys and an unknown package object.
        documents = {
            "project": {
                "defaultProvider": "openai-codex",
                "nested": {"a": 1, "b": {"c": [1, 2, 3]}},
                "packages": [
                    "npm:unknown-pkg",
                    {
                        "source": "npm:unknown-obj",
                        "version": "1.2.3",
                        "config": {"key": "value"},
                    },
                    "git:github.com/NVlabs/SoL-Pi",
                ],
                "skills": ["original-skill"],
            },
            "global": {
                "theme": "dark",
                "nested": {"x": [1, 2]},
                "packages": ["npm:unknown-pkg"],
                "extensions": ["original-ext"],
            },
        }
        # Policy explicitly classifies one package source/resource field.
        policy = {
            "profiles": {
                "bootstrap": {
                    "global": {"extensions": ["!global-ext"], "skills": ["!global-skill"]},
                    "project": {"extensions": ["!proj-ext"], "skills": ["!proj-skill"]},
                }
            },
            "package_policy": {
                "approved": {
                    "git:github.com/NVlabs/SoL-Pi": {
                        "extensions": ["!**", "+src/sol-pi/index.ts"],
                    }
                }
            },
        }
        snap = copy.deepcopy(documents)
        # Repeated encode_json_lf candidates byte-identical.
        candidates1 = self.blg.build_candidate_documents(documents, policy, "bootstrap")
        encoded1 = {name: self.blg.encode_json_lf(candidates1[name]) for name in candidates1}
        candidates2 = self.blg.build_candidate_documents(documents, policy, "bootstrap")
        encoded2 = {name: self.blg.encode_json_lf(candidates2[name]) for name in candidates2}
        for name in candidates1:
            self.assertEqual(encoded1[name], encoded2[name])
        # Inputs unchanged.
        self.assertEqual(documents, snap)
        # Unknown package/nonresource fields preserved.
        proj_packages = candidates1["project"]["packages"]
        unknown_obj = next(p for p in proj_packages if isinstance(p, dict) and p.get("source") == "npm:unknown-obj")
        self.assertEqual(unknown_obj["version"], "1.2.3")
        self.assertEqual(unknown_obj["config"], {"key": "value"})
        self.assertIn("npm:unknown-pkg", proj_packages)
        # Only declared startup/resource fields differ.
        sol_pkg = next(p for p in proj_packages if isinstance(p, dict) and p.get("source") == "git:github.com/NVlabs/SoL-Pi")
        self.assertEqual(sol_pkg["extensions"], ["!**", "+src/sol-pi/index.ts"])
        self.assertEqual(candidates1["project"]["extensions"], ["!proj-ext"])
        self.assertEqual(candidates1["project"]["skills"], ["!proj-skill"])
        self.assertEqual(candidates1["global"]["extensions"], ["!global-ext"])
        self.assertEqual(candidates1["global"]["skills"], ["!global-skill"])
        # Nested unrelated keys preserved.
        self.assertEqual(candidates1["project"]["nested"], {"a": 1, "b": {"c": [1, 2, 3]}})
        self.assertEqual(candidates1["global"]["nested"], {"x": [1, 2]})

    def test_deny_trap_mock_backed_aliases(self):
        # For BOTH deny settings paths, exercise slash/backslash/case/dot-segment
        # aliases through open/os.open and os.replace src/dst. Underlying IO is a
        # Mock, so even a broken guard cannot touch actual settings.
        mock_open = mock.Mock()
        mock_os_open = mock.Mock()
        mock_replace = mock.Mock()
        guarded_open = _deny_open(mock_open)
        guarded_os_open = _deny_os_open(mock_os_open)
        guarded_replace = _deny_os_replace(mock_replace)
        for raw in (_RUNTIME_SETTINGS, _HOME_SETTINGS):
            # Normalize to a single slash representation before aliasing.
            slash = raw.replace("\\", "/")
            # Generate aliases: backslash, case, dot-segment, dot-dot, mixed.
            head, tail = slash.rsplit("/", 1)
            aliases = {
                slash.replace("/", "\\"),
                slash.upper(),
                head + "/./" + tail,
                head + "/sub/../" + tail,
                slash.upper().replace("/", "\\"),
            }
            for alias in aliases:
                with self.assertRaises(AssertionError):
                    guarded_open(alias)
                with self.assertRaises(AssertionError):
                    guarded_os_open(alias)
                with self.assertRaises(AssertionError):
                    guarded_replace(alias, "owned-temp-dest")
                with self.assertRaises(AssertionError):
                    guarded_replace("owned-temp-src", alias)
        # Mock underlying IO never called.
        mock_open.assert_not_called()
        mock_os_open.assert_not_called()
        mock_replace.assert_not_called()


if __name__ == "__main__":
    unittest.main()