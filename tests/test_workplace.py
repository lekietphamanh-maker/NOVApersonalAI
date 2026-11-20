"""The Workplace: what Nova reads of the board, what she can do on it, saving and reading dropped files."""
from __future__ import annotations

import base64
import json
import io
import tempfile
import unittest
import zipfile
from pathlib import Path

import instant_commands
import tools
import workplace

PNG = "data:image/png;base64," + base64.b64encode(b"\x89PNG fake").decode()


def board_with_items():
    sent: list = []
    board = workplace.WorkplaceBoard(Path(tempfile.mkdtemp()), sent.append)
    board.sync(True, "Physics", [
        {"id": "n1", "kind": "note", "x": 10, "y": 20, "w": 260, "h": 200, "text": "Newton's second law: F = m a.\nForce equals mass times acceleration."},
        {"id": "p2", "kind": "picture", "name": "diagram.png", "image": PNG},
        {"id": "f3", "kind": "file", "name": "lab.txt", "text": "Measured g = 9.81 m/s2"},
        {"id": "bad!", "kind": "rocket"}, "junk"], ["n1", "zz"])
    return board, sent


class BoardTests(unittest.TestCase):
    def test_nova_reads_the_board_with_ids_and_the_selection(self) -> None:
        board, _sent = board_with_items()
        text = board.context()
        self.assertIn("“Physics” is open", text)
        self.assertIn("[n1] note (SELECTED): Newton's second law", text)
        self.assertIn("[p2] picture “diagram.png”: (an image: use the workplace tool's look action", text)
        self.assertIn("[f3] file “lab.txt”: Measured g", text)
        self.assertNotIn("rocket", text)
        self.assertEqual(board.selected, ["n1"])
        board.sync(False, "", [], [])
        self.assertEqual(board.context(), "")

    def test_highlight_only_exact_words_and_add_a_note_beside(self) -> None:
        board, sent = board_with_items()
        said = board.act("highlight", {"item": "n1", "text": "force equals  mass", "note": "the law in words"}, None)
        self.assertEqual(said, "Highlighted it in [n1].")
        self.assertEqual(sent[-1], {"type": "workplace_command", "command": "highlight", "item": "n1",
                                    "text": "force equals mass", "note": "the law in words"})
        self.assertIn("isn't in [n1] word for word", board.act("highlight", {"item": "n1", "text": "gravity"}, None))
        self.assertIn("no item has that id", board.act("point", {"item": "x9"}, None))
        self.assertIn("next to [f3]", board.act("add_note", {"item": "f3", "text": "Close to the textbook value."}, None))
        self.assertEqual(sent[-1]["near"], "f3")

    def test_look_sends_the_picture_to_the_vision_model(self) -> None:
        board, _sent = board_with_items()
        asked: list = []
        said = board.act("look", {"item": "p2", "question": "What forces are drawn?"},
                         lambda image, question: asked.append((image, question)) or "Two arrows: weight and normal force.")
        self.assertEqual(asked, [(b"\x89PNG fake", "What forces are drawn?")])
        self.assertIn("Two arrows", said)
        self.assertIn("needs the vision model", board.act("look", {"item": "p2"}, None))
        self.assertIn("works on pictures", board.act("look", {"item": "n1"}, lambda image, question: ""))

    def test_closed_board_and_the_tool_say_so(self) -> None:
        board = workplace.WorkplaceBoard(Path(tempfile.mkdtemp()), lambda event: None)
        self.assertIn("isn't open", board.act("read", {}, None))
        self.assertIn("isn't open", tools.execute_tool("workplace", {"action": "read"}, None, lambda *a: True))
        self.assertEqual(tools.execute_tool("workplace", {"action": "read"}, None, lambda *a: True,
                                            workplace=lambda action, arguments: f"ran {action}"), "ran read")

    def test_save_open_and_delete(self) -> None:
        board, _sent = board_with_items()
        name = board.save('Phys/ics: "ch 3"', board.items)
        self.assertEqual(name, "Phys ics ch 3")
        self.assertEqual([entry["name"] for entry in board.saved()], [name])
        loaded = board.load(name)
        self.assertEqual([item["id"] for item in loaded["items"]], ["n1", "p2", "f3"])
        board.delete(name)
        self.assertEqual(board.saved(), [])
        with self.assertRaises(ValueError):
            board.load(name)

    def test_only_real_pictures_are_kept(self) -> None:
        item = workplace.clean_item({"id": "a1", "kind": "picture", "image": "javascript:alert(1)"})
        self.assertEqual(item["image"], "")


class FileTests(unittest.TestCase):
    def test_text_word_and_unknown_files(self) -> None:
        self.assertEqual(workplace.file_text("notes.md", "# Hi".encode()), "# Hi")
        document = io.BytesIO()
        with zipfile.ZipFile(document, "w") as archive:
            archive.writestr("word/document.xml", '<w:body><w:p><w:r><w:t>First line</w:t></w:r></w:p>'
                                                  '<w:p><w:r><w:t xml:space="preserve">Second </w:t><w:t>line</w:t></w:r></w:p></w:body>')
        self.assertEqual(workplace.file_text("essay.docx", document.getvalue()), "First line\nSecond line")
        with self.assertRaisesRegex(ValueError, "can't read .zip"):
            workplace.file_text("archive.zip", b"PK")


