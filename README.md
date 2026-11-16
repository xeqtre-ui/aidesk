# aidesk — Windows Desktop AI Assistant

A Windows assistant with a radial menu that opens at your cursor. Control desktop
apps, manage music in the background, and use typed or voice commands with your
own Gemini, Claude, or OpenAI API key.

The application interface is in English. The assistant still understands and
responds in Turkish, so the example voice commands below are shown in Turkish.

## Getting started

If you have a packaged `aidesk-windows.zip` build:

1. Extract it to a local folder outside OneDrive, such as `C:\Apps\aidesk`.
2. Double-click `aidesk\aidesk.exe`.
3. In the first-run settings dialog (`Settings`), select a provider, enter your API
   key, and click `Save`.
4. The app runs in the Windows system tray.

| Shortcut | Action |
| --- | --- |
| **Ctrl+Space** | Open the radial menu at the cursor |
| **Ctrl+Shift+Space** | Start a voice command (or a Jarvis conversation) |
| **Click the tray icon** | Open the menu |

To create a desktop shortcut, right-click `aidesk.exe` and select **Send to →
Desktop (create shortcut)**. To launch at sign-in, copy the shortcut into the
folder opened by **Win+R → `shell:startup`**.

## Menu features

| Menu item | Action |
| --- | --- |
| Type a command / center symbol | Open a small command input |
| Voice command | Record until silence is detected or you click the bubble |
| Play/pause, next, previous | Control Spotify, Apple Music, or browser media in the background |
| Now playing | Show the current track |
| Screenshot | Save a screenshot locally |
| Settings | Configure API keys, shortcuts, voice, Jarvis mode, and permissions |

## Jarvis voice mode

Enable it in **Settings → Voice and Jarvis → Enable voice assistant mode**. The voice
shortcut then opens a small 3D holographic orb in the center of the screen and
starts a spoken conversation:

- The orb reacts to your microphone while listening, spins faster while
  thinking, and grows and glows with the assistant's voice while speaking.
- Drag the orb to move it and use the mouse wheel to resize it; its position
  and size are remembered. Right-drag rotates it in 3D, and right-click opens a
  menu (center, reset size, close). Particles move away from the cursor. Click
  it to interrupt the assistant, and double-click it (or press Esc) to close it.
- After each answer the assistant keeps listening. Say "görüşürüz", "bu
  kadar", or "kendini kapat" to end the conversation; commands such as
  "Spotify'ı kapat" are not treated as goodbyes. **Close when silent**
  sets how long silence keeps it open (15 seconds to never; default 1 minute).
- Speech uses the built-in Windows voice (for example Microsoft Tolga for
  Turkish), which works offline and has no API cost. With an OpenAI key you can
  select OpenAI voices instead. Use **Test voice** to preview a voice.

### Wake word

Enable **Settings → Voice and Jarvis → Wake by voice** to start the assistant
hands-free. The microphone audio is processed only on this computer.

- **Hey Jarvis** (recommended), **Alexa**, or **Hey Mycroft** use small
  openWakeWord models (about 3 ms of CPU per 80 ms of audio).
- **Custom phrase** accepts any phrase, such as "hey asistan". Speech segments are
  checked with a small local Whisper model.
- You can say a command right after the wake phrase: "Hey Jarvis, müziği aç".
- Adjust **Sensitivity** if it wakes too rarely (accent, quiet microphone) or too
  often. Detection pauses while the assistant is listening or speaking.

## Playing a specific song

Say or type requests such as "Swimming Pools şarkısını aç", "Spotify'dan Emrin
Olur'u başlat", or "Tarkan çal". The assistant searches the Spotify desktop app
and starts the best matching song without bringing Spotify to the front. This
works with Spotify Free. It uses Windows UI Automation on the Spotify window and
may need updates if Spotify changes its interface. If no result is a close
match, the assistant asks you to repeat the song name instead of playing a
different song.

## Web search, YouTube, and site search

The assistant can research before acting. For a request such as "Tame
Impala'nın GTA 6 için yaptığı müziği aç", it searches the web and YouTube,
identifies the song, and then plays it on Spotify.

| Request | What happens |
| --- | --- |
| "Google'da İstanbul hava durumunu arat" | Opens the Google results page in your browser |
| "YouTube'da Duman Bu Akşam'ı aç" | Finds the video and opens it in your browser |
| "Trendyol'da kablosuz kulaklık ara" | Opens the site's own search page (Google `site:` search for other sites) |
| Questions about recent events | Searches the web and reads pages before answering |

Web search uses public search pages and does not need an extra API key. Search
queries are sent to Yahoo Search and YouTube; Wikipedia is used as a fallback.

## Terminal mode (like Claude Code or Codex)

Run aidesk inside any folder from PowerShell and work on its files through a
conversation:

```powershell
cd C:\projects\my-app
aidesk                               # start a session in this folder
aidesk "explain this project"        # one-off request
aidesk --sor                         # ask before every change, even with Full Access
```

To enable the `aidesk` command, open **Settings → General → Install terminal
command**. It adds the app's `bin` folder to your user PATH; open a new terminal
afterwards. The packaged app ships `aidesk-cli.exe` for this mode.

In terminal mode the assistant can list, read, and search files, edit files
(shown as a colored diff), create files, and run PowerShell commands such as
tests or git. It cannot access paths outside the folder you started it in.
Edits and commands ask for confirmation (`y` yes, `n` no, `a` allow all for
this session) unless **Permissions** is set to Full Access. Session commands:
`/exit`, `/clear`, `/model`, `/help` (the Turkish aliases `/çık`, `/temizle`,
`/yardım` also work).

