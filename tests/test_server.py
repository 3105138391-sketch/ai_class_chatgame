import io
import unittest

import server


class ServerHelpersTest(unittest.TestCase):
    def test_complete_blueprint_fills_required_lists_and_prompt(self):
        blueprint = server.complete_blueprint({"title": "测试游戏", "factions": []})

        self.assertEqual(blueprint["title"], "测试游戏")
        self.assertTrue(blueprint["factions"])
        self.assertTrue(blueprint["identitySuggestions"])
        self.assertIn("测试游戏", blueprint["gmPrompt"])

    def test_extract_json_object_accepts_fenced_json(self):
        handler = object.__new__(server.MyHandler)
        data = handler.extract_json_object('```json\n{"title":"测试","items":[1]}\n```')

        self.assertEqual(data, {"title": "测试", "items": [1]})

    def test_read_json_rejects_invalid_json(self):
        handler = object.__new__(server.MyHandler)
        raw = b'{"bad"'
        handler.headers = {"Content-Length": str(len(raw))}
        handler.rfile = io.BytesIO(raw)

        with self.assertRaisesRegex(ValueError, "JSON"):
            handler._read_json()

    def test_read_json_rejects_oversized_body(self):
        handler = object.__new__(server.MyHandler)
        handler.headers = {"Content-Length": str(server.MAX_REQUEST_SIZE + 1)}
        handler.rfile = io.BytesIO(b"{}")

        with self.assertRaisesRegex(ValueError, "请求体过大"):
            handler._read_json()

    def test_read_json_accepts_empty_body(self):
        handler = object.__new__(server.MyHandler)
        handler.headers = {"Content-Length": "0"}
        handler.rfile = io.BytesIO(b"")

        self.assertEqual(handler._read_json(), {})


if __name__ == "__main__":
    unittest.main()
