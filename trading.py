"""Trading lab: paper trading only, following the day-trader skill's method (Jakeschincariol/day-trader-skill, MIT,
11 skills: scanner, news, entry, exit, timemachine, risk, budget, broker, alerts, analyst, pelosi). The method is
adapted here as text and plain arithmetic; the repo itself is not copied in, and its broker step is left out on
purpose: there is no live-order code path anywhere in this file, no broker keys are stored, and no order is ever
placed. Paper trading is the default, and anything that would risk real money needs the owner's explicit say-so
first — the UI says so on every card.

Free public data only: Yahoo Finance charts and news, and a link to the House Clerk's disclosure search (its
filings are PDFs). Plain Python, standard library only, nothing to install.
Every network call has a short timeout and comes back as a clear error string instead of failing silently, so the
UI can say what went wrong. Not financial advice: most people who day trade lose money.

Adaptations, stated plainly: the original Time Machine replays 5-minute bars; this one replays daily bars (the
free chart endpoint's daily history), so its odds are a rough guide, not a prediction. The original scanner reads
thousands of charts; this one reads a short watchlist the owner gives, or eight liquid names by default.
"""
from __future__ import annotations

import json
import math
import random
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable

TIMEOUT_SECONDS = 10
MAX_SYMBOLS = 12
DEFAULT_WATCHLIST = ("AAPL", "MSFT", "NVDA", "TSLA", "AMD", "META", "AMZN", "GOOGL")
DEFAULT_ACCOUNT = 5000.0
DEFAULT_MAX_LOSS_PCT = 0.01      # risk at most 1% of the account on one trade
ORDER_CAP_SHARES = 1000
TIMEMACHINE_REPLAYS = 10_000
TIMEMACHINE_SEED = 19            # same seed, same numbers (the original's rule)
TIMEMACHINE_DAYS = 5
USER_AGENT = "Nova-Trading-Lab/1.0 (personal use; paper trading only)"
CLERK_URL = "https://disclosures-clerk.house.gov/PublicDisclosure/FinancialDisclosure"
_SYMBOL = re.compile(r"[A-Z0-9.\-^]{1,12}")


def _default_fetch(url: str) -> Any:
    """One public GET, parsed as JSON. Raises on any network or parse failure; callers turn that into words."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


def _short_error(error: Exception) -> str:
    if isinstance(error, urllib.error.HTTPError):
        return f"HTTP {error.code} from the data source"
    if isinstance(error, (TimeoutError, urllib.error.URLError)):
        return "the request timed out or the network is down"
    return " ".join(str(error).split())[:100] or "an unknown error"


def clean_symbol(value: Any) -> str | None:
    """A ticker as Yahoo Finance wants it (AAPL, BRK-B, ^GSPC), or None."""
    symbol = str(value or "").strip().upper()
    return symbol if _SYMBOL.fullmatch(symbol) and any(char.isalnum() for char in symbol) else None


# Well-known company names -> tickers, so typing "coca-cola" works instead of needing KO.
# Keys are the name lower-cased with every non-alphanumeric stripped ("Coca-Cola" -> "cocacola").
COMPANY_NAMES = {
    "apple": "AAPL", "microsoft": "MSFT", "nvidia": "NVDA", "tesla": "TSLA",
    "amazon": "AMZN", "alphabet": "GOOGL", "google": "GOOGL", "meta": "META", "facebook": "META",
    "amd": "AMD", "netflix": "NFLX", "cocacola": "KO", "cocacolacompany": "KO",
    "pepsi": "PEP", "pepsico": "PEP", "walmart": "WMT", "disney": "DIS", "nike": "NKE",
    "mcdonalds": "MCD", "starbucks": "SBUX", "intel": "INTC", "costco": "COST",
    "berkshire": "BRK-B", "berkshirehathaway": "BRK-B",
    "jpmorgan": "JPM", "jpmorganchase": "JPM", "chase": "JPM", "bankofamerica": "BAC",
    "visa": "V", "mastercard": "MA", "paypal": "PYPL", "uber": "UBER", "airbnb": "ABNB",
    "spotify": "SPOT", "cisco": "CSCO", "oracle": "ORCL", "adobe": "ADBE", "salesforce": "CRM",
    "ford": "F", "generalmotors": "GM", "exxon": "XOM", "exxonmobil": "XOM", "chevron": "CVX",
    "pfizer": "PFE", "johnsonjohnson": "JNJ", "jj": "JNJ", "proctergamble": "PG",
    "palantir": "PLTR", "coinbase": "COIN", "gamestop": "GME",
}


def resolve_symbol(value: Any) -> str | None:
    """A ticker from a ticker or a company name ("coca-cola" -> KO, "apple" -> AAPL), or None."""
    raw = str(value or "").strip()
    if not raw:
        return None
    key = re.sub(r"[^a-z0-9]", "", raw.lower())
    if key in COMPANY_NAMES:
        return COMPANY_NAMES[key]
    return clean_symbol(raw)


def _money(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _dollars(number: float) -> str:
    return f"${number:,.2f}"


def _bars_from_chart(data: Any) -> list[dict[str, Any]] | None:
    try:
        result = data["chart"]["result"][0]
        stamps = result["timestamp"]
        quote = result["indicators"]["quote"][0]
    except (KeyError, IndexError, TypeError):
        return None
    bars: list[dict[str, Any]] = []
    for index, stamp in enumerate(stamps):
        try:
            close = quote["close"][index]
            if close is None:
                continue
            bars.append({"date": datetime.fromtimestamp(stamp, timezone.utc).strftime("%Y-%m-%d"),
                         "open": float(quote["open"][index]), "high": float(quote["high"][index]),
                         "low": float(quote["low"][index]), "close": float(close),
                         "volume": quote["volume"][index] or 0})
        except (IndexError, TypeError, ValueError):
            continue
    return bars


def _range_levels(window: list[dict[str, Any]]) -> tuple[float, float, float]:
    """A window's 20-day range: (high, low, midpoint stop). One rule, used by entry, odds and scan alike."""
    top, bottom = max(bar["high"] for bar in window), min(bar["low"] for bar in window)
    return top, bottom, (top + bottom) / 2


