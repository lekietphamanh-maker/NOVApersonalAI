"""Which brain answers a turn: the online brain the owner chose (Claude, or the free one on Ollama Cloud), or the local
model on this PC.

What counts as private is the owner's choice (SETTINGS → Model). "secrets" (the default): only passwords, codes, bank
and card details, and mail; for those Nova asks out loud whether to answer on this PC. "personal": the old strict
rule below, kept on this PC without asking.

Under "personal" an online brain answers unless the turn touches something
personal. Personal stays on this PC: mail, the second brain and notes, what Nova remembers, where the owner is, the
screen, files and photos, health, money, passwords, family, the owner's own plans, anything said "privately". This only
decides where the owner's words go: nothing Nova keeps about the owner (name, remembered facts, location, notes, the
library) is ever sent online, and no online brain gets a tool that reads it.
"""
from __future__ import annotations

import re
import time

PERSONAL = re.compile(r"""
    \b(e-?mails?|gmail|inbox|mailbox|unread\ mail|outlook)\b
  | \b(second\ brain|my\ notes?|obsidian|vault|journal|diary)\b
  | \b(remember|forget|you\ know\ about\ me|about\ me|my\ name|who\ am\ i|call\ me|i\ told\ you)\b
  | \b(what|when|where|who|how|which)('?s|\ is|\ are|\ was|\ were|\ did|\ do)?\ my\b
  | \b(do|did|have)\ you\ (know|remember|have)\ my\b | \b(what|where)\ (did|have)\ i\b | \bdid\ i\b
  | \b(where\ am\ i|near\ me|nearby|around\ here|weather|forecast|umbrella|local\ news|what\ (should\ i|to)\ wear)\b
  | \b(will|is|does)\ it\ (rain|snow|storm|be\ (hot|cold|sunny|windy))
  | \b(rain|raining|temperature|hot|cold)\ (today|tonight|tomorrow|outside|now)\b
  | \bmy\ (location|address|home|house|apartment|room|city|area|neighbou?rhood|street)\b
  | \b(my|this)\ (screen|window|page|tab|files?|folders?|documents?|photos?|pictures?|desktop|downloads?|pc|computer|laptop|phone)\b
  | \bon\ (my|the)\ screen\b
  | \b(passwords?|passcode|pin\ code|otp|bank|account\ number|credit\ card|debit\ card|salary|income|tax(es)?|debts?|loans?)\b
  | \b(heart\ ?rate|bpm|blood|medical|medicines?|doctor|symptoms?|health|diagnos\w*|pregnan\w*|therapy)\b
  | \bmy\ (wife|husband|girlfriend|boyfriend|partner|mom|mum|mother|dad|father|parents?|brother|sister|son|daughter|kids?
         |children|family|friends?|boss|teacher|classmates?|grandma|grandpa|grandmother|grandfather|crush|ex)\b
  | \b(phone\ number|birthday|date\ of\ birth|passport|id\ card|social\ security)\b
  | \bmy\ (tasks?|to-?dos?|schedule|calendar|appointments?|plans?|meetings?|deadlines?|grades?|scores?|maps?|ideas?)\b
  | \b(my|nova'?s)\ (library|projects?|repos?|builds?|shelf)\b | \b(open|show|close)\ (the\ )?library\b
  | \b(to|in|into|from|on)\ (the|my)\ library\b | \blibrary\ (shelf|topics?)\b
  | \b(private|privately|secret|confidential|personal|locally|offline|local\ only)\b
  # Vietnamese
  | \b(thư|hộp\ thư|ghi\ chú|bộ\ não\ thứ\ hai|nhật\ ký|nhớ|quên|tên\ (tôi|mình|em|anh)|tôi\ là\ ai|ở\ đâu|địa\ chỉ)\b
  | \b(nhà\ (tôi|mình)|gần\ đây|thời\ tiết|trời\ mưa|nhiệt\ độ|mật\ khẩu|ngân\ hàng|tài\ khoản|lương|sức\ khỏe|bệnh)\b
  | \b(thuốc|bác\ sĩ|nhịp\ tim|màn\ hình|tệp|tập\ tin|ảnh\ của|hình\ của|vợ|chồng|bạn\ gái|bạn\ trai|người\ yêu)\b
  | \b(mẹ|bố|ba\ (tôi|mình)|anh\ trai|chị\ gái|em\ trai|em\ gái|con\ (tôi|mình)|gia\ đình|sếp|lịch(?!\ sử)|cuộc\ hẹn)\b
  | \b(kế\ hoạch\ của|riêng\ tư|bí\ mật|số\ điện\ thoại|sinh\ nhật|hộ\ chiếu|căn\ cước)\b
""", re.IGNORECASE | re.VERBOSE)
# Under "secrets": passwords, codes, bank and card details, and mail. Everything else may go to the chosen brain.
SECRETS = re.compile(r"""
    \b(pass\ ?words?|passcodes?|pin\ (code|number)s?|otp|2fa|two[-\ ]factor|(verification|security|recovery|login)\ codes?
       |seed\ phrase|private\ keys?|api\ keys?|bank(ing)?|account\ numbers?|(credit|debit|bank)\ cards?|card\ numbers?
       |cvv|iban|routing\ numbers?|social\ security|passport\ numbers?)\b
  | \b(e-?mails?|gmail|inbox|mailbox|unread\ mail|outlook|my\ mail)\b
  | \b(mật\ khẩu|mã\ (pin|otp|xác\ nhận)|ngân\ hàng|số\ tài\ khoản|thẻ\ (tín\ dụng|ngân\ hàng)|hộp\ thư|thư\ của)\b
""", re.IGNORECASE | re.VERBOSE)
MAIL = re.compile(r"\b(e-?mails?|gmail|inbox|mailbox|unread\ mail|outlook|my\ mail|hộp\ thư|thư\ của)\b", re.IGNORECASE)
PRIVATELY = re.compile(r"\b(privately|in\ private|local(ly|\ only)|offline|on\ this\ (pc|computer)|riêng\ tư)\b", re.IGNORECASE)
ASK_CLAUDE = re.compile(r"\b(ask|use|hỏi|dùng)\ claude\b", re.IGNORECASE)
YES = re.compile(r"^(yes|yeah|yep|yup|sure|ok(ay)?|do it|go ahead|please do|yes please|of course|correct|right|"
                 r"có|vâng|dạ|được|ừ|ok luôn|đồng ý)$", re.IGNORECASE)