class VoiceTests(unittest.TestCase):
    def test_open_and_close_by_voice(self) -> None:
        self.assertEqual(instant_commands.match("open my workplace").arguments, {"on": True})
        self.assertEqual(instant_commands.match("close the workspace").arguments, {"on": False})
        self.assertIsNone(instant_commands.match("explain the second note on my workplace"))


if __name__ == "__main__":
    unittest.main()


class HighlightSavingTests(unittest.TestCase):
    def test_highlights_survive_save_and_open_and_nova_sees_them(self) -> None:
        board, _sent = board_with_items()
        items = [dict(item) for item in board.items]
        items[0]["marks"] = [{"text": "  mass times   acceleration ", "note": "the law in words"}, {"text": ""}, "junk"]
        board.sync(True, "Physics", items, [])
        self.assertIn("[already highlighted: “mass times acceleration”]", board.context())
        loaded = board.load(board.save("Physics", items))
        self.assertEqual(loaded["items"][0]["marks"], [{"text": "mass times acceleration", "note": "the law in words"}])
        self.assertEqual(loaded["items"][1]["marks"], [])


class PictureTests(unittest.TestCase):
    def test_a_failing_looker_is_said_not_raised(self) -> None:
        board, _sent = board_with_items()

        def broken(image, question):
            raise RuntimeError("no credit left")
        self.assertIn("Not done: couldn't look at [p2] (no credit left)", board.act("look", {"item": "p2"}, broken))

    def looker_app(self, vision_model=None, entries=(), privacy="secrets", ollama="online · v0.13"):
        import workplace_actions
        pulled: list = []

        class App(workplace_actions.WorkplaceActions):
            pass
        app = App()
        app.state = {"model": {"vision": vision_model, "ollama": ollama}}
        app.agent = type("Agent", (), {"base_url": "http://127.0.0.1:11434"})()
        app.workplace_board, _sent = board_with_items()
        app._private_topics = lambda: privacy
        app._api_entries = lambda: list(entries)
        app._api_entry = lambda: entries[0] if entries else None
        app._api_key = lambda entry: "sk-test"
        app._act_pull_vision = lambda args: pulled.append(args)
        return app, pulled

    def test_who_looks_this_pc_first_then_an_api_brain_then_nova_downloads_the_model(self) -> None:
        import api_brains
        app, _pulled = self.looker_app(vision_model="qwen2.5vl:7b")
        self.assertEqual(app._picture_looker()[1], "the vision model on this PC")
        claude = api_brains.Entry("c1", "anthropic", "claude-sonnet-5-5", "", "Claude")
        groq = api_brains.Entry("g1", "groq", "llama", "https://api.groq.com/openai/v1", "Groq")
        app, _pulled = self.looker_app(entries=[groq, claude])
        self.assertIn("Claude (online", app._picture_looker()[1])  # Groq's models don't see pictures
        app, _pulled = self.looker_app(entries=[claude], privacy="personal")
        self.assertIsNone(app._picture_looker())  # the strict privacy rule: the owner's pictures stay here
        app, pulled = self.looker_app()
        said = app._workplace_act("look", {"item": "p2"})
        self.assertEqual(pulled, [{"consented": True}])
        self.assertIn("downloading the vision model now", said)
        app, pulled = self.looker_app(ollama="offline")
        self.assertIn("needs Ollama running", app._workplace_act("look", {"item": "p2"}))
        self.assertEqual(pulled, [])

    def test_the_api_brain_gets_the_picture_and_the_question(self) -> None:
        import api_brains
        sent: list = []

        class Answer(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

        def opener(request, timeout):
            sent.append(json.loads(request.data))
            return Answer(json.dumps({"choices": [{"message": {"content": "A yellow sun over a field."}}]}).encode())
        entry = api_brains.Entry("o1", "openai", "gpt-5", "https://api.openai.com/v1", "OpenAI")
        said = api_brains.look_at_picture(entry, "sk", b"\x89PNG\r\n\x1a\nrest", "What is it?", opener=opener)
        self.assertEqual(said, "A yellow sun over a field.")
        content = sent[0]["messages"][0]["content"]
        self.assertEqual(content[0], {"type": "text", "text": "What is it?"})
        self.assertTrue(content[1]["image_url"]["url"].startswith("data:image/png;base64,"))

        class Claude:
            class messages:
                @staticmethod
                def create(**params):
                    sent.append(params)
                    return type("Reply", (), {"content": [type("Block", (), {"text": "A leaf diagram."})()]})()
        entry = api_brains.Entry("c1", "anthropic", "claude-sonnet-5-5", "", "Claude")
        self.assertEqual(api_brains.look_at_picture(entry, "sk", b"\xff\xd8jpeg", "What?", anthropic_client=Claude), "A leaf diagram.")
        self.assertEqual(sent[-1]["messages"][0]["content"][0]["source"]["media_type"], "image/jpeg")
