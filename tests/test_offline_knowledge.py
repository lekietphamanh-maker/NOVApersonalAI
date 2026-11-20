"""Offline knowledge: Wikipedia searched in a ZIM file on this PC, the newest file found in Kiwix's catalog and
downloaded with resuming, the owner's notes searched by meaning, and a city's roads kept for offline routes."""
from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

import notes_search
import offline_wikipedia as wiki

try:
    from libzim.writer import Creator, Hint, Item, StringProvider
    CAN_WRITE = True
except ImportError:  # some builds of libzim read ZIM files but can't make them
    CAN_WRITE = False

CATALOG = """<feed xmlns="http://www.w3.org/2005/Atom">
<entry><name>wikipedia_en_simple_all</name><flavour>nopic</flavour><updated>2026-08-01T00:00:00Z</updated>
<link rel="http://opds-spec.org/acquisition/open-access" type="application/x-zim" length="900"
 href="https://download.kiwix.org/zim/wikipedia/wikipedia_en_simple_all_nopic_2026-08.zim.meta4"/></entry>
<entry><name>wikipedia_en_simple_all</name><flavour>nopic</flavour><updated>2026-10-01T00:00:00Z</updated>
<link rel="http://opds-spec.org/acquisition/open-access" type="application/x-zim" length="1000"
 href="https://download.kiwix.org/zim/wikipedia/wikipedia_en_simple_all_nopic_2026-10.zim.meta4"/></entry>
<entry><name>wikipedia_en_simple_all</name><flavour>maxi</flavour><updated>2026-11-01T00:00:00Z</updated>
<link rel="http://opds-spec.org/acquisition/open-access" length="5000" href="https://x/maxi.zim.meta4"/></entry>
</feed>"""


class Answer(io.BytesIO):
    def __init__(self, data: bytes, status: int = 200, headers: dict | None = None) -> None:
        super().__init__(data)
        self.status, self.headers = status, headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def make_zim(folder: Path) -> Path:
    class Page(Item):
        def __init__(self, path: str, title: str, body: str) -> None:
            super().__init__()
            self.path, self.title, self.body = path, title, body

        def get_path(self) -> str:
            return self.path

        def get_title(self) -> str:
            return self.title

        def get_mimetype(self) -> str:
            return "text/html"

        def get_contentprovider(self):
            return StringProvider(self.body)

        def get_hints(self):
            return {Hint.FRONT_ARTICLE: True}
    path = folder / "wikipedia_en_simple_all_nopic_2026-10.zim"
    with Creator(str(path)).config_indexing(True, "eng") as creator:
        creator.set_mainpath("A/Tran_Hung_Dao")
        creator.add_item(Page("A/Tran_Hung_Dao", "Trần Hưng Đạo", "<html><body><p>Trần Hưng Đạo was a Vietnamese general "
                              "who defeated the Mongol invasions.</p><script>tracker()</script></body></html>"))
        creator.add_item(Page("A/Vaccine", "Vaccine", "<html><body><p>A vaccine trains the immune system.</p></body></html>"))
        creator.add_metadata("Title", "Test")
        creator.add_metadata("Language", "eng")
    return path


class WikipediaTests(unittest.TestCase):
    @unittest.skipUnless(CAN_WRITE, "this libzim can't make a test file")
    def test_answers_come_from_the_articles(self) -> None:
        folder = Path(tempfile.mkdtemp())
        make_zim(folder)
        reader = wiki.Wikipedia(folder)
        found = reader.search("Mongol invasions general")
        self.assertIn("## Trần Hưng Đạo", found)
        self.assertIn("defeated the Mongol invasions", found)
        self.assertNotIn("tracker", found)  # scripts aren't article text
        self.assertIn("Nothing in offline Wikipedia", reader.search("quantum chromodynamics"))

    def test_the_newest_file_of_the_pack_and_a_resumed_download(self) -> None:
        pack = wiki.pack("simple")
        found = wiki.parse_catalog(CATALOG, pack)
        self.assertEqual(found["url"], "https://download.kiwix.org/zim/wikipedia/wikipedia_en_simple_all_nopic_2026-10.zim")
        self.assertEqual(found["bytes"], 1000)
        folder = Path(tempfile.mkdtemp())
        (folder / "wikipedia_en_simple_all_nopic_2026-10.zim.part").write_bytes(b"x" * 400)  # cut off earlier
        (folder / "wikipedia_en_simple_all_nopic_2026-08.zim").write_bytes(b"old")
        asked: list = []

        def opener(request, timeout):
            asked.append((request.full_url, request.get_header("Range")))
            if "catalog" in request.full_url:
                return Answer(CATALOG.encode())
            return Answer(b"y" * 600, status=206)
        target = wiki.Wikipedia(folder, opener).download(pack)
        self.assertEqual(asked[-1][1], "bytes=400-")  # carried on from where it stopped
        self.assertEqual(target.stat().st_size, 1000)
        self.assertEqual([path.name for path in wiki.Wikipedia(folder).installed()], [target.name])  # the old edition went

    def test_nothing_downloaded_is_said_plainly(self) -> None:
        self.assertIn("isn't downloaded yet", wiki.Wikipedia(Path(tempfile.mkdtemp())).search("anything"))


