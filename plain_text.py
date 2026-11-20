"""Plain words for Nova's replies, on screen and spoken: no emoji, emoticons or *actions*."""
from __future__ import annotations

import re

# Pictographs, symbols and dingbats, skin tones, flags, and the joiners that build emoji sequences.
_EMOJI = re.compile("[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U00002B00-\U00002BFF\U0000FE0E\U0000FE0F"
                    "\U0000200D\U000020E3]")
# :) ;-) :D =P <3 ^_^ xD, but not times (2:30), ratios (2:3) or links (https://).
_EMOTICON = re.compile(r"(?<![\w:/])(?:[:;=][-'^o]?[)(\]\[DPpOo3|/\\*]+|<3|\^_\^|[xX]D)(?![\w/])")
_ACTION = re.compile(r"\*(?:smiles?|grins?|laughs?|winks?|giggles?|chuckles?|sighs?|nods?|waves?|shrugs?|blushes|"
                     r"beams?|hugs?|claps?)(?: [a-z]+){0,3}\*", re.IGNORECASE)


def without_emoji(text: str) -> str:
    text = _ACTION.sub("", text)
    text = _EMOTICON.sub("", text)
    text = _EMOJI.sub("", text)
    return re.sub(r"[ \t]{2,}", " ", text)