def rsi(bars: list[dict[str, Any]], period: int = 14) -> float | None:
    """Wilder's RSI over the last `period` closes, or None when there aren't enough bars."""
    if len(bars) < period + 1:
        return None
    gains, losses = 0.0, 0.0
    for i in range(len(bars) - period, len(bars)):
        change = bars[i]["close"] - bars[i - 1]["close"]
        gains += max(change, 0.0)
        losses += max(-change, 0.0)
    if losses == 0:
        return 100.0 if gains > 0 else 50.0
    return 100 - 100 / (1 + (gains / period) / (losses / period))


def entry_exit(bars: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, str]:
    """The entry timer's plan from daily bars: the first close above the prior 20-day high triggers it; the stop
    is the range midpoint and the target is 1R above the entry (the original's rule, on daily bars)."""
    if len(bars) < 21:
        return None, "Need at least 21 daily bars to work out an entry — try again when there's more history."
    top, bottom, stop = _range_levels(bars[-21:-1])
    last = bars[-1]["close"]
    entry = last if last > top else top
    return {"top": top, "bottom": bottom, "last": last, "entry": entry, "stop": stop,
            "target": entry + (entry - stop), "triggered": last > top}, ""


def position_size(account: float, max_loss: float, entry: float, stop: float) -> tuple[dict[str, Any] | None, str]:
    """The budget manager's sizing: shares are the floor of the smallest of the max-loss limit, the cash on hand
    and the order cap — the original's rule, in dollars (its worked example: a $5,000 account with a $50 max loss
    takes 8 shares at $364.18, costing $2,913.44 and losing $46.88 at the stop)."""
    risk = entry - stop
    if account <= 0:
        return None, "The account has to be more than $0."
    if max_loss <= 0:
        return None, "The max loss per trade has to be more than $0."
    if risk <= 0:
        return None, "The stop has to sit below the entry — otherwise one share already loses more than the limit."
    shares = max(0, min(math.floor(max_loss / risk), math.floor(account / entry), ORDER_CAP_SHARES))
    return {"shares": shares, "cost": shares * entry, "loss_at_stop": shares * risk, "risk_per_share": risk,
            "by_loss": math.floor(max_loss / risk)}, ""


def _first_hit(days: list[dict[str, Any]], stop: float, target: float) -> str:
    """Which the price touches first over the coming days: a day touching both counts as the stop (the original's
    rule — the stop is checked before the target in every bar)."""
    for bar in days:
        if bar["low"] <= stop:
            return "stop"
        if bar["high"] >= target:
            return "target"
    return "open"


