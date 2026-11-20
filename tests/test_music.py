"""Music mode: what's playing (from Windows' media controls), the sound bars, and the corner orb turning into a disc."""
import sys
import unittest

import numpy

import mini_orb
import music


class MusicTests(unittest.TestCase):
    def test_bars_follow_the_sound_low_to_high(self) -> None:
        t = numpy.arange(music.BLOCK) / music.RATE
        low = music.bands_from(numpy.sin(2 * numpy.pi * 100 * t) * 0.5)
        high = music.bands_from(numpy.sin(2 * numpy.pi * 5000 * t) * 0.5)
        self.assertLess(int(numpy.argmax(low)), 6)
        self.assertGreater(int(numpy.argmax(high)), 18)
        self.assertEqual(max(music.bands_from(numpy.zeros(music.BLOCK))), 0.0)
        falling = music.bands_from(numpy.zeros(music.BLOCK), [1.0] * music.BANDS)  # bars fall slowly, not at once
        self.assertTrue(all(0.5 < level < 1.0 for level in falling))

    def test_a_new_track_or_pause_is_noticed_once(self) -> None:
        tracks = [music.Track("Starboy", "The Weeknd", playing=True, app="Spotify"),
                  music.Track("Starboy", "The Weeknd", playing=True, app="Spotify"),
                  music.Track("Starboy", "The Weeknd", playing=False, app="Spotify"), None]
        changes = []
        player = music.Music(now_playing=lambda: tracks.pop(0), on_change=changes.append)
        for _ in range(4):
            player.check()
        self.assertEqual([None if change is None else change.playing for change in changes], [True, False, None])
        self.assertIsNone(player.state())
        self.assertEqual(music.app_name("SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify"), "Spotify")

    def test_the_corner_orb_becomes_a_spinning_disc_only_when_nothing_else_is_going_on(self) -> None:
        playing = {"music": {"playing": True}, "switches": {"mic": True}}
        self.assertEqual(mini_orb.mode_for(playing, False), "music")
        self.assertEqual(mini_orb.mode_for({**playing, "speaking": True}, False), "speak")
        self.assertEqual(mini_orb.mode_for(playing, True), "act")
        frame = mini_orb.render("music", 1.0, 0.0, (255, 176, 64), (None, [0.5] * music.BANDS))
        self.assertEqual((frame.size, frame.mode), ((mini_orb.SIZE, mini_orb.SIZE), "RGBA"))


@unittest.skipUnless(sys.platform == "win32", "Windows' media controls")
class WindowsMediaTests(unittest.TestCase):
    def test_reading_whats_playing_works_on_windows(self) -> None:
        track = music.windows_now_playing()  # usually nothing plays on a test machine
        print("now playing:", track)
        self.assertTrue(track is None or isinstance(track, music.Track))


if __name__ == "__main__":
    unittest.main()
