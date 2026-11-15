"""Asistan orkestratörü — araç kullanımlı (agentic) döngü.

Kullanıcının isteğini alır, seçili sağlayıcıyla konuşur, model araç
çağırdıkça araçları çalıştırır (riskli olanlar için onay ister) ve sonucu
geri besler. Model araç çağırmayı bıraktığında son yanıtı döner.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from . import config, tools
from .providers import Provider, ToolCall, get_provider

SYSTEM_PROMPT = """Sen "aidesk" adlı bir Windows masaüstü asistanısın. Türkçe konuşursun.
Kullanıcının bilgisayarını onların adına kontrol edebilirsin: uygulama açma,
medya kontrolü (Spotify/Apple Music arka planda), pencere yönetimi, klavye/fare,
kabuk komutları, dosya arama ve açma.

İlkeler:
- Cevapların küçük bir baloncukta gösterilir: en fazla 1-2 kısa cümle yaz,
  markdown (**, `, #, listeler) KULLANMA, düz metin yaz.
- Bir eylemi tamamladıysan tek cümleyle onayla.
- Müzik isteklerinde ("son dinlediğim şarkıyı aç", "müziği başlat") SADECE
  play_music aracını tek seferde çağır; uygulamayı open_app ile ÖNE AÇMA.
  Durdur/sonraki/önceki için media_control kullan. Müzik için asla screenshot
  veya click kullanma.
- En az araç çağrısıyla bitir; hız önemli.
- screenshot ve click yalnızca başka hiçbir araçla yapılamayan görevler içindir.
- Emin değilsen kullanıcıya kısa bir soru sor, varsayım yapıp zarar verme.
- Yıkıcı işlemlerde (dosya silme, süreç sonlandırma) neden gerektiğini açıkla.
"""

TOOL_LABELS = {
    "play_music": "Müzik açılıyor",
    "now_playing": "Çalan şarkıya bakılıyor",
    "media_control": "Müzik kontrol ediliyor",
    "open_app": "Uygulama açılıyor",
    "close_app": "Uygulama kapatılıyor",
    "focus_window": "Pencere öne getiriliyor",
    "list_windows": "Pencerelere bakılıyor",
    "search_files": "Dosya aranıyor",
    "open_path": "Dosya açılıyor",
    "read_text_file": "Dosya okunuyor",
    "screenshot": "Ekran görüntüsü alınıyor",
    "click": "Tıklanıyor",
    "type_text": "Yazılıyor",
    "press_keys": "Tuşlara basılıyor",
    "run_shell": "Komut çalıştırılıyor",
    "set_volume": "Ses ayarlanıyor",
    "get_clipboard": "Pano okunuyor",
    "set_clipboard": "Panoya kopyalanıyor",
}

# Onay geri çağırımı: (araç_adı, argümanlar, risk) -> onaylandı mı?
ConfirmFn = Callable[[str, dict, str], bool]
# İlerleme bildirimi: (mesaj) -> None
ProgressFn = Callable[[str], None]


@dataclass
class Assistant:
    settings: config.Settings
    confirm: ConfirmFn | None = None
    on_progress: ProgressFn | None = None

    def __post_init__(self) -> None:
        tools.load_all()
        self._provider: Provider | None = None
        self._messages: list = []
        self._tool_schema = tools.schema()

    @property
    def provider(self) -> Provider:
        if self._provider is None:
            self._provider = get_provider(self.settings)
        return self._provider

    def reset(self) -> None:
        self._messages = []

    def _progress(self, msg: str) -> None:
        if self.on_progress:
            self.on_progress(msg)

    def _needs_confirm(self, tool: tools.Tool) -> bool:
        if not self.settings.require_confirmation:
            return False
        return tool.risk == tools.Risk.HIGH

    def _run_tool_calls(
        self, calls: list[ToolCall]
    ) -> list[tuple[ToolCall, str]]:
        results: list[tuple[ToolCall, str]] = []
        for call in calls:
            tool = tools.get_tool(call.name)
            if tool is None:
                results.append((call, f"HATA: '{call.name}' bulunamadı."))
                continue
            if self._needs_confirm(tool):
                self._progress(f"Onay bekleniyor: {call.name}")
                approved = True
                if self.confirm:
                    approved = self.confirm(call.name, call.arguments, tool.risk.value)
                if not approved:
                    results.append((call, "Kullanıcı bu eylemi reddetti."))
                    continue
            self._progress(TOOL_LABELS.get(call.name, f"{call.name} çalıştırılıyor") + "…")
            output = tools.execute(call.name, call.arguments)
            results.append((call, output))
        return results

    def ask(self, user_text: str) -> str:
        """Kullanıcı mesajını işler, nihai yanıtı döner."""
        provider = self.provider
        if len(self._messages) > 40:  # çok uzayan geçmişi sıfırla
            self._messages = []
        self._messages.append(provider.user_message(user_text))

        provider_tools = provider.format_tools(self._tool_schema)
        last_text = ""

        for _ in range(self.settings.max_tool_iterations):
            turn = provider.chat(SYSTEM_PROMPT, self._messages, provider_tools)
            provider.append_assistant(self._messages, turn)
            if turn.text:
                last_text = turn.text
            if not turn.wants_tools:
                break
            if turn.text:
                self._progress(turn.text)
            results = self._run_tool_calls(turn.tool_calls)
            provider.append_tool_results(self._messages, results)
        else:
            last_text += "\n(Araç adımı sınırına ulaşıldı.)"

        return last_text or "Tamamlandı."
