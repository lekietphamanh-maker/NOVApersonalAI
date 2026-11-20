"""Nova's side of the HUD controls: the Library moved by voice and gestures, questions answered out loud, and the
owner's own gestures doing what they chose."""
from __future__ import annotations

import queue
import sys
import tempfile
import threading
import time
import types
import unittest
import unittest.mock
from pathlib import Path

try:
    import tkinter  # noqa: F401  (Windows has it; a bare Linux Python may not)
except ImportError:
    sys.modules["tkinter"] = types.SimpleNamespace(Tk=object, TclError=Exception)

import dashboard  # noqa: E402
from library import Library  # noqa: E402


class FakeUi:
    def __init__(self) -> None:
        self.clients = [object()]
        self.sent: list[dict] = []

    def emit(self, event: dict) -> None:
        self.sent.append(event)


class LibraryControlTests(unittest.TestCase):
    def setUp(self) -> None:
        vault = Path(tempfile.mkdtemp())
        shelf = Library(vault)
        shelf.save("Drone app", topic="Robotics")
        self.pressed: list[str] = []
        self.app = types.SimpleNamespace(library_open=True, ui=FakeUi(), library_gesture=("", 0.0), gesture_screen="",
                                         _library=lambda: shelf, _set_voice_state=lambda *_args: None,
                                         _toast=lambda *_args: None, creative=types.SimpleNamespace(open_window=lambda: None))
        original = dashboard.media_keys.press
        dashboard.media_keys.press = lambda action, times=1: self.pressed.append(action)
        self.addCleanup(setattr, dashboard.media_keys, "press", original)

    def commands(self) -> list[str]:
        return [event["command"] for event in self.app.ui.sent]

    def test_gestures_move_the_library_while_it_is_open(self) -> None:
        for action in ("next", "previous", "play_pause", "volume_down", "volume_down", "volume_down", "creative"):
            dashboard.AlfredApp._run_gesture(self.app, action)
        # a held 👎 repeats every 0.2 s: it goes back once
        self.assertEqual(self.commands(), ["next", "previous", "open", "back", "close"])
        self.assertEqual(self.pressed, [])  # no music keys while the Library has them

    def test_with_the_library_closed_gestures_work_as_always(self) -> None:
        self.app.library_open = False
        dashboard.AlfredApp._run_gesture(self.app, "volume_up")
        self.assertEqual(self.pressed, ["volume_up"])
        self.assertEqual(self.app.ui.sent, [])

    def test_short_spoken_commands_move_it_and_anything_else_goes_to_nova(self) -> None:
        said = lambda text: dashboard.AlfredApp._library_said(self.app, text)  # noqa: E731
        self.assertTrue(said("next one"))
        self.assertTrue(said("open 2"))
        self.assertTrue(said("open the drone app"))
        self.assertEqual(self.app.ui.sent[-1], {"type": "library_command", "command": "goto", "kind": "project",
                                                "name": "Drone app", "by": "voice"})
        self.assertFalse(said("open youtube"))  # nothing called that: Nova handles it
        self.assertFalse(said("what's the weather tomorrow"))
        self.app.library_open = False
        self.assertFalse(said("next"))
        self.assertEqual(self.commands(), ["next", "pick", "goto"])



class AnswerOutLoudTests(unittest.TestCase):
    def setUp(self) -> None:
        import threading
        self.event = threading.Event()
        self.states: list[str] = []
        self.app = types.SimpleNamespace(pending_approval=None, _set_voice_state=lambda text, tone="": self.states.append(text))
        self.app._act_approve = lambda args: dashboard.AlfredApp._act_approve(self.app, args)
        self.app._hotkey = lambda which: dashboard.hotkeys.DEFAULTS[which]
        for method in ("_answer", "_question_hint"):
            setattr(self.app, method, types.MethodType(getattr(dashboard.AlfredApp, method), self.app))

    def ask(self, name: str) -> dict:
        import threading
        self.app.pending_approval = {"id": "q1", "event": threading.Event(), "approved": None, "name": name}
        return self.app.pending_approval

    def test_yes_or_no_answers_what_nova_asked(self) -> None:
        answer = lambda text: dashboard.AlfredApp._answer_out_loud(self.app, text)  # noqa: E731
        self.assertFalse(answer("yes"))  # nothing asked: a normal request
        pending = self.ask("add_task")
        self.assertTrue(answer("Yeah, please"))
        self.assertTrue(pending["event"].is_set() and pending["approved"])
        pending = self.ask("send_online")
        self.assertTrue(answer("keep it here"))
        self.assertFalse(pending["approved"])
        pending = self.ask("send_online")
        self.assertTrue(answer("send it to Claude"))
        self.assertTrue(pending["approved"])
        pending = self.ask("add_task")
        self.assertTrue(answer("what's the weather"))  # neither: Nova asks again for a yes or no
        self.assertFalse(pending["event"].is_set())
        self.assertTrue(self.states[-1].startswith("SAY “YES” OR “NO” · OR PRESS"))


class OwnGestureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings: dict = {"custom_gestures": []}
        self.toasts: list[str] = []
        self.sent: list[str] = []
        self.pressed: list[str] = []
        app = types.SimpleNamespace(settings=self.settings, gesture_recording=False, library_open=False, ui=FakeUi(),
                                    gestures=types.SimpleNamespace(running=True, custom=[], record=lambda *_args: None))
        app._custom_gestures = lambda: dashboard.AlfredApp._custom_gestures(app)
        app._gestures_state = lambda: dashboard.AlfredApp._gestures_state(app)
        app._save_setting = lambda key, value: self.settings.__setitem__(key, value)
        app._save_custom_gestures = lambda items: dashboard.AlfredApp._save_custom_gestures(app, items)
        app._update = lambda **_changes: None
        app._toast = lambda text, *_args: self.toasts.append(text)
        app._act_send = lambda args: self.sent.append(args["text"])
        app._act_stop = lambda _args: self.sent.append("(stop)")
        app._open_library = lambda text="": self.sent.append("(library)")
        app.creative = types.SimpleNamespace(open_window=lambda: None)
        app._run_own_gesture = lambda gesture_id: dashboard.AlfredApp._run_own_gesture(app, gesture_id)
        self.app = app
        original = dashboard.media_keys.press
        dashboard.media_keys.press = lambda action, times=1: self.pressed.append(action)
        self.addCleanup(setattr, dashboard.media_keys, "press", original)

    def add(self, **args):
        return dashboard.AlfredApp._act_gesture_add(self.app, args)

    def test_a_known_pose_is_saved_and_does_what_was_chosen(self) -> None:
        self.assertIsNone(self.add(name="Weather", pose="Pointing_Up", action="ask", phrase="what's the weather today?"))
        saved = self.settings["custom_gestures"][0]
        self.assertEqual((saved["pose"], saved["action"]), ("Pointing_Up", "ask"))
        self.assertEqual(self.app.gestures.custom, self.settings["custom_gestures"])  # the webcam reader knows it now
        dashboard.AlfredApp._run_gesture(self.app, f"custom:{saved['id']}")
        self.assertEqual(self.sent, ["what's the weather today?"])
        self.assertIn("Weather → Ask Nova something", self.toasts[-1])

    def test_mistakes_are_refused(self) -> None:
        self.add(name="Point", pose="Pointing_Up", action="mute")
        for args, words in (({"name": "", "pose": "record", "action": "mute"}, "name"),
                            ({"name": "x", "pose": "record", "action": "fly"}, "Choose"),
                            ({"name": "x", "pose": "record", "action": "ask"}, "asked"),
                            ({"name": "point", "pose": "ILoveYou", "action": "mute"}, "already"),
                            ({"name": "Other", "pose": "Pointing_Up", "action": "next"}, "already does")):
            self.assertIn(words, self.add(**args)["error"])

    def test_recording_waits_for_the_webcam_then_saves(self) -> None:
        self.app.root = types.SimpleNamespace(after=lambda *_args: None)
        self.assertIsNone(self.add(name="Rock on", pose="record", action="library"))
        self.assertTrue(self.app.gesture_recording)
        dashboard.AlfredApp._gesture_recorded(self.app, {"id": "r1", "name": "Rock on", "action": "library", "phrase": ""},
                                              [[0.0] * 42] * 12)
        self.assertEqual(self.settings["custom_gestures"][0]["id"], "r1")
        dashboard.AlfredApp._run_gesture(self.app, "custom:r1")
        self.assertEqual(self.sent, ["(library)"])


class AutopilotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings: dict = {}
        self.states: list[str] = []
        self.updates: list[dict] = []
        self.spoken: list[str] = []
        self.events: queue.Queue = queue.Queue()
        self.app = types.SimpleNamespace(
            settings=self.settings, agent=types.SimpleNamespace(autopilot=False), assist=None,
            turn_cancel=threading.Event(), closing=False, pending_approval=None, events=self.events,
            state={"switches": {"speak": False, "mic": False}},
            voice=types.SimpleNamespace(say=self.spoken.append),
            _save_setting=self.settings.__setitem__, _update=lambda **changes: self.updates.append(changes),
            _set_voice_state=lambda text, _tone: self.states.append(text), _poll_keys=lambda: None,
            _stop_walkthrough=lambda: None, _hotkey=lambda _name: (0x11, 0x12),
            AUTOPILOT_SWITCHES=dashboard.AlfredApp.AUTOPILOT_SWITCHES, AGENT_SWITCHES=dashboard.AlfredApp.AGENT_SWITCHES)
        for method in ("_ask_and_wait", "_wait_for_answer", "_set_autopilot_setting", "_answer", "_question_hint", "_act_approve"):  # the real ones, on the stand-in
            setattr(self.app, method, types.MethodType(getattr(dashboard.AlfredApp, method), self.app))

    def confirm(self, name: str, **arguments) -> bool:
        return dashboard.AlfredApp._confirm_action(self.app, name, arguments)

    def ask(self, name: str, **arguments) -> tuple[threading.Thread, list[bool]]:
        """Start a question on its own thread and wait until Nova is waiting for the answer."""
        answers: list[bool] = []
        worker = threading.Thread(target=lambda: answers.append(self.confirm(name, **arguments)), daemon=True)
        worker.start()
        for _ in range(100):
            if self.app.pending_approval is not None:
                break
            time.sleep(0.02)
        self.assertIsNotNone(self.app.pending_approval, "Nova never started waiting for an answer")
        return worker, answers

    def test_safe_steps_just_happen_on_autopilot(self) -> None:
        self.app.agent.autopilot, self.app.assist = True, object()
        self.assertTrue(self.confirm("click", summary='Click button "Next" in "ArtGuard Setup"'))
        self.assertTrue(self.confirm("web_search", summary="Search the web (DuckDuckGo) for:\n\nartguard install"))
        self.assertTrue(self.events.empty() and not self.spoken)  # nothing was shown, said or asked
        self.assertEqual(self.states[0], 'AUTOPILOT · Click button "Next" in "ArtGuard Setup"')

    def test_by_default_nothing_asks_not_even_money_or_deleting(self) -> None:
        self.app.agent.autopilot, self.app.assist = True, object()
        for name, arguments in (("click", {"summary": 'Click button "Pay now" in "Shop"'}),
                                ("click", {"summary": 'Click button "Delete" in "Files"'}),
                                ("type_text", {"summary": 'Type into edit "Password" in "Sign in":\n\nx'}),
                                ("add_task", {"task": "buy milk"}), ("library", {"summary": "Save this to your library"}),
                                ("draft_mail", {"summary": "Save this Gmail draft"}), ("set_location", {"summary": "Use Da Nang"})):
            self.assertTrue(self.confirm(name, **arguments), name)
        self.assertTrue(self.events.empty() and not self.spoken)

    def test_a_question_is_asked_out_loud_with_no_popup_and_a_spoken_yes_answers_it(self) -> None:
        self.app.agent.autopilot, self.app.assist = True, object()
        self.settings["ask_risky"] = True
        worker, answers = self.ask("click", summary='Click button "Pay now" in "Shop"')
        self.assertTrue(self.events.empty())  # no pop-up, nothing to click
        self.assertEqual(self.spoken, ["This could spend money, send or post something, delete or submit: Click button Pay now in Shop. "
                                       "Should I go ahead?"])
        self.assertTrue(self.states[-1].startswith("SAY “YES” OR “NO” · OR PRESS"))
        dashboard.AlfredApp._act_approve(self.app, {"id": self.app.pending_approval["id"], "yes": True})  # what a spoken yes does
        worker.join(5)
        self.assertEqual(answers, [True])
        self.assertIsNone(self.app.pending_approval)

    def test_what_leaves_the_pc_still_asks_on_autopilot_and_esc_ends_the_wait(self) -> None:
        self.app.agent.autopilot, self.app.assist = True, object()
        for name, spoken in (("send_online", "Should I send it to Claude?"), ("ask_claude", "Should I send this question to Claude?")):
            self.spoken.clear()
            worker, answers = self.ask(name, summary="Send this question to Claude", **({"speak": spoken} if name == "send_online" else {}))
            self.assertEqual(self.spoken, [spoken])
            self.app.turn_cancel.set()  # Esc
            worker.join(5)
            self.assertEqual(answers, [False])
            self.app.turn_cancel.clear()

    def test_the_no_key_answers_the_question(self) -> None:
        self.app.assist = object()
        worker, answers = self.ask("click", summary='Click button "Next" in "Setup"')
        self.app._answer(False)  # what pressing the no key does
        worker.join(5)
        self.assertEqual((answers, self.states[-1]), ([False], "NO"))

    def test_with_autopilot_off_every_step_asks(self) -> None:
        self.app.assist = object()
        worker, answers = self.ask("click", summary='Click button "Next" in "Setup"')
        self.assertEqual(self.spoken, ["Okay to click button Next in Setup?"])
        self.app.turn_cancel.set()
        worker.join(5)
        self.assertEqual(answers, [False])

    def test_nobody_answering_is_asked_again_and_then_counts_as_no(self) -> None:
        self.app.assist = object()
        original = dashboard.ASK_REMIND_SECONDS, dashboard.ASK_GIVE_UP_SECONDS
        dashboard.ASK_REMIND_SECONDS, dashboard.ASK_GIVE_UP_SECONDS = 0.3, 0.7
        self.addCleanup(lambda: setattr(dashboard, "ASK_REMIND_SECONDS", original[0]))
        self.addCleanup(lambda: setattr(dashboard, "ASK_GIVE_UP_SECONDS", original[1]))
        worker, answers = self.ask("click", summary='Click button "Next" in "Setup"')
        worker.join(5)
        self.assertEqual(answers, [False])
        self.assertEqual(self.spoken[1:], ["Still waiting for a yes or no.", "No answer, so I didn't do it."])

    def test_with_voice_questions_off_the_old_popup_comes_back(self) -> None:
        self.app.assist = object()
        self.settings["ask_by_voice"] = False
        worker, answers = self.ask("click", summary='Click button "Next" in "Setup"')
        self.assertEqual(self.events.get(timeout=5)[0], "approval_open")
        dashboard.AlfredApp._act_approve(self.app, {"id": self.app.pending_approval["id"], "yes": True})
        worker.join(5)
        self.assertEqual((answers, self.events.get(timeout=5)[0]), ([True], "approval_closed"))

    def test_consent_is_asked_once_then_screen_assist_stays_on(self) -> None:
        import screen_assist
        started: list[int] = []
        original, was_windows = screen_assist.ScreenAssist, dashboard.IS_WINDOWS
        screen_assist.ScreenAssist = lambda: started.append(1) or types.SimpleNamespace(close=lambda: None)
        dashboard.IS_WINDOWS = True
        self.addCleanup(setattr, screen_assist, "ScreenAssist", original)
        self.addCleanup(setattr, dashboard, "IS_WINDOWS", was_windows)
        act = lambda **args: dashboard.AlfredApp._act_assist(self.app, args)  # noqa: E731
        self.assertEqual(act(on=True), {"need_consent": "assist"})
        self.assertIsNone(act(on=True, consented=True))
        self.assertEqual((self.settings["assist_consented"], self.settings["autopilot"], self.settings["assist_on"],
                          self.app.agent.autopilot, started), (True, True, True, True, [1]))
        self.assertIsNone(act(on=True))  # already on: nothing started twice
        self.assertEqual(started, [1])
        self.assertIsNone(act(on=False))
        self.assertFalse(self.settings["assist_on"])
        self.assertIsNone(act(on=True))  # no second consent question
        self.assertEqual((started, self.settings["assist_on"]), ([1, 1], True))

    def test_first_run_switches_everything_on_once_and_respects_what_the_owner_set(self) -> None:
        was_windows = dashboard.IS_WINDOWS
        dashboard.IS_WINDOWS = True
        self.addCleanup(setattr, dashboard, "IS_WINDOWS", was_windows)
        settings: dict = {"second_brain": False}  # the owner had turned the second brain off before
        saved = lambda key, value: settings.__setitem__(key, value)  # noqa: E731
        self.assertTrue(dashboard._always_on_defaults(settings, saved))
        self.assertEqual({key: settings[key] for key in ("assist_consented", "autopilot", "assist_on", "second_brain_consented", "second_brain")},
                         {"assist_consented": True, "autopilot": True, "assist_on": True, "second_brain_consented": True,
                          "second_brain": False})
        settings["assist_on"] = False  # switched off later: it stays off
        self.assertFalse(dashboard._always_on_defaults(settings, saved))
        self.assertFalse(settings["assist_on"])

    def test_autopilot_can_be_switched_off_and_on(self) -> None:
        dashboard.AlfredApp._act_autopilot(self.app, {"on": False})
        self.assertEqual((self.settings["autopilot"], self.app.agent.autopilot), (False, False))
        dashboard.AlfredApp._act_autopilot(self.app, {"on": True})
        self.assertEqual((self.settings["autopilot"], self.app.agent.autopilot), (True, True))


