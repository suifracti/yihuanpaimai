import hashlib
import json
import os
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
CORE_DIR = PROJECT_ROOT / "core"
for entry in (str(APP_DIR), str(CORE_DIR)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import runtime_data  # noqa: E402
from canonical_history_store import CanonicalHistoryStore, HistoryStoreError  # noqa: E402
from main_view_state import LOCAL_TIME_ZONE, MainViewStateProvider  # noqa: E402
from main_window import MainWindowBridge, OverlayVisibilityController  # noqa: E402
from mascot_presentation_state import MascotPresentationSnapshot  # noqa: E402
from presentation_runtime import PresentationRuntimeSnapshot  # noqa: E402


NOW = datetime(2026, 8, 22, 12, 0, tzinfo=LOCAL_TIME_ZONE)


class _FakeOverlay:
    Visible = True

    def Show(self):
        self.Visible = True

    def Hide(self):
        self.Visible = False


def _history(records=None):
    return json.dumps(
        {"version": "v0.67-runtime", "schemaVersion": 6, "records": records or []},
        ensure_ascii=False,
    ).encode("utf-8")


class RuntimeDataResolverTests(unittest.TestCase):
    def test_source_and_package_default_share_per_user_semantics(self):
        with tempfile.TemporaryDirectory() as local:
            env = {"LOCALAPPDATA": local}
            expected = Path(local) / "异环拍卖助手" / "data"
            self.assertEqual(runtime_data.resolve_runtime_data_root(env), expected.resolve())
            with mock.patch.object(sys, "frozen", False, create=True):
                source = runtime_data.resolve_runtime_history_path(env)
            with mock.patch.object(sys, "frozen", True, create=True), mock.patch.object(
                sys, "_MEIPASS", str(Path(local) / "bundle"), create=True
            ):
                packaged = runtime_data.resolve_runtime_history_path(env)
            self.assertEqual(source, packaged)
            self.assertEqual(source, expected.resolve() / "history" / "异环拍卖数据.json")

    def test_explicit_override_is_independent_of_cwd_meipass_and_executable(self):
        with tempfile.TemporaryDirectory() as target, tempfile.TemporaryDirectory() as cwd:
            env = {"YIHUAN_DATA_ROOT": target, "LOCALAPPDATA": "ignored"}
            before = Path.cwd()
            try:
                os.chdir(cwd)
                with mock.patch.object(sys, "_MEIPASS", str(Path(cwd) / "_internal"), create=True), mock.patch.object(
                    sys, "executable", str(Path(cwd) / "app.exe")
                ):
                    resolved = runtime_data.resolve_runtime_history_path(env)
            finally:
                os.chdir(before)
            self.assertEqual(resolved, Path(target).resolve() / "history" / "异环拍卖数据.json")
            self.assertNotIn("_internal", str(resolved))

    def test_missing_localappdata_has_no_unsafe_fallback(self):
        with self.assertRaises(runtime_data.RuntimeDataUnavailable) as raised:
            runtime_data.resolve_runtime_data_root({})
        self.assertEqual(raised.exception.reason, "LOCALAPPDATA_UNAVAILABLE")

    def test_first_run_creates_empty_valid_store_not_reference_data(self):
        with tempfile.TemporaryDirectory() as root:
            result = runtime_data.initialize_runtime_data(
                env={"YIHUAN_DATA_ROOT": root}
            )
            self.assertTrue(result.available)
            self.assertEqual(result.availability, "EMPTY")
            document = json.loads(result.paths.history_path.read_text(encoding="utf-8"))
            self.assertEqual(document["records"], [])
            self.assertEqual(
                MainViewStateProvider(result.paths.history_path).snapshot(NOW).match_count.value,
                0,
            )

    def test_bundled_baseline_is_not_migrated(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as legacy:
            source = Path(legacy) / runtime_data.HISTORY_FILENAME
            payload = _history([{"id": "developer-record"}])
            source.write_bytes(payload)
            digest = hashlib.sha256(payload).hexdigest()
            candidate = runtime_data.LegacyHistoryCandidate(source, "LEGACY_PACKAGED_INTERNAL")
            with mock.patch.object(
                runtime_data, "KNOWN_BUNDLED_REFERENCE_SHA256", frozenset({digest})
            ):
                result = runtime_data.initialize_runtime_data(
                    env={"YIHUAN_DATA_ROOT": root}, legacy_candidates=[candidate]
                )
            installed = json.loads(result.paths.history_path.read_text(encoding="utf-8"))
            self.assertEqual(installed["records"], [])
            self.assertEqual(result.migration.result, "SKIPPED_BUNDLED_REFERENCE")

    def test_changed_valid_legacy_candidate_migrates_copy_first(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as legacy:
            source = Path(legacy) / runtime_data.HISTORY_FILENAME
            payload = _history([{"id": "legacy-user", "lifecycleStatus": "DRAFT"}])
            source.write_bytes(payload)
            candidate = runtime_data.LegacyHistoryCandidate(source, "LEGACY_PACKAGED_INTERNAL")
            result = runtime_data.initialize_runtime_data(
                env={"YIHUAN_DATA_ROOT": root}, legacy_candidates=[candidate]
            )
            self.assertEqual(result.migration.result, "MIGRATED")
            self.assertEqual(result.paths.history_path.read_bytes(), payload)
            self.assertEqual(source.read_bytes(), payload)
            metadata = json.loads(result.paths.migration_metadata_path.read_text(encoding="utf-8"))
            self.assertEqual(metadata["sourcePathClassification"], "LEGACY_PACKAGED_INTERNAL")
            self.assertEqual(metadata["sourceSha256"], metadata["destinationSha256"])

            second = runtime_data.initialize_runtime_data(
                env={"YIHUAN_DATA_ROOT": root}, legacy_candidates=[]
            )
            self.assertEqual(second.migration.result, "NOT_REQUIRED")
            self.assertEqual(second.paths.history_path.read_bytes(), payload)

    def test_existing_destination_wins_and_reports_conflict(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as legacy:
            first = runtime_data.initialize_runtime_data(env={"YIHUAN_DATA_ROOT": root})
            source = Path(legacy) / runtime_data.HISTORY_FILENAME
            source.write_bytes(_history([{"id": "legacy"}]))
            before = first.paths.history_path.read_bytes()
            result = runtime_data.initialize_runtime_data(
                env={"YIHUAN_DATA_ROOT": root},
                legacy_candidates=[runtime_data.LegacyHistoryCandidate(source, "LEGACY_EXECUTABLE_ADJACENT")],
            )
            self.assertEqual(result.availability, "MIGRATION_CONFLICT")
            self.assertEqual(first.paths.history_path.read_bytes(), before)

    def test_corrupt_legacy_is_rejected_and_old_source_untouched(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as legacy:
            source = Path(legacy) / runtime_data.HISTORY_FILENAME
            source.write_bytes(b"{not-json")
            result = runtime_data.initialize_runtime_data(
                env={"YIHUAN_DATA_ROOT": root},
                legacy_candidates=[runtime_data.LegacyHistoryCandidate(source, "LEGACY_PACKAGED_INTERNAL")],
            )
            self.assertEqual(result.availability, "EMPTY")
            self.assertEqual(result.migration.result, "REJECTED_CORRUPT")
            self.assertEqual(source.read_bytes(), b"{not-json")

    def test_migration_write_failure_preserves_source(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as legacy:
            source = Path(legacy) / runtime_data.HISTORY_FILENAME
            payload = _history([{"id": "legacy"}])
            source.write_bytes(payload)
            original = runtime_data._atomic_write_bytes

            def fail_destination(destination, data):
                if Path(destination).name == runtime_data.HISTORY_FILENAME:
                    raise OSError("disk full")
                return original(destination, data)

            with mock.patch.object(runtime_data, "_atomic_write_bytes", side_effect=fail_destination):
                result = runtime_data.initialize_runtime_data(
                    env={"YIHUAN_DATA_ROOT": root},
                    legacy_candidates=[runtime_data.LegacyHistoryCandidate(source, "LEGACY_PACKAGED_INTERNAL")],
                )
            self.assertFalse(result.available)
            self.assertEqual(result.reason, "HISTORY_MIGRATION_WRITE_FAILED")
            self.assertEqual(source.read_bytes(), payload)


class FailSoftAndWriteTests(unittest.TestCase):
    def _payload(self, path):
        return MainViewStateProvider(path).snapshot(NOW).to_payload()

    def test_missing_corrupt_and_invalid_root_are_fail_soft(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "history.json"
            missing = self._payload(path)
            self.assertEqual(missing["history"]["availability"], "UNAVAILABLE")
            path.write_text("{broken", encoding="utf-8")
            corrupt = self._payload(path)
            self.assertEqual(corrupt["history"], {
                "availability": "CORRUPT",
                "reason": "HISTORY_PARSE_FAILED",
                "totalCount": None,
                "admittedCount": None,
                "excludedCount": None,
                "recentRecords": [],
                "boundedLimit": 50,
            })
            path.write_text(json.dumps({"records": {}}), encoding="utf-8")
            invalid = self._payload(path)
            self.assertEqual(invalid["history"]["reason"], "HISTORY_SCHEMA_INVALID")

    def test_permission_and_read_errors_are_sanitized(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "history.json"
            path.write_bytes(_history())
            provider = MainViewStateProvider(path)
            with mock.patch.object(Path, "read_bytes", side_effect=PermissionError("C:/secret")):
                payload = provider.snapshot(NOW).to_payload()
            serialized = json.dumps(payload, ensure_ascii=False)
            self.assertEqual(payload["history"]["reason"], "HISTORY_PERMISSION_DENIED")
            self.assertNotIn("secret", serialized)
            self.assertNotIn(str(path), serialized)

    def test_unchanged_corrupt_source_uses_revision_cache(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "history.json"
            path.write_text("{broken", encoding="utf-8")
            provider = MainViewStateProvider(path)
            with mock.patch.object(
                provider, "_read_stable_bytes", wraps=provider._read_stable_bytes
            ) as reader:
                first = provider.snapshot(NOW)
                second = provider.snapshot(NOW)
            self.assertIs(first, second)
            self.assertEqual(reader.call_count, 1)

    def test_bridge_keeps_app_status_when_history_provider_fails(self):
        def fail():
            raise RuntimeError("private C:/path")

        bridge = MainWindowBridge(
            OverlayVisibilityController(_FakeOverlay()),
            presentation_runtime_provider=lambda: PresentationRuntimeSnapshot(
                vision_process_state="running"
            ),
            main_view_state_provider=fail,
            mascot_state_provider=lambda _application_state: MascotPresentationSnapshot(
                snapshot_version=1,
                state="idle",
                asset_id="mascot.chibi.idle",
            ),
        )
        response = bridge.dispatch({"action": "request_app_status"})
        self.assertTrue(response["overlayVisible"])
        self.assertEqual(response["applicationState"], "ready")
        self.assertEqual(response["solverOwner"], "overlay_runtime")
        self.assertEqual(response["presentationRuntime"]["visionProcessState"], "running")
        self.assertEqual(response["mascotState"]["state"], "idle")
        self.assertEqual(
            response["mainViewState"]["history"]["reason"],
            "HISTORY_PROVIDER_FAILED",
        )
        self.assertNotIn("private", json.dumps(response, ensure_ascii=False))

    def test_atomic_write_failure_preserves_previous_history(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "history.json"
            path.write_bytes(_history([{"id": "old", "lifecycleStatus": "DRAFT"}]))
            before = path.read_bytes()
            store = CanonicalHistoryStore(path)
            with mock.patch("canonical_history_store.os.replace", side_effect=OSError("denied")):
                with self.assertRaises(HistoryStoreError):
                    store.persist_record_transactional(
                        {"id": "new", "lifecycleStatus": "DRAFT"},
                        is_finalized=False,
                    )
            self.assertEqual(path.read_bytes(), before)

    def test_repeated_concurrent_draft_saves_never_truncate_json(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "history.json"
            path.write_bytes(_history())
            store = CanonicalHistoryStore(path)

            def persist(index):
                return store.persist_record_transactional(
                    {
                        "id": "same-draft",
                        "lifecycleStatus": "DRAFT",
                        "sequence": index,
                    },
                    is_finalized=False,
                )

            with ThreadPoolExecutor(max_workers=6) as executor:
                list(executor.map(persist, range(24)))
            document = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(len(document["records"]), 1)
            self.assertEqual(document["records"][0]["id"], "same-draft")

    def test_product_sources_have_one_runtime_path_authority(self):
        main_source = (APP_DIR / "main.py").read_text(encoding="utf-8")
        auto_source = (CORE_DIR / "auto_archiver.py").read_text(encoding="utf-8")
        store_source = (CORE_DIR / "canonical_history_store.py").read_text(encoding="utf-8")
        shadow_source = (CORE_DIR / "live_shadow.py").read_text(encoding="utf-8")
        config = json.loads((APP_DIR / "config.json").read_text(encoding="utf-8"))
        spec = (APP_DIR / "异环拍卖助手.spec").read_text(encoding="utf-8")
        self.assertIn("initialize_runtime_data", main_source)
        self.assertIn("resolve_runtime_history_path", auto_source)
        self.assertIn("resolve_runtime_history_path", store_source)
        self.assertIn("resolve_runtime_history_path", shadow_source)
        self.assertNotIn("canonicalDatabase", config["archiver"])
        self.assertNotIn("targetDatabases", config["archiver"])
        self.assertNotIn("PROJECT_ROOT, '异环拍卖数据.json'", spec)

    def test_test_execution_with_isolated_root_leaves_production_root_untouched(self):
        """Tests executed with YIHUAN_DATA_ROOT override must never mutate production data root."""
        from runtime_data import runtime_data_paths
        prod_paths = runtime_data_paths()
        prod_before_bytes = prod_paths.history_path.read_bytes() if prod_paths.history_path.exists() else None
        prod_before_hash = hashlib.sha256(prod_before_bytes).hexdigest() if prod_before_bytes else None

        with tempfile.TemporaryDirectory() as isolated_temp:
            isolated_paths = runtime_data_paths({"YIHUAN_DATA_ROOT": isolated_temp})
            self.assertNotEqual(str(prod_paths.root), str(isolated_paths.root))

            # Perform isolated writes
            store = CanonicalHistoryStore(isolated_paths.history_path)
            store.persist_record_transactional({
                "id": "isolated_test_match_999",
                "lifecycleStatus": "FINALIZED",
                "playedAt": "2026-08-23T18:00:00+08:00",
                "admitted": True,
            }, is_finalized=True)

            self.assertEqual(len(store.read_database().get("records", [])), 1)

        # Production root must remain 100% untouched
        prod_after_bytes = prod_paths.history_path.read_bytes() if prod_paths.history_path.exists() else None
        prod_after_hash = hashlib.sha256(prod_after_bytes).hexdigest() if prod_after_bytes else None
        self.assertEqual(prod_before_hash, prod_after_hash)


if __name__ == "__main__":
    unittest.main()
