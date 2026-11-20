"""The prompt optimizer: a prompt rewritten so an AI answers it better, and checked rather than assumed.

The idea comes from linshenkx/prompt-optimizer (optimize, test both, compare, iterate); this is Nova's own
implementation with its own instructions (that project is AGPL-3.0, so none of its code or templates are used).

1. Rewrite the prompt (a user prompt, or a system prompt that sets up an assistant).
2. Run the original and the rewrite on the same model.
3. A judge sees both answers in random order, blind to which is which, and picks the better one for the author's goal.
4. If the original won, rewrite once more using the judge's note, and test again.
"""
from __future__ import annotations

import json
import random
import re
from dataclasses import asdict, dataclass, field
from typing import Callable

Ask = Callable[[str, str], str]  # (system, prompt) -> the model's answer
MAX_ROUNDS = 2

REWRITE = {
    "user": ("You improve prompts. Rewrite the prompt you're given so an AI model answers it better. Keep the "
             "author's goal, facts, names and language exactly; never invent requirements. Make clear what the task "
             "is, the context the model needs, the constraints (length, tone, audience, format) and what a good answer "
             "looks like. Where something essential is missing, add a short [placeholder] the author can fill in. "
             "Reply with only the new prompt, no preamble."),
    "system": ("You improve system prompts. Rewrite the system prompt you're given so the assistant it sets up "
               "behaves better. Keep its purpose, facts and rules; never invent new rules. Make clear the assistant's "
               "role and audience, what good output looks like, the rules in order of importance with the reason for "
               "each, and what to do when unsure or when a request falls outside its job. Reply with only the new "
               "system prompt, no preamble."),
}
SAMPLE_TASK = "Write a short, typical first message a user might send to this assistant, and nothing else."
JUDGE = ("You compare two answers, A and B, written for the same request. Decide which better gives the request's "
         "author what they wanted: correct, complete, following every constraint, clear and well organised. Length is "
         "not quality. Reply with only JSON: {\"winner\": \"A\" or \"B\" or \"tie\", \"why\": \"one sentence\", "
         "\"fix\": \"one sentence: what the losing prompt should say to do better\"}")


@dataclass
class Result:
    original: str
    optimized: str
    kind: str
    winner: str = "untested"   # "optimized", "original", "tie" or "untested"
    why: str = ""
    rounds: int = 1
    answers: dict[str, str] = field(default_factory=dict)

    def summary(self) -> str:
        verdict = {"optimized": "tested: the new prompt's answer was better",
                   "original": "tested: the original still did better, so keep it or edit the new one",
                   "tie": "tested: both answered about as well",
                   "untested": "not tested"}[self.winner]
        return (f"Optimized {self.kind} prompt ({verdict}{f'; {self.why}' if self.why else ''}):\n\n{self.optimized}")

    def as_dict(self) -> dict:
        return asdict(self)


def clean(text: str) -> str:
    """The model's rewrite without wrappers it sometimes adds (code fences, "Here is…", quotes)."""
    text = re.sub(r"^(here(?:'s| is) (?:the |an |your )?(?:improved|optimi[sz]ed|rewritten|new) (?:system )?prompt:?\s*)",
                  "", text.strip(), flags=re.IGNORECASE)
    fenced = re.fullmatch(r"```[a-z]*\n(.*?)\n```", text.strip(), re.DOTALL)
    if fenced:
        text = fenced[1]
    return text.strip().strip('"“”').strip()


def verdict(text: str) -> dict[str, str]:
    found = re.search(r"\{.*\}", text, re.DOTALL)
    try:
        data = json.loads(found[0]) if found else {}
    except ValueError:
        data = {}
    winner = str(data.get("winner", "tie")).strip().upper()
    return {"winner": winner if winner in ("A", "B") else "TIE", "why": str(data.get("why") or "")[:300],
            "fix": str(data.get("fix") or "")[:300]}


def _answer(ask: Ask, kind: str, prompt: str, sample: str) -> str:
    return ask(prompt, sample) if kind == "system" else ask("", prompt)


def optimize(prompt: str, ask: Ask, kind: str = "user", test: bool = True,
             shuffle: Callable[[list], None] = random.shuffle) -> Result:
    prompt = str(prompt).strip()
    if not prompt:
        raise ValueError("give the prompt to optimize")
    kind = kind if kind in REWRITE else "user"
    optimized = clean(ask(REWRITE[kind], prompt))
    result = Result(prompt, optimized, kind)
    if not test:
        return result
    sample = ask("", f"System prompt:\n{prompt}\n\n{SAMPLE_TASK}").strip() if kind == "system" else ""
    original_answer = _answer(ask, kind, prompt, sample)
    request = sample or prompt
    for round_number in range(1, MAX_ROUNDS + 1):
        new_answer = _answer(ask, kind, result.optimized, sample)
        pair = [("original", original_answer), ("optimized", new_answer)]
        shuffle(pair)
        judged = verdict(ask(JUDGE, f"Request:\n{request}\n\nAnswer A:\n{pair[0][1]}\n\nAnswer B:\n{pair[1][1]}"))
        winner = {"A": pair[0][0], "B": pair[1][0]}.get(judged["winner"], "tie")
        result.winner, result.why, result.rounds = winner, judged["why"], round_number
        result.answers = {"original": original_answer, "optimized": new_answer}
        if winner != "original" or round_number == MAX_ROUNDS:
            break
        result.optimized = clean(ask(REWRITE[kind], f"{prompt}\n\n(Your last rewrite lost to the original. A judge said: "
                                                     f"{judged['fix'] or judged['why']})"))
    return result