class ClaudePlanChoiceTests(unittest.TestCase):
    """SETTINGS → Claude → Pay with: the Claude plan (Claude Code) by default when it is installed, else the API key."""

    def app(self, settings: dict, claude_code: str | None, key: str | None):
        import claude_expert
        import claude_code as code
        patches = [unittest.mock.patch.object(code, "find", lambda: claude_code),
                   unittest.mock.patch.object(claude_expert, "key", lambda: key),
                   unittest.mock.patch.object(claude_expert, "key_hint", lambda: "…abcd" if key else ""),
                   unittest.mock.patch.object(claude_expert, "available", lambda: bool(key))]
        for active in patches:
            active.start()
            self.addCleanup(active.stop)
        updates: list[dict] = []
        warmed: list[bool] = []
        app = types.SimpleNamespace(settings=settings, agent=types.SimpleNamespace(cloud=None, warm_plan=lambda: warmed.append(True)),
                                    tool_server=None, _update=lambda **changes: updates.append(changes))
        app.warmed = warmed
        for method in ("_claude_via", "_claude_ready", "_brain_choice", "_apply_claude", "_cloud_tool", "_cloud_agent",
                       "_api_entries", "_api_entry", "_api_key", "_brains_state"):
            setattr(app, method, types.MethodType(getattr(dashboard.AlfredApp, method), app))
        app.updates = updates
        return app

    def test_the_plan_is_the_default_when_claude_code_is_installed(self) -> None:
        app = self.app({"brain": "claude"}, "claude", None)
        app._apply_claude()
        self.assertTrue(getattr(app.agent.cloud, "plan", False))
        self.assertIsNotNone(app.agent.cloud_tools)  # a tool that can't run here can go to Claude on the plan
        self.assertIsNotNone(app.tool_server)
        self.assertEqual((app.updates[-1]["claude"]["via"], app.updates[-1]["claude"]["on"]), ("plan", True))
        self.assertEqual(app.warmed, [True])  # Claude Code starts before the first question
        app.agent.cloud.close()
        app.tool_server.shutdown()

    def test_without_claude_code_or_a_key_claude_is_off(self) -> None:
        app = self.app({"brain": "claude"}, None, None)
        app._apply_claude()
        self.assertIsNone(app.agent.cloud)
        self.assertEqual(app.updates[-1]["claude"]["via"], "key")

    def test_the_owner_can_choose_the_api_key(self) -> None:
        app = self.app({"brain": "claude", "claude_via": "key"}, "claude", "sk-ant-" + "x" * 40)
        with unittest.mock.patch.object(dashboard.cloud_brain, "CloudBrain", lambda key, model, effort: types.SimpleNamespace(key=key)):
            app._apply_claude()
        self.assertFalse(getattr(app.agent.cloud, "plan", False))
        self.assertTrue(app.agent.cloud.key.startswith("sk-ant-"))


