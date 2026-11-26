# Nova

An offline-first voice assistant for Windows. Say **"Hey Nova"** or hold **Ctrl+Alt** and talk: she hears you, sees your screen, answers out loud and can work your PC for you. The AI runs on your own PC by default; online brains are opt-in.

## Install

1. Install [Ollama](https://ollama.com/download).
2. Download **Nova-Setup.exe** from the [latest release](../../releases/latest) and run it (no admin needed).
3. Start Nova and click **Download** on the model she suggests for your PC.

**On a Mac** (Apple silicon): most of Nova runs there too, from source for now; see [INSTALL.md part I](INSTALL.md#i-nova-on-a-mac-apple-silicon-15-min).

Everything else is set up from inside Nova: **SETTINGS → Need to** has step-by-step folders for each feature. The full guide is in [INSTALL.md](INSTALL.md). Updates download in the background and install when you click **Restart to update**.

## What she does

| | |
|---|---|
| **Voice** | Wake word, hold-to-talk, interrupt any time. Whisper speech recognition and natural voices (Kokoro, Piper), all on your PC. |
| **Screen assist** | Reads the app you're in, points, highlights, and drives the mouse and keyboard step by step. Esc stops her. |
| **Brains** | The model on your PC, or Claude (your Claude plan via Claude Code, or an API key), or Ollama Cloud. Auto mode sends only hard questions online. |
| **Google** | Gmail (read and draft, never send), Calendar, Drive (read-only). Also served to Claude Code and Claude Desktop over MCP. |
| **World** | A live globe: earthquakes, disaster alerts, storms, fires, volcanoes and news by country. "What's happening in Japan?" |
| **Knowledge** | Second brain in Obsidian, a Library of your projects and ideas, a daily news desk with sources, a daily brief. Offline: Wikipedia on your PC (Kiwix ZIM files) and search of your own notes by meaning. |
| **Routes** | The fastest way from A to B with stops, worked out on your PC from OpenStreetMap roads, the search animated on the map. Keep a city's roads for offline use. |
| **Apps** | Instant commands with no AI (timers, volume, media, open apps). Real Word, Excel and PowerPoint files; OBS (record, stream, scenes); VS Code. Clicking on the screen is the fallback. |
| **Work** | Reminders, timers, skills (tasks run by phrase or schedule), long jobs and builds handed to Claude Code, Discover (GitHub picks studied read-only). |
| **Rea** | Reverse engineering with REA through Claude Code: the app drawn as a blueprint of its parts; click a part for what was found. Reports in the Library. |
| **Shannon** | An AI pentester on your own app: it attacks it for real and reports only proven holes, with proof and fix, on a mission board. Your apps on this PC or home network only. |
| **Creative mode** | Webcam mirror with hand-controlled 3D holograms, camera lenses, photo booth. |
| **Other screens** | Telegram from anywhere (even with the PC off, via your own Cloudflare relay), an old iPhone as a companion, the TV as a dashboard, the iPad as a keyboard and widget deck, a second laptop sharing memory. |

## Privacy

- By default nothing leaves your PC: the model, speech recognition and voices run locally.
- Online brains are off until you choose one. Passwords and mail questions are asked about out loud before they go online. Start with "privately" to keep any question local.
- Web searches send only the search words. The world feeds get plain requests, with nothing about you.
- Secrets (API keys, the Google sign-in, the Telegram and GitHub tokens) stay on your PC, sealed for your account (Windows DPAPI; the Keychain on the Mac). The phone and TV pairing codes, the local certificate's key and the MCP key file are plain files in your user folder. None are in this repository.

## Build from source

Python 3.14 on Windows:

```powershell
py -m pip install -r requirements.txt
py -m unittest discover -s tests
run.bat
```

Releases are built by the `build` workflow (Actions → build → Run workflow with a version).


