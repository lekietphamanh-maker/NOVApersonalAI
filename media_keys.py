"""System media keys: work with Spotify, YouTube in a browser, Windows Media Player and most players."""
from __future__ import annotations

ACTIONS = {"volume_up": 0xAF, "volume_down": 0xAE, "mute": 0xAD, "next": 0xB0, "previous": 0xB1, "play_pause": 0xB3}
KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP = 0x1, 0x2


def press(action: str, times: int = 1) -> None:
    import sys
    if sys.platform == "darwin":  # no media keys to send: the volume and the player are told directly
        import mac
        if action in ("volume_up", "volume_down", "mute"):
            mac.change_volume(action, times)
        else:
            mac.media(action)
        return
    import ctypes
    key = ACTIONS[action]
    for _ in range(max(1, min(times, 25))):
        ctypes.windll.user32.keybd_event(key, 0, KEYEVENTF_EXTENDEDKEY, 0)
        ctypes.windll.user32.keybd_event(key, 0, KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP, 0)
