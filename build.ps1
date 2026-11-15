# aidesk'i Windows uygulaması olarak paketler.
# Sonuç: dist\aidesk\aidesk.exe  ve  dist\aidesk-windows.zip (dağıtım için)
#
# Kullanım (PowerShell):   .\build.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv")) { python -m venv .venv }
$py = ".\.venv\Scripts\python.exe"

Write-Host "1/4 Bagimliliklar kuruluyor..."
& $py -m pip install --quiet --disable-pip-version-check -r requirements.txt pyinstaller pillow

Write-Host "2/4 Ikon uretiliyor..."
& $py scripts\make_icon.py

Write-Host "3/4 aidesk.exe derleniyor (birkac dakika surer)..."
& $py -m PyInstaller --noconfirm --clean --windowed --name aidesk --icon assets\aidesk.ico `
    --collect-all faster_whisper --collect-all ctranslate2 --collect-all onnxruntime `
    --collect-all av --collect-all winsdk `
    --hidden-import pygetwindow --hidden-import pyperclip --hidden-import keyboard `
    --exclude-module tkinter --exclude-module matplotlib `
    --exclude-module google.generativeai --exclude-module googleapiclient `
    run_aidesk.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller basarisiz" }

Write-Host "Oz-test calistiriliyor..."
$p = Start-Process -FilePath "dist\aidesk\aidesk.exe" -ArgumentList "--selftest" -Wait -PassThru
Get-Content "$env:APPDATA\aidesk\selftest.txt"
if ($p.ExitCode -ne 0) { throw "Oz-test basarisiz" }

Write-Host "4/4 Zip olusturuluyor..."
if (Test-Path "dist\aidesk-windows.zip") { Remove-Item "dist\aidesk-windows.zip" }
# Compress-Archive, uygulama açıkken kilitli dosyalarda hata veriyor; Python zipfile paylaşımlı okur.
& $py -c "import shutil; shutil.make_archive('dist/aidesk-windows', 'zip', 'dist', 'aidesk')"
if ($LASTEXITCODE -ne 0) { throw "Zip olusturulamadi" }
Write-Host "Hazir: dist\aidesk\aidesk.exe  ve  dist\aidesk-windows.zip"