def time_machine_odds(bars: list[dict[str, Any]], entry: float, stop: float, target: float,
                      replays: int = TIMEMACHINE_REPLAYS, seed: int = TIMEMACHINE_SEED,
                      days: int = TIMEMACHINE_DAYS) -> tuple[dict[str, Any] | None, str]:
    """The Time Machine on daily bars: (a) what the same setup really did every past time it fired, and (b)
    10,000 seeded replays of the next `days` days, each day drawn from the stock's own past bars (open, high, low
    and close as ratios, so a day's real range is kept). A simulation, not a prediction."""
    if len(bars) < 26:
        return None, "Need at least 26 daily bars to replay the odds — try again when there's more history."
    if stop >= entry or target <= entry:
        return None, "The stop has to sit below the entry and the target above it."
    fired = target_first = stop_first = still_open = 0
    for i in range(20, len(bars) - days):
        top, bottom, past_stop = _range_levels(bars[i - 20:i])
        if bars[i]["close"] > top:
            fired += 1
            past_entry = bars[i]["close"]
            past_target = past_entry + (past_entry - past_stop)
            outcome = _first_hit(bars[i + 1:i + 1 + days], past_stop, past_target)
            if outcome == "target":
                target_first += 1
            elif outcome == "stop":
                stop_first += 1
            else:
                still_open += 1
    ratios = []
    for i in range(1, len(bars)):
        prev = bars[i - 1]["close"]
        if prev > 0:
            ratios.append((bars[i]["open"] / prev, bars[i]["high"] / prev, bars[i]["low"] / prev,
                           bars[i]["close"] / prev))
    if not ratios:
        return None, "The price history has no usable days in it."
    rng = random.Random(seed)
    replay_target = replay_stop = replay_open = 0
    for _ in range(replays):
        price, outcome = entry, "open"
        for _day in range(days):
            _open, high, low, close = rng.choice(ratios)
            if price * low <= stop:
                outcome = "stop"
                break
            if price * high >= target:
                outcome = "target"
                break
            price *= close
        if outcome == "target":
            replay_target += 1
        elif outcome == "stop":
            replay_stop += 1
        else:
            replay_open += 1
    return {"fired": fired, "past_target": target_first, "past_stop": stop_first, "past_open": still_open,
            "replays": replays, "target_pct": 100 * replay_target / replays, "stop_pct": 100 * replay_stop / replays,
            "open_pct": 100 * replay_open / replays, "days": days}, ""


def _scan_setups(bars: list[dict[str, Any]]) -> list[str]:
    """The scanner's setups on daily bars: a breakout (a close above the 20-day high), an oversold
    bounce (RSI under 30 and up on the day), and a flag (a tight 5-day range after a 10%+ run)."""
    setups: list[str] = []
    last = bars[-1]
    if len(bars) >= 21:
        top = max(bar["high"] for bar in bars[-21:-1])
        if last["close"] > top:
            setups.append(f"Breakout — closed above the 20-day high ({_dollars(top)})")
    value = rsi(bars)
    if value is not None and value < 30 and last["close"] > last["open"]:
        setups.append(f"Oversold bounce — RSI(14) {value:.0f}, up on the day")
    if len(bars) >= 26:
        run = bars[-6]["close"] / bars[-26]["close"] - 1 if bars[-26]["close"] > 0 else 0
        recent = bars[-5:]
        span = (max(bar["high"] for bar in recent) - min(bar["low"] for bar in recent)) / last["close"]
        if run >= 0.10 and span <= 0.02:
            setups.append("Flag — a tight 5-day range after a 10%+ run")
    return setups