NO = re.compile(r"^(no|nope|nah|don'?t|do not|no thanks|cancel|stop|never ?mind|not now|không|thôi|đừng)$", re.IGNORECASE)
ONLINE = re.compile(r"\b(send it|go online|online|(to |use |ask )?claude|the cloud|cloud)\b", re.IGNORECASE)
LOCAL = re.compile(r"\b(keep it|here|locally|local|this (pc|computer)|privately|private|riêng tư|máy này)\b", re.IGNORECASE)
OFFLINE_SECONDS = 30  # after the online brain couldn't be reached, answer locally this long before trying again


# "Auto" (the owner's choice in Settings): the AI on this PC answers everyday questions; these go to the online brain.
ADVANCED = re.compile(r"""
    \b(prove|proof|derive|derivation|theorem|integral|derivative|calculus|probability|statistics|regression
       |algorithm|complexity|architecture|refactor|debug|stack\ trace|traceback|segfault|race\ condition
       |research|in[-\ ]depth|thorough|literature|analy[sz]e|analysis|trade-?offs?|pros\ and\ cons|strategy
       |business\ plan|essay|contract|legal|compare|versus|vs\.?|explain\ why|step\ by\ step|design\ a)\b
""", re.IGNORECASE | re.VERBOSE)
CODE = re.compile(r"```|\bdef \w+\(|\bclass \w+[:(]|\bfunction \w+\(|=>|;\s*$|\bSELECT .* FROM\b", re.IGNORECASE | re.MULTILINE)


def advanced(text: str) -> bool:
    """Hard enough for the online brain under "Auto": long, multi-part, code, or research, analysis or proofs."""
    words = len(str(text).split())
    return words >= 45 or bool(CODE.search(text)) or (words >= 3 and bool(ADVANCED.search(text)))


def personal(text: str) -> bool:
    return bool(PERSONAL.search(str(text)))


def spoken_answer(text: str) -> bool | None:
    """A spoken yes or no to the question Nova asked (True: yes), or None when it is neither."""
    said = " ".join(re.sub(r"[^\w\s']", " ", str(text).lower()).split())
    said = re.sub(r"^(hey nova|nova|um|uh|well)\s+|\s+(please|thanks|thank you|nova)$", "", said).strip()
    return True if YES.match(said) else False if NO.match(said) else None


def spoken_place(text: str) -> str | None:
    """Where the owner said to answer a passwords-or-mail question: "online", "local", or None."""
    said = " ".join(str(text).lower().split())
    if LOCAL.search(said):
        return "local"
    return "online" if ONLINE.search(said) else None


class Router:
    def __init__(self) -> None:
        self._offline_until = 0.0

    def choose(self, text: str, cloud_ready: bool, screen_on: bool = False, private: str = "personal") -> tuple[str, str]:
        """('online' | 'local' | 'ask', why): why is 'online', 'asked', 'off', 'offline', 'screen' or 'personal'.
        'ask': under "secrets", a turn about passwords or mail: Nova asks the owner where it should be answered."""
        if not cloud_ready:
            return "local", "off"
        if screen_on:
            return "local", "screen"  # the turn carries what is on the owner's screen
        if time.monotonic() < self._offline_until:
            return "local", "offline"
        if ASK_CLAUDE.search(text):
            return "online", "asked"
        if private == "personal":
            return ("local", "personal") if personal(text) else ("online", "online")
        if PRIVATELY.search(text):
            return "local", "personal"
        if SECRETS.search(text):
            return "ask", "personal"
        return "online", "online"

    def offline(self) -> None:
        """The PC couldn't reach the internet: the local model answers for a while, then online is tried again."""
        self._offline_until = time.monotonic() + OFFLINE_SECONDS

    def is_offline(self) -> bool:
        return time.monotonic() < self._offline_until
