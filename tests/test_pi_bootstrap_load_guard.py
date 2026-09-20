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
        # H7: checkpoint capture state.
        self._captured_digest = None
        self._captured_descriptor = None

    def _make_sink(self):
        """Create a checkpoint_sink that captures descriptor and digest."""
        def sink(descriptor, digest):
            self._captured_descriptor = json.loads(json.dumps(descriptor))
            self._captured_digest = digest
        return sink

    def _digest(self):
        """Return the captured checkpoint digest from prewrite sink."""
        if self._captured_digest is None:
            raise AssertionError("checkpoint not captured; call prepare/apply with sink first")
        return self._captured_digest

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
            checkpoint_sink=self._make_sink(),
        )
        # Both applied bytes equal encoded candidates.
        for name, path in self.targets.items():
            self.assertEqual(path.read_bytes(), encoded[name])
        # Rollback restores both original byte strings exactly.
        self.blg.rollback_transaction(targets=self.targets, state_dir=self.state_dir, checkpoint_digest=self._digest())
        for name, path in self.targets.items():
            self.assertEqual(path.read_bytes(), originals[name])
        # Rollback again is idempotent success.
        result = self.blg.rollback_transaction(targets=self.targets, state_dir=self.state_dir, checkpoint_digest=self._digest())
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
                checkpoint_sink=self._make_sink(),
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
            checkpoint_sink=self._make_sink(),
        )
        # Capture both applied byte strings.
        applied = {name: path.read_bytes() for name, path in self.targets.items()}
        # Externally modify only global TEMP target to distinctive bytes.
        third_state = b"injected: third-state external edit\n"
        self.targets["global"].write_bytes(third_state)
        # Call rollback and require GuardError.
        with self.assertRaises(self.blg.GuardError):
            self.blg.rollback_transaction(targets=self.targets, state_dir=self.state_dir, checkpoint_digest=self._digest())
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
            checkpoint_sink=self._make_sink(),
        )
        # Simulate interrupted apply: write only project candidate bytes.
        candidates = self.blg.build_candidate_documents(self.documents, self.policy, "bootstrap")
        self.blg._atomic_write(self.targets["project"], self.blg.encode_json_lf(candidates["project"]))
        # Global stays original.
        self.assertEqual(self.targets["global"].read_bytes(), originals["global"])
        # recover_transaction must restore exact originals and journal rolled_back.
        self.blg.recover_transaction(targets=self.targets, state_dir=self.state_dir, checkpoint_digest=self._digest())
        for name, path in self.targets.items():
            self.assertEqual(path.read_bytes(), originals[name])
        journal = json.loads((self.state_dir / "apply-journal.json").read_text(encoding="utf-8"))
        self.assertEqual(journal.get("status"), "rolled_back")
        # Repeated recovery idempotent.
        self.blg.recover_transaction(targets=self.targets, state_dir=self.state_dir, checkpoint_digest=self._digest())
        for name, path in self.targets.items():
            self.assertEqual(path.read_bytes(), originals[name])

    def test_journal_binding_tamper_rejected_before_any_write(self):
        # Apply normally.
        self.blg.apply_transaction(
            targets=self.targets,
            documents=self.documents,
            policy=self.policy,
            state_dir=self.state_dir,
            checkpoint_sink=self._make_sink(),
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
            self.blg.rollback_transaction(targets=self.targets, state_dir=self.state_dir, checkpoint_digest=self._digest())
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
            checkpoint_sink=self._make_sink(),
        )
        # Capture both applied byte strings.
        applied = {name: path.read_bytes() for name, path in self.targets.items()}
        # Corrupt global original backup in state_dir.
        backup_copy = self.state_dir / "global-settings.json.orig"
        backup_copy.write_bytes(b"corrupted backup\n")
        # rollback must GuardError before restoring project.
        with self.assertRaises(self.blg.GuardError):
            self.blg.rollback_transaction(targets=self.targets, state_dir=self.state_dir, checkpoint_digest=self._digest())
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


    # --- Slice 1: Path/Identity Safety regressions (H1, H2, H8, M1) ---

    def test_hardlink_backup_interruption_rejected(self):
        """H1: A hard-linked backup that is the same file as the target
        must be rejected by file-identity check before any write."""
        with tempfile.TemporaryDirectory() as td:
            state_dir = Path(td) / "state"
            target = Path(td) / "settings.json"
            target.write_text('{"extensions": []}\n', encoding="utf-8")
            other = Path(td) / "global.json"
            other.write_text('{"extensions": []}\n', encoding="utf-8")
            # Create a hard link: backup path IS the target file.
            state_dir.mkdir(parents=True)
            backup_path = state_dir / "project-settings.json.orig"
            os.link(str(target), str(backup_path))
            # The file identity of backup == target; prepare must reject.
            docs = {"project": {"extensions": []}, "global": {"extensions": []}}
            targets = {"project": target, "global": other}
            with self.assertRaises(self.blg.GuardError) as ctx:
                self.blg.prepare_transaction(
                    targets=targets, documents=docs, policy=self.policy,
                    state_dir=state_dir,
                    checkpoint_sink=self._make_sink(),
                )
            self.assertIn("hard-link alias", str(ctx.exception))

    def test_cross_target_alias_rejected(self):
        """H1: Two targets pointing to the same file must be rejected."""
        with tempfile.TemporaryDirectory() as td:
            state_dir = Path(td) / "state"
            shared = Path(td) / "shared.json"
            shared.write_text('{"extensions": []}\n', encoding="utf-8")
            docs = {"project": {"extensions": []}, "global": {"extensions": []}}
            targets = {"project": shared, "global": shared}  # same file
            with self.assertRaises(self.blg.GuardError) as ctx:
                self.blg.prepare_transaction(
                    targets=targets, documents=docs, policy=self.policy,
                    state_dir=state_dir,
                    checkpoint_sink=self._make_sink(),
                )
            self.assertIn("cross-target alias", str(ctx.exception))

    def test_manifest_as_target_rejected(self):
        """H1: A target path equal to the rollback manifest must be rejected."""
        with tempfile.TemporaryDirectory() as td:
            state_dir = Path(td) / "state"
            state_dir.mkdir(parents=True)
            manifest = state_dir / "rollback-manifest.json"
            manifest.write_text('{}\n', encoding="utf-8")
            other = Path(td) / "other.json"
            other.write_text('{"extensions": []}\n', encoding="utf-8")
            docs = {"project": {"extensions": []}, "global": {"extensions": []}}
            targets = {"project": manifest, "global": other}
            with self.assertRaises(self.blg.GuardError) as ctx:
                self.blg.prepare_transaction(
                    targets=targets, documents=docs, policy=self.policy,
                    state_dir=state_dir,
                    checkpoint_sink=self._make_sink(),
                )
            self.assertIn("aliases settings target", str(ctx.exception))

    def test_symlink_backup_escape_rejected(self):
        """H2: A symlink backup path pointing outside state_dir must be
        rejected before any write. UNPROVED on Windows without SeCreateSymbolicLinkPrivilege."""
        with tempfile.TemporaryDirectory() as td:
            state_dir = Path(td) / "state"
            state_dir.mkdir(parents=True)
            target = Path(td) / "settings.json"
            target.write_text('{"extensions": []}\n', encoding="utf-8")
            other = Path(td) / "global.json"
            other.write_text('{"extensions": []}\n', encoding="utf-8")
            outside = Path(td) / "outside-secret.json"
            outside.write_text('do not touch\n', encoding="utf-8")
            backup_link = state_dir / "project-settings.json.orig"
            try:
                backup_link.symlink_to(outside)
            except OSError:
                # Windows without symlink privilege: explicit unproved evidence.
                self.skipTest("symlink creation requires SeCreateSymbolicLinkPrivilege; H2 unproved on this host")
            docs = {"project": {"extensions": []}, "global": {"extensions": []}}
            targets = {"project": target, "global": other}
            with self.assertRaises(self.blg.GuardError) as ctx:
                self.blg.prepare_transaction(
                    targets=targets, documents=docs, policy=self.policy,
                    state_dir=state_dir,
                    checkpoint_sink=self._make_sink(),
                )
            self.assertIn("symlink", str(ctx.exception))
            # Outside file must be unchanged.
            self.assertEqual(outside.read_text(encoding="utf-8"), "do not touch\n")

    def test_mock_symlink_reparse_rejection(self):
        """H2 (mock branch): Patch Path.is_symlink to True for the backup
        path. Proves _check_no_symlink() logic raises GuardError. Does NOT
        prove actual OS symlink behavior (that is the junction/real test)."""
        with tempfile.TemporaryDirectory() as td:
            state_dir = Path(td) / "state"
            state_dir.mkdir(parents=True)
            target = Path(td) / "settings.json"
            target.write_text('{"extensions": []}\n', encoding="utf-8")
            other = Path(td) / "global.json"
            other.write_text('{"extensions": []}\n', encoding="utf-8")
            backup_path = state_dir / "project-settings.json.orig"
            # Create a regular file at backup path, then mock is_symlink=True.
            backup_path.write_text('fake\n', encoding="utf-8")
            docs = {"project": {"extensions": []}, "global": {"extensions": []}}
            targets = {"project": target, "global": other}
            with mock.patch.object(Path, "is_symlink", return_value=True):
                with self.assertRaises(self.blg.GuardError) as ctx:
                    self.blg.prepare_transaction(
                        targets=targets, documents=docs, policy=self.policy,
                        state_dir=state_dir,
                        checkpoint_sink=self._make_sink(),
                    )
            self.assertIn("symlink", str(ctx.exception))

    def test_windows_junction_backup_escape_rejected(self):
        """H2 (real Windows junction): Create a directory junction (mklink /J,
        no privilege needed) at the backup path pointing outside state_dir.
        Proves actual OS reparse-point detection. NOT file-symlink proof.
        Sentinels: all paths are owned temporary fixture paths."""
        if os.name != "nt":
            self.skipTest("Windows-only junction test")
        with tempfile.TemporaryDirectory() as td:
            state_dir = Path(td) / "state"
            state_dir.mkdir(parents=True)
            target = Path(td) / "settings.json"
            target.write_text('{"extensions": []}\n', encoding="utf-8")
            other = Path(td) / "global.json"
            other.write_text('{"extensions": []}\n', encoding="utf-8")
            # Outside destination (owned temp fixture).
            outside_dir = Path(td) / "outside-dir"
            outside_dir.mkdir()
            sentinel = outside_dir / "sentinel.txt"
            sentinel.write_text('do not touch\n', encoding="utf-8")
            # Create directory junction: backup path -> outside_dir.
            backup_junction = state_dir / "project-settings.json.orig"
            result = os.system(f'mklink /J "{backup_junction}" "{outside_dir}" >nul 2>&1')
            if result != 0:
                self.skipTest("mklink /J not supported on this host; H2 junction unproved")
            if not backup_junction.exists():
                self.skipTest("junction creation failed; H2 junction unproved")
            docs = {"project": {"extensions": []}, "global": {"extensions": []}}
            targets = {"project": target, "global": other}
            with self.assertRaises(self.blg.GuardError) as ctx:
                self.blg.prepare_transaction(
                    targets=targets, documents=docs, policy=self.policy,
                    state_dir=state_dir,
                    checkpoint_sink=self._make_sink(),
                )
            self.assertIn("reparse point", str(ctx.exception))
            # Sentinel must be unchanged.
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "do not touch\n")
            # Cleanup: remove ONLY the junction entry (not traverse outside).
            os.system(f'rmdir "{backup_junction}" >nul 2>&1')

    def test_relative_path_rebinding_rejected(self):
        """H8: Relative target paths must be rejected at prepare time."""
        with tempfile.TemporaryDirectory() as td:
            state_dir = Path(td) / "state"
            other = Path(td) / "global.json"
            other.write_text('{"extensions": []}\n', encoding="utf-8")
            docs = {"project": {"extensions": []}, "global": {"extensions": []}}
            # Use a relative path (cwd-dependent, rebinding attack).
            rel_target = Path("settings.json")  # relative!
            targets = {"project": rel_target, "global": other}
            with self.assertRaises(self.blg.GuardError) as ctx:
                self.blg.prepare_transaction(
                    targets=targets, documents=docs, policy=self.policy,
                    state_dir=state_dir,
                    checkpoint_sink=self._make_sink(),
                )
            self.assertIn("must be absolute", str(ctx.exception))

    def test_public_schema_version_rejection(self):
        """M1: Public recover/rollback must reject unknown schema/version
        before any action (not just _recover_pending)."""
        with tempfile.TemporaryDirectory() as td:
            state_dir = Path(td) / "state"
            state_dir.mkdir(parents=True)
            target = Path(td) / "settings.json"
            target.write_text('{"extensions": []}\n', encoding="utf-8")
            other = Path(td) / "global.json"
            other.write_text('{"extensions": []}\n', encoding="utf-8")
            targets = {"project": target, "global": other}
            # Write a journal with wrong schema.
            bad_journal = {
                "schema": "evil-schema", "version": 999,
                "transaction_id": "x", "status": "in_progress",
                "targets": {
                    "project": {"path": str(target), "original_sha256": "a", "applied_sha256": "b", "backup": "x", "status": "pending"},
                    "global": {"path": str(other), "original_sha256": "c", "applied_sha256": "d", "backup": "y", "status": "pending"},
                },
            }
            jpath = state_dir / "apply-journal.json"
            jpath.write_text(json.dumps(bad_journal), encoding="utf-8")
            # Synthetic well-formed digest (NOT derived from attacked journal).
            # Schema rejection occurs before digest comparison, so value is
            # irrelevant; it just needs to be a valid non-empty string.
            synthetic_digest = "a" * 64
            # Public recover must reject (schema failure before digest check).
            with self.assertRaises(self.blg.GuardError) as ctx:
                self.blg.recover_transaction(targets=targets, state_dir=state_dir, checkpoint_digest=synthetic_digest)
            self.assertIn("schema", str(ctx.exception))
            # Public rollback must also reject.
            with self.assertRaises(self.blg.GuardError) as ctx2:
                self.blg.rollback_transaction(targets=targets, state_dir=state_dir, checkpoint_digest=synthetic_digest)
            self.assertIn("schema", str(ctx2.exception))
            # Bytes unchanged (no writes from rejected calls).
            self.assertEqual(target.read_text(encoding="utf-8"), '{"extensions": []}\n')
            self.assertEqual(other.read_text(encoding="utf-8"), '{"extensions": []}\n')


    # --- Slice 2: State Machine Integrity regressions (H3-H6, M2, M3) ---

    def test_stale_documents_rejected(self):
        """H3: If the target file has been modified since documents were
        captured, prepare must reject (stale snapshot)."""
        with tempfile.TemporaryDirectory() as td:
            state_dir = Path(td) / "state"
            target = Path(td) / "settings.json"
            target.write_text('{"extensions": ["real"], "skills": []}\n', encoding="utf-8")
            other = Path(td) / "global.json"
            other.write_text('{"extensions": []}\n', encoding="utf-8")
            # Documents are STALE: they say extensions=[] but file has ["real"].
            docs = {"project": {"extensions": [], "skills": []}, "global": {"extensions": []}}
            targets = {"project": target, "global": other}
            with self.assertRaises(self.blg.GuardError) as ctx:
                self.blg.prepare_transaction(
                    targets=targets, documents=docs, policy=self.policy,
                    state_dir=state_dir,
                    checkpoint_sink=self._make_sink(),
                )
            self.assertIn("stale injected snapshot", str(ctx.exception))

    def test_post_preflight_edit_survives_rollback(self):
        """H4: An edit made AFTER completed preflight but BEFORE the next
        restore must be detected by the per-write recheck. The external edit
        survives (is not overwritten). Uses mock.patch on _atomic_write to
        inject the mutation between preflight and second restore."""
        with tempfile.TemporaryDirectory() as td:
            state_dir = Path(td) / "state"
            original_text = '{"extensions": []}\n'
            target = Path(td) / "settings.json"
            target.write_text(original_text, encoding="utf-8")
            other = Path(td) / "global.json"
            other.write_text(original_text, encoding="utf-8")
            docs = {"project": {"extensions": []}, "global": {"extensions": []}}
            targets = {"project": target, "global": other}
            # Apply successfully.
            self.blg.apply_transaction(
                targets=targets, documents=docs, policy=self.policy,
                state_dir=state_dir,
                checkpoint_sink=self._make_sink(),
            )
            # Patch _atomic_write to inject a post-preflight edit after the
            # first restore succeeds. The second target's external edit must
            # be detected by H4 recheck before it's overwritten.
            real_atomic_write = self.blg._atomic_write
            call_count = [0]
            def injecting_atomic_write(path, data):
                call_count[0] += 1
                real_atomic_write(path, data)
                # After the first target restore (call 2: call 1 is journal),
                # inject an external edit to the second target.
                if call_count[0] == 2:
                    Path(other).write_text('{"extensions": ["user-edit"]}\n', encoding="utf-8")
            with mock.patch.object(self.blg, "_atomic_write", side_effect=injecting_atomic_write):
                with self.assertRaises(self.blg.GuardError) as ctx:
                    self.blg.rollback_transaction(targets=targets, state_dir=state_dir, checkpoint_digest=self._digest())
            self.assertIn("state changed since preflight", str(ctx.exception))
            # The external edit must survive (not overwritten).
            self.assertEqual(other.read_text(encoding="utf-8"), '{"extensions": ["user-edit"]}\n')

    def test_interrupted_rollback_recovery_idempotent(self):
        """H5: Interrupted rollback (status=rollback_in_progress) is
        recoverable and idempotent. Never reports rolled_back until complete."""
        with tempfile.TemporaryDirectory() as td:
            state_dir = Path(td) / "state"
            target = Path(td) / "settings.json"
            target.write_text('{"extensions": []}\n', encoding="utf-8")
            other = Path(td) / "global.json"
            other.write_text('{"extensions": []}\n', encoding="utf-8")
            docs = {"project": {"extensions": []}, "global": {"extensions": []}}
            targets = {"project": target, "global": other}
            # Apply.
            self.blg.apply_transaction(
                targets=targets, documents=docs, policy=self.policy,
                state_dir=state_dir,
                checkpoint_sink=self._make_sink(),
            )
            # Simulate interrupted rollback: set status to rollback_in_progress.
            jpath = state_dir / "apply-journal.json"
            journal = json.loads(jpath.read_text(encoding="utf-8"))
            journal["status"] = "rollback_in_progress"
            jpath.write_text(json.dumps(journal, indent=1) + "\n", encoding="utf-8")
            # Recovery must handle rollback_in_progress and complete the rollback.
            result = self.blg.recover_transaction(targets=targets, state_dir=state_dir, checkpoint_digest=self._digest())
            self.assertEqual(result["action"], "RECOVERED")
            self.assertEqual(result["status"], "rolled_back")
            # Idempotent: second recovery is a no-op.
            result2 = self.blg.recover_transaction(targets=targets, state_dir=state_dir, checkpoint_digest=self._digest())
            self.assertEqual(result2["action"], "NO_RECOVERY_NEEDED")

    def test_final_verify_failure_triggers_rollback(self):
        """H6: Final verification failure must trigger auto-rollback
        (not enter an unsupported recovery state). The write seam restores
        one target to ORIGINAL after writing (authorized state, not THIRD_STATE),
        so final-verify fails but rollback can proceed."""
        with tempfile.TemporaryDirectory() as td:
            state_dir = Path(td) / "state"
            original_text = '{"extensions": []}\n'
            target = Path(td) / "settings.json"
            target.write_text(original_text, encoding="utf-8")
            other = Path(td) / "global.json"
            other.write_text(original_text, encoding="utf-8")
            docs = {"project": {"extensions": []}, "global": {"extensions": []}}
            targets = {"project": target, "global": other}
            # Inject a write that succeeds normally but then restores global
            # to its ORIGINAL content (authorized state, NOT a third state).
            # This makes final-verify fail (global at original, not applied)
            # while rollback can still proceed (original=skip, applied=restore).
            def reverting_write(path, data):
                self.blg._atomic_write(path, data)
                if "global" in str(path):
                    # Restore to original (authorized state for rollback).
                    Path(path).write_text(original_text, encoding="utf-8")
            with self.assertRaises(self.blg.GuardError):
                self.blg.apply_transaction(
                    targets=targets, documents=docs, policy=self.policy,
                    state_dir=state_dir, write=reverting_write,
                    checkpoint_sink=self._make_sink(),
                )
            # After auto-rollback, both targets must be at original.
            self.assertEqual(target.read_text(encoding="utf-8"), original_text)
            self.assertEqual(other.read_text(encoding="utf-8"), original_text)

    def test_recovery_returns_reloaded_status(self):
        """M2: recover_transaction must return the reloaded persisted status,
        not the stale pre-recovery dict value."""
        with tempfile.TemporaryDirectory() as td:
            state_dir = Path(td) / "state"
            target = Path(td) / "settings.json"
            target.write_text('{"extensions": []}\n', encoding="utf-8")
            other = Path(td) / "global.json"
            other.write_text('{"extensions": []}\n', encoding="utf-8")
            docs = {"project": {"extensions": []}, "global": {"extensions": []}}
            targets = {"project": target, "global": other}
            # Apply.
            self.blg.apply_transaction(
                targets=targets, documents=docs, policy=self.policy,
                state_dir=state_dir,
                checkpoint_sink=self._make_sink(),
            )
            # Simulate interrupted apply: set status to in_progress.
            jpath = state_dir / "apply-journal.json"
            journal = json.loads(jpath.read_text(encoding="utf-8"))
            journal["status"] = "in_progress"
            jpath.write_text(json.dumps(journal, indent=1) + "\n", encoding="utf-8")
            # Recovery should complete rollback and return rolled_back.
            result = self.blg.recover_transaction(targets=targets, state_dir=state_dir, checkpoint_digest=self._digest())
            self.assertEqual(result["action"], "RECOVERED")
            # M2: returned status must be the PERSISTED status (rolled_back),
            # not the pre-recovery status (in_progress).
            self.assertEqual(result["status"], "rolled_back")

    def test_manifest_failure_leaves_recoverable_state(self):
        """M3: If manifest write fails, journal status must remain
        recoverable (not applied). Retry must work."""
        with tempfile.TemporaryDirectory() as td:
            state_dir = Path(td) / "state"
            target = Path(td) / "settings.json"
            target.write_text('{"extensions": []}\n', encoding="utf-8")
            other = Path(td) / "global.json"
            other.write_text('{"extensions": []}\n', encoding="utf-8")
            docs = {"project": {"extensions": []}, "global": {"extensions": []}}
            targets = {"project": target, "global": other}
            # Inject a failing manifest write by making the manifest path
            # a directory (write will fail).
            manifest_path = state_dir / "rollback-manifest.json"
            manifest_path.mkdir(parents=True)  # directory, not file
            with self.assertRaises((self.blg.GuardError, OSError)):
                self.blg.apply_transaction(
                    targets=targets, documents=docs, policy=self.policy,
                    state_dir=state_dir,
                    checkpoint_sink=self._make_sink(),
                )
            # Journal must NOT be at applied (M3: manifest before applied).
            jpath = state_dir / "apply-journal.json"
            journal = json.loads(jpath.read_text(encoding="utf-8"))
            self.assertNotEqual(journal["status"], "applied")


    # --- H7 Matrix: First Three Negative Tests (Master scope ruling) ---

    def test_h7_missing_authority_refuses_rollback_and_recover(self):
        """H7-1: Missing/None caller authority refuses public rollback AND
        recover on existing journal. Target/journal bytes unchanged."""
        with tempfile.TemporaryDirectory() as td:
            state_dir = Path(td) / "state"
            state_dir.mkdir(parents=True)
            target = Path(td) / "settings.json"
            target.write_text('{"extensions": []}\n', encoding="utf-8")
            other = Path(td) / "global.json"
            other.write_text('{"extensions": []}\n', encoding="utf-8")
            docs = {"project": {"extensions": []}, "global": {"extensions": []}}
            targets = {"project": target, "global": other}
            # Valid apply with sink (legitimate setup).
            self.blg.apply_transaction(
                targets=targets, documents=docs, policy=self.policy,
                state_dir=state_dir, checkpoint_sink=self._make_sink(),
            )
            # Snapshot bytes before rejected calls.
            jpath = state_dir / "apply-journal.json"
            journal_before = jpath.read_bytes()
            target_before = target.read_bytes()
            other_before = other.read_bytes()
            # Rollback with None: must refuse.
            with self.assertRaises(self.blg.GuardError) as ctx_rb:
                self.blg.rollback_transaction(
                    targets=targets, state_dir=state_dir, checkpoint_digest=None,
                )
            self.assertIn("H7", str(ctx_rb.exception))
            # Recover with None: must refuse.
            with self.assertRaises(self.blg.GuardError) as ctx_rc:
                self.blg.recover_transaction(
                    targets=targets, state_dir=state_dir, checkpoint_digest=None,
                )
            self.assertIn("H7", str(ctx_rc.exception))
            # Bytes unchanged.
            self.assertEqual(jpath.read_bytes(), journal_before)
            self.assertEqual(target.read_bytes(), target_before)
            self.assertEqual(other.read_bytes(), other_before)

    def test_h7_deleted_stored_seal_refuses_even_with_genuine_digest(self):
        """H7-2: Delete stored checkpoint_digest from journal after valid
        apply. Both public entrypoints reject even with genuine
        independently sink-held digest. No target/state writes."""
        with tempfile.TemporaryDirectory() as td:
            state_dir = Path(td) / "state"
            state_dir.mkdir(parents=True)
            target = Path(td) / "settings.json"
            target.write_text('{"extensions": []}\n', encoding="utf-8")
            other = Path(td) / "global.json"
            other.write_text('{"extensions": []}\n', encoding="utf-8")
            docs = {"project": {"extensions": []}, "global": {"extensions": []}}
            targets = {"project": target, "global": other}
            # Valid apply with sink.
            self.blg.apply_transaction(
                targets=targets, documents=docs, policy=self.policy,
                state_dir=state_dir, checkpoint_sink=self._make_sink(),
            )
            genuine_digest = self._digest()  # from sink memory, NOT journal
            # Snapshot.
            jpath = state_dir / "apply-journal.json"
            target_before = target.read_bytes()
            other_before = other.read_bytes()
            # Attacker deletes stored checkpoint_digest field.
            journal = json.loads(jpath.read_text(encoding="utf-8"))
            del journal["checkpoint_digest"]
            jpath.write_text(json.dumps(journal, indent=1) + "\n", encoding="utf-8")
            # Rollback with genuine digest: must refuse (stored field missing = schema failure).
            with self.assertRaises(self.blg.GuardError) as ctx_rb:
                self.blg.rollback_transaction(
                    targets=targets, state_dir=state_dir, checkpoint_digest=genuine_digest,
                )
            self.assertIn("checkpoint_digest", str(ctx_rb.exception))
            # Recover with genuine digest: must refuse.
            with self.assertRaises(self.blg.GuardError) as ctx_rc:
                self.blg.recover_transaction(
                    targets=targets, state_dir=state_dir, checkpoint_digest=genuine_digest,
                )
            self.assertIn("checkpoint_digest", str(ctx_rc.exception))
            # No target/state writes.
            self.assertEqual(target.read_bytes(), target_before)
            self.assertEqual(other.read_bytes(), other_before)

    def test_h7_wrong_authority_refuses_terminal_statuses(self):
        """H7-3: Wrong authority refuses BOTH rollback and recover for
        terminal applied AND rolled_back journals. No terminal/no-op bypass.
        Uses genuine saved digest for legitimate setup only."""
        with tempfile.TemporaryDirectory() as td:
            state_dir = Path(td) / "state"
            state_dir.mkdir(parents=True)
            target = Path(td) / "settings.json"
            target.write_text('{"extensions": []}\n', encoding="utf-8")
            other = Path(td) / "global.json"
            other.write_text('{"extensions": []}\n', encoding="utf-8")
            docs = {"project": {"extensions": []}, "global": {"extensions": []}}
            targets = {"project": target, "global": other}
            # Valid apply with sink.
            self.blg.apply_transaction(
                targets=targets, documents=docs, policy=self.policy,
                state_dir=state_dir, checkpoint_sink=self._make_sink(),
            )
            genuine_digest = self._digest()
            wrong_digest = "0" * 64  # valid format, wrong value
            jpath = state_dir / "apply-journal.json"
            target_before = target.read_bytes()
            other_before = other.read_bytes()
            # Terminal status: applied (current state after apply).
            journal = json.loads(jpath.read_text(encoding="utf-8"))
            self.assertEqual(journal["status"], "applied")
            # Wrong digest on applied journal: rollback refuses.
            with self.assertRaises(self.blg.GuardError) as ctx_rb_applied:
                self.blg.rollback_transaction(
                    targets=targets, state_dir=state_dir, checkpoint_digest=wrong_digest,
                )
            self.assertIn("H7", str(ctx_rb_applied.exception))
            # Wrong digest on applied journal: recover refuses.
            with self.assertRaises(self.blg.GuardError) as ctx_rc_applied:
                self.blg.recover_transaction(
                    targets=targets, state_dir=state_dir, checkpoint_digest=wrong_digest,
                )
            self.assertIn("H7", str(ctx_rc_applied.exception))
            # Now legitimately roll back with correct digest.
            self.blg.rollback_transaction(
                targets=targets, state_dir=state_dir, checkpoint_digest=genuine_digest,
            )
            # Terminal status: rolled_back.
            journal2 = json.loads(jpath.read_text(encoding="utf-8"))
            self.assertEqual(journal2["status"], "rolled_back")
            target_before2 = target.read_bytes()
            other_before2 = other.read_bytes()
            # Wrong digest on rolled_back journal: rollback refuses.
            with self.assertRaises(self.blg.GuardError) as ctx_rb_rb:
                self.blg.rollback_transaction(
                    targets=targets, state_dir=state_dir, checkpoint_digest=wrong_digest,
                )
            self.assertIn("H7", str(ctx_rb_rb.exception))
            # Wrong digest on rolled_back journal: recover refuses.
            with self.assertRaises(self.blg.GuardError) as ctx_rc_rb:
                self.blg.recover_transaction(
                    targets=targets, state_dir=state_dir, checkpoint_digest=wrong_digest,
                )
            self.assertIn("H7", str(ctx_rc_rb.exception))
            # Bytes unchanged by rejected calls.
            self.assertEqual(target.read_bytes(), target_before2)
            self.assertEqual(other.read_bytes(), other_before2)


    # --- H7 Callback Tests (Master scope ruling: exactly 3) ---

    def test_h7_sink_called_before_helper_writes(self):
        """H7-CB1: Sink is called BEFORE helper backup/journal/target writes.
        Observe actual write seams (backup + atomic). At callback time,
        no owned state files exist. Sink-held digest supports legitimate
        rollback."""
        with tempfile.TemporaryDirectory() as td:
            state_dir = Path(td) / "state"
            state_dir.mkdir(parents=True)
            target = Path(td) / "settings.json"
            target.write_text('{"extensions": []}\n', encoding="utf-8")
            other = Path(td) / "global.json"
            other.write_text('{"extensions": []}\n', encoding="utf-8")
            docs = {"project": {"extensions": []}, "global": {"extensions": []}}
            targets = {"project": target, "global": other}
            # Track write order: sink vs backup/atomic writes.
            write_order = []
            state_files_at_sink = [None]
            def observing_sink(descriptor, digest):
                write_order.append("sink")
                # At sink time: no backup/journal files should exist yet.
                state_files_at_sink[0] = {
                    "project_backup": (state_dir / "project-settings.json.orig").exists(),
                    "global_backup": (state_dir / "global-settings.json.orig").exists(),
                    "journal": (state_dir / "apply-journal.json").exists(),
                }
                self._captured_descriptor = json.loads(json.dumps(descriptor))
                self._captured_digest = digest
            # Patch backup write channel (Path.write_bytes on state_dir children).
            real_write_bytes = Path.write_bytes
            def observing_write_bytes(self_path, data):
                if self_path.parent == state_dir:
                    write_order.append(f"backup_write:{self_path.name}")
                real_write_bytes(self_path, data)
            # Patch _atomic_write to observe journal/target writes.
            real_atomic_write = self.blg._atomic_write
            def observing_atomic_write(path, data):
                write_order.append(f"atomic_write:{Path(path).name}")
                real_atomic_write(path, data)
            with mock.patch.object(Path, "write_bytes", autospec=True, side_effect=observing_write_bytes):
                with mock.patch.object(self.blg, "_atomic_write", side_effect=observing_atomic_write):
                    self.blg.prepare_transaction(
                        targets=targets, documents=docs, policy=self.policy,
                        state_dir=state_dir, checkpoint_sink=observing_sink,
                    )
            # Sink must be FIRST in write order.
            self.assertEqual(write_order[0], "sink")
            # At sink time: NO state files existed.
            self.assertFalse(state_files_at_sink[0]["project_backup"])
            self.assertFalse(state_files_at_sink[0]["global_backup"])
            self.assertFalse(state_files_at_sink[0]["journal"])
            # All subsequent entries are writes (backup or atomic).
            for i, entry in enumerate(write_order):
                if i > 0:
                    self.assertTrue(
                        entry.startswith("backup_write:") or entry.startswith("atomic_write:"),
                        f"Unexpected entry at position {i}: {entry}"
                    )
            # Sink-held digest supports legitimate rollback.
            self.assertIsNotNone(self._captured_digest)
            self.blg.rollback_transaction(
                targets=targets, state_dir=state_dir,
                checkpoint_digest=self._captured_digest,
            )
            # Targets restored to original.
            self.assertEqual(target.read_text(encoding="utf-8"), '{"extensions": []}\n')
            self.assertEqual(other.read_text(encoding="utf-8"), '{"extensions": []}\n')

    def test_h7_sink_raises_zero_helper_writes(self):
        """H7-CB2: Sink raises -> stable refusal with zero helper
        backup/journal/target writes. Existing target bytes unchanged."""
        with tempfile.TemporaryDirectory() as td:
            state_dir = Path(td) / "state"
            state_dir.mkdir(parents=True)
            target = Path(td) / "settings.json"
            target.write_text('{"extensions": []}\n', encoding="utf-8")
            other = Path(td) / "global.json"
            other.write_text('{"extensions": []}\n', encoding="utf-8")
            docs = {"project": {"extensions": []}, "global": {"extensions": []}}
            targets = {"project": target, "global": other}
            # Snapshot target bytes.
            target_before = target.read_bytes()
            other_before = other.read_bytes()
            # Counting sink that raises with a synthetic secret marker.
            SECRET_MARKER = "TEST_SECRET_MARKER_XK99"
            def raising_sink(descriptor, digest):
                raise RuntimeError(f"sink refused: {SECRET_MARKER}")
            # Patch _atomic_write to count calls (should be zero).
            write_count = [0]
            real_atomic_write = self.blg._atomic_write
            def counting_atomic_write(path, data):
                write_count[0] += 1
                real_atomic_write(path, data)
            with mock.patch.object(self.blg, "_atomic_write", side_effect=counting_atomic_write):
                with self.assertRaises(self.blg.GuardError) as ctx:
                    self.blg.prepare_transaction(
                        targets=targets, documents=docs, policy=self.policy,
                        state_dir=state_dir, checkpoint_sink=raising_sink,
                    )
            # Secret marker must be absent from formatted exception/traceback.
            import traceback as _tb
            exc = ctx.exception
            # Format the caught exception explicitly (not format_exc which
            # is empty after assertRaises context exits).
            formatted = "".join(_tb.format_exception(type(exc), exc, exc.__traceback__))
            # Require actual GuardError message in formatted output.
            self.assertIn("GuardError", formatted)
            self.assertIn("checkpoint_sink callback failed", formatted)
            # Marker absent from formatted traceback and str.
            self.assertNotIn(SECRET_MARKER, formatted)
            self.assertNotIn(SECRET_MARKER, str(exc))
            # Context suppression: __suppress_context__ must be True.
            self.assertTrue(exc.__suppress_context__)
            # No cause chain.
            self.assertIsNone(exc.__cause__)
            # Zero helper writes.
            self.assertEqual(write_count[0], 0)
            # No backup files created.
            self.assertFalse((state_dir / "project-settings.json.orig").exists())
            self.assertFalse((state_dir / "global-settings.json.orig").exists())
            # No journal created.
            self.assertFalse((state_dir / "apply-journal.json").exists())
            # Target bytes unchanged.
            self.assertEqual(target.read_bytes(), target_before)
            self.assertEqual(other.read_bytes(), other_before)

    def test_h7_sink_mutates_descriptor_copy_refused(self):
        """H7-CB3: Sink mutates nested descriptor COPY -> immediate refusal
        before helper writes. Internal authority not contaminated. Failure
        is NOT postponed to later recovery."""
        with tempfile.TemporaryDirectory() as td:
            state_dir = Path(td) / "state"
            state_dir.mkdir(parents=True)
            target = Path(td) / "settings.json"
            target.write_text('{"extensions": []}\n', encoding="utf-8")
            other = Path(td) / "global.json"
            other.write_text('{"extensions": []}\n', encoding="utf-8")
            docs = {"project": {"extensions": []}, "global": {"extensions": []}}
            targets = {"project": target, "global": other}
            # Snapshot.
            target_before = target.read_bytes()
            other_before = other.read_bytes()
            # Sink that mutates a nested field in the descriptor copy.
            def mutating_sink(descriptor, digest):
                # Mutate nested target hash (simulates attacker tampering).
                descriptor["targets"]["project"]["original_sha256"] = "f" * 64
            # Counting atomic_write (should be zero).
            write_count = [0]
            real_atomic_write = self.blg._atomic_write
            def counting_atomic_write(path, data):
                write_count[0] += 1
                real_atomic_write(path, data)
            with mock.patch.object(self.blg, "_atomic_write", side_effect=counting_atomic_write):
                with self.assertRaises(self.blg.GuardError) as ctx:
                    self.blg.prepare_transaction(
                        targets=targets, documents=docs, policy=self.policy,
                        state_dir=state_dir, checkpoint_sink=mutating_sink,
                    )
            # Immediate refusal (not postponed).
            self.assertIn("mutated", str(ctx.exception))
            # Zero helper writes.
            self.assertEqual(write_count[0], 0)
            # No journal/backup created.
            self.assertFalse((state_dir / "apply-journal.json").exists())
            self.assertFalse((state_dir / "project-settings.json.orig").exists())
            # Target bytes unchanged.
            self.assertEqual(target.read_bytes(), target_before)
            self.assertEqual(other.read_bytes(), other_before)


    # --- H7 Tamper Group (3 methods) ---

    def test_h7_tampered_hash_and_forged_seal_refused(self):
        """H7-T1: Immutable-field tampering (original_sha256) plus forged
        STORED seal must fail both public rollback/recover while using
        unchanged genuine SINK-held expected digest. Targets/journal
        unchanged by rejected calls."""
        with tempfile.TemporaryDirectory() as td:
            state_dir = Path(td) / "state"
            state_dir.mkdir(parents=True)
            target = Path(td) / "settings.json"
            target.write_text('{"extensions": []}\n', encoding="utf-8")
            other = Path(td) / "global.json"
            other.write_text('{"extensions": []}\n', encoding="utf-8")
            docs = {"project": {"extensions": []}, "global": {"extensions": []}}
            targets = {"project": target, "global": other}
            # Valid apply with sink (legitimate setup).
            self.blg.apply_transaction(
                targets=targets, documents=docs, policy=self.policy,
                state_dir=state_dir, checkpoint_sink=self._make_sink(),
            )
            genuine_digest = self._digest()  # from sink memory
            jpath = state_dir / "apply-journal.json"
            target_before = target.read_bytes()
            other_before = other.read_bytes()
            journal_before = jpath.read_bytes()
            # Attacker tampers original_sha256 AND forges stored seal.
            journal = json.loads(jpath.read_text(encoding="utf-8"))
            journal["targets"]["project"]["original_sha256"] = "e" * 64
            # Forge stored seal to match tampered descriptor (attacker compute).
            tampered_descriptor = self.blg.compute_checkpoint_descriptor(journal)
            forged_seal = self.blg.compute_checkpoint_digest(tampered_descriptor)
            journal["checkpoint_digest"] = forged_seal
            jpath.write_text(json.dumps(journal, indent=1) + "\n", encoding="utf-8")
            # Caller uses GENUINE sink-held digest (NOT the forged seal).
            # Rollback must refuse (genuine != recomputed from tampered journal).
            with self.assertRaises(self.blg.GuardError) as ctx_rb:
                self.blg.rollback_transaction(
                    targets=targets, state_dir=state_dir,
                    checkpoint_digest=genuine_digest,
                )
            self.assertIn("H7", str(ctx_rb.exception))
            # Recover must also refuse.
            with self.assertRaises(self.blg.GuardError) as ctx_rc:
                self.blg.recover_transaction(
                    targets=targets, state_dir=state_dir,
                    checkpoint_digest=genuine_digest,
                )
            self.assertIn("H7", str(ctx_rc.exception))
            # Targets unchanged by rejected calls.
            self.assertEqual(target.read_bytes(), target_before)
            self.assertEqual(other.read_bytes(), other_before)

    def test_h7_cross_transaction_replay_refused(self):
        """H7-T2: Checkpoint from tx-A replayed against separately owned
        tx-B -> refusal, no writes."""
        with tempfile.TemporaryDirectory() as td:
            state_dir_a = Path(td) / "state_a"
            state_dir_b = Path(td) / "state_b"
            state_dir_a.mkdir(parents=True)
            state_dir_b.mkdir(parents=True)
            # TX-A: valid apply.
            target_a = Path(td) / "a_settings.json"
            target_a.write_text('{"extensions": []}\n', encoding="utf-8")
            other_a = Path(td) / "a_global.json"
            other_a.write_text('{"extensions": []}\n', encoding="utf-8")
            targets_a = {"project": target_a, "global": other_a}
            docs = {"project": {"extensions": []}, "global": {"extensions": []}}
            self.blg.apply_transaction(
                targets=targets_a, documents=docs, policy=self.policy,
                state_dir=state_dir_a, checkpoint_sink=self._make_sink(),
            )
            digest_a = self._digest()  # TX-A checkpoint
            # TX-B: separate valid apply (different state_dir, different targets).
            target_b = Path(td) / "b_settings.json"
            target_b.write_text('{"extensions": []}\n', encoding="utf-8")
            other_b = Path(td) / "b_global.json"
            other_b.write_text('{"extensions": []}\n', encoding="utf-8")
            targets_b = {"project": target_b, "global": other_b}
            self.blg.apply_transaction(
                targets=targets_b, documents=docs, policy=self.policy,
                state_dir=state_dir_b, checkpoint_sink=self._make_sink(),
            )
            digest_b = self._digest()  # TX-B checkpoint
            # Snapshot TX-B state.
            jpath_b = state_dir_b / "apply-journal.json"
            target_b_before = target_b.read_bytes()
            other_b_before = other_b.read_bytes()
            journal_b_before = jpath_b.read_bytes()
            # Replay TX-A digest against TX-B journal: must refuse.
            with self.assertRaises(self.blg.GuardError) as ctx_rb:
                self.blg.rollback_transaction(
                    targets=targets_b, state_dir=state_dir_b,
                    checkpoint_digest=digest_a,  # WRONG tx
                )
            self.assertIn("H7", str(ctx_rb.exception))
            # Recover with TX-A digest on TX-B: must refuse.
            with self.assertRaises(self.blg.GuardError) as ctx_rc:
                self.blg.recover_transaction(
                    targets=targets_b, state_dir=state_dir_b,
                    checkpoint_digest=digest_a,  # WRONG tx
                )
            self.assertIn("H7", str(ctx_rc.exception))
            # TX-B state unchanged.
            self.assertEqual(target_b.read_bytes(), target_b_before)
            self.assertEqual(other_b.read_bytes(), other_b_before)
            self.assertEqual(jpath_b.read_bytes(), journal_b_before)

    def test_h7_wrong_prior_checkpoint_refuses_new_prepare(self):
        """H7-T3: Wrong PRIOR checkpoint for new prepare/apply over existing
        journal -> refuse before replacement checkpoint mint or prior
        journal/backup/target changes."""
        with tempfile.TemporaryDirectory() as td:
            state_dir = Path(td) / "state"
            state_dir.mkdir(parents=True)
            target = Path(td) / "settings.json"
            target.write_text('{"extensions": []}\n', encoding="utf-8")
            other = Path(td) / "global.json"
            other.write_text('{"extensions": []}\n', encoding="utf-8")
            docs = {"project": {"extensions": []}, "global": {"extensions": []}}
            targets = {"project": target, "global": other}
            # Valid apply (creates existing journal).
            self.blg.apply_transaction(
                targets=targets, documents=docs, policy=self.policy,
                state_dir=state_dir, checkpoint_sink=self._make_sink(),
            )
            # Snapshot existing state.
            jpath = state_dir / "apply-journal.json"
            journal_before = jpath.read_bytes()
            target_before = target.read_bytes()
            other_before = other.read_bytes()
            backup_a_before = (state_dir / "project-settings.json.orig").read_bytes()
            backup_b_before = (state_dir / "global-settings.json.orig").read_bytes()
            # WRONG prior checkpoint (not from this transaction).
            wrong_prior = "b" * 64
            # New prepare/apply with wrong prior: must refuse BEFORE any
            # replacement checkpoint mint or prior state changes.
            with self.assertRaises(self.blg.GuardError) as ctx:
                self.blg.apply_transaction(
                    targets=targets, documents=docs, policy=self.policy,
                    state_dir=state_dir, checkpoint_sink=self._make_sink(),
                    prior_checkpoint_digest=wrong_prior,
                )
            # Must be a checkpoint/H7 error, NOT a stale-document error.
            self.assertIn("H7", str(ctx.exception))
            self.assertNotIn("stale", str(ctx.exception))
            # Prior state unchanged (no replacement, no overwrite).
            self.assertEqual(jpath.read_bytes(), journal_before)
            self.assertEqual(target.read_bytes(), target_before)
            self.assertEqual(other.read_bytes(), other_before)
            self.assertEqual(
                (state_dir / "project-settings.json.orig").read_bytes(), backup_a_before
            )
            self.assertEqual(
                (state_dir / "global-settings.json.orig").read_bytes(), backup_b_before
            )


    # --- H7 Schema/Type Snapshot Tests (3 methods) ---

    def test_h7_typed_stale_snapshot_bool_vs_numeric_rejected(self):
        """H7-ST1: Python True==1 but JSON types differ. A document with
        bool True where the file has numeric 1 (or vice versa) in a nested
        unrelated field must be rejected as stale. Not treated as equal."""
        with tempfile.TemporaryDirectory() as td:
            state_dir = Path(td) / "state"
            state_dir.mkdir(parents=True)
            # File has numeric 1 in a nested unrelated field.
            file_content = '{"extensions": [], "nested": {"count": 1}}\n'
            target = Path(td) / "settings.json"
            target.write_text(file_content, encoding="utf-8")
            other = Path(td) / "global.json"
            other.write_text('{"extensions": []}\n', encoding="utf-8")
            targets = {"project": target, "global": other}
            # Document has bool True (Python True == 1, but JSON types differ).
            docs = {"project": {"extensions": [], "nested": {"count": True}},
                    "global": {"extensions": []}}
            # Snapshot: no state files should be created.
            with self.assertRaises(self.blg.GuardError) as ctx:
                self.blg.prepare_transaction(
                    targets=targets, documents=docs, policy=self.policy,
                    state_dir=state_dir, checkpoint_sink=self._make_sink(),
                )
            # Must be stale rejection, not a different error.
            self.assertIn("stale", str(ctx.exception))
            # No helper state/target writes.
            self.assertFalse((state_dir / "project-settings.json.orig").exists())
            self.assertFalse((state_dir / "global-settings.json.orig").exists())
            self.assertFalse((state_dir / "apply-journal.json").exists())
            # Target unchanged.
            self.assertEqual(target.read_text(encoding="utf-8"), file_content)

    def test_h7_unknown_progress_status_rejected_by_public_entrypoints(self):
        """H7-ST2: Unknown root AND per-target progress status rejected by
        BOTH public recover/rollback before writes. Uses genuine sink-held
        checkpoint. Unknown progress is excluded from digest, so this tests
        status-only bypass, not wrong authority."""
        with tempfile.TemporaryDirectory() as td:
            state_dir = Path(td) / "state"
            state_dir.mkdir(parents=True)
            target = Path(td) / "settings.json"
            target.write_text('{"extensions": []}\n', encoding="utf-8")
            other = Path(td) / "global.json"
            other.write_text('{"extensions": []}\n', encoding="utf-8")
            docs = {"project": {"extensions": []}, "global": {"extensions": []}}
            targets = {"project": target, "global": other}
            # Valid apply (legitimate setup).
            self.blg.apply_transaction(
                targets=targets, documents=docs, policy=self.policy,
                state_dir=state_dir, checkpoint_sink=self._make_sink(),
            )
            genuine_digest = self._digest()
            jpath = state_dir / "apply-journal.json"
            target_before = target.read_bytes()
            other_before = other.read_bytes()
            journal_before = jpath.read_bytes()
            # Attacker sets unknown root status + unknown per-target status.
            journal = json.loads(jpath.read_text(encoding="utf-8"))
            journal["status"] = "mysterious_unknown_status"
            journal["targets"]["project"]["status"] = "weird_target_state"
            jpath.write_text(json.dumps(journal, indent=1) + "\n", encoding="utf-8")
            # Public recover with genuine digest: must reject unknown status.
            with self.assertRaises(self.blg.GuardError) as ctx_rc:
                self.blg.recover_transaction(
                    targets=targets, state_dir=state_dir,
                    checkpoint_digest=genuine_digest,
                )
            # Must be a status/recovery error, not a digest mismatch.
            self.assertNotIn("does not match recomputed", str(ctx_rc.exception))
            # Public rollback with genuine digest: must also reject.
            with self.assertRaises(self.blg.GuardError) as ctx_rb:
                self.blg.rollback_transaction(
                    targets=targets, state_dir=state_dir,
                    checkpoint_digest=genuine_digest,
                )
            self.assertNotIn("does not match recomputed", str(ctx_rb.exception))
            # No writes from rejected calls.
            self.assertEqual(target.read_bytes(), target_before)
            self.assertEqual(other.read_bytes(), other_before)

    def test_h7_legacy_schema_and_ill_typed_version_rejected(self):
        """H7-ST3: Legacy/unsealed schema (v1) and ill-typed journal version
        (e.g. 2.0 float instead of int 2) rejected specifically by
        schema/version gate, not merely eventual digest mismatch."""
        with tempfile.TemporaryDirectory() as td:
            state_dir = Path(td) / "state"
            state_dir.mkdir(parents=True)
            target = Path(td) / "settings.json"
            target.write_text('{"extensions": []}\n', encoding="utf-8")
            other = Path(td) / "global.json"
            other.write_text('{"extensions": []}\n', encoding="utf-8")
            targets = {"project": target, "global": other}
            jpath = state_dir / "apply-journal.json"
            target_before = target.read_bytes()
            other_before = other.read_bytes()
            # Sub-test A: Legacy v1 schema.
            legacy_journal = {
                "schema": "blg-apply-journal",  # v1 (unsealed)
                "version": 1,
                "transaction_id": "legacy",
                "status": "applied",
                "checkpoint_digest": "a" * 64,
                "targets": {
                    "project": {"path": str(target), "original_sha256": "a", "applied_sha256": "b", "backup": "x", "status": "applied"},
                    "global": {"path": str(other), "original_sha256": "c", "applied_sha256": "d", "backup": "y", "status": "applied"},
                },
            }
            jpath.write_text(json.dumps(legacy_journal), encoding="utf-8")
            with self.assertRaises(self.blg.GuardError) as ctx_legacy:
                self.blg.rollback_transaction(
                    targets=targets, state_dir=state_dir,
                    checkpoint_digest="a" * 64,
                )
            # Must be schema rejection, not digest mismatch.
            self.assertIn("schema", str(ctx_legacy.exception).lower())
            self.assertNotIn("does not match recomputed", str(ctx_legacy.exception))
            # Sub-test B: Ill-typed version (float 2.0 instead of int 2).
            bad_version_journal = {
                "schema": "blg-apply-journal-v2",
                "version": 2.0,  # float, not int
                "transaction_id": "x",
                "status": "applied",
                "checkpoint_digest": "a" * 64,
                "targets": {
                    "project": {"path": str(target), "original_sha256": "a", "applied_sha256": "b", "backup": "x", "status": "applied"},
                    "global": {"path": str(other), "original_sha256": "c", "applied_sha256": "d", "backup": "y", "status": "applied"},
                },
            }
            jpath.write_text(json.dumps(bad_version_journal), encoding="utf-8")
            with self.assertRaises(self.blg.GuardError) as ctx_ver:
                self.blg.recover_transaction(
                    targets=targets, state_dir=state_dir,
                    checkpoint_digest="a" * 64,
                )
            # Must be version rejection.
            self.assertIn("version", str(ctx_ver.exception).lower())
            # No target writes from either rejection.
            self.assertEqual(target.read_bytes(), target_before)
            self.assertEqual(other.read_bytes(), other_before)


    # --- M4: Stable-Code Sanitization Regression ---

    def test_m4_no_raw_values_in_guarderror_messages(self):
        """M4: Synthetic TEST_ markers in package source, profile, and
        target path must be absent from GuardError messages and formatted
        exceptions. Tests are non-vacuous: genuine exception/code/message
        must be present in formatted output."""
        SECRET_SOURCE = "TEST_SECRET_SRC_M4_001"
        SECRET_PROFILE = "TEST_SECRET_PROF_M4_002"
        SECRET_PATH = "TEST_SECRET_PATH_M4_003"
        with tempfile.TemporaryDirectory() as td:
            state_dir = Path(td) / "state"
            state_dir.mkdir(parents=True)
            # Target with secret in path name.
            target = Path(td) / f"{SECRET_PATH}.json"
            target.write_text('{"extensions": []}\n', encoding="utf-8")
            other = Path(td) / "global.json"
            other.write_text('{"extensions": []}\n', encoding="utf-8")
            targets = {"project": target, "global": other}
            # Documents with secret in package source.
            docs = {"project": {"extensions": [], "packages": [SECRET_SOURCE]},
                    "global": {"extensions": []}}
            # Policy with secret in profile name.
            policy = {
                "profiles": {
                    SECRET_PROFILE: {
                        "global": {"extensions": [], "skills": []},
                        "project": {"extensions": [], "skills": []},
                    }
                },
                "package_policy": {"approved": {}},
            }
            # Trigger a GuardError (missing profile in policy).
            with self.assertRaises(self.blg.GuardError) as ctx:
                self.blg.build_candidate_documents(docs, policy, "bootstrap")
            exc = ctx.exception
            # Format the caught exception explicitly.
            import traceback as _tb
            formatted = "".join(_tb.format_exception(type(exc), exc, exc.__traceback__))
            # Non-vacuous: genuine exception type and code present.
            self.assertIn("GuardError", formatted)
            self.assertIn("BLG-E", formatted)
            # Markers absent from message and formatted output.
            self.assertNotIn(SECRET_SOURCE, str(exc))
            self.assertNotIn(SECRET_PROFILE, str(exc))
            self.assertNotIn(SECRET_PATH, str(exc))
            self.assertNotIn(SECRET_SOURCE, formatted)
            self.assertNotIn(SECRET_PROFILE, formatted)
            self.assertNotIn(SECRET_PATH, formatted)

            # Subcase: invalid JSON/encoding parse in prepare.
            # Target file contains invalid JSON (not parseable).
            bad_target = Path(td) / "bad.json"
            bad_target.write_text('not valid json{{{\n', encoding="utf-8")
            bad_other = Path(td) / "bad_global.json"
            bad_other.write_text('{"extensions": []}\n', encoding="utf-8")
            bad_targets = {"project": bad_target, "global": bad_other}
            bad_docs = {"project": {"extensions": []}, "global": {"extensions": []}}
            with self.assertRaises(self.blg.GuardError) as ctx_parse:
                self.blg.prepare_transaction(
                    targets=bad_targets, documents=bad_docs, policy=self.policy,
                    state_dir=state_dir, checkpoint_sink=self._make_sink(),
                )
            exc_parse = ctx_parse.exception
            # Format explicitly (not vacuous format_exc).
            formatted_parse = "".join(_tb.format_exception(type(exc_parse), exc_parse, exc_parse.__traceback__))
            # Non-vacuous: genuine exception + static code present.
            self.assertIn("GuardError", formatted_parse)
            self.assertIn("BLG-E020", formatted_parse)
            # Context suppressed.
            self.assertTrue(exc_parse.__suppress_context__)
            self.assertIsNone(exc_parse.__cause__)
            # No raw parse error details leaked.
            self.assertNotIn("not valid json", formatted_parse)


    # --- M5 Boundary Tests (3 methods) ---

    def test_m5_rollback_interruption_matrix(self):
        """M5-B1: Rollback interruption at four boundaries:
        before1, after1, before2, after2. Counts writes to ACTUAL target
        paths (not journal ordinal). Fresh setup per subcase."""
        original_text = '{"extensions": []}\n'
        docs = {"project": {"extensions": []}, "global": {"extensions": []}}
        # Four boundaries with explicit mode:
        #   "before" N: raise BEFORE the Nth target write completes
        #   "after" N:  raise AFTER the Nth target write completes
        # target_write_limit = number of target writes that complete before interruption.
        cases = [
            ("before1", 0, "before"),  # 0 complete, raise before 1st
            ("after1", 1, "after"),    # 1 complete, raise after 1st
            ("before2", 1, "before"),  # 1 complete, raise before 2nd
            ("after2", 2, "after"),    # 2 complete, raise after 2nd
        ]
        for boundary_name, target_write_limit, mode in cases:
            with tempfile.TemporaryDirectory() as td:
                state_dir = Path(td) / "state"
                state_dir.mkdir(parents=True)
                target = Path(td) / "settings.json"
                target.write_text(original_text, encoding="utf-8")
                other = Path(td) / "global.json"
                other.write_text(original_text, encoding="utf-8")
                targets = {"project": target, "global": other}
                # Fresh apply.
                self.blg.apply_transaction(
                    targets=targets, documents=docs, policy=self.policy,
                    state_dir=state_dir, checkpoint_sink=self._make_sink(),
                )
                genuine_digest = self._digest()
                jpath = state_dir / "apply-journal.json"
                # Count writes to actual target paths only.
                target_write_count = [0]
                real_aw = self.blg._atomic_write
                def counting_target_write(path, data):
                    p = Path(path)
                    if p in (target, other):
                        if mode == "before":
                            # Raise before the (limit+1)th target write.
                            if target_write_count[0] >= target_write_limit:
                                raise BaseException(f"synthetic interruption: {boundary_name}")
                            real_aw(path, data)
                            target_write_count[0] += 1
                        else:  # "after"
                            real_aw(path, data)
                            target_write_count[0] += 1
                            if target_write_count[0] >= target_write_limit:
                                raise BaseException(f"synthetic interruption: {boundary_name}")
                    else:
                        real_aw(path, data)
                with mock.patch.object(self.blg, "_atomic_write", side_effect=counting_target_write):
                    with self.assertRaises(BaseException) as ctx:
                        self.blg.rollback_transaction(
                            targets=targets, state_dir=state_dir,
                            checkpoint_digest=genuine_digest,
                        )
                # Robust evidence the intended injection fired.
                self.assertIn(f"synthetic interruption: {boundary_name}", str(ctx.exception))
                # rollback_in_progress must be persisted.
                journal = json.loads(jpath.read_text(encoding="utf-8"))
                self.assertEqual(journal["status"], "rollback_in_progress")
                # Verify exact number of target writes completed.
                self.assertEqual(target_write_count[0], target_write_limit)
                # Recover with original sink checkpoint.
                result = self.blg.recover_transaction(
                    targets=targets, state_dir=state_dir,
                    checkpoint_digest=genuine_digest,
                )
                self.assertEqual(result["action"], "RECOVERED")
                self.assertEqual(result["status"], "rolled_back")
                # Exact originals restored.
                self.assertEqual(target.read_text(encoding="utf-8"), original_text)
                self.assertEqual(other.read_text(encoding="utf-8"), original_text)
                # Repeat recovery: truthful/idempotent.
                result2 = self.blg.recover_transaction(
                    targets=targets, state_dir=state_dir,
                    checkpoint_digest=genuine_digest,
                )
                self.assertEqual(result2["action"], "NO_RECOVERY_NEEDED")
                self.assertEqual(result2["status"], "rolled_back")

    def test_m5_manifest_failure_recovery_reapply(self):
        """M5-B2: Manifest-write failure -> retain authority -> valid
        recovery if needed -> remove fixture blocker -> reapply with
        legitimate PRIOR checkpoint + fresh sink. Old checkpoint cannot
        authorize new transaction."""
        with tempfile.TemporaryDirectory() as td:
            state_dir = Path(td) / "state"
            state_dir.mkdir(parents=True)
            original_text = '{"extensions": []}\n'
            target = Path(td) / "settings.json"
            target.write_text(original_text, encoding="utf-8")
            other = Path(td) / "global.json"
            other.write_text(original_text, encoding="utf-8")
            docs = {"project": {"extensions": []}, "global": {"extensions": []}}
            targets = {"project": target, "global": other}
            # Block manifest write: make manifest path a directory.
            manifest_path = state_dir / "rollback-manifest.json"
            manifest_path.mkdir(parents=True)
            # Apply will fail at manifest write.
            with self.assertRaises((self.blg.GuardError, OSError)):
                self.blg.apply_transaction(
                    targets=targets, documents=docs, policy=self.policy,
                    state_dir=state_dir, checkpoint_sink=self._make_sink(),
                )
            old_digest = self._digest()  # retained authority
            jpath = state_dir / "apply-journal.json"
            # Journal must NOT be at applied (M3: manifest before applied).
            journal = json.loads(jpath.read_text(encoding="utf-8"))
            self.assertNotEqual(journal["status"], "applied")
            # Recover if needed.
            if journal["status"] in ("in_progress", "rollback_in_progress"):
                self.blg.recover_transaction(
                    targets=targets, state_dir=state_dir,
                    checkpoint_digest=old_digest,
                )
            # Remove ONLY the fixture-created manifest blocker.
            manifest_path.rmdir()
            # Reapply with fresh sink + explicit PRIOR digest (existing
            # terminal journal must be validated, not derived from disk).
            self.blg.apply_transaction(
                targets=targets, documents=docs, policy=self.policy,
                state_dir=state_dir, checkpoint_sink=self._make_sink(),
                prior_checkpoint_digest=old_digest,
            )
            new_digest = self._digest()
            # Old checkpoint cannot authorize new transaction.
            self.assertNotEqual(old_digest, new_digest)
            # Correct manifest + terminal status.
            journal2 = json.loads(jpath.read_text(encoding="utf-8"))
            self.assertEqual(journal2["status"], "applied")
            self.assertTrue((state_dir / "rollback-manifest.json").exists())
            # Exact target bytes (applied candidates).
            candidates = self.blg.build_candidate_documents(docs, self.policy, "bootstrap")
            for name, path in targets.items():
                self.assertEqual(path.read_bytes(), self.blg.encode_json_lf(candidates[name]))

    def test_m5_nonterminal_states_recover_or_fail_closed(self):
        """M5-B3: Each supported nonterminal root state must recover
        restorable ORIGINAL/APPLIED data or fail closed honestly. Never
        report successful NO_RECOVERY_NEEDED as if terminal."""
        original_text = '{"extensions": []}\n'
        docs = {"project": {"extensions": []}, "global": {"extensions": []}}
        # All four unresolved states that must recover or fail closed.
        # "failed_final_verify" is a legal root status (guard line 189)
        # and must NOT be treated as terminal no-op.
        nonterminal_states = [
            "in_progress", "rollback_in_progress",
            "failed_final_verify", "rolled_back_partial",
        ]
        for state in nonterminal_states:
            with tempfile.TemporaryDirectory() as td:
                state_dir = Path(td) / "state"
                state_dir.mkdir(parents=True)
                target = Path(td) / "settings.json"
                target.write_text(original_text, encoding="utf-8")
                other = Path(td) / "global.json"
                other.write_text(original_text, encoding="utf-8")
                targets = {"project": target, "global": other}
                # Fresh apply (no prior journal in this independent state dir).
                self.blg.apply_transaction(
                    targets=targets, documents=docs, policy=self.policy,
                    state_dir=state_dir, checkpoint_sink=self._make_sink(),
                )
                fresh_digest = self._digest()
                jpath = state_dir / "apply-journal.json"
                # Set the nonterminal state in the journal.
                # Status is excluded from the checkpoint descriptor, so the
                # digest still verifies without modification.
                journal = json.loads(jpath.read_text(encoding="utf-8"))
                journal["status"] = state
                jpath.write_text(json.dumps(journal, indent=1) + "\n", encoding="utf-8")
                # Snapshot pre-recovery state for fail-closed assertion.
                pre_target_bytes = target.read_bytes()
                pre_other_bytes = other.read_bytes()
                pre_journal_bytes = jpath.read_bytes()
                # Recover: must either RECOVER or fail closed.
                # Must NOT return NO_RECOVERY_NEEDED for any of these states.
                try:
                    result = self.blg.recover_transaction(
                        targets=targets, state_dir=state_dir,
                        checkpoint_digest=fresh_digest,
                    )
                    # If it returns, must be RECOVERED (not NO_RECOVERY_NEEDED).
                    self.assertNotEqual(
                        result["action"], "NO_RECOVERY_NEEDED",
                        f"State {state} must not be treated as terminal no-op"
                    )
                    self.assertEqual(result["action"], "RECOVERED")
                    self.assertEqual(result["status"], "rolled_back")
                    # Strictly verify actual persisted journal status.
                    reloaded = json.loads(jpath.read_text(encoding="utf-8"))
                    self.assertEqual(reloaded["status"], "rolled_back")
                    # Both exact originals restored.
                    self.assertEqual(target.read_text(encoding="utf-8"), original_text)
                    self.assertEqual(other.read_text(encoding="utf-8"), original_text)
                except self.blg.GuardError:
                    # Fail closed is acceptable (honest refusal).
                    # Assert NO mutation: targets and journal unchanged.
                    self.assertEqual(target.read_bytes(), pre_target_bytes)
                    self.assertEqual(other.read_bytes(), pre_other_bytes)
                    self.assertEqual(jpath.read_bytes(), pre_journal_bytes)


if __name__ == "__main__":
    unittest.main()