# aidesk — Masaüstü AI Asistanı

Fare neredeyse orada açılan küçük, yuvarlak bir menüyle çalışan; **kendi API
anahtarınızla** (Gemini / Claude / GPT) bilgisayarınızı kontrol eden ve **sesli
komut** alan bir Windows asistanı.

## Kullanıcılar için (terminal gerekmez)

1. `aidesk-windows.zip` dosyasını indirip istediğiniz bir klasöre çıkarın
   (OneDrive klasörü **olmasın**, ör. `C:\Programlar\aidesk`).
2. `aidesk\aidesk.exe`'ye çift tıklayın.
3. İlk açılışta **Ayarlar** penceresi gelir: sağlayıcınızı seçip API anahtarınızı
   yapıştırın, **Kaydet**.
4. Uygulama sağ alttaki tepside çalışır.
   - **Ctrl+Space** → fare imlecinin olduğu yerde yuvarlak menü açılır.
   - **Ctrl+Shift+Space** → doğrudan sesli komut.
   - Tepsi ikonuna tıklamak da menüyü açar.

> İpucu: Masaüstü kısayolu için `aidesk.exe`'ye sağ tıklayın → *Gönder* →
> *Masaüstü (kısayol oluştur)*. Windows ile başlaması için kısayolu
> `Win+R` → `shell:startup` klasörüne kopyalayın.

### Menü

| Dilim | Ne yapar |
|---|---|
| ✍️ Komut yaz / ortadaki ✦ | Küçük bir yazı kutusu açar |
| 🎤 Sesli komut | Konuşun; susunca veya baloncuğa tıklayınca biter |
| ⏯️ ⏭️ ⏮️ | Spotify / Apple Music / tarayıcıyı **arka planda** kontrol eder |
| 🎵 Ne çalıyor? | Çalan şarkıyı söyler |
| 📷 Ekran görüntüsü | Ekranı kaydeder |
| ⚙️ Ayarlar | API anahtarları, kısayollar, ses modeli |

### Sesli komut çalışmıyorsa

- **Ayarlar → Gizlilik ve güvenlik → Mikrofon → "Masaüstü uygulamalarının
  mikrofona erişmesine izin ver"** açık olmalı.
- **Ayarlar → Sistem → Ses → Giriş** altında doğru mikrofonun seçili ve ses
  seviyesinin yüksek olduğundan emin olun.
- İlk sesli komutta ses modeli (~460 MB) bir kez indirilir.

### Kayıtlar

Ayarlar ve hata kaydı: `%APPDATA%\aidesk\` (`aidesk.log`). API anahtarları bu
bilgisayara özgü şekilde şifrelenerek saklanır.

---

## Geliştiriciler için

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m aidesk            # kaynaktan çalıştır
.\build.ps1                 # dist\aidesk\aidesk.exe + dist\aidesk-windows.zip
dist\aidesk\aidesk.exe --selftest   # paketlenmiş uygulamayı test et
```

### Mimari

```
aidesk/
├── main.py        # giriş noktası, tek kopya, global kısayol, öz-test
├── ui.py          # yuvarlak menü, yazı kutusu, baloncuk, denetleyici, tepsi
├── assistant.py   # araç kullanan AI döngüsü + onay akışı
├── config.py      # ayarlar + şifreli API anahtarları
├── voice.py       # yerel konuşma tanıma (faster-whisper)
├── logsetup.py    # hata kaydı (çökme yerine log)
├── providers/     # Gemini (google-genai), Claude, GPT
└── tools/         # uygulama, medya (Windows SMTC), sistem, dosya araçları
```

- Riskli araçlar (kabuk komutu, tıklama, yazma, süreç kapatma) çalışmadan önce
  onay penceresi açar.
- Gemini modeli emekliye ayrılırsa veya yanıt vermezse uygulama erişilebilen
  başka bir "flash" modele otomatik geçer.
