"""Unit tests for Fast-Path Intent Router (Phase 2)."""

import unittest
from assistant.core.router import IntentRouter
from assistant.tools.launch.site_manager import SiteManager
from assistant.tools.launch.app_launcher import AppIndexer
from assistant.tools.base import ToolResult


class MockOrchestrator:
    def __init__(self):
        self.last_call = None

    def run_tool(self, name: str, args: dict):
        self.last_call = (name, args)
        return ToolResult.success(data=args, summary=f"Mock executed {name} with {args}")


class TestIntentRouter(unittest.TestCase):
    def setUp(self):
        self.mock_orch = MockOrchestrator()
        self.router = IntentRouter(orch=self.mock_orch)

    def test_normalize_strips_filler_words(self):
        self.assertEqual(
            self.router.normalize("Tolong bukain youtube dong!"),
            "bukain youtube"
        )
        self.assertEqual(
            self.router.normalize("coba cari lagu lofi di youtube ya?"),
            "cari lagu lofi di youtube"
        )
        self.assertEqual(
            self.router.normalize("Please open chrome pls"),
            "open chrome"
        )

    def test_route_youtube_search(self):
        res = self.router.route("tolong cari lofi hip hop di youtube dong")
        self.assertTrue(res.matched)
        self.assertEqual(res.intent, "youtube_search")
        self.assertEqual(res.tool_name, "launch.youtube_search")
        self.assertEqual(res.args.get("query"), "lofi hip hop")

    def test_route_open_known_site(self):
        res = self.router.route("buka youtube")
        self.assertTrue(res.matched)
        self.assertEqual(res.intent, "open_site")
        self.assertEqual(res.tool_name, "launch.open_url")
        self.assertEqual(res.args.get("url"), "https://www.youtube.com")

    def test_route_open_kuramanime(self):
        res = self.router.route("buka web kuramanime")
        self.assertTrue(res.matched)
        self.assertEqual(res.intent, "open_site")
        self.assertEqual(res.tool_name, "launch.open_url")
        self.assertIn("kuramanime", res.args.get("url"))

    def test_route_open_idlix(self):
        res = self.router.route("buka idlix")
        self.assertTrue(res.matched)
        self.assertEqual(res.intent, "open_site")
        self.assertEqual(res.tool_name, "launch.open_url")
        self.assertIn("idlix", res.args.get("url"))

    def test_route_open_folder(self):
        res = self.router.route("tolong buka folder download")
        self.assertTrue(res.matched)
        self.assertEqual(res.intent, "open_folder")
        self.assertEqual(res.tool_name, "launch.open_folder")
        self.assertEqual(res.args.get("folder"), "download")

    def test_route_open_app(self):
        res = self.router.route("buka notepad")
        self.assertTrue(res.matched)
        self.assertEqual(res.intent, "open_app")
        self.assertEqual(res.tool_name, "launch.open_app")
        self.assertIn("notepad.exe", res.args.get("name").lower())

    def test_route_web_search(self):
        res = self.router.route("cari resep rendang di google")
        self.assertTrue(res.matched)
        self.assertEqual(res.intent, "web_search")
        self.assertEqual(res.tool_name, "launch.web_search")
        self.assertEqual(res.args.get("query"), "resep rendang")

    def test_route_update_site_alias(self):
        res = self.router.route("update kuramanime https://v21.kuramanime.ing/")
        self.assertTrue(res.matched)
        self.assertEqual(res.intent, "update_site_alias")
        self.assertEqual(res.tool_name, "launch.update_site")
        self.assertEqual(res.args.get("alias"), "kuramanime")
        self.assertEqual(res.args.get("url"), "https://v21.kuramanime.ing/")

    def test_route_unmatched_falls_back_to_llm(self):
        res = self.router.route("kenapa semalem laptop tiba-tiba layar biru?")
        self.assertFalse(res.matched)
        self.assertEqual(res.route, "llm")


if __name__ == "__main__":
    unittest.main()
