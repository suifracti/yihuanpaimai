import os
import unittest


class TestMainWindowSettlementUX(unittest.TestCase):
    def setUp(self):
        self.root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.html_path = os.path.join(self.root_dir, "core", "main_window.html")
        self.js_path = os.path.join(self.root_dir, "core", "main_window.js")
        with open(self.html_path, "r", encoding="utf-8") as f:
            self.html = f.read()
        with open(self.js_path, "r", encoding="utf-8") as f:
            self.js = f.read()

    def test_cost_inputs_removed_and_replaced_with_readonly_displays(self):
        # Editable inputs should no longer exist in HTML
        self.assertNotIn('id="match-input-intel-cost"', self.html)
        self.assertNotIn('id="match-input-other-cost"', self.html)
        self.assertNotIn('id="match-input-future-cost"', self.html)

        # Readonly display containers must exist
        self.assertIn('id="match-display-intel-cost"', self.html)
        self.assertIn('id="match-display-other-cost"', self.html)
        self.assertIn('id="match-display-future-cost"', self.html)

    def test_settle_modal_redesign_structure(self):
        # Summary card elements must exist
        self.assertIn('id="settle-summary-card"', self.html)
        self.assertIn('id="settle-summary-winner"', self.html)
        self.assertIn('id="settle-summary-clearing"', self.html)
        self.assertIn('id="settle-summary-actual"', self.html)
        self.assertIn('id="settle-summary-profit"', self.html)
        self.assertIn('id="settle-summary-acquired"', self.html)
        self.assertIn('id="settle-summary-assistant"', self.html)

        # Collapsible manual edit container and toggle button
        self.assertIn('id="settle-manual-edit-container"', self.html)
        self.assertIn('id="settle-modal-toggle-edit-btn"', self.html)
        self.assertIn('id="settle-modal-confirm-btn"', self.html)

        # Conflicting/duplicate action button removed
        self.assertNotIn('id="settle-modal-keep-draft-btn"', self.html)

    def test_js_logic_for_settlement_and_costs(self):
        # Toggle function and event listener
        self.assertIn("function toggleManualSettleEdit()", self.js)
        self.assertIn('"settle-modal-toggle-edit-btn"', self.js)
        self.assertIn("settleToggleEditBtn.addEventListener", self.js)

        # Cost display synchronization
        self.assertIn('"match-display-intel-cost"', self.js)
        self.assertIn('"match-display-other-cost"', self.js)
        self.assertIn('"match-display-future-cost"', self.js)

        # Removed from input listeners
        self.assertNotIn('"match-input-intel-cost"', self.js)
        self.assertNotIn('"match-input-other-cost"', self.js)
        self.assertNotIn('"match-input-future-cost"', self.js)


if __name__ == "__main__":
    unittest.main()
