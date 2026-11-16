# Packages aidesk as a Windows application.
# Result: dist\aidesk\aidesk.exe  and  dist\aidesk-windows.zip (for distribution)
#
# Usage (PowerShell):   .\build.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv")) { python -m venv .venv }
$py = ".\.venv\Scripts\python.exe"

Write-Host "1/4 Installing dependencies..."
& $py -m pip install --quiet --disable-pip-version-check -r requirements.txt pyinstaller pillow
# openwakeword: with --no-deps (scipy/scikit-learn are only for model TRAINING; ~100 MB saved)
& $py -m pip install --quiet --disable-pip-version-check --no-deps "openwakeword>=0.6.0"
# Pre-download the wake models to embed them in the package (hey_jarvis, alexa, hey_mycroft)
& $py -c "from aidesk.wake import ensure_models; ensure_models(['hey_jarvis', 'alexa', 'hey_mycroft'])"
if ($LASTEXITCODE -ne 0) { throw "Could not download wake models" }
# Generate uiautomation's COM wrappers (they can't be generated in the packaged app)
& $py -c "import uiautomation; print('uiautomation', uiautomation.VERSION)"

Write-Host "2/4 Generating icon..."
& $py scripts\make_icon.py

Write-Host "3/4 Building aidesk.exe (takes a few minutes)..."
& $py -m PyInstaller --noconfirm --clean --distpath dist --workpath build packaging/aidesk.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
# Terminal command shortcut: rebuild the bin folder added to PATH on every build
New-Item -ItemType Directory -Force "dist/aidesk/bin" | Out-Null
Set-Content -Encoding ascii "dist/aidesk/bin/aidesk.cmd" "@echo off`r`n`"%~dp0..\aidesk-cli.exe`" %*"

Write-Host "Checking terminal mode..."
$cliHelp = & "dist/aidesk/aidesk-cli.exe" --help
if ($LASTEXITCODE -ne 0) { throw "aidesk-cli.exe does not work" }
$cliHelp | Select-Object -First 1

Write-Host "Running self-test..."
$p = Start-Process -FilePath "dist\aidesk\aidesk.exe" -ArgumentList "--selftest" -Wait -PassThru
Get-Content "$env:APPDATA\aidesk\selftest.txt"
if ($p.ExitCode -ne 0) { throw "Self-test failed" }

Write-Host "4/4 Creating zip..."
if (Test-Path "dist\aidesk-windows.zip") { Remove-Item "dist\aidesk-windows.zip" }
# Compress-Archive errors on locked files while the app is open; Python's zipfile reads shared.
& $py -c "import shutil; shutil.make_archive('dist/aidesk-windows', 'zip', 'dist', 'aidesk')"
if ($LASTEXITCODE -ne 0) { throw "Could not create zip" }
Write-Host "Ready: dist\aidesk\aidesk.exe  and  dist\aidesk-windows.zip"
