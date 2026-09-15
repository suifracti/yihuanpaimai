import dataclasses
import os
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
APP_DIR = os.path.join(PROJECT_ROOT, "app")
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

from main_window import (  # noqa: E402
    MainWindowBridge,
    OverlayVisibilityController,
    load_mascot_presentation_contract,
)
from mascot_presentation_state import (  # noqa: E402
    MascotPresentationSnapshot,
    MascotPresentationStateCoordinator,
)
from presentation_runtime import PresentationRuntimeSnapshot  # noqa: E402


class _FakeOverlay:
    Visible = True

    def Show(self):
        self.Visible = True

    def Hide(self):
        self.Visible = False


class MascotPresentationStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = load_mascot_presentation_contract(PROJECT_ROOT)

    def make_coordinator(self):
        return MascotPresentationStateCoordinator(self.contract)

    def test_priority_rule_matches_the_frozen_automatic_contract(self):
        cases = (
            ("ready", PresentationRuntimeSnapshot(), "idle"),
            (
                "ready",
                PresentationRuntimeSnapshot(
                    refresh_pending=True,
                    scene_class="auction",
                    shadow_updating=True,
                ),
                "loading",
            ),
            (
                "ready",
                PresentationRuntimeSnapshot(
                    scene_class="loading", shadow_updating=True
                ),
                "loading",
            ),
            (
                "ready",
                PresentationRuntimeSnapshot(
                    scene_class="auction", shadow_updating=True
                ),
                "thinking",
            ),
            (
                "shutting_down",
                PresentationRuntimeSnapshot(
                    refresh_pending=True,
                    scene_class="loading",
                    shadow_updating=True,
                ),
                "sleep",
            ),
        )
        coordinator = self.make_coordinator()
        for application_state, runtime, expected in cases:
            with self.subTest(expected=expected):
                snapshot = coordinator.update(application_state, runtime)
                self.assertEqual(snapshot.state, expected)
                self.assertEqual(
                    snapshot.asset_id, self.contract["states"][expected]
                )

    def test_automatic_selector_never_emits_manual_only_states(self):
        coordinator = self.make_coordinator()
        states = {
            coordinator.update("ready", PresentationRuntimeSnapshot()).state,
            coordinator.update(
                "ready", PresentationRuntimeSnapshot(refresh_pending=True)
            ).state,
            coordinator.update(
                "ready", PresentationRuntimeSnapshot(shadow_updating=True)
            ).state,
            coordinator.update(
                "shutting_down", PresentationRuntimeSnapshot()
            ).state,
        }
        self.assertNotIn("success", states)
        self.assertNotIn("warning", states)

    def test_snapshot_is_frozen_and_payload_is_a_fresh_primitive_object(self):
        coordinator = self.make_coordinator()
        snapshot = coordinator.snapshot()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            snapshot.state = "loading"
        first = snapshot.to_payload()
        first["state"] = "tampered"
        self.assertEqual(coordinator.snapshot().to_payload()["state"], "idle")

    def test_bridge_and_pet_provider_can_share_the_same_snapshot(self):
        coordinator = self.make_coordinator()
        runtime = PresentationRuntimeSnapshot(scene_class="loading")

        def provider(application_state):
            return coordinator.update(application_state, runtime)

        bridge = MainWindowBridge(
            OverlayVisibilityController(_FakeOverlay()),
            mascot_state_provider=provider,
        )
        pet_snapshot = provider("ready")
        main_payload = bridge.dispatch({"action": "request_app_status"})[
            "mascotState"
        ]
        self.assertIsInstance(pet_snapshot, MascotPresentationSnapshot)
        self.assertEqual(main_payload, pet_snapshot.to_payload())

    def test_invalid_mutable_runtime_is_rejected(self):
        coordinator = self.make_coordinator()
        with self.assertRaises(TypeError):
            coordinator.update("ready", {"sceneClass": "loading"})

    def test_contract_cannot_expand_state_or_asset_authority(self):
        mutable = dict(self.contract)
        mutable["states"] = dict(self.contract["states"])
        mutable["states"]["business_success"] = mutable["states"]["success"]
        with self.assertRaises(ValueError):
            MascotPresentationStateCoordinator(mutable)

    def test_main_javascript_consumes_host_state_instead_of_selecting(self):
        paths = (
            os.path.join(PROJECT_ROOT, "core", "main_window.js"),
            os.path.join(PROJECT_ROOT, "core", "mascot_runtime_binding.js"),
        )
        source = "\n".join(Path(path).read_text(encoding="utf-8") for path in paths)
        self.assertIn("consumeHostMascotState", source)
        self.assertNotIn("selectAutomaticMascotState", source)
        self.assertNotIn('postNative("set_mascot_state")', source)


if __name__ == "__main__":
    unittest.main()
