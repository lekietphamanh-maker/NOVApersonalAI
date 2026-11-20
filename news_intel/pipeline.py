"""One run of the news desk, in order: collect from every provider → normalize → remove duplicates → check dates
→ categorize → analyze with the AI → save → daily briefing → log what happened. A provider that fails is noted and
the run goes on without it; articles the AI couldn't read yet stay searchable and are tried again next time."""
from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from .analysis import AnalysisError, Analyzer, OllamaAnalyzer, Unreachable
from .briefing import make_briefing
from .collectors.gdelt import GdeltCollector
from .collectors.gnews import GNewsCollector
from .collectors.http import Fetcher, redact
from .collectors.rss import RssCollector
from .config import NewsConfig
from .normalize import canonical_url, clean, date_problem
from .store import Store

log = logging.getLogger("news_intel")


@dataclass
class RunReport:
    run_id: int
    collected: int = 0
    added: int = 0
    duplicates: int = 0
    rejected: dict[str, int] = field(default_factory=dict)
    processed: int = 0
    failed: int = 0
    providers: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    briefing: str = ""

    def line(self) -> str:
        return (f"collected {self.collected}, new {self.added}, duplicates {self.duplicates}, "
                f"skipped {sum(self.rejected.values())}, analyzed {self.processed}, failed {self.failed}, "
                f"problems {len(self.errors)}")


def default_collectors(config: NewsConfig, fetcher: Fetcher) -> list[Any]:
    collectors: list[Any] = [GNewsCollector(config.gnews_key, fetcher, config.gnews_lang, config.gnews_country,
                                            config.gnews_max)]
    if config.gdelt:
        collectors.append(GdeltCollector(fetcher, config.gdelt_max))
    collectors.append(RssCollector(config.feeds, fetcher, config.google_news_sites))
    return collectors


def run(config: NewsConfig | None = None, store: Store | None = None, collectors: list[Any] | None = None,
        analyzer: Analyzer | None = None, now: datetime | None = None,
        progress: Callable[[str], None] = lambda _message: None) -> RunReport:
    config = config or NewsConfig()
    own_store = store is None
    store = store or Store(config.db_path)
    now = now or datetime.now(timezone.utc)
    report = RunReport(run_id=store.start_run(now))
    try:
        # 1-2: collect, each provider on its own
        found = []
        for collector in collectors if collectors is not None else default_collectors(config, Fetcher()):
            progress(f"Collecting from {collector.name}…")
            try:
                articles = collector.collect()
            except Exception as exc:  # one provider failing never stops the run
                articles = []
                report.errors.append(redact(f"{collector.name}: {exc}"))
            report.providers[collector.name] = len(articles)
            report.errors += [redact(error) for error in getattr(collector, "errors", [])]
            found += articles
        report.collected = len(found)
        # 3-6: normalize, check dates, remove duplicates (the same link, or the same headline from one publisher), save
        rejected: Counter[str] = Counter()
        seen: set[str] = set()
        for article in found:
            clean(article)
            problem = date_problem(article, now, config.max_age_hours)
            key = canonical_url(article.url)
            if problem or not key or not article.title:
                rejected[problem or "no link or title"] += 1
                continue
            if key in seen or store.add(article, key, now) is None:
                report.duplicates += 1
            else:
                report.added += 1
            seen.add(key)
        report.rejected = dict(rejected)
        # 7-8: the AI reads the newest articles first; the rest wait for the next run
        analyzer = analyzer or OllamaAnalyzer(config.ollama_url, config.llm_model)
        done: list[int] = []
        pending = store.pending(config.max_analyze)
        for index, article in enumerate(pending, start=1):
            progress(f"Reading articles with {analyzer.model}: {index}/{len(pending)}")
            try:
                store.save_analysis(article["id"], analyzer.analyze(article), analyzer.model)
                report.processed += 1
                done.append(article["id"])
            except Unreachable as exc:
                report.errors.append(f"AI analysis stopped: {exc}. The articles are saved and wait for the next run.")
                break
            except (AnalysisError, KeyError, ValueError) as exc:
                store.mark_failed(article["id"], str(exc))
                report.failed += 1
        store.link_related(done)
        # 9-10: the briefing and the run log
        report.briefing = make_briefing(store, now)
    except Exception as exc:  # the run log still says what happened
        report.errors.append(redact(f"run stopped: {exc}"))
        raise
    finally:
        store.finish_run(report.run_id, collected=report.collected, added=report.added, duplicates=report.duplicates,
                         rejected=report.rejected, processed=report.processed, failed=report.failed,
                         providers=report.providers, errors=report.errors, briefing=report.briefing)
        log.info("news run %s: %s", report.run_id, report.line())
        for error in report.errors:
            log.warning("news run %s: %s", report.run_id, error)
        if own_store:
            store.close()
    return report
