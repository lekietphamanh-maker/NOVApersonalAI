"""The prompt optimizer: rewrite, run both on the same model, a blind judge in random order, one more round when the
original wins, and a system prompt tested on a sample message it sets up."""
from __future__ import annotations

import json
import unittest

import prompt_optimizer as po


class Model:
    """Answers by what it's asked: rewrites, answers, samples and verdicts, recording every call."""

    def __init__(self, rewrites: list[str], verdicts: list[str]) -> None:
        self.rewrites, self.verdicts, self.calls = list(rewrites), list(verdicts), []

    def __call__(self, system: str, prompt: str) -> str:
        self.calls.append((system, prompt))
        if system in po.REWRITE.values():
            return self.rewrites.pop(0)
        if system == po.JUDGE:
            return self.verdicts.pop(0)
        if po.SAMPLE_TASK in prompt:
            return "How do I reset my password?"
        return f"answer to: {prompt[:30]}"


def keep_order(pair: list) -> None:
    pass  # A = original, B = optimized


class OptimizeTests(unittest.TestCase):
    def test_the_rewrite_wins_and_wrappers_are_removed(self) -> None:
        model = Model(["Here is the improved prompt:\n```\nWrite a 200-word cover letter for [role] at [company].\n```"],
                      [json.dumps({"winner": "B", "why": "it's specific", "fix": ""})])
        result = po.optimize("write me a cover letter", model, shuffle=keep_order)
        self.assertEqual(result.optimized, "Write a 200-word cover letter for [role] at [company].")
        self.assertEqual((result.winner, result.rounds), ("optimized", 1))
        self.assertIn("the new prompt's answer was better", result.summary())

    def test_the_judge_is_blind_to_which_is_which(self) -> None:
        swapped = lambda pair: pair.reverse()  # noqa: E731 - A = optimized, B = original
        model = Model(["Better prompt"], ['{"winner": "A", "why": "clearer"}'])
        self.assertEqual(po.optimize("prompt", model, shuffle=swapped).winner, "optimized")
        judge_prompt = next(prompt for system, prompt in model.calls if system == po.JUDGE)
        self.assertNotIn("optimized", judge_prompt.lower())
        self.assertNotIn("original", judge_prompt.lower())

    def test_a_losing_rewrite_gets_one_more_round_with_the_judges_note(self) -> None:
        model = Model(["Worse prompt", "Prompt v2"],
                      ['{"winner": "A", "why": "kept the tone", "fix": "say the tone is formal"}', '{"winner": "B"}'])
        result = po.optimize("prompt", model, shuffle=keep_order)
        self.assertEqual((result.optimized, result.winner, result.rounds), ("Prompt v2", "optimized", 2))
        second_rewrite = [prompt for system, prompt in model.calls if system in po.REWRITE.values()][1]
        self.assertIn("say the tone is formal", second_rewrite)

    def test_system_prompts_are_tested_on_a_sample_message(self) -> None:
        model = Model(["You are a support agent for Acme. Be brief."], ['{"winner": "tie"}'])
        result = po.optimize("support bot for acme", model, kind="system", shuffle=keep_order)
        answered = [(system, prompt) for system, prompt in model.calls if prompt == "How do I reset my password?"]
        self.assertEqual([system for system, _ in answered], ["support bot for acme", "You are a support agent for Acme. Be brief."])
        self.assertEqual(result.winner, "tie")

    def test_quick_mode_and_empty_prompts(self) -> None:
        model = Model(["Better"], [])
        self.assertEqual(po.optimize("x", model, test=False).winner, "untested")
        self.assertEqual(len(model.calls), 1)
        with self.assertRaises(ValueError):
            po.optimize("  ", model)


if __name__ == "__main__":
    unittest.main()
