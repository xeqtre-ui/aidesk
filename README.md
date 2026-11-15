# aidesk — Windows Desktop AI Assistant

A Windows assistant with a radial menu that opens at your cursor. Control desktop
apps, manage music in the background, and use typed or voice commands with your
own Gemini, Claude, or OpenAI API key.

The application interface and assistant responses are currently in Turkish.

## Getting started

If you have a packaged `aidesk-windows.zip` build:

1. Extract it to a local folder outside OneDrive, such as `C:\Apps\aidesk`.
2. Double-click `aidesk\aidesk.exe`.
3. In the first-run settings dialog (`Ayarlar`), select a provider, enter your API
   key, and click Save (`Kaydet`).
4. The app runs in the Windows system tray.

| Shortcut | Action |
| --- | --- |
| **Ctrl+Space** | Open the radial menu at the cursor |
| **Ctrl+Shift+Space** | Start a voice command |
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
| Settings | Configure API keys, shortcuts, and speech recognition |

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
- Keep confirmation for high-risk actions enabled. Shell commands, keyboard and
  mouse input, and process termination can affect your files and applications.
  File and clipboard reads currently do not require confirmation. Opening apps
  or paths also does not require confirmation and can launch executable content.
- The assistant currently allows high-risk tool execution when no confirmation
  callback is installed. The desktop UI installs a callback; other integrations
  must account for this behavior.
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
├── ui.py          # Radial menu, command input, bubbles, controller, system tray
├── assistant.py   # AI tool loop and confirmation flow
├── config.py      # Settings and encrypted API key storage
├── voice.py       # Cloud transcription and local faster-whisper recognition
├── logsetup.py    # Rotating logs and exception handling
├── providers/     # Gemini (google-genai), Claude, and OpenAI adapters
└── tools/         # Apps, Windows SMTC media, system, and file tools
```

The Gemini adapter can fall back to another available Flash model when a model
is unavailable or rate-limited.
