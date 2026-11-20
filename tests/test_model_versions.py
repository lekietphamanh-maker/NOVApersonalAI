"""Custom model versions: names, what is sent to Ollama, and originals that can't be deleted from Nova."""
from __future__ import annotations

import unittest

import model_versions as versions


class VersionTests(unittest.TestCase):
    def test_names_and_what_ollama_gets(self) -> None:
        self.assertEqual(versions.version_name("Study Buddy!"), "nova-study-buddy")
        self.assertEqual(versions.version_name("nova-coder"), "nova-coder")
        sent: list = []
        made = versions.create(lambda url, body: sent.append((url, body)), "http://127.0.0.1:11434", base="qwen3:4b",
                               name="study", system="Answer briefly.", temperature=0.4, num_ctx=8192)
        self.assertEqual(made, "nova-study")
        self.assertEqual(sent, [("http://127.0.0.1:11434/api/create", {
            "model": "nova-study", "from": "qwen3:4b", "stream": False, "system": "Answer briefly.",
            "parameters": {"temperature": 0.4, "num_ctx": 8192}})])

    def test_bad_settings_are_refused(self) -> None:
        for fields in ({"base": "", "name": "x"}, {"base": "qwen3:4b", "name": "!!!"},
                       {"base": "qwen3:4b", "name": "x", "temperature": 3}, {"base": "qwen3:4b", "name": "x", "num_ctx": 100}):
            with self.assertRaises(ValueError):
                versions.create_payload(**fields)

    def test_only_novas_own_versions_can_be_deleted(self) -> None:
        deleted: list = []
        versions.delete(lambda url, body: deleted.append(body), "http://x", "nova-study:latest")
        self.assertEqual(deleted, [{"model": "nova-study:latest"}])
        with self.assertRaises(ValueError):
            versions.delete(lambda url, body: deleted.append(body), "http://x", "qwen3:4b")
        self.assertEqual(versions.custom_versions(["qwen3:4b", "nova-study:latest", "gemma3:4b"]), ["nova-study:latest"])


if __name__ == "__main__":
    unittest.main()
