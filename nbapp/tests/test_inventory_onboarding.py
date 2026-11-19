"""First-run inventory searches and workbook imports in a new, isolated project."""
import http.client
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest
from urllib.parse import quote

from nbapp import inventory, project_setup, server


class InventoryOnboarding(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.app = server.App(tmp.name)
        self.http = server.NotebookServer(("127.0.0.1", 0), self.app)
        thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.http.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(self.http.shutdown)
        self.sample = inventory.DEMO_FOLDER / "Teaching inventory.xlsx"

    def call(self, path, body=None):
        conn = http.client.HTTPConnection(*self.http.server_address, timeout=10)
        try:
            conn.request("GET" if body is None else "POST", path, body, {"X-NB-Token": self.app.token})
            response = conn.getresponse()
            return response.status, json.load(response)
        finally:
            conn.close()

    def test_demo_and_real_inventory(self):
        demo = project_setup.demo(self.app.project)
        url = "/api/inventory?q=acetone&case=" + quote(demo.name)
        self.assertFalse(self.call("/api/state")[1]["inventory"])
        self.assertEqual(self.call("/api/inventory?q=acetone")[1]["total"], 0)
        result = self.call(url)[1]
        self.assertTrue(result["demo_inventory"])
        self.assertEqual(result["items"][0]["smiles"], "CC(C)=O")
        import_url = "/api/inventory/import?name=My%20inventory.xlsx"
        self.assertEqual(self.call(import_url, b"not an xlsx workbook")[0], 400)
        self.assertFalse(self.call("/api/state")[1]["inventory"])
        data = self.sample.read_bytes()
        self.assertEqual(self.call(import_url, data), (201, {"name": "My inventory.xlsx", "bottles": 3}))
        self.assertEqual(self.call(import_url, data)[0], 409)
        self.assertEqual((self.root / "inventory" / "My inventory.xlsx").read_bytes(), data)
        result = self.call(url)[1]
        self.assertFalse(result["demo_inventory"])
        self.assertEqual(result["items"][0]["group"], "My")
        self.assertTrue(self.call("/api/state")[1]["inventory"])
        self.assertEqual(self.call("/api/inventory?q=67-64-1")[1]["total"], 1)

    def test_first_run_browser(self):
        node = shutil.which("node")
        if not node or subprocess.run([node, "-e", "require.resolve('playwright')"], capture_output=True).returncode:
            self.skipTest("Browser check requires Node and Playwright.")
        url = "http://127.0.0.1:%s/" % self.http.server_port
        script = Path(__file__).with_name("inventory_onboarding.cjs")
        subprocess.run([node, str(script), url, str(self.sample)], check=True, timeout=60, env=os.environ)


if __name__ == "__main__":
    unittest.main()