class TradingDesk:
    """One lab's worth of paper trading: `act(action, arguments)` answers the Trading tab's cards. It reads free
    public data and does arithmetic; it holds no money, no broker account and no keys, and it cannot place an
    order — there is deliberately no code here that talks to a broker."""

    def __init__(self, fetcher: Callable[[str], Any] | None = None) -> None:
        self._fetch = fetcher or _default_fetch

    # ---------- data (defensive: every failure is a sentence, never a crash) ----------

    def _chart(self, symbol: str, range_: str = "6mo") -> tuple[list[dict[str, Any]] | None, str]:
        url = ("https://query1.finance.yahoo.com/v8/finance/chart/" + urllib.parse.quote(symbol)
               + f"?range={range_}&interval=1d&includePrePost=false")
        try:
            data = self._fetch(url)
        except Exception as error:  # noqa: BLE001 - any network failure is a sentence for the UI
            if isinstance(error, urllib.error.HTTPError) and error.code == 404:
                return None, (f"No such symbol as {symbol} on Yahoo Finance — try a ticker like AAPL, "
                              "or a company name like Coca-Cola.")
            return None, (f"Couldn't reach Yahoo Finance for {symbol} ({_short_error(error)}). "
                          "Check Nova is online and try again.")
        bars = _bars_from_chart(data)
        if bars is None:
            return None, f"Yahoo Finance sent back something unexpected for {symbol} — try again in a bit."
        if not bars:
            return None, f"No price history for {symbol} — check the symbol is right."
        return bars, ""

    def _news(self, symbol: str) -> tuple[list[dict[str, Any]], str]:
        url = ("https://query2.finance.yahoo.com/v1/finance/search?q=" + urllib.parse.quote(symbol)
               + "&newsCount=8&quotesCount=0")
        try:
            data = self._fetch(url)
        except Exception as error:  # noqa: BLE001 - any network failure is a sentence for the UI
            return [], (f"Couldn't reach Yahoo Finance news for {symbol} ({_short_error(error)}). "
                        "Check Nova is online and try again.")
        items: list[dict[str, Any]] = []
        for entry in (data.get("news") or [])[:8]:
            if isinstance(entry, dict) and entry.get("title"):
                when = entry.get("providerPublishTime")
                items.append({"title": str(entry["title"])[:160], "source": str(entry.get("publisher") or "")[:40],
                              "when": datetime.fromtimestamp(when, timezone.utc).strftime("%d %b %H:%M")
                              if isinstance(when, (int, float)) else "",
                              "link": str(entry.get("link") or "")[:400]})
        return items, ""

    # ---------- the cards ----------

    def _symbols(self, arguments: dict[str, Any]) -> tuple[list[str], str]:
        raw = arguments.get("symbols") or arguments.get("symbol") or ""
        wanted = [item.strip() for item in str(raw).split(",") if item.strip()] or list(DEFAULT_WATCHLIST)
        symbols = [symbol for symbol in (resolve_symbol(item) for item in wanted[:MAX_SYMBOLS]) if symbol]
        if not symbols:
            return [], "Give a symbol, e.g. AAPL — or a few, comma-separated."
        return symbols, ""

    def _plan(self, arguments: dict[str, Any]) -> tuple[dict[str, Any] | None, str, str]:
        """An entry/stop/target plan: from the numbers given, or worked out from the symbol's own bars."""
        entry = _money(arguments.get("entry"), 0)
        stop = _money(arguments.get("stop"), 0)
        target = _money(arguments.get("target"), 0)
        if entry > 0 and stop > 0:
            if target <= 0:
                target = entry + (entry - stop)
            return {"entry": entry, "stop": stop, "target": target, "triggered": True}, "", ""
        symbol = resolve_symbol(arguments.get("symbol"))
        if symbol is None:
            return None, "", "Give a symbol, e.g. AAPL — or an entry and a stop."
        bars, problem = self._chart(symbol, "6mo")
        if bars is None:
            return None, "", problem
        plan, problem = entry_exit(bars)
        if plan is None:
            return None, "", problem
        return plan, symbol, ""

    def _act_scan(self, arguments: dict[str, Any]) -> dict[str, Any]:
        symbols, problem = self._symbols(arguments)
        if problem:
            return {"ok": False, "error": problem}
        lines: list[str] = []
        for symbol in symbols:
            bars, error = self._chart(symbol, "6mo")
            if bars is None:
                lines.append(f"{symbol}: {error}")
                continue
            last, prev = bars[-1], bars[-2] if len(bars) > 1 else bars[-1]
            change = 100 * (last["close"] / prev["close"] - 1) if prev["close"] else 0
            setups = _scan_setups(bars)
            head = f"{symbol} {_dollars(last['close'])} ({change:+.1f}% today)"
            lines.append(head + (" — " + "; ".join(setups) if setups else " — no setup today"))
        return {"ok": True, "title": "Scan", "lines": lines}

    def _act_news(self, arguments: dict[str, Any]) -> dict[str, Any]:
        symbol = resolve_symbol(arguments.get("symbol"))
        if symbol is None:
            return {"ok": False, "error": "Give a symbol, e.g. AAPL."}
        items, problem = self._news(symbol)
        if problem:
            return {"ok": False, "error": problem}
        lines = [f"{symbol}: {len(items)} headline{'s' if len(items) != 1 else ''} from Yahoo Finance."]
        if not items:
            lines.append("No headlines for it right now.")
        return {"ok": True, "title": f"News — {symbol}", "lines": lines,
                "items": items + [{"title": "Congress trades — search the House Clerk disclosures",
                                   "source": "House Clerk", "when": "", "link": CLERK_URL}]}

    def _act_entry(self, arguments: dict[str, Any]) -> dict[str, Any]:
        symbol = resolve_symbol(arguments.get("symbol"))
        if symbol is None:
            return {"ok": False, "error": "Give a symbol, e.g. AAPL."}
        bars, problem = self._chart(symbol, "6mo")
        if bars is None:
            return {"ok": False, "error": problem}
        plan, problem = entry_exit(bars)
        if plan is None:
            return {"ok": False, "error": problem}
        lines = [f"{symbol} last {_dollars(plan['last'])}; the 20-day range is "
                 f"{_dollars(plan['bottom'])} – {_dollars(plan['top'])}."]
        if plan["triggered"]:
            lines.append(f"Triggered — it closed above the range. Entry about {_dollars(plan['entry'])}.")
        else:
            lines.append(f"Not triggered yet — it triggers on a close above {_dollars(plan['top'])}.")
        lines.append(f"Stop {_dollars(plan['stop'])} (the range midpoint); target {_dollars(plan['target'])} (1R).")
        lines.append("Wait for the close: an intraday poke above the range doesn't count.")
        return {"ok": True, "title": f"Entry — {symbol}", "lines": lines}

    def _act_exit(self, arguments: dict[str, Any]) -> dict[str, Any]:
        plan, symbol, problem = self._plan(arguments)
        if plan is None:
            return {"ok": False, "error": problem}
        risk = plan["entry"] - plan["stop"]
        lines = [f"Entry {_dollars(plan['entry'])} · stop {_dollars(plan['stop'])} · target {_dollars(plan['target'])}"
                 + (f" — {symbol}" if symbol else "") + ".",
                 f"One share risks {_dollars(risk)} and makes {_dollars(plan['target'] - plan['entry'])} (1R).",
                 "Set the stop and the target before you enter, so you know when to get out.",
                 "If the stop is hit, the trade was wrong — don't move it further away."]
        return {"ok": True, "title": "Exit", "lines": lines}

    def _act_odds(self, arguments: dict[str, Any]) -> dict[str, Any]:
        plan, symbol, problem = self._plan(arguments)
        if plan is None:
            return {"ok": False, "error": problem}
        symbol = symbol or resolve_symbol(arguments.get("symbol"))
        if symbol is None:
            return {"ok": False, "error": "Give a symbol, e.g. AAPL, so the odds have a history to replay."}
        bars, error = self._chart(symbol, "2y")
        if bars is None:
            return {"ok": False, "error": error}
        odds, problem = time_machine_odds(bars, plan["entry"], plan["stop"], plan["target"])
        if odds is None:
            return {"ok": False, "error": problem}
        lines = [f"Entry {_dollars(plan['entry'])} · stop {_dollars(plan['stop'])} · target {_dollars(plan['target'])}"
                 + (f" — {symbol}" if symbol else "") + ".",
                 f"10,000 replays of the next {odds['days']} days: target first {odds['target_pct']:.1f}%, "
                 f"stop first {odds['stop_pct']:.1f}%, still open {odds['open_pct']:.1f}%.",
                 f"The same setup fired {odds['fired']} times before: target first {odds['past_target']}, "
                 f"stop first {odds['past_stop']}, still open {odds['past_open']}.",
                 "A simulation, not a prediction — daily bars, not 5-minute bars, so treat the odds as a rough guide.",
                 "Not financial advice."]
        return {"ok": True, "title": "Time Machine odds", "lines": lines}

    def _sized_plan(self, arguments: dict[str, Any]) -> tuple[float, float, dict[str, Any] | None,
                                                              dict[str, Any] | None, str]:
        """The shared risk/budget preamble: account, 1% max loss, plan and sizing — or an error to show."""
        account = _money(arguments.get("account"), DEFAULT_ACCOUNT)
        max_loss = account * DEFAULT_MAX_LOSS_PCT
        plan, _symbol, problem = self._plan(arguments)
        if plan is None:
            return account, max_loss, None, None, problem
        sizing, problem = position_size(account, max_loss, plan["entry"], plan["stop"])
        if sizing is None:
            return account, max_loss, None, None, problem
        return account, max_loss, plan, sizing, ""

    def _act_risk(self, arguments: dict[str, Any]) -> dict[str, Any]:
        account, max_loss, plan, sizing, problem = self._sized_plan(arguments)
        if plan is None or sizing is None:
            return {"ok": False, "error": problem}
        lines = [f"Account {_dollars(account)} · max loss per trade {_dollars(max_loss)} (1%).",
                 f"One share risks {_dollars(sizing['risk_per_share'])} — at most {sizing['by_loss']} shares "
                 f"on the loss limit.",
                 f"Daily loss limit: {_dollars(2 * max_loss)} — stop trading for the day past it. Max 3 trades a day."]
        shares = _money(arguments.get("shares"), 0)
        if shares > 0:
            reasons = []
            if shares * sizing["risk_per_share"] > max_loss:
                reasons.append(f"loses {_dollars(shares * sizing['risk_per_share'])} at the stop, over the "
                               f"{_dollars(max_loss)} limit")
            if shares * plan["entry"] > account:
                reasons.append("costs more than the account holds")
            if shares > ORDER_CAP_SHARES:
                reasons.append(f"is over the {ORDER_CAP_SHARES}-share order cap")
            lines.append(f"{int(shares)} shares: " + ("BLOCK — " + "; ".join(reasons) + "."
                         if reasons else "PASS — inside every limit."))
        return {"ok": True, "title": "Risk", "lines": lines}

    def _act_budget(self, arguments: dict[str, Any]) -> dict[str, Any]:
        account, max_loss, plan, sizing, problem = self._sized_plan(arguments)
        if plan is None or sizing is None:
            return {"ok": False, "error": problem}
        lines = [f"Account {_dollars(account)} · max loss per trade {_dollars(max_loss)} (1%).",
                 f"{sizing['shares']} shares at {_dollars(plan['entry'])} = {_dollars(sizing['cost'])}.",
                 f"A fill at the stop loses {_dollars(sizing['loss_at_stop'])}.",
                 "This sizes a plan — it places nothing. Paper trading only."]
        return {"ok": True, "title": "Budget", "lines": lines}

    def answer(self, action: str, arguments: dict[str, Any]) -> str:
        """The same card as plain text, for Nova to say out loud (the `trading` tool). Still paper only."""
        result = self.act(action, arguments)
        if not result["ok"]:
            return str(result["error"])
        return "\n".join([str(result.get("title") or "Trading")] + [str(line) for line in result.get("lines", [])])

    def _act_chart(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """The hero chart's data: the symbol's recent daily closes, straight from Yahoo Finance."""
        symbol = resolve_symbol(arguments.get("symbol"))
        if symbol is None:
            return {"ok": False, "error": "Type a symbol or a company name, e.g. AAPL or Coca-Cola."}
        bars, problem = self._chart(symbol, "3mo")
        if bars is None:
            return {"ok": False, "error": problem}
        points = [{"date": bar["date"], "close": round(bar["close"], 2)} for bar in bars[-60:]]
        last = bars[-1]["close"]
        prev = bars[-2]["close"] if len(bars) > 1 else last
        change = 100 * (last / prev - 1) if prev else 0
        return {"ok": True, "title": f"{symbol} — last {len(points)} closes",
                "symbol": symbol, "points": points, "last": round(last, 2),
                "change_pct": round(change, 1),
                "lines": [f"{symbol} last {_dollars(last)} ({change:+.1f}% on the day) — "
                          f"{len(points)} closes, {points[0]['date']} to {points[-1]['date']}."]}

    def act(self, action: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """One card's answer: scan, news, entry, exit, odds, risk or budget. Never places an order."""
        handler = {"scan": self._act_scan, "news": self._act_news, "entry": self._act_entry,
                   "exit": self._act_exit, "odds": self._act_odds, "risk": self._act_risk,
                   "budget": self._act_budget, "chart": self._act_chart}.get(str(action or "").strip().lower())
        if handler is None:
            return {"ok": False,
                    "error": "Not done: the action is scan, news, entry, exit, odds, risk, budget or chart."}
        try:
            return handler(arguments if isinstance(arguments, dict) else {})
        except Exception as error:  # noqa: BLE001 - a card must answer, even when something unexpected breaks
            return {"ok": False, "error": f"Trading hit a problem ({' '.join(str(error).split())[:120]}). Try again."}
