"""Advance mode: a red HUD with the orb on the left and a board on the right. Row 1 is the whole Library, row 2 what
Nova can do (the Skills board), row 3 the owner's widgets (add, remove, reorder), row 4 separate apps (Rea and
Shannon in their own windows, self-hosted apps in Docker, desktop apps and the owner's own).

A mixin for AlfredApp: it uses the app's settings, state, ui, library and skills board, and keeps that file smaller.
"""
from __future__ import annotations

import threading
import webbrowser
from typing import Any

import app_window
import secret_store
import separate_apps
import skills_board

WIDGETS = {"clock": "Clock", "weather": "Weather", "timers": "Timers", "reminders": "Reminders", "tasks": "Tasks",
           "music": "Now playing", "pc": "This PC", "brain": "Who answers", "news": "Headlines"}
DEFAULT_WIDGETS = ["clock", "weather", "timers", "reminders", "music", "pc"]
OPENPROJECT_SECRET = "openproject_secret"


def clean_widgets(value: Any) -> list[str]:
    return list(dict.fromkeys(item for item in value if item in WIDGETS)) if isinstance(value, list) else list(DEFAULT_WIDGETS)


class AdvanceMode:
    settings: dict[str, Any]
    docker_apps: separate_apps.Docker

    def _advance_settings(self) -> dict[str, Any]:
        return {"advance": bool(self.settings.get("advance")),
                "advance_widgets": clean_widgets(self.settings.get("advance_widgets", DEFAULT_WIDGETS))}

    def _set_advance(self, on: bool) -> str:
        self._save_setting("advance", on)
        self._update(settings={"advance": on})
        return "Advance mode on." if on else "Advance mode off."

    def _act_advance(self, args: dict[str, Any]) -> None:
        self._set_advance(bool(args.get("on")))

    def _act_advance_widgets(self, args: dict[str, Any]) -> dict[str, Any] | None:
        widgets = clean_widgets(args.get("widgets"))
        self._save_setting("advance_widgets", widgets)
        self._update(settings={"advance_widgets": widgets})
        return None

    def _act_advance_board(self, _args: dict[str, Any]) -> dict[str, Any]:
        library = self._library().snapshot()
        board = skills_board.board(self._skills_status(), self._skills_state()["list"], self._hotkey_state())
        return {"ok": True, "library": {"projects": library["projects"], "topics": library["topics"]},
                "skills": board["entries"], "counts": board["counts"], "widgets": WIDGETS, "apps": self._apps_list(False)}

    # ---------- separate apps ----------

    def _apps_list(self, check: bool) -> list[dict[str, Any]]:
        """Every app with what it can do now. check=False skips the Docker questions (fast first paint)."""
        apps = []
        for app in separate_apps.CATALOG:
            item = {"id": app.id, "name": app.name, "what": app.what, "kind": app.kind, "runs_on": app.runs_on,
                    "licence": app.licence, "page": app.page, "state": ""}
            if app.kind == "docker" and check:
                item["state"] = self.docker_apps.status(app) or "no-docker"
            elif app.kind == "download":
                item["state"] = "installed" if separate_apps.installed_path(app) else "absent"
            apps.append(item)
        for own in separate_apps.own_apps(self.settings.get("advance_apps")):
            apps.append({"id": own.id, "name": own.name, "what": own.target, "kind": "own", "state": "", "runs_on": "",
                         "licence": "", "page": ""})
        return apps

    def _act_advance_apps(self, _args: dict[str, Any]) -> None:
        """Docker's answers come later as an advance_apps event: actions run on Nova's main thread, which never waits."""
        threading.Thread(target=lambda: self.ui.emit({"type": "advance_apps", "apps": self._apps_list(True)}),
                         name="NovaAppsCheck", daemon=True).start()

    def _open_app_window(self, view: str) -> None:
        """One of Nova's screens as its own app window, beside the HUD (same events, same actions)."""
        app_window.open_window(self.ui.url + f"&app={view}", self._data_folder() / "hud-browser")

    def _docker_job(self, app: separate_apps.App, start: bool) -> None:
        def secret() -> str:
            value = secret_store.load(OPENPROJECT_SECRET)
            if not value:
                import secrets
                value = secrets.token_hex(48)
                secret_store.save(OPENPROJECT_SECRET, value)
            return value

        def work() -> None:
            try:
                if start and self.docker_apps.status(app) == "running":
                    webbrowser.open(app.open_url)
                    return
                said = self.docker_apps.start(app, secret) if start else self.docker_apps.stop(app)
                self._toast(said, "info")
            except Exception as exc:  # Docker's own message: the owner can act on it
                action = {"label": "Get Docker", "url": separate_apps.DOCKER_PAGE} if "isn't installed" in str(exc) else None
                self._toast(f"{app.name}: {exc}", "warn", action)
            self.ui.emit({"type": "advance_apps", "apps": self._apps_list(True)})
        threading.Thread(target=work, name=f"NovaApp-{app.id}", daemon=True).start()

    def _act_app_open(self, args: dict[str, Any]) -> dict[str, Any] | None:
        app_id = str(args.get("id") or "")
        app = separate_apps.find(app_id)
        if app is None:
            own = next((item for item in separate_apps.own_apps(self.settings.get("advance_apps")) if item.id == app_id), None)
            if own is None:
                return {"ok": False, "error": "That app isn't on the board any more."}
            webbrowser.open(own.target) if separate_apps.is_web(own.target) else app_window.open_path(own.target)
            return None
        if app.kind == "window":
            self._open_app_window(app.id)
        elif app.kind == "docker":
            self._docker_job(app, start=True)  # opens it when it's already running
        elif app.kind == "download":
            path = separate_apps.installed_path(app)
            webbrowser.open(app.page) if path is None else app_window.open_path(path)
        else:
            webbrowser.open(app.open_url or app.page)
        return None

    def _act_app_stop(self, args: dict[str, Any]) -> dict[str, Any] | None:
        app = separate_apps.find(str(args.get("id") or ""))
        if app is None or app.kind != "docker":
            return {"ok": False, "error": "Only the Docker apps can be stopped from here."}
        self._docker_job(app, start=False)
        return None

    def _act_app_page(self, args: dict[str, Any]) -> dict[str, Any] | None:
        app = separate_apps.find(str(args.get("id") or ""))
        if app is None or not app.page:
            return {"ok": False, "error": "That app has no page."}
        webbrowser.open(app.page)
        return None

    def _act_app_add(self, args: dict[str, Any]) -> dict[str, Any]:
        saved = separate_apps.own_apps(self.settings.get("advance_apps"))
        if len(saved) >= separate_apps.MAX_OWN_APPS:
            return {"ok": False, "error": f"The board holds {separate_apps.MAX_OWN_APPS} of your own apps."}
        own = separate_apps.OwnApp.new(str(args.get("name", "")), str(args.get("target", "")))
        self._save_setting("advance_apps", [item.as_dict() for item in saved + [own]])
        return {"ok": True, "apps": self._apps_list(False)}

    def _act_app_remove(self, args: dict[str, Any]) -> dict[str, Any]:
        saved = [item for item in separate_apps.own_apps(self.settings.get("advance_apps")) if item.id != args.get("id")]
        self._save_setting("advance_apps", [item.as_dict() for item in saved])
        return {"ok": True, "apps": self._apps_list(False)}
