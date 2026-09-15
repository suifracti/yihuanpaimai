import hashlib
import json
import os
import sys
import unittest

from PIL import Image


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
APP_DIR = os.path.join(PROJECT_ROOT, "app")
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

from main_window import load_mascot_presentation_contract


MANIFEST_PATH = os.path.join(
    PROJECT_ROOT, "design", "mascot", "mascot_final_asset_manifest_v1.json"
)
STATE_MAP_PATH = os.path.join(
    PROJECT_ROOT, "design", "mascot", "mascot_state_asset_map_v1.json"
)


def _load_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


class MascotAssetManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = _load_json(MANIFEST_PATH)
        cls.state_map = _load_json(STATE_MAP_PATH)
        cls.assets = {
            asset["assetId"]: asset for asset in cls.manifest["assets"]
        }

    def test_manifest_assets_exist_and_match_declared_bytes(self):
        self.assertEqual(len(self.assets), len(self.manifest["assets"]))
        for asset in self.manifest["assets"]:
            with self.subTest(asset=asset["assetId"]):
                path = os.path.join(PROJECT_ROOT, *asset["path"].split("/"))
                self.assertTrue(os.path.isfile(path))
                with open(path, "rb") as handle:
                    digest = hashlib.sha256(handle.read()).hexdigest()
                self.assertEqual(digest, asset["sha256"])
                with Image.open(path) as image:
                    self.assertEqual(image.mode, "RGBA")
                    self.assertEqual(image.size, (asset["width"], asset["height"]))
                self.assertEqual(asset["status"], "approved_final")

    def test_source_provenance_is_content_addressed(self):
        sources = [self.manifest["visualAuthority"], *self.manifest["sourceFiles"]]
        self.assertEqual(self.manifest["bboxConvention"], "source_pixel_xyxy_half_open")
        for source in sources:
            with self.subTest(source=source["path"]):
                path = os.path.join(PROJECT_ROOT, *source["path"].split("/"))
                with open(path, "rb") as handle:
                    digest = hashlib.sha256(handle.read()).hexdigest()
                self.assertEqual(digest, source["sha256"])

    def test_every_state_resolves_to_an_approved_chibi_asset(self):
        self.assertEqual(self.state_map["fallbackState"], "idle")
        self.assertEqual(
            set(self.state_map["states"]),
            {"idle", "thinking", "loading", "success", "warning", "sleep"},
        )
        for state, asset_id in self.state_map["states"].items():
            with self.subTest(state=state):
                self.assertIn(asset_id, self.assets)
                self.assertEqual(self.assets[asset_id]["role"], "chibi_state")
                self.assertEqual(self.assets[asset_id]["status"], "approved_final")

    def test_loading_state_uses_only_the_approved_v2_asset(self):
        loading_id = self.state_map["states"]["loading"]
        self.assertEqual(loading_id, "mascot.chibi.loading.v2")
        self.assertEqual(
            self.assets[loading_id]["path"],
            "design/mascot/exports/chibi/mascot_chibi_loading_v2.png",
        )
        referenced = {asset["path"] for asset in self.manifest["assets"]}
        self.assertNotIn(
            "design/mascot/exports/chibi/mascot_chibi_loading.png", referenced
        )

    def test_state_mapping_has_no_solver_or_fact_authority(self):
        boundary = self.state_map["authorityBoundary"]
        self.assertTrue(boundary["controlsPresentationAssetOnly"])
        self.assertFalse(boundary["controlsSolverState"])
        self.assertFalse(boundary["controlsCanonicalFacts"])

    def test_native_contract_resolves_the_frozen_mapping_to_local_asset_uris(self):
        contract = load_mascot_presentation_contract(PROJECT_ROOT)
        self.assertEqual(contract["mode"], "presentation_only")
        self.assertEqual(contract["defaultPortraitAssetId"], "mascot.portrait.default")
        self.assertEqual(contract["fallbackState"], "idle")
        self.assertEqual(contract["states"], self.state_map["states"])
        self.assertEqual(contract["states"]["loading"], "mascot.chibi.loading.v2")
        for asset in contract["assets"].values():
            self.assertTrue(asset["uri"].startswith("file:///"))

    def test_main_page_exposes_only_local_presentation_state_switching(self):
        html_path = os.path.join(PROJECT_ROOT, "core", "main_window.html")
        js_path = os.path.join(PROJECT_ROOT, "core", "main_window.js")
        with open(html_path, encoding="utf-8") as handle:
            html = handle.read()
        with open(js_path, encoding="utf-8") as handle:
            javascript = handle.read()

        # 1. 手动 debug controls 已从主页面移除
        for state in self.state_map["states"]:
            self.assertNotIn(f'data-mascot-state="{state}"', html)

        # 2. 真实 mascot host 与 presentation elements 依然存在
        self.assertIn('id="mascot-panel"', html)
        self.assertIn('id="mascot-portrait"', html)
        self.assertIn('id="mascot-state-image"', html)
        self.assertIn('id="mascot-state-title"', html)
        self.assertIn('id="mascot-state-chip"', html)
        self.assertIn("mascot_runtime_binding.js", html)

        # 3. runtime presentation 绑定与单向纯展示隔离
        self.assertIn("function configureMascotPresentation(contract)", javascript)
        self.assertIn("function setMascotState(state)", javascript)
        self.assertNotIn('postNative("set_mascot_state")', javascript)

    def test_packaging_spec_names_manifest_mapping_and_all_final_assets(self):
        spec_path = os.path.join(PROJECT_ROOT, "app", "异环拍卖助手.spec")
        with open(spec_path, encoding="utf-8") as handle:
            spec = handle.read()
        for name in (
            "mascot_final_asset_manifest_v1.json",
            "mascot_state_asset_map_v1.json",
            *(os.path.basename(asset["path"]) for asset in self.manifest["assets"]),
        ):
            with self.subTest(name=name):
                self.assertIn(name, spec)
        self.assertNotIn("mascot_chibi_loading.png", spec)


if __name__ == "__main__":
    unittest.main()