## Context and memory

Each request includes what is happening right now, captured at the moment you
press the shortcut or say the wake word: the active window and app, the
browser page address, the current media, the date and time, and your last few
commands. This lets the assistant understand requests such as "burada Duman'ı
ara" (search here) or "bir öncekini aç".

Say "bunu hatırla" (remember this) to store a preference, for example "Emrin
Olur dediğimde Kayahan'ınkini kastediyorum". Say "unut" to remove it. Memories
are stored in `%APPDATA%\aidesk\memory.json` and are sent to the AI provider
with each request.

## Seeing the screen and acting in apps

- **look_at_screen** answers questions by sending a screenshot to the AI
  ("ekranda ne var", "bu hata ne diyor").
- **click_on_screen**, **type_into**, and **scroll_screen** act inside any app
  or browser ("ilk videoya tıkla", "arama kutusuna Duman yaz"). The element is
  located from a screenshot; the assistant hides its own orb and bubbles while
  capturing. Typing uses the clipboard so Turkish characters are entered
  correctly.
- These actions use the keyboard and mouse category in **Permissions** (Ask by
  default). Screenshots are sent to your AI provider.

## Providers and keys

**Settings → General** shows the model for the selected provider and a **Check
keys** button that reports whether each key works, has no credits, or has hit
its quota. If the selected provider runs out of quota or credits, the request
is retried with another provider that has a key. OpenAI requires prepaid API
credits; a ChatGPT subscription does not include them.

## Permissions

**Settings → Permissions** controls what the assistant may do without asking:

| Mode | Behavior |
| --- | --- |
| Standard (default) | Media, opening apps, files, screenshots, clipboard, and volume run directly. Closing apps, keyboard/mouse input, and shell commands ask first. |
| Full Access | Nothing asks for confirmation. Enabling it requires an explicit warning confirmation. |
| Custom | Choose **Allow**, **Ask**, or **Block** for each category. |

Blocked categories are hidden from the AI model and also blocked for menu and
quick voice commands.

## Voice troubleshooting

- In Windows **Settings → Privacy & security → Microphone**, allow desktop apps
  to access the microphone.
- In **Settings → System → Sound → Input**, select the correct microphone and
  check its input level.
- Local recognition downloads a Whisper model on first use. Download size varies
  with the selected model.
- Speech recognition supports cloud and local modes. In automatic mode, an
  available Gemini or OpenAI key can enable cloud transcription.

## Privacy and security

- Settings, encrypted API keys, logs, and saved screenshots are stored under
  `%APPDATA%\aidesk\`. Do not upload this directory or share its contents without
  reviewing them.
- API keys are encrypted at rest using a key derived from machine and user
  information. This protects against casual plaintext exposure; it does not
  provide strong protection against someone who can access those files and
  reproduce the machine and user information.
- AI requests send conversation text and tool results to the selected provider.
  File contents and clipboard text returned by tools can therefore leave your
  computer. Cloud speech recognition also sends recorded audio to its provider.
- Recognized voice commands and some command details are written to local logs.
- Prefer the Standard permission mode. Shell commands, keyboard and mouse
  input, and process termination can affect your files and applications. In
  Standard mode, file and clipboard reads and opening apps or paths do not ask
  for confirmation, and opening paths can launch executable content; set those
  categories to **Ask** or **Block** in Custom mode if needed.
- Full Access removes every confirmation. Only enable it if you accept that a
  misunderstood request can run commands or change files without asking.
- When no confirmation callback is installed (for example, when the assistant
  is used outside the desktop UI), actions in **Ask** categories are rejected.
- The app can execute code with the permissions of the account running it.

## Development

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m aidesk
```

Build and check the Windows package:

```powershell
.\build.ps1
dist\aidesk\aidesk.exe --selftest
```

The build script creates `dist\aidesk\aidesk.exe` and
`dist\aidesk-windows.zip`. Self-test results are written to
`%APPDATA%\aidesk\selftest.txt`.

## Architecture

```text
aidesk/
├── main.py        # Entry point, single instance, global shortcuts, self-test
├── ui.py          # Radial menu, command input, bubbles, controller, Jarvis loop, tray
├── settings.py    # Settings dialog (General, Voice & Jarvis, Permissions tabs)
├── orb.py         # 3D holographic Jarvis orb (numpy renderer)
├── tts.py         # Text-to-speech (Windows voices, OpenAI) with live levels
├── permissions.py # Permission modes and per-category levels
├── wake.py        # Wake word listener (openWakeWord or a custom phrase)
├── intents.py     # Fast-path command matching (music, specific songs)
├── apierrors.py   # Quota handling, model cooldowns, readable error messages
├── context.py     # Active window, page address, media, recent commands
├── memory.py      # Persistent preferences ("bunu hatırla")
├── keycheck.py    # API key validation for the settings dialog
├── cli.py         # Terminal mode (aidesk-cli.exe)
├── workspace.py   # Folder tools for terminal mode (read, search, edit, run)
├── cli_install.py # Adds the `aidesk` command to the user PATH
├── assistant.py   # AI tool loop and confirmation flow
├── config.py      # Settings and encrypted API key storage
├── voice.py       # Cloud transcription and local faster-whisper recognition
├── logsetup.py    # Rotating logs and exception handling
├── providers/     # Gemini (google-genai), Claude, and OpenAI adapters
└── tools/         # Apps, media, Spotify search, web/YouTube, system, and file tools
```

The Gemini adapter can fall back to another available Flash model when a model
is unavailable or rate-limited.