class TelegramTurnTests(unittest.TestCase):
    """A turn asked from Telegram: autopilot steps just happen, other questions are asked in the chat, and the
    send_file tool exists only during that turn."""

    def setUp(self) -> None:
        self.settings: dict = {}
        self.events: queue.Queue = queue.Queue()
        self.seen: dict = {}

        def ask(text, approve_tool, screen=None, cancel=None):
            self.seen.update(text=text, screen=screen, send_file=agent.send_file,
                             web=approve_tool("web", {"summary": "Open example.com"}),
                             online=approve_tool("send_online", {"summary": "Send it to Claude?"}))
            return "Done."
        agent = types.SimpleNamespace(autopilot=True, send_file=None, ask=ask)
        self.agent = agent
        self.app = types.SimpleNamespace(settings=self.settings, agent=agent, agent_lock=threading.Lock(), events=self.events,
                                         turn_cancel=threading.Event(), assist=None)

    def test_autopilot_steps_happen_and_questions_go_to_the_chat(self) -> None:
        asked: list[str] = []
        reply = dashboard.AlfredApp._ask_from_telegram(self.app, "open example.com and send me the report",
                                                       lambda summary: asked.append(summary) or False, lambda words: "sent")
        self.assertEqual(reply, "Done.")
        self.assertEqual((self.seen["web"], self.seen["online"]), (True, False))
        self.assertEqual(asked, ["Send it to Claude?"])
        self.assertEqual(self.seen["send_file"]("report"), "sent")
        self.assertIsNone(self.agent.send_file)  # gone after the turn
        self.assertEqual(self.events.get_nowait(), ("phone_chat", ("YOU · TELEGRAM", "open example.com and send me the report", "user")))

    def test_without_autopilot_every_step_is_asked_in_the_chat(self) -> None:
        self.agent.autopilot = False
        asked: list[str] = []
        dashboard.AlfredApp._ask_from_telegram(self.app, "hi", lambda summary: asked.append(summary) or True, lambda _w: "")
        self.assertEqual(asked, ["Open example.com", "Send it to Claude?"])


