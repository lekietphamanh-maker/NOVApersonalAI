"""The Workplace, wired into Nova: the HUD's actions, the board sent with each question while it's open, and Nova's
hands on it (the workplace tool). A mixin for AlfredApp; the board itself is workplace.WorkplaceBoard."""
from __future__ import annotations

import base64
import secrets
from typing import Any, Callable

import api_brains
import vision
import workplace
from agent import SCREEN_MARKER


class WorkplaceActions:
    def _picture_looker(self) -> tuple[Callable[[bytes, str], str], str] | None:
        """Who looks at a picture: the vision model on this PC first (nothing leaves it); without it, the owner's API
        brain when it sees pictures and the privacy setting lets the owner's things go online."""
        vision_model = self.state["model"].get("vision")
        if vision_model:
            return (lambda image, question: workplace.ask_picture(self.agent.base_url, vision_model, image, question),
                    "the vision model on this PC")
        if self._private_topics() == "personal":
            return None
        entry = next((item for item in [self._api_entry(), *self._api_entries()]
                      if item is not None and item.provider in api_brains.SEES_PICTURES and self._api_key(item)), None)
        if entry is None:
            return None
        key = self._api_key(entry)
        return (lambda image, question: api_brains.look_at_picture(entry, key, image, question),
                f"{entry.label} (online: the picture was sent to it)")

    def _start_vision_download(self) -> str:
        """No one can see pictures yet: Nova gets the vision model herself, in the background."""
        model = self.state["model"]
        if model.get("vision_downloading"):
            return "The vision model is already downloading; Nova can look at pictures once it's in."
        if model.get("ollama") in ("offline", "checking", None):
            return ("Nova can't see pictures yet: the vision model needs Ollama running (SETTINGS → Downloads → Set up "
                    "everything), or add an API brain that sees pictures (Claude, OpenAI or Gemini).")
        answer = self._act_pull_vision({"consented": True}) or {}
        if answer.get("ok") is False:
            return f"Nova can't see pictures yet: {answer.get('error', 'the vision model download did not start')}."
        return (f"Nova is downloading the vision model now (about {vision.VISION_GB} GB, it runs on this PC). Tell the "
                "owner she can look at pictures and sketches once it's in, and meanwhile describe only what the board's "
                "text says about them.")

    def _workplace_act(self, action: str, arguments: dict[str, Any]) -> str:
        looker = self._picture_looker() if action == "look" else None
        if action == "look" and looker is None:
            item = self.workplace_board.find(str(arguments.get("item") or ""))
            if item is not None and item["kind"] in ("picture", "sketch") and item["image"]:
                return self._start_vision_download()
        look = None
        if looker is not None:
            see, who = looker
            look = lambda image, question: f"{see(image, question)} (seen by {who})"  # noqa: E731
        return self.workplace_board.act(action, arguments, look)

    def _with_workplace(self, prompt: str) -> str:
        """The question as the model gets it: the open board rides along like a screen does (never saved, and only
        the latest board stays in the conversation)."""
        board = self.workplace_board.context()
        return f"{prompt}{SCREEN_MARKER} {secrets.token_hex(4)}: {board}" if board else prompt

    def _open_workplace(self, on: bool) -> str:
        if self.ui.clients:
            self.ui.emit({"type": "workplace_command", "command": "open" if on else "close"})
        elif on:
            self.events.put(("open_window", "open=workplace"))
        return "Workplace open." if on else "Closing the Workplace."

    def _act_workplace_sync(self, args: dict[str, Any]) -> None:
        self.workplace_board.sync(bool(args.get("open")), str(args.get("name") or ""), args.get("items"), args.get("selected"))
        self.agent.workplace = self._workplace_act if self.workplace_board.open else None

    def _act_workplace_save(self, args: dict[str, Any]) -> dict[str, Any]:
        name = self.workplace_board.save(str(args.get("name") or ""), args.get("items"))
        return {"ok": True, "name": name, "saved": self.workplace_board.saved()}

    def _act_workplace_list(self, _args: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "saved": self.workplace_board.saved()}

    def _act_workplace_load(self, args: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, **self.workplace_board.load(str(args.get("name") or ""))}

    def _act_workplace_delete(self, args: dict[str, Any]) -> dict[str, Any]:
        self.workplace_board.delete(str(args.get("name") or ""))
        return {"ok": True, "saved": self.workplace_board.saved()}

    def _act_workplace_file(self, args: dict[str, Any]) -> dict[str, Any]:
        """A dropped PDF or Word file: its text, read on this PC, so Nova can read and highlight it."""
        try:
            data = base64.b64decode(str(args.get("data") or ""), validate=True)
        except ValueError:
            return {"ok": False, "error": "That file didn't arrive whole."}
        try:
            return {"ok": True, "text": workplace.file_text(str(args.get("name") or ""), data)}
        except Exception as exc:  # pypdf and zip errors: the file stays on the board without its text
            return {"ok": False, "error": str(exc)[:200]}