class NotesTests(unittest.TestCase):
    def test_notes_are_found_by_meaning_and_kept_up_to_date(self) -> None:
        topics = {"sleep": [1.0, 0.0, 0.0], "money": [0.0, 1.0, 0.0], "food": [0.0, 0.0, 1.0]}
        words = {"sleep": ("bed", "sleep", "tired", "rest"), "money": ("budget", "money", "save"), "food": ("pho", "eat")}

        def embed(texts: list[str]) -> list[list[float]]:
            return [next((topics[topic] for topic, keys in words.items() if any(key in text.lower() for key in keys)),
                         [0.3, 0.3, 0.3]) for text in texts]
        vault = Path(tempfile.mkdtemp())
        (vault / "wiki").mkdir()
        (vault / "wiki" / "Habits.md").write_text("# Habits\n\nBed by 11 on weeknights.", encoding="utf-8")
        (vault / "wiki" / "Money.md").write_text("# Money\n\nThe budget for November.", encoding="utf-8")
        (vault / ".obsidian").mkdir()
        (vault / ".obsidian" / "config.md").write_text("ignored", encoding="utf-8")
        index = notes_search.NotesIndex(Path(tempfile.mkdtemp()) / "notes.sqlite3", embed)
        self.assertEqual(index.refresh(vault), {"read": 2, "removed": 0, "notes": 2})
        found = index.search("how much rest am I getting")
        self.assertTrue(found.splitlines()[2].startswith("## wiki/Habits.md"))
        self.assertEqual(index.refresh(vault)["read"], 0)  # nothing changed: nothing read again
        (vault / "wiki" / "Money.md").unlink()
        self.assertEqual(index.refresh(vault)["removed"], 1)
        self.assertEqual(index.count(), 1)

    def test_long_notes_are_cut_into_passages(self) -> None:
        pieces = notes_search.passages("\n\n".join(f"Paragraph {number} " + "word " * 100 for number in range(6)))
        self.assertTrue(len(pieces) >= 3 and all(len(piece) <= notes_search.PASSAGE_CHARS * 2 for piece in pieces))


class KeptCityTests(unittest.TestCase):
    def test_a_kept_city_serves_routes_inside_it_and_places_are_remembered(self) -> None:
        import routes
        from tests.test_routes import city
        calls: list[str] = []

        def opener(request, timeout):
            calls.append(request.full_url)
            if "nominatim" in request.full_url and "Saigon" in request.full_url:
                return Answer(json.dumps([{"lat": "10.79", "lon": "106.61", "boundingbox": ["10.70", "10.85", "106.55", "106.70"]}]).encode())
            if "nominatim" in request.full_url:
                return Answer(json.dumps([{"lat": "10.80", "lon": "106.60"}]).encode())
            return Answer(json.dumps(city()).encode())
        router = routes.Router(Path(tempfile.mkdtemp()), opener=opener, clock=lambda: 10_000.0 + len(calls) * 10)
        self.assertEqual(router.keep_city("Saigon"), "Saigon")
        self.assertEqual(router.kept_cities(), ["Saigon"])
        downloads = sum("overpass" in url for url in calls)
        router.route("A", "B", mode="walk")
        self.assertEqual(sum("overpass" in url for url in calls), downloads)  # the kept city's roads, no new download
        asked = len(calls)
        router.geocode("A")
        self.assertEqual(len(calls), asked)  # a place found once is remembered (works offline)


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(__import__("os").environ.get("ALFRED_TEST_DOWNLOADS") == "1", "set ALFRED_TEST_DOWNLOADS=1 to reach Kiwix")
class LiveCatalogTests(unittest.TestCase):
    def test_kiwix_has_each_pack(self) -> None:
        reader = wiki.Wikipedia(Path(tempfile.mkdtemp()))
        for pack in wiki.PACKS:
            found = reader.find(pack)
            print(pack.key, found)
            if found is None:  # what Kiwix lists under that name, so a renamed pack is easy to fix
                query = wiki.urlencode({"name": pack.name, "count": 50})
                with wiki.urlopen(wiki.Request(f"{wiki.CATALOG}?{query}", headers={"User-Agent": wiki.USER_AGENT}), timeout=30) as response:
                    print(response.read()[:3000].decode("utf-8", "replace"))
            self.assertIsNotNone(found, pack.key)
            self.assertTrue(found["url"].endswith(".zim") and found["bytes"] > 0)
