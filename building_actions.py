"""Building mode, wired into Nova: the HUD's actions, the bench sent with each question while it's open, and Nova's hands
on it (the building tool). A mixin for AlfredApp; the bench itself is building.BuildingBench."""
from __future__ import annotations

import secrets
from typing import Any

from agent import SCREEN_MARKER


class BuildingActions:
    def _building_act(self, action: str, arguments: dict[str, Any]) -> str:
        return self.building_bench.act(action, arguments)

    def _with_building(self, prompt: str) -> str:
        """The question as the model gets it: the open bench rides along like a screen does (never saved, and only the
        latest one stays in the conversation)."""
        bench = self.building_bench.context()
        if not bench or SCREEN_MARKER in prompt:
            return prompt
        return f"{prompt}{SCREEN_MARKER} {secrets.token_hex(4)}: {bench}"

    def _open_building(self, on: bool) -> str:
        if self.ui.clients:
            self.ui.emit({"type": "building_command", "command": "open" if on else "close"})
        elif on:
            self.events.put(("open_window", "open=building"))
        return "Building mode open." if on else "Closing Building mode."

    def _act_build_sync(self, args: dict[str, Any]) -> None:
        self.building_bench.sync(bool(args.get("open")), str(args.get("name") or ""), str(args.get("title") or ""),
                                 str(args.get("text") or ""), args.get("circuit"), args.get("bom"), args.get("steps"),
                                 str(args.get("notes") or ""), str(args.get("applied") or ""), args.get("result"))
        self.agent.building = self._building_act if self.building_bench.open else None

    def _act_build_save(self, args: dict[str, Any]) -> dict[str, Any]:
        name = self.building_bench.save(str(args.get("name") or ""), str(args.get("title") or ""), args.get("circuit"),
                                        args.get("bom"), args.get("steps"), str(args.get("notes") or ""))
        return {"ok": True, "name": name, "saved": self.building_bench.saved()}

    def _act_build_list(self, _args: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "saved": self.building_bench.saved()}

    def _act_build_load(self, args: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, **self.building_bench.load(str(args.get("name") or ""))}

    def _act_build_delete(self, args: dict[str, Any]) -> dict[str, Any]:
        self.building_bench.delete(str(args.get("name") or ""))
        return {"ok": True, "saved": self.building_bench.saved()}
