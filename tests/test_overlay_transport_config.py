import json
from pathlib import Path
import re
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]

class OverlayTransportConfigTests(unittest.TestCase):
    def test_actual_page_resolves_configured_port_and_safe_defaults(self):
        html=(ROOT/'core/overlay_alpha.html').read_text(encoding='utf-8')
        fn=re.search(r'    function hudWebSocketUrl\(search\) \{.*?\n    \}',html,re.S)
        self.assertIsNotNone(fn)
        queries=['wsPort=18766','','?wsPort=0','?wsPort=65536','?wsPort=evil','?wsPort=65535']
        code=fn.group(0)+'\nconsole.log(JSON.stringify('+json.dumps(queries)+'.map(hudWebSocketUrl)));'
        result=subprocess.run(['node','-e',code],capture_output=True,text=True,check=True)
        self.assertEqual(json.loads(result.stdout),['ws://127.0.0.1:'+str(p) for p in (18766,8766,8766,8766,8766,65535)])
        self.assertIn('new WebSocket(hudWebSocketUrl(window.location.hash.slice(1) || window.location.search))',html)
