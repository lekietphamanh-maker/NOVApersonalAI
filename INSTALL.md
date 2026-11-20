# Install Nova, step by step

Do **A** first. Everything after it is optional, in any order (D needs PHONE from C turned on; F works best after E).

| Phase | What you get | Time |
|---|---|---|
| A. The PC | Nova on your Windows PC, chatting | 20 min |
| B. Voice | "Hey Nova", natural voice, hold-to-talk | 10 min |
| C. iPhone | the old iPhone as Nova's companion screen | 10 min |
| D. TV and iPad | Nova on the TV; the iPad as a keyboard with widgets | 10 min |
| E. Second brain | Obsidian notes of what you read and watch | 10 min |
| F. Laptop | a second Nova with the same memory and second brain | 20 min |
| G. Telegram | Nova from anywhere by text or voice note, even with the PC off | 10–20 min |
| H. Extras | weather, Gmail, Claude, heart rate, gestures, away from home | as you like |

**You need:** Windows 10 or 11 (64-bit), 8 GB RAM or more (16 GB+ is better; a graphics card makes answers faster), about 10 GB free disk, and internet for the downloads. After that Nova works offline.

## Everything to download (checklist)

**Needed for Nova on the PC**
- [ ] [Ollama](https://ollama.com/download): runs the AI on your PC.
- [ ] **Nova-Desktop.zip** from this repository's Releases page.
- [ ] The AI model: Nova offers the one that suits your PC on first start (1.4 to 9.3 GB). Microsoft Edge, which draws Nova's window, is already part of Windows.

**Inside Nova, one click each (recommended)**
- [ ] Whisper speech recognition, about 190 MB: SETTINGS → Voice & audio → Install Whisper.
- [ ] A natural voice: Heart, Bella or Emma (Kokoro, 132 MB) or, on a slow PC, Amy, Lessac or Jenny (Piper, 85 MB): SETTINGS → Voice & audio → Nova's voice.
- [ ] The Vietnamese voice, 65 MB: offered the first time Nova answers in Vietnamese.
- [ ] The vision model, about 3 GB: SETTINGS → Model → Download vision model (creative mode then names anything you show the camera).

**Other apps, only for the feature that needs them**
- [ ] [Obsidian](https://obsidian.md): the second brain.
- [ ] Syncthing on both PCs ([SyncTrayzor](https://github.com/GermanCoding/SyncTrayzor/releases), or `winget install --id BillStewart.SyncthingWindowsSetup -e`): the laptop sharing memory and notes.
- [ ] [Tailscale](https://tailscale.com) on the PC and on the phone, iPad or laptop: Nova away from home.

**Accounts and keys (nothing to install)**
- [ ] Claude Code ([claude.com/product/claude-code](https://claude.com/product/claude-code)), signed in once with `claude`: Claude as Nova's brain on your Claude plan, no API credit. Or an Anthropic API key ([console.anthropic.com](https://console.anthropic.com) → API keys), paid per question.
- [ ] A Telegram bot from **@BotFather** (free): Nova from anywhere, by text or voice note.
- [ ] Or a free [Ollama](https://ollama.com) account: Ollama Cloud as Nova's brain, free with limits.
- [ ] Google (Gmail, Calendar, Drive): the one-time Google setup in SETTINGS → Need to → Google.
- [ ] Node.js LTS (nodejs.org), only for Rea (reverse engineering) or Nova's Gmail and Drive in Claude Desktop.
- [ ] For Shannon only: WSL2, [Docker Desktop](https://www.docker.com/products/docker-desktop/) and an Anthropic API key (see H).

**Nothing to download for:** the iPhone and iPad (Nova's certificate comes from your PC's setup page; the apps are web pages you add to the Home Screen), the TV (its own browser), a heart-rate band (Bluetooth), the webcam and mic.

**Inside Nova:** SETTINGS → **Need to** shows the same list with a tick or a button each, and the iPhone, TV, iPad, fitness band and laptop steps below.

**Instead of the PC install:** Nova-USB.zip on a USB drive, then Prepare USB.bat once (about 8.5 GB); fully offline, no Claude.

---

## A. The PC (20 min)

1. **Install Ollama**, the program that runs the AI model on your PC: [ollama.com/download](https://ollama.com/download) → Windows → run the installer.
2. **Download Nova:** this repository's **Releases** page → newest release → **Nova-Setup.exe** → run it (no admin needed). It installs Nova, adds it to the Start menu (and the desktop if you tick it), and starts it. From then on **Nova updates herself**: new versions download in the background and SETTINGS → Updates (or the notice) says **Restart to update**.
   Windows may say "Windows protected your PC" because Nova isn't code-signed yet: **More info → Run anyway**.
   Prefer a folder you control? **Nova-Desktop.zip** still works: unzip to `C:\Nova`, then **Check Nova.bat** and **Start Nova.bat** (zip copies only tell you about updates).
3. (Zip only) Double-click **Check Nova.bat**. It ends with a line saying the runtime and the model passed.
4. Nova starts. The gold window opens: a glowing line with orbits. Nova checks your PC's processor, graphics and memory and offers the right model (for example `qwen3:8b` with a strong graphics card, `qwen3:4b` on a laptop): click **Download** and wait.
5. **SETTINGS → What should Nova call you?** → your name.

**Done when:** you type "hello" at the bottom and Nova answers. Closing the window keeps Nova in the tray (gold ring icon); tray icon → **Quit Nova** stops it.

## B. Voice (10 min)

1. Click **MIC** at the bottom and allow the microphone. Say **"Hey Nova, what time is it?"**: the line opens into the orb and she answers.
2. **SETTINGS → Voice & audio → Install Whisper**: Nova understands you much better (and the second brain can write down what videos say).
3. **SETTINGS → Voice & audio → Nova's voice → Heart** (one 132 MB download, the most natural). Slow PC: **Amy** instead (85 MB). Vietnamese answers get a Vietnamese voice, offered the first time.
4. Pick your microphone and speaker there too, then **Test mic**.
5. Hotkeys: **hold Ctrl+Alt** to talk, let go to send; **Esc** stops Nova. Change them in **SETTINGS → Hotkeys**.

**Done when:** "Hey Nova" works from across the room and you can cut her off by saying "Hey Nova" again.

## C. Old iPhone as Nova's companion (10 min)

1. On the PC, click **PHONE** at the bottom. If Windows asks about networks, allow **Private networks**.
2. Open the iPhone camera, point it at the QR code in Nova and open the link. A setup page opens.
3. Tap **Download certificate** → **Allow**. Then iPhone **Settings → Profile Downloaded → Install**, then **Settings → General → About → Certificate Trust Settings** → turn on **Alfred Local CA**. (Once. It's your own PC's certificate and only works for home-network addresses.)
4. Back on the setup page it says **Secure connection works**: tap **Open Nova Lite**, then **Share → Add to Home Screen**.
5. Open it from the Home Screen. Put the phone on a stand with its charger, and set **Settings → Display & Brightness → Auto-Lock → Never** so it stays on.

**Done when:** the phone shows Nova's gold orb, the ring of quick keys and the weather, and **Hold to talk** gets an answer. (Phone and PC must be on the same Wi-Fi; see G for away from home.)

## D. TV and iPad (10 min)

PHONE (from C) must be on.

1. On the PC: **SETTINGS → Screens → Show the links**.
2. **TV:** open the TV's web browser, go to the address shown (like `http://192.168.1.20:8767/tv`) and bookmark it. The TV shows a 4-digit code: click **Allow** on that code in Nova. No browser on the TV? Mirror the PC instead (Win+K, Chromecast or HDMI).
3. **iPad:** install the certificate on the iPad first (C step 3), then scan the **deck code** with the iPad camera, open it and **Share → Add to Home Screen**.
4. Try the iPad: type on its keyboard and the letters appear in the window in front on your PC; **Type** sends text in any language; the widgets show Nova, the time, weather and the song.
5. Try the TV: in Nova's window, drag a reply (or a photo from Explorer) onto **Drop here to show it on the TV**, or say **"Hey Nova, put that on the TV"**.

**Done when:** the TV shows the orb and the clock, and the iPad types on the PC. **Forget TVs** and **New code** undo the pairing.

## E. Second brain in Obsidian (10 min)

1. Install **Obsidian** (free): [obsidian.md](https://obsidian.md).
2. In Nova: **SETTINGS → Second brain → Turn on**, read what it does, allow it.
3. In Obsidian: **Open folder as vault** → `Documents\Second Brain`.
4. Optional: tick **Also listen to videos and reels I watch** (needs Whisper from B step 2). Add anything private to **Never read**.
5. Use the PC normally. Every 20 minutes Nova writes a summary into `raw/activity` and grows the topic pages in `wiki`.

**Done when:** after about 20 minutes there's a note for today, and **"Hey Nova, what did I learn today?"** answers from it. Say **"save this to my second brain"** to keep the page you're reading.

## F. Laptop with the same memory (20 min)

1. **Install Nova on the laptop** exactly like A. It picks the model that suits the laptop.
2. **Install Syncthing on both PCs** (free, PC to PC, no cloud): [SyncTrayzor](https://github.com/GermanCoding/SyncTrayzor/releases) (GermanCoding's version, with a tray icon), or in PowerShell `winget install --id BillStewart.SyncthingWindowsSetup -e`.
3. In Syncthing on the **PC**: **Add Folder** → `Documents\Second Brain`. **Add Remote Device** → the laptop's ID (in Syncthing on the laptop: **Actions → Show ID**), and share the folder with it. On the **laptop**, accept the folder into a new, empty folder (for example `Documents\Second Brain`).
4. On the laptop: **SETTINGS → Second brain** → set that folder as the vault → **Save**.
5. On **both** PCs: **SETTINGS → Your other PC → Turn on**.

**Done when:** Settings says "*LAPTOP-NAME* was here … min ago", and "Hey Nova, remember I like window seats" on one PC shows up under **What Nova remembers** on the other a minute later. The TV can follow the laptop too: open the laptop's TV link (D step 2) and slide things on from there.

## G. Nova on Telegram, from anywhere (10 min, + 10 min for PC-off)

**Part 1: your own bot (the PC answers)**

1. Install **Telegram** on your phone and sign in.
2. In Telegram, search **@BotFather** (blue tick) → **Start** → send `/newbot`.
3. Send it a display name (for example `Nova`), then a username that ends in `bot` (for example `my_nova_bot`; it must be unused).
4. BotFather replies with a token like `123456789:AAH…`. Copy the whole thing. Treat it like a password.
5. On the PC: **SETTINGS → Telegram · Nova from anywhere** → paste the token → **Save token** → **Turn Telegram on** (read the note, then OK).
6. A 6-digit **Pairing code** appears. In Telegram, open your new bot (tap the link BotFather sent) → **Start** → send the code.
7. The bot answers "Paired". From now on it answers only you.

**Done when:** you text the bot "what time is it?" and Nova answers. Try a voice note, and "send me the report on my desktop".

**Part 2: even with the PC off (optional, free)**

1. Make a free account at [dash.cloudflare.com](https://dash.cloudflare.com/sign-up) (no card).
2. Top right **profile icon → My Profile → API Tokens → Create Token** → template **Edit Cloudflare Workers** → **Use template** → under *Account Resources* pick your account → **Continue to summary → Create Token**. Copy it.
3. Back in **SETTINGS → Telegram**, under *Even with the PC off*: paste the Cloudflare token, choose who answers while the PC is off:
   - **Claude Haiku** (uses your Anthropic API key; about a tenth of a cent a message), or
   - **Ollama Cloud** (free account: [ollama.com](https://ollama.com) → Settings → **Keys** → create one and paste it), or
   - **Nobody** (Nova just says the PC is off; reminders still come).
4. Click **Set up relay**. Nova deploys it to your Cloudflare account in about 10 seconds and doesn't keep the Cloudflare token.

**Done when:** you shut the PC down, text the bot, and get an answer within a few seconds. Turn the PC back on: Nova takes Telegram back and the messages you sent while it was off show in her chat.

How it works: while the PC is on, Nova checks in with the relay every 5 minutes. When Nova closes (or misses two check-ins, about 11 minutes, after a crash or power cut), the relay takes over. While the PC is off she can talk and plan and send your reminders, but she can't use the PC, read your files or hear voice notes: those wait for the PC.

## H. Extras (any time)

- **Weather and local news:** **SETTINGS → Location** → type your city → **Save** (or **Use this PC's location**). Then "Hey Nova, will it rain tomorrow?"
- **Away from home:** install [Tailscale](https://tailscale.com) on the PC and on the phone / iPad / laptop with the same account; Nova Lite and the deck then work anywhere.
- **Google: Gmail, Calendar, Drive** (mail is read and drafted, never sent; Drive is read-only). One time, about 10 minutes:
  1. **console.cloud.google.com** → New project (any name).
  2. **APIs & Services → Library**: enable **Gmail API**, **Google Calendar API**, **Google Drive API**.
  3. **OAuth consent screen**: External; add your own Gmail address under **Test users**.
  4. **Clients → Create client → Desktop app → Download JSON**, saved as `%LOCALAPPDATA%\Alfred\google_client.json`.
  5. **SETTINGS → Connections → Connect Google**, pick your account, **Continue** past "Google hasn't verified this app" (it's yours), and allow all three. Connected before? **Add Google Calendar** / **Add Google Drive** asks for the new part.
- **Claude with your claude.ai connectors**: connect Gmail and Google Drive on **claude.ai → Settings → Connectors**, then tick **Also let Claude use my claude.ai Gmail and Google Drive connectors** under SETTINGS → Nova's brain (Claude on your plan only).
- **Nova's Gmail and Drive in Claude Code / Claude Desktop**: **SETTINGS → Need to → Your Claude apps → Turn on**. Claude Code: copy the command, run it in a terminal, check `claude mcp list`. Claude Desktop (needs Node.js): **Settings → Developer → Edit Config**, add the copied `nova-google` entry under `"mcpServers"`, save, restart it. Nova must be running (keep it in the tray).
- **Nova's brain** (SETTINGS → Model → *Who answers your questions*): **Claude** (the best answers; with Claude Code installed and signed in it runs on your Claude plan with no API credit, **Pay with → My Claude plan**; or paste an API key from [console.anthropic.com](https://console.anthropic.com) and choose **An API key**; default Sonnet 5.5 at medium effort) or **Ollama Cloud** (free with an Ollama account: click **Sign in to Ollama** once). Offline, the AI on this PC answers. Passwords and mail: Nova asks you out loud whether to send them (*yes* sends, *no* keeps them here). On the laptop, choose it there too.
- **Rea (reverse engineering)**: needs Claude Code and Node.js 22.23+. **REA** in the top bar → type the app, file, folder or site and what you want to know → **Analyse** (the first time Nova asks you to agree to the rules). Steps show live; the result is a blueprint of its parts. Only software you're allowed to analyse.
- **Shannon (break into your own app)**, one time, about 20 minutes:
  1. Admin PowerShell: `wsl --install`, restart, open **Ubuntu** once and pick a user name.
  2. Install **Docker Desktop** → Settings → Resources → **WSL integration** → turn on Ubuntu. Keep Docker running.
  3. In Ubuntu: `curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash`, reopen it, `nvm install --lts`.
  4. An Anthropic API key in **SETTINGS → Model → Claude → API key** (Shannon 3.5 doesn't work on a Claude plan; a full run costs API credit and takes an hour or two).
  5. Start your app (a test copy: Shannon really attacks it). **SHANNON** in the top bar → your project folder (from Documents\Nova Projects, or a full path) → where it runs, like `localhost:3000` → **Run**.
  The report lands in Documents\Nova Projects\Security checks and your Library.
- **Library**: **LIBRARY** in the top bar, or "Hey Nova, open my library". Add your repos and ideas with **+ New**; move it by voice or gestures.
- **Your own gestures**: SETTINGS → Gestures → name it, pick what it does, then hold the pose for 3 seconds while Nova records it.
- **Heart rate:** wear a Bluetooth heart-rate band or watch with broadcast on, then **SETTINGS → Fitness → Connect heart rate**.
- **Webcam gestures:** turn on **GESTURES**: 👍 volume up, 👎 down, ✋ next / previous, ✊ play/pause, ✌ creative mode.

---

## I. Nova on a Mac (Apple silicon, 15 min)

Most of Nova runs on the Mac: voice and hold-to-talk, every brain (the AI on the Mac, Claude, Ollama Cloud), the World, Route, Library, Rea and Shannon screens, Gmail/Calendar/Drive, Telegram, music mode, offline knowledge and documents. Not yet: screen assist, the second brain's reading of your screen, the corner orb and the tray (closing Nova's window quits it). The model is chosen from the Mac's memory: Apple silicon's GPU shares the RAM, so 8 GB gets qwen3:4b, 16 GB qwen3:8b, 24 GB or more qwen3:14b. **SETTINGS → This PC** shows what Nova found.

1. Install [Python 3.14](https://www.python.org/downloads/) (the macOS installer) and [Ollama](https://ollama.com/download) (drag it to Applications, open it once). Google Chrome is optional: it gives Nova its own window.
2. Download this repository (**Code → Download ZIP**, or `git clone`), open Terminal in its folder and run `bash macos/setup.sh`.
3. Double-click **macos/Start Nova.command**. The first time, macOS asks to allow **Input Monitoring** (needed to hold **Control+Option** to talk while another app is in front) and the **microphone**: allow both. If you missed it: System Settings → Privacy & Security → Input Monitoring → turn on Terminal.
4. Claude Code, Node.js (for Rea) and Docker (for Shannon) work the same as on Windows; install them with their Mac installers or Homebrew, and Nova finds them.

## If something doesn't work

1. **Check Nova.bat fails at the model:** open PowerShell and run `ollama pull qwen3:4b` (or the model Nova offered), then try again.
2. **The phone or iPad says it can't reach Nova:** same Wi-Fi as the PC, PHONE on in Nova, the PC awake, and Windows allowed Nova on **Private networks** (Windows Security → Firewall → Allow an app).
3. **Typing from the iPad does nothing in one window:** that window runs as administrator; Windows doesn't let other apps type into it.
4. **Telegram says "Telegram said 401" or nothing answers:** the token was mistyped or revoked: paste it again (BotFather → /mybots → your bot → API Token). Not paired? Send the code shown in Settings again; after five wrong codes a new one appears.
5. **The relay says "Authentication error":** the Cloudflare token needs the **Edit Cloudflare Workers** template with your account selected; make a new one.
6. **The laptop says "No other PC seen yet":** in Syncthing both PCs show the folder **Up to Date**, and **Your other PC** is on on both.
7. **Nova doesn't hear you:** **SETTINGS → Voice & audio** → choose the right microphone → **Test mic**; install Whisper if it isn't.

**Run from source** (developers): install Python 3.14, then in this folder `py -m pip install -r requirements.txt` and `run.bat`.
