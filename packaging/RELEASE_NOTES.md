## New in v2.15.0

- **Trading tab** (the new **TRADING** button): Nova's take on the day-trader skill, in plain language. Seven cards — Scan, News, Entry, Exit, Time Machine odds, Risk and Budget — over free public data (Yahoo Finance, SEC EDGAR, the House Clerk). **Paper trading only**: no broker, no keys, no live orders anywhere in the code, and no trade goes through without you saying yes.
- **AiSOC in Nova's core + Shannon "Simulate attack"**: a lightweight AiSOC-inspired module lives in Nova now — alert fusion, triage verdicts, a MITRE ATT&CK table and a replayable decision ledger (no Docker, no extra downloads). In the Shannon tab, pick an app, file or local address under **Simulate attack** and watch red blocks land on the shield as each scripted attack step lands; AiSOC then resolves it and writes a report. Nothing really runs: the same local-only checks as a real Shannon run apply.
- **REA auto-fit**: after Rea analyses an app, file or site, Nova scores how well it could make Nova better. Good fits glow gold — click one for a report of what it is and how it helps, then **Add it to Nova** (Nova asks you first, then studies it read-only and proposes the change as an update).
- **Anatomy in Building mode**: the **Explain with Anatomy** button draws a labelled, isometric picture of your bench — board, parts and wires — so you can see what you've built at a glance.
- **"What I can do" on every tab**: each tab now has its own panel of things to say, closely related to that tab.
- **Browse buttons in Rea and Shannon**: **Browse file…** / **Browse folder…** in Rea, and **Browse…** in Shannon (on the project folder and in Simulate attack) open the normal file window, so you click the file or folder instead of typing its path.
- **GitHub rule change**: Nova no longer refuses to install code from GitHub outright — she asks you first. Study stays read-only; installing is a separate, approved step.
- **Fixed**: the Galaxy button could open the tab but the Galaxy never loaded behind it (the backend asked for a vault that didn't exist); Galaxy search now actually hides the stars that don't match, instead of only moving to them; Shannon's "Open full report" failed for simulated attacks; AiSOC's alert fusion could join the wrong group.
- **Cleaned up and optimised**: dead code removed across the whole codebase (unused helpers, imports and styles), and the slow paths — Rea's fit scoring, Trading's sizing, Building's figure drawing, Shannon's and Rea's per-frame drawing — made faster. Full suite: 635 tests, 0 failures.

## New in v2.14.0

- **Building mode** (the new **BUILD** button, or say "building mode"): a 3D electronics bench on a screen of its own, from your Robotics Lab. Pick a board (Arduino Uno, Nano or Mega, ESP32, NodeMCU, Raspberry Pi Pico, STM32 Blue Pill, Raspberry Pi 4) and parts (LED, RGB LED, button, knob, buzzer, servo, motor and driver, battery, distance sensor, OLED, DHT11, light sensor, level shifter), click a pin and then another to run a wire, and press **Run**. **Missions** walk you through real builds; **Free build** lets you wire anything. The bench checks the wiring itself: a short circuit, 5 V into a 3.3 V pin, TX wired to TX, two boards that don't share a ground.
  - **Blueprint**: describe what you want, typed or out loud ("build me a blinking LED on an Uno", "a servo that follows a knob on an ESP32"). Nova picks the board and parts, wires them on the bench, and the **Blueprint** panel fills with the parts list (what's on the bench plus what else to buy: resistors, jumper wires, a USB cable) and the build steps. The bench checks her wiring and tells her what it finds, so she fixes a short circuit herself. A plan is checked against the bench's real list of boards, parts and pin names first, so nothing is invented.
  - **Nova reads it**: ask "is my circuit wired right?" and she reads the parts, the wires and the bench's checks, says what's wrong and how to fix it. She can't move wires on a bench you built: you do.
  - **Projects**: **Save**, **Open** and **New** by name; closing Building mode keeps the bench as it was. A blueprint starts the bench fresh, so if you'd built something yourself, it's saved first as "Before Nova's build". Delete, R (rotate) and Esc work inside a bench you've clicked without leaving the screen.
  - **Everything stays on this PC**: the 3D bench is part of Nova (three.js included) and makes no network requests.
- **More agents in the Cloud brain** (SETTINGS → Cloud brain): **Hermes Agent** (Nous Research, MIT) and **OpenCode** join Claude Code, Codex and Gemini CLI. **Install** gets each one (Hermes with its own official installer, fetched over HTTPS and run in your own folders without an administrator prompt; OpenCode with npm), **Connect account** opens the agent's own setup in a terminal, **Use** makes it answer. Both can run on the Ollama on this PC: pick it in their setup (Hermes needs a model with a 64K context). They answer in words and use their own tools, not Nova's, so anything done on your PC stays with Claude Code or the AI on this PC. Neither is installed unless you press Install.
- **Fixed**: the Workplace's projector beams could stop animating for good if its first frame arrived a moment early.

## New in v2.11.0

- **Archmancer knowledge base**: "search archmancer for prompt injection", "how should I design an agent loop for my app", "what does archmancer say about tool authorization". Nova can search and read 42 agent-system architecture docs from lehoanganhtai13/archmancer (Apache-2.0), covering agent loops, tools, models, context management, trust and privacy, evaluation, and delivery. Everything stays on your PC. Useful when you're designing, building or debugging an AI agent system. On the Skills board under Knowledge.

## New in v2.10.0

- **Workplace** (the new WORKPLACE button, or say "workplace mode"): a blue holo-desk for working on things with Nova beside you. Her orb waits in the middle. Tap it and it drops to the bottom as a projector pad, and everything on the board appears as a see-through hologram. Each item gets its own beam of light, with light running up it, and the beams follow the items as you drag them. The pad glows brighter while Nova thinks or talks.
  - **What goes on it**: notes you type in; sketch notes you draw on with a mouse, pen or finger (four inks and an eraser); pictures, by drop, paste or + Picture; and files, by drop or + File. Text, code, PDF and Word files are read on your PC, so Nova can read them too.
  - **Moving around**: drag items by their top bar, resize them from the corner, drag the empty board to pan and scroll to zoom.
  - **Nova works on the board**: select something and ask, by typing or talking ("explain this", "highlight what matters", "what's in this picture?").
    - She highlights the key words in your note or file.
    - She puts her own note beside the item, linked by a dashed line.
    - She points at what she means.
    - She looks at pictures and sketches with the vision model on your PC.
  - **Saving**: closing asks **Save / Don't save / Cancel**. **Open ▾** brings back a saved board with Nova's highlights and notes, and Ctrl+S saves.
  - **Pictures**: Nova looks with the vision model on your PC.
    - **No vision model yet:** she uses your API brain instead, if it can see pictures (Claude, OpenAI, Gemini, OpenRouter or xAI). She says the picture went online. With the strict privacy setting, pictures never go online.
    - **No API brain that sees pictures either:** she starts downloading the vision model herself and tells you when she'll be able to look.
  - **Its own window**: open it from Advance → Separate apps.
  - **Privacy**: the board goes along with your questions only while it's open, and isn't kept in the conversation history. It goes to whichever brain answers, just like anything you type.
- **Top bar** fits on one row again, down to 1280-pixel-wide screens.

## New in v2.9.0

- **Set up everything**: on the first start, Nova downloads and turns on what every feature needs by herself, one step after another: Ollama (no administrator prompt), the strongest model for your PC (measured), the meaning-search model, her natural voice, Whisper, the vision model, ffmpeg, Node.js, and the Claude Code, Codex and Gemini CLIs. Anything already there is just turned on. If a step fails, the rest still run, and a step that would fill the disk is skipped. Watch it or run it again from SETTINGS → Downloads → **Set up everything**; the first-start message has **Stop**. Two things can't be automatic: Docker Desktop (it needs an administrator prompt and a restart) and signing in to your accounts.
- **Advance mode** (the new ADVANCE button, or say "advance mode"): the HUD turns red, the orb moves to the left, and a board fills the right side:
  - **Library**: every topic and project.
  - **What Nova can do**: every skill, with what to say.
  - **Widgets**: clock, weather, timers, reminders, tasks, now playing, this PC, who answered, headlines. **Edit** adds, removes and reorders them.
  - **Separate apps**: Rea and Shannon each open in their own window. OpenProject runs in Docker on this PC only. AppFlowy, Cap and OpenWhispr open once installed (else their download page). VoiceStudio, Chatwoot, Open Generative AI, Cal.diy and open-seo open their pages. **+ Your app** adds any site or program.
  
  "Exit advance mode" goes back.
- **API brain** (was "Claude with a key"): add any AI with your own API key. That's Claude, OpenAI, Google Gemini, OpenRouter, Groq, DeepSeek, Mistral, xAI or Together, or any OpenAI-compatible address such as LM Studio. **Load models** lists what your key can use. Add several and switch between them. Keys stay sealed on this PC.
- **Cloud brain** (was "Claude plan"): an AI you sign in to, no key needed. That's Claude Code (Claude plan), Codex (ChatGPT plan) or Gemini CLI (Google account). **Install** and **Connect account** are one click each.
- **From the repos you sent, built into Nova:**
  - **Dictation**: hold Ctrl+Win, speak, and the words are typed where you are (from OpenWhispr).
  - **Screen recording**: "record my screen" … "stop recording" saves an MP4 in Videos\Nova Recordings (from Cap's idea).
  - **SEO check**: "SEO check klee.dev" lists what to fix first (from open-seo).
  - **Free time**: "when am I free for an hour this week" reads your Google Calendar and drafts a message (from cal.diy).
  - **Pictures**: "make a picture of …" uses your OpenAI API brain (from Open Generative AI).
- **Fixed**: Rea's side card could show "nullnull".

## New in v2.8.1

- **Rea, redrawn as an orbit**: the app you analyse is a small glowing core, and its parts orbit it on tilted rings, each leaving a faint trail, with their links arcing through the core. Around the edges: the app's name, the counts, the chosen part's card (what Rea found, what it talks to), the stages, and a live timeline of what Rea is doing. Drag to spin and tilt it, scroll or pinch to zoom, click a part to bring it round to the front; ← → go part by part.
- **Shannon, redrawn as a shield**: your app is a hexagon shield with a glowing heart, and Shannon's attacks swirl around it, faster while it works. Every hole it proved is a bracketed spot on the shield: **red and pulsing means look at it first** (critical and high), amber is medium, yellow is low. When you've fixed one, press **Mark fixed** and it calms to green; Nova remembers, and the banner counts what's still open.
- **Webcam gestures** move Rea and Shannon while they're open: swipe for the next or previous part or spot, 👍/👎 to zoom, ✊ to open (in Shannon: mark the spot fixed), ✌ to close.

## New in v2.8.0

- **Tuned for your PC, after every update**: Nova measures the models on your PC and runs the strongest one that stays smooth. Your graphics card gets the whole model, Ollama gets flash attention and a compact memory (twice the context in the same graphics memory), and a Radeon that Ollama left on the processor is switched to Vulkan. A bigger model downloads by itself when your PC can run it, and Nova takes the longest context (up to 32K) that still fits on the card, so she remembers more of the conversation. SETTINGS → This PC shows what was measured (speed, how much is on the graphics card) and has **Tune now**.
- **What your PC can't do, Claude does**: when a tool can't run here (offline Wikipedia not downloaded, the map servers down, maths or data that needs real code), Nova hands that one job to Claude in the cloud and says so. Claude uses its web search, or its code sandbox for exact maths, statistics and data. Nothing that acts on your PC, and none of your private data, goes there; "privately…" and the strict privacy setting keep everything here. Switch in SETTINGS → Claude.
- **Skills board** (the new SKILLS button): every skill Nova has in one place, grouped, each with what to say and whether it's ready, needs setting up (and where), runs on Claude, or is off. Search it, filter it, click an example to put it in the ask box. Your own skills are there with **Run**, and your hotkeys at the bottom. Every new feature adds itself to the board.
- **Prompt optimizer**: "optimize this prompt: …" rewrites it so an AI answers it better, then runs both versions on the same model and has a blind judge pick the better answer. If the original wins, Nova rewrites again using the judge's note. Works for system prompts too (tested on a sample message). The result is kept in outputs/. Inspired by linshenkx/prompt-optimizer; Nova's own implementation.
- **Routes start on the globe**: ask for a route and the globe opens and flies to the city while the roads are worked out, then dives into the street map where the search plays.
- **Nova on a Mac** (Apple silicon, from source for now): voice and hold Control+Option to talk, every brain, the screens, Google, Telegram, music and offline knowledge. The model is picked from the Mac's memory (the GPU shares it: 8 GB gets qwen3:4b, 16 GB qwen3:8b, 24 GB or more qwen3:14b). Not yet: screen assist, the tray and the corner orb. INSTALL.md part I.
- **Fixed**: VS Code refused files in your own folders when Windows used a short folder name; notes search named notes with backslashes on Windows.
- **Instant commands, no AI**: "timer for 10 minutes", "volume 30", "mute", "next song", "what time is it", "open Spotify" are done at once (a few milliseconds), without asking the model. Anything longer or with "and/then" still goes to the AI.
- **Fastest route** (the new ROUTE button): "fastest way from District 12 to District 7 via Ben Thanh". Nova finds the places, downloads the roads from OpenStreetMap and works the route out on your PC by motorbike, car or on foot (motorbikes stay off motorways), puts several stops in the best order, and plays the search spreading through the streets before the fastest path lights up. Normal speeds, no live traffic: **Open in Google Maps** has that.
- **Offline knowledge** (SETTINGS → Offline knowledge):
  - **Wikipedia on your PC**: pick Simple English, the most-read articles, every article's start, all of English Wikipedia, or Vietnamese. It downloads from Kiwix (the files Project NOMAD uses) and carries on if cut off; then Nova answers from the real articles with the internet off.
  - **Search your notes by meaning**: "what did I write about sleeping better?" finds "bed by 11". A small model in Ollama reads your vault once; only changed notes are read again. Nothing leaves your PC.
  - **Keep a city's roads** so routes there work offline.
- **Direct app control**: "make an Excel sheet of my November spending with a bar chart", "make a PowerPoint about…", "write it up in Word": real .docx / .xlsx / .pptx files in Documents\Nova Documents, opened for you. **OBS**: record, stop, switch scene, go live (asks first), through OBS's own remote control. **VS Code**: "open my portfolio project in VS Code at line 40". Clicking on the screen stays the fallback for everything else.
- **Rea** (the new REA button): reverse engineering with REA through Claude Code, on its own screen. Type the app, file, folder or site and what you want to know; Claude's steps show live, and the result is a glowing **blueprint** of the app's main parts and how they talk. Click a part to see what Rea found in it; past reports sit along the bottom and in your Library.
- **Shannon** (the new SHANNON button): an AI pentester on **your own** app. Pick the project folder and where it runs (like localhost:3000), press Run, and the **mission board** lights up recon → analysis → exploit → validate → report. It really attacks the app and keeps only the holes it could prove, each as a card (critical first) with its proof and the fix. Only apps on this PC or your home network. Needs WSL2, Docker Desktop and an Anthropic API key; a full run takes an hour or two and costs API credit. Setup: INSTALL.md part H.

## New in v2.7.0

- **Claude on your plan answers much sooner**: Nova now keeps one Claude Code session open instead of starting Claude Code (and connecting Nova's tools) for every question. It starts as soon as Nova does, so even the first question doesn't wait. Each question sends only what's new, since the session remembers the conversation. In a test, follow-up questions started answering in about half a second. A fresh session starts by itself when Nova's instructions or tools change, after 30 questions, or if Claude Code stopped (after sleep, for example).

## New in v2.6.0

- **Faster answers**:
  - With Screen assist on, Nova used to read your screen before *every* question and keep every question on this PC, even with Claude chosen. Now she reads the screen only when the question is about it ("this", "here", "click…", "my homework"). Everything else goes to the brain you chose.
  - The AI on this PC is sent only the tools the question needs: about 1,200 tokens instead of 6,000. Earlier conversation is trimmed to fit its context, so Ollama can reuse what it already read instead of reading it all again.
  - Nova thinks before answering only on hard questions or long ones (40 words or more, up from 25).
- **Where the time goes**: SETTINGS → This PC shows the last answer's timings (hover the latency at the top left too): loading the model, reading the prompt, writing speed, reading the screen. They're also kept in `timings.jsonl` in Nova's data folder, so slowness can be traced to its real cause.
- **Fixed: Node.js not found.** Nova now reads Windows' PATH again each time, so a Node.js installed while Nova was running counts. She also looks in the usual install places (the official installer, nvm, fnm, Volta, Scoop, Chocolatey). For an unzipped Node.js, paste where node.exe is in SETTINGS → Need to → Reverse engineering. Nova also says whether Node.js is missing or just too old.

## New in v2.5.0

- **Nova has a new home**: github.com/lekietphamanh-maker/NOVApersonalAI. A Nova installed from the old repository can't see new versions: install **Nova-Setup.exe** from this release once (your settings, memory and models stay), and updates arrive by themselves from then on.
- **World view** (the new WORLD button): a gold line globe with what's happening on Earth right now. It shows earthquakes (USGS), disaster alerts (GDACS), storms, wildfires and volcanoes (NASA EONET), and, with the news desk on, news and conflict stories on the country they're about. Drag to turn it, scroll to zoom, click a dot for the story and its source, and switch between the last 24 hours and 7 days. Ask "what's happening in the Middle East this week?" and Nova answers from it while the globe flies there. The feeds get plain requests only: nothing about you.
- **Holograms with a Tron look** in creative mode: glowing wireframe edges over faint faces with drifting scan lines, on by default (**Look** switches back to solid, or press W). **Pinch a hologram twice quickly**, or double-click it, to take it apart into its pieces, and again to put it back. A 3D model you load takes the look too. "Make the holograms solid" works by voice.
- **Fixed**: in v2.4.0 the switches *Also let Claude use my claude.ai Gmail and Google Drive connectors* and *Your Claude apps → Turn on* answered "Unknown action". They work now, and a new test checks that every button in Nova's window reaches something that runs it.
- Under the hood, each tool now registers itself with what runs it (Calendar and Drive in their own files), so a new feature is added in one place.

## New in v2.4.0

- **Google Drive**: "find my budget in Drive", "what did I change in Drive lately?", "read file 2". Nova searches your Drive and reads Google Docs, Sheets, Slides, PDFs and text files, read-only: it never changes, shares or deletes anything. It uses the same Google sign-in as Gmail and Calendar; already connected? Turn on the **Google Drive API** for your Google Cloud project and click **Add Google Drive** in SETTINGS → Connections once.
- **Your claude.ai Gmail and Google Drive inside Nova's Claude**: SETTINGS → Nova's brain → *Also let Claude use my claude.ai Gmail and Google Drive connectors*. When Claude answers on your plan, it can use the connectors you connected on claude.ai. Nova lets it read, search and draft only; sending mail and sharing, changing or deleting files are blocked.
- **Nova's Gmail and Drive in your own Claude apps**: SETTINGS → Need to → *Your Claude apps* turns on a small MCP server on this PC only (with a private key), and gives you a one-line command for Claude Code and a ready block for Claude Desktop. Then Claude Code or Claude Desktop can read your unread mail, save drafts (never send) and search and read Drive through Nova's sign-in.
- **Every setup in one place**: SETTINGS → Need to now has step-by-step folders for Google (Gmail, Calendar, Drive), Claude (plan, API key, connectors), your Claude apps, install and updates, Discover, reverse engineering and Ollama Cloud, beside the iPhone, Telegram, TV, iPad, fitness band and laptop ones. Node.js shows up in the Download list when something you turned on needs it.

## In v2.3.0

- **Discover** (TASKS → Discover): GitHub projects picked for you from your interests, and from your own repos and stars if you give your GitHub username. Each says why it was picked. **Not for me** teaches it what to skip; **Add to Nova** pins the project to its current commit, notes its license, and has Claude Code study it read-only and propose how Nova could use it: a skill (which you read and approve before it's added) or a project for Claude Code to build. Nothing from GitHub is ever installed into Nova or run. Say "what should I add to Nova?" or "add number 2" too.
- **Holo deck, new layout**: the dial now sits on top, smaller, with Nova's latest words on its left and what's coming up (timers, reminders) on its right; the curved keyboard runs the full width underneath, so its keys are bigger. At rest the dial is big in the middle; swipe and it glides up as the keys rise from the bottom.
- **Reverse engineering with REA** (TASKS → Reverse engineering, off until you turn it on): "reverse engineer Spotify and tell me how its sync works" runs REA (github.com/morluto/rea, pinned to rea-agents 6.9.0) through Claude Code on your plan, in the background. The report goes to outputs/ and your Library under Reverse engineering. It needs Claude Code and Node.js 22.23 or newer, and is only for software you're allowed to analyse.

## In v2.2.0

- **Install once, update forever**: new **Nova-Setup.exe** installs Nova for your Windows user (no admin), with a Start-menu entry, an optional desktop icon and an uninstaller. From now on Nova checks GitHub for new versions, downloads them in the background, checks each download's SHA-256 and asks you to **Restart to update**. SETTINGS → Updates turns it off, checks now, or installs the previous version if an update misbehaves. The zips are still there; a zip copy tells you when a new version is out.
- **Nova's own icon** on the exe, the installer, the taskbar, shortcuts and the tray.
- **Holo deck** (the iPad): it rests as a big round dial: Nova's orb in the middle, the time, weather, the song (with ⏮ ⏯ ⏭) and your timers around it, and an outer ring of shortcuts (copy, paste, undo, save, find, snip, files…). **Swipe** across it, or along the bar, and a curved 60% keyboard of glowing line-art keys slides in beside the dial (fn + 1…= for F1–F12, fn + I J K L for the arrows, fn + U / O for Home / End). **Hide keys**, or 3 minutes untouched, puts it away, so nothing types on your PC by accident. **Classic** in the header brings back the old flat layout.
- **Google Calendar**: "what's on today?", "what's my week look like?", "add dentist Friday at 3". It uses the same Google sign-in as Gmail (SETTINGS → Connect Gmail and Calendar). Already connected Gmail? Click **Add Google Calendar** once.
- **Fixed**: Gmail stopped working an hour after Nova started (Google's access token expired and was never renewed). It renews itself now.

## In v2.1.0

- **Telegram 24/7, even with the PC off**: SETTINGS → Telegram → *Even with the PC off* puts a small relay on your own free Cloudflare account in about 10 seconds (Nova uses your Cloudflare token once and doesn't keep it). When you shut the PC down, or it stops checking in for about 11 minutes, your bot keeps answering: Claude Haiku (your API key) or Ollama Cloud (free key) replies, knowing your name and what Nova remembers, and your reminders still arrive on time. With the PC off it can't use the PC, read files or hear voice notes. When the PC starts again, Nova takes Telegram back, adds what you said while it was off to the conversation, and doesn't repeat reminders the relay already sent.
- **Telegram setup guide**: INSTALL.md part G walks through @BotFather, pairing and the relay, step by step.

## In v2.0.0

- **Claude on your Claude plan, no API credit**: Nova's everyday Claude answers now go through Claude Code on the subscription you already pay for (SETTINGS → Claude → Pay with: *My Claude plan*), the default whenever Claude Code is installed and signed in. Claude keeps all of Nova's tools (timers, reminders, web, notes, Library, builds) through a small connection inside Nova that only this PC can use. Answers start a few seconds later than with an API key; when your plan's limit is reached, the AI on your PC answers and Nova says why. You can still choose an API key instead. Screen jobs that send screenshots to Claude still use the API key; without one, the AI on your PC does them.
- **Nova on Telegram, from anywhere**: make your own bot with @BotFather, paste its token in SETTINGS → Telegram, turn it on and send the bot the pairing code. From then on it answers only you: text or voice notes (heard on your PC, not kept), the same memory and tools, "send me the report on my desktop" sends the file, and with Screen assist on she can work the PC for you while you're out. When she needs a yes or no, she asks in the chat with two buttons. Nothing on your PC opens to the internet. Your PC has to be on; messages travel through Telegram's servers, so don't send passwords there.

## In v1.9.0

- **Reminders at a time**: "remind me at 5 pm to call mom", "every weekday at 8 remind me to stretch". Said out loud on time, listed in TASKS → Reminders (✕ cancels), on the iPad deck and Nova Lite, and kept across restarts; one that came due while the PC was off is said when Nova starts.
- **Build mode**: "build me a portfolio website", "make a Python script that …": Claude Code builds it on your plan in `Documents\Nova Projects\<name>`, and Nova opens it when it's done. Say the same name again to change it. It can only write files in that folder and use git: no python, node, npm or pip commands, since any of those could run anything on your PC.

## In v1.8.0

- **Web jobs out of sight**: research, reading whole articles, comparing sites and simple web forms now happen in Nova's own browser, the Edge already on your PC running invisibly, so you keep your screen and mouse while she works. She reads the page (long ones in parts), follows links, fills fields by their labels, ticks boxes, picks options and presses buttons. Each time it is a fresh private session: your own Edge logins, cookies and history are never used, only web pages open, and password fields are never offered to her. Screen autopilot is still there for your own desktop apps.

## In v1.7.1

- **Long work always on your Claude plan**: Claude Code now runs on your signed-in Claude plan (Pro or Max) even when an Anthropic API key is set on the PC, so explainers and reports never use API credits.

## In v1.7.0

- **Skills**: a task written down once, as a note in your vault's `skills/`. Say its phrase ("plan my day"), press Run in TASKS → Skills, or let its schedule run it (daily, weekdays, weekly, monthly; a PC that was off catches up the same day). Four to start: Plan my day, Morning brief, Tidy my notes, Weekly review. Make more by voice ("make a skill that…"), or press **Suggest skills from my last 30 days**.
- **outputs/**: every plan, brief, review and report a skill makes is saved as a dated note in your vault.
- **Long work on Claude Code**: with Claude Code installed and signed in, big jobs (an explainer, a research report) run in the background on your Claude plan, read-only (your vault and the web), and Nova tells you when the result is in outputs/.

## In v1.6.0

- **Claude sees your screen, like HeyClicky**: with Claude set up (SETTINGS → Claude), screen jobs ("install this", "fill in this form", "do this homework") go to Claude, which gets a screenshot of the window at every step with every control's number drawn on it. It understands pictures, layouts, what is selected and error messages, and drives your mouse by those numbers. Only the newest screenshot is sent each step, and a long job (up to 300 steps) sends only its newest steps, to keep it quick and cheap.
- The screenshots go to Anthropic and cost a little per step on your own API key. Without Claude, when you start with "privately", or with **SCREEN → See the screen with Claude → Turn off**, the AI on your PC does the job from the list of controls and nothing leaves your PC. If Claude can't be reached, the AI on your PC takes over.

## In v1.5.1

- **Answer keys**: when Nova asks yes or no, press **F8** for yes or **F10** for no instead of speaking (they only count while she is asking). Change them, like every Nova key (talk, stop, keep a highlight), in **SETTINGS → Hotkeys**.
- Tidier code inside: Nova's question handling, screen steps and hotkeys were reorganized; nothing you use changed.

## In v1.5.0

- **Nova just does what you ask.** No question before any step on your PC: clicking, typing, keys, scrolling, opening programs and web addresses, web searches, saving a task or a library entry, a Gmail draft (never sent), changing your city. Money, sending and deleting included. Esc stops her at once. Only what would send your own words off this PC still asks (a password or mail question going online, "ask Claude"). A safety net is one click away: **SCREEN → Ask before risky steps**.
- **Screen assist and the second brain are on by themselves** the first time this version runs, and stay on after restarts. They never read private windows, password managers, banking, calls and chats, or password fields (SETTINGS → Second brain has the list; you can add your own).
- **Highlight, then F9**: select text with the mouse in any window and press F9 (SETTINGS → Hotkeys changes the key). Nova keeps exactly that text in `raw/clips`, folds it into the wiki, and gives your clipboard back as it was.
- **Up to 300 steps** for one request (Nova sends the model the newest steps plus a digest of the earlier ones).
- **Questions by voice, no pop-up**: when Nova still has to ask yes or no she says it out loud and you answer by voice (hold the talk key and say yes or no). She asks again after 25 seconds; no answer after 90 seconds is a no. SCREEN → Questions by voice → Turn off brings the pop-up back.
- Everything the second brain watches is compressed first: only summaries and wiki pages are written, the raw screen text is dropped, and "What did I learn about …?" still finds it.

## In v1.4.0

- **Autopilot for screen assist**: turn Screen assist on once (SCREEN → Screen assist; you are asked one time and it stays on, also after a restart). Then "review this homework", "review this article" or "do this homework" makes Nova read all of it by herself, scrolling down the page, without asking, and "install ArtGuard" or "open notepad and type hello" makes her drive your real mouse and keyboard step after step with no OK at each step.
- **More she can do**: double-click, right-click, scroll, and open a program, web address, file or folder. Up to 40 steps per request.
- **What still asks you (out loud, yes or no)**: spending money, sending or posting, deleting or submitting, password, card or account-number fields, bank and payment pages, Shift+Delete, Alt+F4, and opening a script or a command shell. SCREEN → Autopilot → Turn off brings back the question before every step. Esc always stops her.
- Windows won't let Nova click in a window that runs as administrator (an installer's permission box): press Yes yourself. A page can hold text written to trick an AI, so watch the screen while Nova works on something you don't trust.

## In v1.3.1

- **ABC News headlines are back**: Google News files ABC News under abcnews.com now, so "Headlines from" your sites found nothing for the old abcnews.go.com. Nova moves a saved abcnews.go.com to abcnews.com by itself; nothing to change.
- **CNN through Google News**: CNN's own news feed hasn't been updated since 2023, so the news desk takes CNN from Google News (one of your sites by default).
- **Steadier brief**: a news source that times out or is busy gets one more try before the brief gives up on it.
- **Politer news desk**: when GDELT asks Nova to slow down, Nova waits longer and stops asking it for the rest of that run; the others carry on. A source that sends nothing now says what it sent instead.

## In v1.3.0

- **News desk** (BRIEF → News desk): every morning Nova collects the news from GNews (free key), GDELT and news sites, the AI on your PC summarizes and scores each article (facts, names, place, importance, which claims are only allegations), and keeps it in a searchable database. "What happened today?", "biggest tech news this week?", "latest on Nvidia?" get answers with title, publisher, date and link. Search it yourself in the same panel.
- **Auto brain**: the AI on your PC answers everyday questions; hard ones (code, research, analysis, long questions) go to Claude or Ollama Cloud. **Who answered recently** shows which brain answered each request and why.
- **This PC, live**: CPU, RAM, GPU and graphics memory, and where the model really runs as Ollama measures it, with Load / Unload. A Radeon RX 6600 XT that leaves the model on the processor gets the Vulkan fix.
- **Custom model versions**: your own instructions, temperature and context on an installed model, saved as nova-…; compare two models with Nova's quick checks.

## In v1.2.0

- **Choose Nova's brain** (SETTINGS → Model): this PC, **Claude**, or **Ollama Cloud** (a big open model, free with an Ollama account). Offline, the AI on your PC answers.
- **Only passwords and mail are private by default**: for those Nova asks out loud "Should I send it to Claude?"; say yes or no (No keeps it on your PC). Weather, news and everyday questions go to the brain you chose. The strict rule is one click away.
- **Free web search for Claude**: searches go through DuckDuckGo from your PC instead of Claude's paid search.
- **Library**: your projects, repos and ideas by topic on a gold 3D shelf, linked to your second brain; "Needs you" shows what to do next. Move it by voice ("next", "open 3", "open robotics", "back") or gestures.
- **Your own gestures**: record a hand pose and choose what it does (music, the Library, stop Nova, or ask Nova something).
- **Steadier hands in creative mode**: less jitter when still, no lag when moving fast.
- **Headlines from your news sites**: NBC News, CNN and ABC News to start (BRIEF → Headlines from; add or remove any site), through Google News. A bad reply from a news site no longer breaks the brief.
- **SETTINGS → Need to**: what's left to download, and how to set up the iPhone, TV, iPad, fitness band and laptop, all in one folder.

## In v1.1.0

- **Claude as Nova's online brain** (Desktop Edition, off until you turn it on): SETTINGS → Claude → Turn on, paste your Anthropic API key. While the PC is online Nova answers with Claude (default Claude Sonnet 5.5 at medium effort; Opus 5.5 or Haiku 5.5 and low/high effort in Settings), speaking while Claude writes and searching the web for anything current. Offline, and for anything personal (mail, notes, what she remembers, where you are, your screen, files, health, money, family, anything you start with "privately"), the AI on your PC answers. Nothing Nova keeps about you is sent to Claude. Your phone and TV use it through the PC; on a laptop, paste the key there too. Billed per question to your Anthropic account.
- **One way of talking and thinking on both brains**: answer first, honest and direct, sure only when it's sure. The AI on your PC learns from Claude's recent answers and thinks before hard questions.
- **Nova no longer asks where you are** when your city is saved; other cities' weather doesn't change yours.
- **Everything to download** in one checklist in [INSTALL.md](https://github.com/lekietphamanh-maker/NOVApersonalAI/blob/main/INSTALL.md).

## Install (Windows 10/11, 64-bit)

Everything step by step (the PC, voice, the iPhone, TV and iPad, the second brain, a laptop):
[INSTALL.md](https://github.com/lekietphamanh-maker/NOVApersonalAI/blob/main/INSTALL.md).

**Desktop Edition**: uses the Ollama on this PC.
1. Install [Ollama](https://ollama.com/download).
2. Download **Nova-Desktop.zip** below and unzip it to a normal folder such as `C:\Nova` (not inside OneDrive).
3. Double-click **Check Nova.bat**, then **Start Nova.bat**. Nova checks the PC's processor, graphics and memory and offers the model that suits it: click **Download**.

**USB Edition**: carries its own Ollama and models.
1. Download **Nova-USB.zip** and unzip it onto a USB drive formatted exFAT or NTFS with at least 16 GB free.
2. On the drive, double-click **Prepare USB.bat** once (about 8.5 GB), or copy the `Ollama` folder from an older USB Edition into it.
3. Double-click **Start Nova USB.bat**.

## What's inside

- **Nova's gold HUD**: asleep, a glowing line with orbits; say "Hey Nova" and it opens into the orb. Voice with a wake word you can interrupt, hold Ctrl+Alt to talk, natural voices (Kokoro, Piper) and Whisper as optional downloads in SETTINGS → Voice & audio.
- **Screen assist**, **creative mode** (camera lenses, photo booth), **webcam gestures**, **music mode** (the cover spins as a disc), idea maps, timers, walkthroughs, a daily brief, weather and local news.
- **Second brain** in Obsidian (off until you turn it on): notes of what you read and watch, summed up into linked topic pages.
- **Other screens**: an old iPhone as Nova's companion (Nova Lite), the TV as Nova's dashboard, an iPad as a real keyboard for the PC with widgets.
- **A laptop**: a second Nova that shares memory and the second brain with your PC through one folder synced with Syncthing (PC to PC, no cloud).
- **Optional, Desktop only**: Claude (your API key) or Ollama Cloud (free account) as Nova's brain, Gmail read and drafts (never sends).

## Tested

On Windows in CI: unit tests, screen assist end to end, voices and Whisper downloads, real keys and text typed into a window from the deck's keyboard, the Claude brain through the real Anthropic SDK against a test server, the packaged app opening and connecting with the Claude SDK bundled. Not yet tried: a real Claude call (that's your key's first question), a real iPhone, iPad or TV, or two real PCs.
