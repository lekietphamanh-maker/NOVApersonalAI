"""User-triggered local screen text extraction. Nothing is saved automatically."""
from __future__ import annotations

import asyncio
import ctypes
import io
from typing import Any

MAX_TEXT = 6000


def list_monitors() -> list[dict[str, Any]]:
    try:
        import mss
        with mss.mss() as capture:
            return [dict(monitor) for monitor in capture.monitors[1:]]
    except Exception as exc:
        raise RuntimeError(f"Could not enumerate displays: {exc}") from exc


def _accessible_text() -> tuple[str, bool]:
    """Read visible UI Automation text from the foreground window, skipping password controls and edits."""
    try:
        from pywinauto import Desktop
        handle = ctypes.windll.user32.GetForegroundWindow()
        if not handle:
            return "", False
        window = Desktop(backend="uia").window(handle=handle)
        title = window.window_text().strip()
        chunks: list[str] = []
        controls = [window]
        controls.extend(window.descendants())
        for control in controls:
            info = control.element_info
            if bool(getattr(info, "is_password", False)):
                continue
            kind = str(getattr(info, "control_type", ""))
            # Do not read editable fields, even if the provider fails to mark passwords.
            if kind in {"Edit", "ComboBox", "Document"}:
                continue
            if kind not in {"Text", "Button", "TabItem", "ListItem", "TreeItem", "Hyperlink", "MenuItem", "Header", "CheckBox", "RadioButton"}:
                continue
            value = control.window_text().strip()
            if value and value not in chunks:
                chunks.append(value)
            if sum(map(len, chunks)) >= MAX_TEXT:
                break
        text = "\n".join(chunks)
        if title and title not in text:
            text = f"Window: {title}\n{text}"
        return text[:MAX_TEXT], True
    except Exception:
        # OCR fallback below first verifies that UIA can enumerate password boxes.
        return "", False


def _password_rectangles() -> list[tuple[int, int, int, int]]:
    """Find password control bounds so OCR can black them out before recognition."""
    from pywinauto import Desktop
    desktop = Desktop(backend="uia")
    rectangles: list[tuple[int, int, int, int]] = []
    for window in desktop.windows(visible_only=True):
        try:
            controls = [window]
            controls.extend(window.descendants())
            for control in controls:
                if bool(getattr(control.element_info, "is_password", False)):
                    rect = control.rectangle()
                    rectangles.append((rect.left, rect.top, rect.right, rect.bottom))
        except Exception:
            # If even one visible window's UIA tree cannot be inspected, do not OCR it.
            raise RuntimeError("Password fields could not be checked safely; screen OCR was skipped.")
    return rectangles


async def _recognize_png(png: bytes) -> str:
    from winrt.windows.graphics.imaging import BitmapDecoder, BitmapPixelFormat, BitmapAlphaMode
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream
    stream = InMemoryRandomAccessStream()
    writer = DataWriter(stream)
    writer.write_bytes(png)
    await writer.store_async()
    await writer.flush_async()
    stream.seek(0)
    decoder = await BitmapDecoder.create_async(stream)
    bitmap = await decoder.get_software_bitmap_async(BitmapPixelFormat.BGRA8, BitmapAlphaMode.PREMULTIPLIED)
    engine = OcrEngine.try_create_from_user_profile_languages()
    if engine is None:
        raise RuntimeError("Windows local OCR has no installed language pack for the current Windows account.")
    result = await engine.recognize_async(bitmap)
    return str(result.text or "")[:MAX_TEXT]


def read_display(monitor_index: int) -> dict[str, str]:
    """Explicitly capture one selected display. UIA preferred; OCR is in-memory fallback."""
    accessible, checked = _accessible_text()
    if accessible.strip():
        return {"source": "Windows UI Automation", "text": accessible, "warning": "Editable fields and password controls were skipped."}
    if not checked:
        # UIA must be available to verify/blackout password controls before OCR.
        raise RuntimeError("Accessible text was unavailable and password fields could not be safely checked. OCR was not run.")
    try:
        import mss
        from PIL import Image, ImageDraw
        monitors = list_monitors()
        if monitor_index < 1 or monitor_index > len(monitors):
            raise RuntimeError("That display is no longer available; refresh the display list and try again.")
        monitor = monitors[monitor_index - 1]
        with mss.mss() as capture:
            raw = capture.grab(monitor)
        image = Image.frombytes("RGB", raw.size, raw.rgb)
        draw = ImageDraw.Draw(image)
        # Mask every password control from all visible windows before local OCR.
        for left, top, right, bottom in _password_rectangles():
            x1, y1 = left - monitor["left"], top - monitor["top"]
            x2, y2 = right - monitor["left"], bottom - monitor["top"]
            if x2 > 0 and y2 > 0 and x1 < image.width and y1 < image.height:
                draw.rectangle((max(0, x1), max(0, y1), min(image.width, x2), min(image.height, y2)), fill="black")
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        image.close()
        text = asyncio.run(_recognize_png(buffer.getvalue()))
        buffer.close()
        if not text.strip():
            raise RuntimeError("Windows OCR found no readable text on this display.")
        return {"source": "Windows local OCR", "text": text, "warning": "Pixels stayed in memory and were discarded; OCR can miss small text or images. Detected password-field rectangles were masked."}
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Local OCR failed: {exc}") from exc
