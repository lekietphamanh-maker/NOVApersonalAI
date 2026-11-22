"""Set up everything, wired into Nova: which steps this PC needs, and what turns each feature on once it's here.
A mixin for AlfredApp (see setup_everything.py for the runner and the installers)."""
from __future__ import annotations

import json
import sys
import time
from typing import Any
from urllib.request import urlopen

import claude_code
import cloud_agents
import kokoro_voice
import node_runtime
import notes_search
import screen_record
import setup_everything
import vision
import whisper_engine
from setup_everything import Step

NATURAL_VOICE = "Heart (US, female, most natural)"
FIRST_RUN_DELAY_MS = 20_000  # after the window, the model check and the first greeting


class SetupActions:
    def _ollama_up(self) -> bool:
        try:
            with urlopen(f"{self.agent.base_url.rstrip('/')}/api/version", timeout=3) as response:
                return bool(json.loads(response.read()).get("version"))
        except Exception:
            return False

    def _install_ollama(self, progress: setup_everything.Progress) -> None:
        setup_everything.install_ollama(progress)
        progress("Waiting for Ollama to start")
        if not setup_everything.wait_for(self._ollama_up):
            raise RuntimeError("Ollama was installed but doesn't answer yet: restart Nova, then Set up everything again")

    def _pull(self, name: str, progress: setup_everything.Progress) -> None:
        from hardware_advisor import pull_model
        if not self._ollama_up():
            raise RuntimeError("Ollama isn't running, so models can't be downloaded yet")
        pull_model(self.agent.base_url, name, progress)

    def _tuned(self, progress: setup_everything.Progress) -> None:
        setup_everything.wait_for(lambda: not self.tuning_now, 3600)  # auto-tune may have started on its own
        if self._model_tuned():
            return
        problem = self._tune(progress)
        if problem:
            raise RuntimeError(problem)

    def _model_tuned(self) -> bool:
        import auto_tune
        from build_info import VERSION
        return bool(self.settings.get("tuning")) and self.hardware is not None and \
            not auto_tune.due(self.settings.get("tuning"), VERSION, self.hardware)

    def _natural_voice(self) -> None:
        natural_already = (self.voice.voice_name or "").split(" (")[0] in ("Heart", "Bella", "Emma")
        if not natural_already:  # the owner's own pick of another Kokoro voice stays
            self._voice_installed(NATURAL_VOICE)

    def _ffmpeg(self, progress: setup_everything.Progress) -> None:
        if sys.platform == "darwin":
            brew = setup_everything.brew()
            if brew is None:
                raise RuntimeError("install Homebrew (brew.sh), then this step installs ffmpeg")
            setup_everything._command([brew, "install", "ffmpeg"], progress, "Installing ffmpeg with Homebrew")
        else:
            screen_record.install_ffmpeg(self._data_folder(), progress)

    def _agent_step(self, key: str) -> Step:
        agent = next(item for item in cloud_agents.AGENTS if item.key == key)
        found = claude_code.find if key == "claude-code" else (lambda: cloud_agents.find(agent))
        def install(progress: setup_everything.Progress) -> None:
            progress(f"Installing {agent.label}")
            cloud_agents.install(agent)
        return Step(f"agent-{key}", agent.label, f"Ready for the Cloud brain: sign in once with {agent.account}.", 150,
                    lambda: found() is not None, install)

    def _setup_steps(self, usb: bool = False) -> list[Step]:
        steps: list[Step] = []
        if not usb:
            steps.append(Step("ollama", "Ollama", "Runs the AI on this PC.", 1000, self._ollama_up, self._install_ollama,
                              self._resolve_model))  # finds the models, and tunes when it's due
            steps.append(Step("model", "The best AI model for this PC", "Measured on this PC: the strongest that stays quick.",
                              6000, self._model_tuned, self._tuned))
        steps += [
            Step("meaning", "Meaning search model", "Finds what you wrote about something, even in other words.", 300,
                 self._embedding_model_ready, lambda progress: self._pull(notes_search.MODEL, progress),
                 lambda: self._status_worker()),
            Step("voice", "Nova's natural voice", "Kokoro: the most natural voice, on this PC.", kokoro_voice.DOWNLOAD_MB,
                 kokoro_voice.installed, kokoro_voice.install, self._natural_voice),
        ]
        if sys.platform == "win32":
            steps.append(Step("whisper", "Whisper speech recognition", "Understands accents and broken English.",
                              whisper_engine.DOWNLOAD_MB, whisper_engine.installed, whisper_engine.install,
                              lambda: setattr(self.voice, "whisper", whisper_engine.WhisperEngine())))
        if not usb:
            steps.append(Step("vision", "Vision model", "Names anything you show the camera; reads pictures on this PC.",
                              int(vision.VISION_GB * 1024), lambda: bool(self.state["model"].get("vision")),
                              lambda progress: self._pull(vision.VISION_MODEL, progress),
                              lambda: self.events.put(("vision_pulled", vision.VISION_MODEL))))
        steps += [
            Step("ffmpeg", "ffmpeg", "Screen recording.", 150, lambda: screen_record.ffmpeg_path(self._data_folder()) is not None,
                 self._ffmpeg),
            Step("node", "Node.js", "Runs Rea, Claude Code, Codex and Gemini CLI.", 100,
                 lambda: node_runtime.find(str(self.settings.get("node_path") or "")) is not None, setup_everything.install_node),
            self._agent_step("claude-code"), self._agent_step("codex"), self._agent_step("gemini"),
        ]
        return steps

    def _setup_report(self, state: dict[str, Any]) -> None:
        self._update(setup=state)
        if not state["running"] and state["steps"]:
            self._toast(self.setup.summary(), "ok")
            self.events.put(("downloads", None))

    def _act_setup_everything(self, _args: dict[str, Any]) -> dict[str, Any] | None:
        # Not `from dashboard import USB`: run as `python dashboard.py` that module is __main__, and importing it
        # again loads a second copy of the whole app.
        if not self.setup.start(self._setup_steps(self.usb_edition)):
            return {"ok": False, "error": "Nova is setting up already."}
        return None

    def _act_setup_stop(self, _args: dict[str, Any]) -> None:
        self.setup.stop()
        self._toast("Stopping after the current step.", "info")

    def _setup_first_run(self) -> None:
        """The first start after install: Nova sets everything up by herself (the toast can stop it). Never in a
        smoke test or CI, where it would really install Ollama on the build machine."""
        if self.settings.get("setup_started") or not self.auto_setup:
            return
        self._save_setting("setup_started", time.strftime("%Y-%m-%d"))
        self._act_setup_everything({})
        self._toast("Setting up everything Nova needs (models, voice, speech recognition, tools). It runs in the "
                    "background; SETTINGS → Downloads shows each step.", "info", {"label": "Stop", "name": "setup_stop"})
