"""The Workplace, wired into Nova: the HUD's actions, the board sent with each question while it's open, and Nova's
hands on it (the workplace tool). A mixin for AlfredApp; the board itself is workplace.WorkplaceBoard."""
from __future__ import annotations

import base64
import secrets
from typing import Any

import workplace
from agent import SCREEN_MARKER


class WorkplaceActions:
    def _workplace_act(self, action: str, arguments: dict[str, Any]) -> str:
        vision_model = self.state["model"].get("vision")
        look = (lambda image, question: workplace.ask_picture(self.agent.base_url, vision_model, image, question)) \
            if vision_model else None
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