class DiscoverSkillOfferTests(unittest.TestCase):
    """A study that proposes a skill: offered, read, then added only when the owner says so."""

    def test_a_proposed_skill_waits_for_the_owner(self) -> None:
        import skills as skill_notes
        vault = Path(tempfile.mkdtemp())
        (vault / "outputs").mkdir()
        (vault / "outputs" / "study.md").write_text(
            "It sorts files.\n\n```skill\n---\ntitle: Tidy downloads\nsays: tidy my downloads\nschedule: manual\n"
            "tools: \nbrain: auto\noutput: yes\n---\nSort the Downloads folder by type.\n```\n", encoding="utf-8")
        toasts: list[str] = []
        app = types.SimpleNamespace(discover_studies={"Discover a b": "a/b"}, skill_offers=[], _vault_folder=lambda: vault,
                                    _toast=lambda text, tone="info", action=None: toasts.append(text),
                                    skills=skill_notes.Skills(vault), _update=lambda **_: None, _skills_state=lambda: {},
                                    _discover_state=lambda **_: {})
        for method in ("_offer_skill", "_act_discover_install_skill", "_act_discover_drop_skill"):
            setattr(app, method, types.MethodType(getattr(dashboard.AlfredApp, method), app))
        app._offer_skill("Discover a b", "outputs/study.md")
        self.assertEqual([offer["repo"] for offer in app.skill_offers], ["a/b"])
        self.assertEqual(app.skills.all(), [])  # nothing added yet
        app._act_discover_install_skill({"repo": "a/b"})
        self.assertEqual([skill.title for skill in app.skills.all()], ["Tidy downloads"])
        self.assertEqual(app.skill_offers, [])
        self.assertIn("Skill added: Tidy downloads", toasts[-1])


if __name__ == "__main__":
    unittest.main()


class EveryButtonReachesNovaTests(unittest.TestCase):
    """Each act("name") in the HUD's scripts is an action Nova accepts (one missing answers "Unknown action")."""

    def test_the_hud_only_asks_for_actions_nova_runs(self) -> None:
        import re
        ui = Path(__file__).resolve().parent.parent / "ui"
        asked = set()
        for script in ("app.js", "library.js", "world.js", "advance.js", "workplace.js"):
            asked |= set(re.findall(r"""\bact\(\s*["']([a-z_]+)["']""", (ui / script).read_text(encoding="utf-8")))
        self.assertIn("world", asked)
        self.assertEqual(sorted(asked - dashboard.AlfredApp.ACTIONS), [])
        for name in asked:
            self.assertTrue(callable(getattr(dashboard.AlfredApp, f"_act_{name}", None)), name)
