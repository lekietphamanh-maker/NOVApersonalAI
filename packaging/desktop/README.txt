NOVA — DESKTOP EDITION
========================

Start: double-click Start Nova.bat.
Check: double-click Check Nova.bat. The packaged check loads the bundled Vosk English speech model and constructs its offline recognizer, then enumerates audio endpoints; it does not record from the microphone or capture the monitor. Screen UI Automation is optional and loads only when you explicitly request screen reading; an automation import failure cannot block Nova's main dashboard.

This edition keeps inference on the installed Ollama at 127.0.0.1:11434 and uses qwen3:8b Q4_K_M. Ollama must be installed/running and that model must already be present. No internet is needed for ordinary chat once both are installed. The model's GPU use on the target PC was observed as 100% GPU; Ollama has also emitted an AMD driver warning, so check `ollama ps` after a reply if acceleration matters.

Local data: %LOCALAPPDATA%\Alfred\DesktopData. The first launch copies the legacy %LOCALAPPDATA%\JarvisLocalAssistant\memory.sqlite3 using SQLite's backup API if present; the old file is not deleted or overwritten. This data location avoids OneDrive syncing the chat and tasks from the redirected Desktop. Do not put passwords or secrets in chat.

Features: local chat; save a task only after an explicit confirmation; offline push-to-talk and optional wake-word listening (English; requires mic permission); offline Windows speech replies; user-triggered screen reading with review; selected plain-text file review; editable offline idea maps. Spoken commands such as “visualize my idea: …”, “add … to the map”, “remove … from the map”, and “rename the map to …” open or update the visual note after Nova transcribes the bounded utterance; these map edits auto-save locally.

Audio Settings lets you choose a microphone and SAPI speaker/headphone output, restore System default, refresh the device lists, and run short mic-level and quiet playback tests. While push-to-talk or wake listening is explicitly active, the core visualizer pulses from the selected microphone's live RMS level; with the mic off or on voice error it settles still. Audio samples stay briefly in RAM and are discarded, never recorded to files. This meter shows sound level, not speech meaning.

Screen assist (off by default): highlights, notes and approved click/type/key steps in the app you are using; hold Ctrl+Alt to talk, Esc stops. See README.md in the source.

Not included yet: email authorization/access, folder indexing, source/topic-based web refresh, daily refresh/catch-up, Wi-Fi-return refresh, and a general model/app update checker. This app does not access browser passwords/cookies or submit homework. For homework, use Nova to explain selected text, then review and manually paste anywhere else.

Built for Windows 10/11 x64; package built/tested on Windows 11 x64. No Windows ARM, Mac, Linux, Android, or iPhone support. Screen OCR can miss small text; inaccessible/password-protected UIA can make a screen read fail safely. The rebuilt packaged app successfully loaded the Vosk model and initialized its recognizer, and the selected NexiGo N60 microphone level test and Yeti SAPI speaker playback passed on this PC. A spoken command through the rebuilt package, the mic-reactive visualizer, wake false/missed activations, and the complete voice-to-idea-map flow still require a live user speech test. Model behavior is not guaranteed; see EVALUATION.md in Developer Source.
