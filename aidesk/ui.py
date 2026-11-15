"""Masaüstü arayüzü.

- RadialMenu  : fare imlecinin olduğu yerde açılan küçük, tam yuvarlak çark.
- CommandBar  : yazılı komut için küçük hap şeklinde giriş kutusu.
- Toast       : sonuç / "dinliyorum" gibi mesajlar için küçük baloncuk.
- AppController: hepsini yöneten, arka plan işlerini güvenle çalıştıran sınıf.

ÖNEMLİ: Arka plan iş parçacıkları arayüze asla doğrudan dokunmaz; sonuçlar
sinyal ile ana (GUI) iş parçacığına taşınır. Aksi halde Qt uygulamayı çökertir.
"""
from __future__ import annotations

import logging
import math
import os
import re
import threading
from typing import Any, Callable

from PyQt6.QtCore import (
    QEasingCurve,
    QObject,
    QPoint,
    QPointF,
    QRectF,
    Qt,
    QThread,
    QTimer,
    QVariantAnimation,
    pyqtSignal,
    pyqtSlot,
)
from PyQt6.QtGui import (
    QAction,
    QColor,
    QCursor,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
)
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QSystemTrayIcon,
    QWidget,
)

from . import config, intents, tools
from .assistant import Assistant

log = logging.getLogger("aidesk.ui")

SURFACE = "#111916"
PANEL = "#182420"
BORDER = "#33463e"
INK = "#eaf4ef"
MUTED = "#a3b8ae"
ACCENT = "#a9f2ce"
TEXT_FONT = "Segoe UI"


DIALOG_STYLE = f"""
QDialog {{
    background: {SURFACE};
    color: {INK};
    font: 13px "{TEXT_FONT}";
}}
QLabel, QCheckBox {{ color: {INK}; }}
QLabel#settingsTitle {{ font-size: 25px; font-weight: 650; }}
QLabel[section="true"] {{
    color: {ACCENT};
    font-weight: 600;
    border-bottom: 1px solid {BORDER};
    padding: 7px 0 4px;
}}
QLineEdit, QComboBox {{
    background: {PANEL};
    color: {INK};
    border: 1px solid {BORDER};
    border-radius: 7px;
    padding: 4px 9px;
    min-height: 20px;
    selection-background-color: #386951;
    selection-color: {INK};
}}
QLineEdit:focus, QComboBox:focus, QCheckBox:focus, QPushButton:focus {{
    border: 1px solid #76bd9a;
}}
QComboBox QAbstractItemView {{
    background: {PANEL};
    color: {INK};
    border: 1px solid {BORDER};
    selection-background-color: #386951;
    selection-color: {INK};
    outline: 0;
}}
QPushButton {{
    color: {INK};
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 7px;
    padding: 7px 16px;
    min-height: 19px;
}}
QPushButton:hover {{ background: #254536; }}
QPushButton#settingsSave {{
    color: #10271c;
    background: {ACCENT};
    border: 1px solid {ACCENT};
    font-weight: 650;
}}
QPushButton#settingsSave:hover, QPushButton#settingsSave:focus {{
    background: #c7f9df;
    border-color: #f2fff8;
}}
"""



def draw_icon(p: QPainter, name: str, center: QPointF, size: float, color: str) -> None:
    """Çözünürlükten bağımsız, 24 × 24 çizgi ikonları."""
    p.save()
    p.translate(center)
    p.scale(size / 24, size / 24)
    p.translate(-12, -12)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(QColor(color), 1.65, Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))

    def lines(*points: tuple[float, float]) -> None:
        p.drawPolyline(QPolygonF([QPointF(x, y) for x, y in points]))

    if name == "brand":
        lines((3, 11), (3, 5), (5, 3), (13, 3))
        lines((21, 13), (21, 19), (19, 21), (11, 21))
        lines((5, 16), (12, 8), (19, 16))
        lines((9, 13), (15, 13))
    elif name == "type":
        lines((5, 7), (10, 12), (5, 17))
        lines((13, 17), (20, 17))
    elif name == "voice":
        p.drawRoundedRect(QRectF(9, 3, 6, 12), 3, 3)
        p.drawArc(QRectF(6, 5, 12, 13), 180 * 16, 180 * 16)
        lines((12, 18), (12, 21))
        lines((9, 21), (15, 21))
    elif name == "toggle":
        lines((4, 6), (13, 12), (4, 18), (4, 6))
        lines((16, 7), (16, 17))
        lines((20, 7), (20, 17))
    elif name in ("next", "prev"):
        if name == "prev":
            p.translate(24, 0)
            p.scale(-1, 1)
        lines((5, 6), (15, 12), (5, 18), (5, 6))
        lines((19, 6), (19, 18))
    elif name == "playing":
        for x, length in ((4, 6), (8, 12), (12, 18), (16, 11), (20, 6)):
            lines((x, 12 - length / 2), (x, 12 + length / 2))
    elif name == "shot":
        lines((9, 4), (4, 4), (4, 9))
        lines((15, 4), (20, 4), (20, 9))
        lines((20, 15), (20, 20), (15, 20))
        lines((9, 20), (4, 20), (4, 15))
        p.drawEllipse(QRectF(9, 9, 6, 6))
    elif name == "settings":
        for y, knob in ((6, 8), (12, 16), (18, 10)):
            lines((4, y), (knob - 2, y))
            p.drawEllipse(QRectF(knob - 2, y - 2, 4, 4))
            lines((knob + 2, y), (20, y))
    elif name == "warning":
        lines((12, 3), (21, 20), (3, 20), (12, 3))
        lines((12, 9), (12, 13))
        p.drawPoint(QPointF(12, 16.5))
    elif name == "busy":
        p.drawEllipse(QRectF(4, 4, 16, 16))
        lines((12, 7), (12, 12), (16, 14))
    elif name == "exit":
        lines((10, 4), (5, 4), (5, 20), (10, 20))
        lines((10, 12), (20, 12))
        lines((16, 8), (20, 12), (16, 16))

    p.restore()


def icon_pixmap(name: str, size: int, color: str = ACCENT, dpr: float = 1.0) -> QPixmap:
    pm = QPixmap(round(size * dpr), round(size * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    draw_icon(p, name, QPointF(size / 2, size / 2), size, color)
    p.end()
    return pm


def app_pixmap(size: int = 256) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#16382a"))
    p.drawRoundedRect(QRectF(0, 0, size, size), size * .23, size * .23)
    draw_icon(p, "brand", QPointF(size / 2, size / 2), size * .82, ACCENT)
    p.end()
    return pm


def app_icon() -> QIcon:
    icon = QIcon()
    for s in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(app_pixmap(s))
    return icon


def force_foreground(widget: QWidget) -> None:
    """Windows, arka plandaki bir uygulamanın öne gelmesini engeller.
    Global kısayolla açıldığında pencereyi gerçekten öne almak için ALT hilesi."""
    widget.raise_()
    widget.activateWindow()
    if os.name != "nt":
        return
    try:
        import ctypes

        user32 = ctypes.windll.user32
        user32.keybd_event(0x12, 0, 0, 0)        # ALT bas
        user32.keybd_event(0x12, 0, 0x0002, 0)   # ALT bırak
        user32.SetForegroundWindow(int(widget.winId()))
    except Exception:  # noqa: BLE001
        log.debug("force_foreground başarısız", exc_info=True)


def _clamp_to_screen(x: int, y: int, w: int, h: int, at: QPoint) -> tuple[int, int]:
    screen = QGuiApplication.screenAt(at) or QGuiApplication.primaryScreen()
    g = screen.availableGeometry()
    x = max(g.left() + 4, min(x, g.right() - w - 4))
    y = max(g.top() + 4, min(y, g.bottom() - h - 4))
    return x, y


# ===========================================================================
# Yuvarlak menü
# ===========================================================================
class RadialMenu(QWidget):
    triggered = pyqtSignal(str)
    SCALE = 0.6

    R_OUT = 154   # çarkın dış yarıçapı
    R_IN = 55     # ortadaki düğmenin yarıçapı
    PAD = 12

    def __init__(self, items: list[tuple[str, str, str]]) -> None:
        super().__init__(
            None,
            Qt.WindowType.Popup
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint,
        )
        self.items = items  # (anahtar, kısa etiket, tam etiket)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        d = round(2 * (self.R_OUT + self.PAD) * self.SCALE)
        self.setFixedSize(d, d)
        self.setMouseTracking(True)
        self._hover: int | None = None   # -1 = merkez
        self._t = 1.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(150)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._on_anim)

    def _on_anim(self, v) -> None:
        self._t = float(v)
        self.update()

    def popup_at(self, pos: QPoint) -> None:
        x, y = _clamp_to_screen(
            pos.x() - self.width() // 2, pos.y() - self.height() // 2,
            self.width(), self.height(), pos,
        )
        self.move(x, y)
        self._hover = None
        self._t = 0.0
        self.show()
        force_foreground(self)
        self._anim.start()

    def center_global(self) -> QPoint:
        return self.mapToGlobal(self.rect().center())

    # --- İsabet testi ------------------------------------------------------
    def _hit(self, pt: QPointF) -> int | None:
        c = QPointF(self.width() / 2, self.height() / 2)
        dx, dy = (pt.x() - c.x()) / self.SCALE, (pt.y() - c.y()) / self.SCALE
        r = math.hypot(dx, dy)
        if r <= self.R_IN:
            return -1
        if r > self.R_OUT:
            return None
        n = len(self.items)
        seg = 2 * math.pi / n
        a = (math.atan2(dy, dx) + math.pi / 2 + seg / 2) % (2 * math.pi)
        return int(a // seg) % n

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        h = self._hit(e.position())
        if h != self._hover:
            self._hover = h
            self.update()

    def leaveEvent(self, e) -> None:  # noqa: N802
        self._hover = None
        self.update()

    def mousePressEvent(self, e) -> None:  # noqa: N802
        h = self._hit(e.position())
        self.hide()
        if h is None:
            return
        self.triggered.emit("type" if h == -1 else self.items[h][0])

    def keyPressEvent(self, e) -> None:  # noqa: N802
        if e.key() == Qt.Key.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(e)

    # --- Çizim -------------------------------------------------------------
    def paintEvent(self, e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        p.setOpacity(self._t)
        p.translate(self.width() / 2, self.height() / 2)
        scale = .9 + .1 * self._t
        p.scale(scale * self.SCALE, scale * self.SCALE)

        outer, inner = self.R_OUT, self.R_IN
        outer_rect = QRectF(-outer, -outer, outer * 2, outer * 2)
        inner_edge = inner + 5
        inner_rect = QRectF(-inner_edge, -inner_edge, inner_edge * 2, inner_edge * 2)

        p.setPen(Qt.PenStyle.NoPen)
        for offset, alpha in ((10, 16), (7, 24), (4, 36)):
            p.setBrush(QColor(0, 0, 0, alpha))
            p.drawEllipse(outer_rect.adjusted(-offset, -offset + 2, offset, offset + 2))

        background = QLinearGradient(0, -outer, 0, outer)
        background.setColorAt(0, QColor("#1c2a24"))
        background.setColorAt(1, QColor(SURFACE))
        p.setBrush(background)
        p.setPen(QPen(QColor(BORDER), 1))
        p.drawEllipse(outer_rect.adjusted(.5, .5, -.5, -.5))

        def point(angle: float, radius: float) -> QPointF:
            radians = math.radians(angle)
            return QPointF(radius * math.cos(radians), radius * math.sin(radians))

        span = 360 / len(self.items)
        for index, (key, caption, _) in enumerate(self.items):
            angle = -90 + index * span
            start = angle - span / 2
            selected = self._hover == index

            if selected:
                active_rect = outer_rect.adjusted(8, 8, -8, -8)
                tile = QPainterPath()
                tile.arcMoveTo(active_rect, -start - 1.6)
                tile.arcTo(active_rect, -start - 1.6, -span + 3.2)
                tile.arcTo(inner_rect, -start - span + 1.6, span - 3.2)
                tile.closeSubpath()
                p.setBrush(QColor("#254536"))
                p.setPen(QPen(QColor("#4f8268"), 1))
                p.drawPath(tile)

            p.setPen(QPen(QColor(BORDER), 1))
            p.drawLine(point(start, inner + 9), point(start, outer - 9))
            p.setPen(QPen(QColor(ACCENT if selected else "#4b6157"),
                          2.4 if selected else 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(point(angle, outer - 7), point(angle, outer - 4))

            anchor = point(angle, (outer + inner) / 2 + 2)
            draw_icon(p, key, anchor - QPointF(0, 8), 22, ACCENT if selected else INK)
            p.setFont(QFont(TEXT_FONT, 8, QFont.Weight.DemiBold))
            p.setPen(QColor(INK if selected else MUTED))
            p.drawText(QRectF(anchor.x() - 36, anchor.y() + 7, 72, 16),
                       Qt.AlignmentFlag.AlignCenter, caption)

        center_active = self._hover == -1
        p.setBrush(QColor("#244233" if center_active else "#0f1814"))
        p.setPen(QPen(QColor("#6bbe94" if center_active else "#415b50"), 1))
        p.drawEllipse(QRectF(-inner + .5, -inner + .5, inner * 2 - 1, inner * 2 - 1))

        if self._hover is None or center_active:
            draw_icon(p, "type" if center_active else "brand", QPointF(0, -10), 24, ACCENT)
            p.setFont(QFont(TEXT_FONT, 9, QFont.Weight.DemiBold))
            p.setPen(QColor(INK))
            p.drawText(QRectF(-inner, 5, inner * 2, 20),
                       Qt.AlignmentFlag.AlignCenter, "Komut yaz" if center_active else "aidesk")
        else:
            key, _, label = self.items[self._hover]
            draw_icon(p, key, QPointF(0, -15), 19, ACCENT)
            p.setFont(QFont(TEXT_FONT, 8, QFont.Weight.DemiBold))
            p.setPen(QColor(INK))
            p.drawText(QRectF(-inner + 9, -1, inner * 2 - 18, 36),
                       Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, label)
        p.end()


# ===========================================================================
# Küçük yazı kutusu (hap şeklinde)
# ===========================================================================
class CommandBar(QWidget):
    submitted = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(438, 60)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 9, 14, 9)
        lay.setSpacing(12)
        mark = QLabel()
        mark.setFixedSize(32, 32)
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setPixmap(icon_pixmap("type", 21, dpr=self.devicePixelRatioF()))
        mark.setStyleSheet("background:#254536; border-radius:8px;")
        lay.addWidget(mark)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("Ne yapmamı istersin?")
        self.edit.setStyleSheet(
            f"QLineEdit{{background:transparent; border:none; color:{INK}; selection-background-color:#386951;"
            f"font-family:'{TEXT_FONT}'; font-size:15px;}}"
        )
        self.edit.returnPressed.connect(self._submit)
        self.edit.setAccessibleName("Yazılı komut")
        lay.addWidget(self.edit, 1)
        hint = QLabel("Enter")
        hint.setStyleSheet(f"color:{MUTED}; background:{PANEL}; border:1px solid {BORDER};"
                           "border-radius:6px; padding:4px 7px; font-size:11px;")
        lay.addWidget(hint)

    def open_at(self, center: QPoint) -> None:
        x, y = _clamp_to_screen(
            center.x() - self.width() // 2, center.y() - self.height() // 2,
            self.width(), self.height(), center,
        )
        self.move(x, y)
        self.edit.clear()
        self.show()
        force_foreground(self)
        self.edit.setFocus()

    def _submit(self) -> None:
        text = self.edit.text().strip()
        if text:
            self.hide()
            self.submitted.emit(text)

    def keyPressEvent(self, e) -> None:  # noqa: N802
        if e.key() == Qt.Key.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(e)

    def changeEvent(self, e) -> None:  # noqa: N802
        # Başka yere tıklanınca kapan.
        if e.type() == e.Type.ActivationChange and self.isVisible() and not self.isActiveWindow():
            QTimer.singleShot(150, lambda: (not self.isActiveWindow()) and self.hide())
        super().changeEvent(e)

    def paintEvent(self, e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor(SURFACE))
        p.setPen(QPen(QColor("#4f8268"), 1))
        p.drawRoundedRect(QRectF(1, 1, self.width() - 2, self.height() - 2), 15, 15)
        p.end()


# ===========================================================================
# Küçük bilgi baloncuğu
# ===========================================================================
class Toast(QWidget):
    clicked = pyqtSignal()
    MAX_W = 386
    TEXT_LEFT = 46
    TEXT_RIGHT = 16

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.label = QLabel(self)
        self.label.setWordWrap(True)
        self.label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        font = QFont(TEXT_FONT)
        font.setPixelSize(13)
        self.label.setFont(font)  # ölçüm için font doğrudan verilir (stylesheet değil)
        self.label.setStyleSheet(f"color:{INK}; background:transparent;")
        self._icon = "brand"
        self._level: float | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)
        self._anchor = QPoint()

    def show_message(self, text: str, anchor: QPoint, persistent: bool = False, meter: bool = False) -> None:
        text = re.sub(r"\*\*|__|`|^#+\s*", "", text, flags=re.MULTILINE).strip()  # markdown işaretlerini at
        self._anchor = anchor
        self._level = 0.0 if meter else None
        spoken, separator, status = text[2:].partition("”\n") if text.startswith("🗣 ") else ("", "", text)
        if separator:
            separator = "”\n"
        self._icon = "brand"
        for prefix, icon in (("🎤 ", "voice"), ("⚠ ", "warning"), ("⏳ ", "busy"), ("… ", "busy")):
            if status.startswith(prefix):
                status = status.removeprefix(prefix)
                self._icon = icon
                break
        if status == "…":
            self._icon = "busy"
        text = spoken + separator + status
        self.label.setText(text)
        fm = QFontMetrics(self.label.font())
        longest = max((fm.horizontalAdvance(line) for line in text.splitlines() or [""]), default=0)
        padding = self.TEXT_LEFT + self.TEXT_RIGHT
        w = max(172, min(self.MAX_W, longest + 8 + padding))
        inner = w - padding
        self.label.setFixedWidth(inner)
        rect = fm.boundingRect(0, 0, inner, 10000, Qt.TextFlag.TextWordWrap, text)
        lh = rect.height() + 2
        h = max(42, lh + 24) + (12 if meter else 0)
        self.label.move(self.TEXT_LEFT, 12)
        self.label.setFixedHeight(lh)
        self.setFixedSize(w, h)
        self.update()
        x, y = _clamp_to_screen(anchor.x() - w // 2, anchor.y() + 28, w, h, anchor)
        self.move(x, y)
        self.show()
        self.raise_()
        if persistent:
            self._timer.stop()
        else:
            self._timer.start(max(2500, min(14000, 2500 + len(text) * 45)))

    @pyqtSlot(float)
    def set_level(self, level: float) -> None:
        if self._level is None:
            return
        target = min(1.0, math.sqrt(max(level, 0.0) / 0.03))
        self._level = self._level * 0.6 + target * 0.4
        self.update()

    def mousePressEvent(self, e) -> None:  # noqa: N802
        self.clicked.emit()

    def paintEvent(self, e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor(SURFACE))
        p.setPen(QPen(QColor(BORDER), 1))
        p.drawRoundedRect(QRectF(1, 1, self.width() - 2, self.height() - 2), 12, 12)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#372a1b" if self._icon == "warning" else "#254536"))
        p.drawRoundedRect(QRectF(11, 8, 25, 25), 7, 7)
        draw_icon(p, self._icon, QPointF(23.5, 20.5), 17,
                  "#ffd094" if self._icon == "warning" else ACCENT)
        if self._level is not None:
            width = self.width() - self.TEXT_LEFT - self.TEXT_RIGHT
            y = self.height() - 12
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(BORDER))
            p.drawRoundedRect(QRectF(self.TEXT_LEFT, y, width, 4), 2, 2)
            p.setBrush(QColor(ACCENT))
            p.drawRoundedRect(QRectF(self.TEXT_LEFT, y, width * self._level, 4), 2, 2)
        p.end()


# ===========================================================================
# Arka plan işçisi
# ===========================================================================
class _Worker(QObject):
    # (geri çağırım, sonuç) — ana iş parçacığında çalıştırılmak üzere taşınır
    finished = pyqtSignal(object, object)

    def __init__(self, fn: Callable[[], Any], on_done: Callable, on_fail: Callable) -> None:
        super().__init__()
        self._fn, self._on_done, self._on_fail = fn, on_done, on_fail

    def run(self) -> None:
        try:
            result = self._fn()
            self.finished.emit(self._on_done, result)
        except Exception as e:  # noqa: BLE001
            log.exception("Arka plan işi başarısız")
            self.finished.emit(self._on_fail, e)


# ===========================================================================
# Denetleyici
# ===========================================================================
MENU_ITEMS = [
    ("type", "Komut", "Komut yaz"),
    ("voice", "Ses", "Sesli komut"),
    ("toggle", "Oynat", "Oynat / Duraklat"),
    ("next", "Sonraki", "Sonraki şarkı"),
    ("prev", "Önceki", "Önceki şarkı"),
    ("playing", "Şu an", "Ne çalıyor?"),
    ("shot", "Ekran", "Ekran görüntüsü"),
    ("settings", "Ayarlar", "Ayarlar"),
]


class AppController(QObject):
    progress_sig = pyqtSignal(str)
    confirm_sig = pyqtSignal(str, object, str)
    level_sig = pyqtSignal(float)

    def __init__(self, settings: config.Settings) -> None:
        super().__init__()
        self.settings = settings
        tools.load_all()
        self.assistant = Assistant(settings=settings)
        self.assistant.confirm = self._confirm_blocking
        self.assistant.on_progress = self.progress_sig.emit
        self._stt = None
        self._heard: str | None = None       # sesle duyulan son cümle (baloncukta gösterilir)
        self._listening: str | None = None   # None | "recording" | "transcribing"
        self._jobs: list[tuple[QThread, _Worker]] = []
        self._busy = False
        self._anchor = QPoint()
        self._confirm_event = threading.Event()
        self._confirm_ok = False

        self.menu = RadialMenu(MENU_ITEMS)
        self.menu.triggered.connect(self._on_menu)
        self.bar = CommandBar()
        self.bar.submitted.connect(self.run_text)
        self.toast = Toast()
        self.toast.clicked.connect(self._on_toast_clicked)

        self.progress_sig.connect(self._on_progress)
        self.confirm_sig.connect(self._on_confirm)
        self.level_sig.connect(self.toast.set_level)

    # --- Arka plan işleri (güvenli) ----------------------------------------
    def _run(self, fn: Callable[[], Any], on_done: Callable, on_fail: Callable | None = None) -> None:
        th = QThread()
        w = _Worker(fn, on_done, on_fail or self._on_error)
        w.moveToThread(th)
        th.started.connect(w.run)
        w.finished.connect(self._dispatch)   # ana iş parçacığında çalışır
        w.finished.connect(th.quit)
        th.finished.connect(self._cleanup_jobs)
        self._jobs.append((th, w))
        th.start()

    @pyqtSlot(object, object)
    def _dispatch(self, callback: Callable, result: Any) -> None:
        try:
            callback(result)
        except Exception:  # noqa: BLE001
            log.exception("Geri çağırım hatası")

    @pyqtSlot()
    def _cleanup_jobs(self) -> None:
        alive = []
        for th, w in self._jobs:
            if th.isFinished():
                th.wait()
            else:
                alive.append((th, w))
        self._jobs = alive

    def _on_error(self, e: Exception) -> None:
        from .apierrors import humanize

        self._busy = False
        self._show(f"⚠ {humanize(e)}")

    def _show(self, msg: str, persistent: bool = False, meter: bool = False) -> None:
        """Baloncuğa yazar; sesli komutsa duyulan cümle hep en üstte kalır."""
        if self._heard:
            msg = f"🗣 “{self._heard}”\n{msg}"
        self.toast.show_message(msg, self._anchor, persistent, meter)

    # --- Menü --------------------------------------------------------------
    def open_menu(self) -> None:
        self.bar.hide()
        self.menu.popup_at(QCursor.pos())

    def _on_menu(self, key: str) -> None:
        self._anchor = self.menu.center_global()
        self._heard = None
        if key == "type":
            self.bar.open_at(self._anchor)
        elif key == "voice":
            self.start_voice(self._anchor)
        elif key in ("toggle", "next", "prev"):
            action = {"toggle": "toggle", "next": "next", "prev": "previous"}[key]
            self.direct("media_control", {"action": action})
        elif key == "playing":
            self.direct("now_playing", {})
        elif key == "shot":
            self.direct("screenshot", {})
        elif key == "settings":
            self.open_settings()

    def direct(self, name: str, args: dict, label: str = "…") -> None:
        """AI'ya gitmeden aracı doğrudan çalıştırır (hızlı yol)."""
        self._show(f"⏳ {label}" if label != "…" else label, persistent=True)
        self._run(lambda: tools.execute(name, args), lambda r: self._show(str(r)))

    # --- Yazılı / sesli komut ----------------------------------------------
    def run_text(self, text: str, heard: bool = False) -> None:
        self._heard = text if heard else None
        # 1) Hızlı yol: bilinen müzik komutları AI'sız, anında
        intent = intents.match(text)
        if intent is not None:
            log.info("Hızlı yol: %r -> %s %s", text, intent.tool, intent.args)
            self.direct(intent.tool, intent.args, f"{intent.label}…")
            return
        # 2) Diğer her şey AI'ya
        if self._busy:
            self._show("Hâlâ önceki komut üzerinde çalışıyorum…")
            return
        self._busy = True
        self._show("⏳ Düşünüyorum…", persistent=True)

        def done(r: Any) -> None:
            self._busy = False
            self._show(str(r))

        self._run(lambda: self.assistant.ask(text), done)

    @pyqtSlot(str)
    def _on_progress(self, msg: str) -> None:
        self._show(f"… {msg}", persistent=True)

    # --- Onay --------------------------------------------------------------
    def _confirm_blocking(self, name: str, args: dict, risk: str) -> bool:
        """Arka plan iş parçacığından çağrılır; ana iş parçacığında soru sorar."""
        self._confirm_event.clear()
        self.confirm_sig.emit(name, args, risk)
        self._confirm_event.wait()
        return self._confirm_ok

    @pyqtSlot(str, object, str)
    def _on_confirm(self, name: str, args: object, risk: str) -> None:
        box = QMessageBox()
        box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        box.setWindowIcon(app_icon())
        box.setStyleSheet(DIALOG_STYLE)
        box.setIconPixmap(icon_pixmap("warning", 36, "#ffd094", box.devicePixelRatioF()))
        box.setWindowTitle("aidesk — Onay")
        box.setText(f"Asistan şu eylemi yapmak istiyor ({risk} risk):")
        box.setInformativeText(f"{name}\n{args}")
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        force_foreground(box)
        self._confirm_ok = box.exec() == QMessageBox.StandardButton.Yes
        self._confirm_event.set()

    # --- Ses ---------------------------------------------------------------
    def _get_stt(self):
        if self._stt is None:
            from .voice import CloudTranscriber, SpeechToText

            cloud = None
            if self.settings.stt_mode in ("auto", "cloud"):
                # Önce seçili sağlayıcı, yoksa anahtarı olan ses destekli diğeri
                for prov in (self.settings.provider, "gemini", "openai"):
                    key = config.get_api_key(prov) if prov in ("gemini", "openai") else None
                    if key:
                        cloud = CloudTranscriber(prov, key, self.settings.language)
                        break
            log.info("Ses tanıma: %s", f"bulut ({cloud.provider})" if cloud else f"yerel ({self.settings.whisper_model})")
            self._stt = SpeechToText(self.settings.whisper_model, self.settings.language, cloud,
                                     mic_name=self.settings.mic_name)
        return self._stt

    def preload_voice(self) -> None:
        try:
            stt = self._get_stt()
        except Exception:  # noqa: BLE001 — ses paketleri yoksa sessizce geç
            log.warning("Ses modülü yüklenemedi", exc_info=True)
            return
        # Bulut varken yerel model yalnızca yedek: yine de arka planda hazırla.
        self._run(stt.preload, lambda r: log.info(r), lambda e: log.warning("Ses modeli: %s", e))

    def start_voice(self, anchor: QPoint | None = None) -> None:
        self._anchor = anchor or QCursor.pos()
        try:
            stt = self._get_stt()
        except Exception as e:  # noqa: BLE001
            self.toast.show_message(f"⚠ Ses modülü yok: {e}", self._anchor)
            return
        if self._listening == "recording":  # ikinci basış = kaydı bitir
            stt.stop()
            return
        if self._listening == "transcribing":
            return  # zaten çözümleniyor, bekle
        if self._busy:
            self.toast.show_message("Hâlâ önceki komut üzerinde çalışıyorum…", self._anchor)
            return
        self._listening = "recording"  # ana iş parçacığında, hemen işaretle
        self._heard = None
        stt.arm()  # erken "bitir" basışı kaybolmasın
        hint = "" if (stt.ready or stt.cloud) else "\n(ilk kullanım: ses modeli hazırlanıyor)"
        self._show(f"🎤 Dinliyorum… bitirmek için tıkla{hint}", persistent=True, meter=True)

        def failed(e: Exception) -> None:
            self._listening = None
            self._show(f"⚠ Ses hatası: {e}")

        def recorded(audio: Any) -> None:
            self._listening = "transcribing"
            self._show("⏳ Anlıyorum…", persistent=True)
            self._run(lambda: stt.transcribe(audio), heard, failed)

        def heard(text: Any) -> None:
            self._listening = None
            text = str(text or "").strip()
            if not text:
                self._show("Bir şey duyamadım. Mikrofona biraz daha yakın konuş.")
                return
            self.run_text(text, heard=True)  # duyulan cümle baloncukta kalır

        self._run(lambda: stt.record(on_level=self.level_sig.emit), recorded, failed)

    def _on_toast_clicked(self) -> None:
        if self._listening == "recording" and self._stt is not None:
            self._stt.stop()
        else:
            self.toast.hide()

    # --- Ayarlar -----------------------------------------------------------
    def open_settings(self) -> None:
        dlg = SetupDialog(self.settings)
        if dlg.exec():
            self.settings = config.load_settings()
            self.assistant.settings = self.settings
            self.assistant._provider = None   # yeni anahtar/sağlayıcı ile yeniden kur
            self.assistant.reset()
            if self._listening is None:  # ses ayarları/anahtarlar değişmiş olabilir
                self._stt = None
                self.preload_voice()


# ===========================================================================
# Kurulum / ayarlar penceresi
# ===========================================================================
class SetupDialog(QDialog):
    def __init__(self, settings: config.Settings) -> None:
        super().__init__(None, Qt.WindowType.WindowStaysOnTopHint)
        self.settings = settings
        self.setWindowTitle("aidesk — Ayarlar")
        self.setWindowIcon(app_icon())
        self.setStyleSheet(DIALOG_STYLE)
        self.resize(620, 605)
        form = QFormLayout(self)
        form.setContentsMargins(24, 17, 24, 19)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(4)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        header = QHBoxLayout()
        header.setSpacing(12)
        mark = QLabel()
        mark.setPixmap(app_pixmap(round(36 * self.devicePixelRatioF())))
        pm = mark.pixmap()
        pm.setDevicePixelRatio(self.devicePixelRatioF())
        mark.setPixmap(pm)
        header.addWidget(mark)
        title = QLabel("Ayarlar")
        title.setObjectName("settingsTitle")
        header.addWidget(title, 1)
        form.addRow(header)

        def add_section(text: str) -> None:
            heading = QLabel(text)
            heading.setProperty("section", True)
            form.addRow(heading)

        add_section("Sağlayıcı ve API anahtarları")

        self.provider = QComboBox()
        self.provider.addItems(["anthropic", "openai", "gemini"])
        self.provider.setCurrentText(settings.provider)
        form.addRow("Varsayılan sağlayıcı:", self.provider)

        self.keys: dict[str, QLineEdit] = {}
        for prov, label, ph in (
            ("anthropic", "Anthropic API anahtarı:", "sk-ant-..."),
            ("openai", "OpenAI API anahtarı:", "sk-..."),
            ("gemini", "Gemini API anahtarı:", "AIza..."),
        ):
            le = QLineEdit(config.get_api_key(prov) or "")
            le.setEchoMode(QLineEdit.EchoMode.Password)
            le.setPlaceholderText(ph)
            self.keys[prov] = le
            form.addRow(label, le)

        add_section("Kısayollar")
        self.hotkey = QLineEdit(settings.hotkey)
        form.addRow("Menü kısayolu:", self.hotkey)
        self.voice_hotkey = QLineEdit(settings.voice_hotkey)
        form.addRow("Sesli komut kısayolu:", self.voice_hotkey)

        add_section("Ses ve mikrofon")
        self.stt_mode = QComboBox()
        self._stt_modes = [
            ("auto", "Hızlı — bulut (Gemini/OpenAI anahtarınla, ~1 sn)"),
            ("local", "Yerel — çevrimdışı, ses bilgisayardan çıkmaz"),
        ]
        for _, label in self._stt_modes:
            self.stt_mode.addItem(label)
        self.stt_mode.setCurrentIndex(0 if settings.stt_mode != "local" else 1)
        form.addRow("Ses tanıma:", self.stt_mode)

        self.mic = QComboBox()
        self.mic.addItem("Otomatik (dahili mikrofon önce)", "")
        try:
            from .voice import list_microphones

            for name in list_microphones():
                self.mic.addItem(name, name)
        except Exception:  # noqa: BLE001
            log.warning("Mikrofon listesi alınamadı", exc_info=True)
        idx = self.mic.findData(settings.mic_name)
        self.mic.setCurrentIndex(idx if idx >= 0 else 0)
        form.addRow("Mikrofon:", self.mic)

        self.whisper = QComboBox()
        self.whisper.addItems(["tiny", "base", "small", "medium"])
        self.whisper.setCurrentText(settings.whisper_model)
        self.whisper.setToolTip("Yerel modda / internet yokken kullanılır. Büyük = daha iyi Türkçe, daha yavaş")
        form.addRow("Yerel ses modeli:", self.whisper)

        add_section("Güvenlik")
        self.confirm = QCheckBox("Riskli eylemlerden önce onay iste")
        self.confirm.setChecked(settings.require_confirmation)
        form.addRow(self.confirm)

        info = QLabel("Anahtarlar bu bilgisayarda şifrelenerek saklanır. "
                      "Kısayol değişiklikleri yeniden başlatınca geçerli olur.")
        info.setWordWrap(True)
        info.setStyleSheet(f"color:{MUTED}; font-size:11px; padding: 2px 0 6px;")
        form.addRow(info)

        save = QPushButton("Kaydet")
        save.setObjectName("settingsSave")
        save.setDefault(True)
        save.clicked.connect(self._save)
        form.addRow(save)

    def showEvent(self, e) -> None:  # noqa: N802
        super().showEvent(e)
        force_foreground(self)

    def _save(self) -> None:
        for prov, le in self.keys.items():
            if le.text().strip():
                config.set_api_key(prov, le.text())
        s = self.settings
        s.provider = self.provider.currentText()
        s.hotkey = self.hotkey.text().strip() or "ctrl+space"
        s.voice_hotkey = self.voice_hotkey.text().strip() or "ctrl+shift+space"
        s.whisper_model = self.whisper.currentText()
        s.stt_mode = self._stt_modes[self.stt_mode.currentIndex()][0]
        s.mic_name = self.mic.currentData() or ""
        s.require_confirmation = self.confirm.isChecked()
        config.save_settings(s)
        if not config.get_api_key(s.provider):
            QMessageBox.warning(self, "Eksik", f"Seçili sağlayıcı ({s.provider}) için API anahtarı girin.")
            return
        self.accept()


# ===========================================================================
# Tepsi ikonu
# ===========================================================================
def make_tray(app: QApplication, ctrl: AppController) -> QSystemTrayIcon:
    tray = QSystemTrayIcon(app_icon(), app)
    tray.setToolTip("aidesk — AI masaüstü asistanı")
    menu = QMenu()
    menu.setStyleSheet(f"""
        QMenu {{
            background: {SURFACE}; color: {INK}; border: 1px solid {BORDER};
            padding: 5px; font: 13px "{TEXT_FONT}";
        }}
        QMenu::item {{ padding: 8px 22px 8px 32px; border-radius: 5px; }}
        QMenu::item:selected {{ background: #254536; }}
        QMenu::icon {{ left: 8px; }}
    """)
    for key, text, fn in (
        ("brand", "Menüyü aç", ctrl.open_menu),
        ("type", "Yazılı komut", lambda: ctrl.bar.open_at(QCursor.pos())),
        ("voice", "Sesli komut", lambda: ctrl.start_voice(QCursor.pos())),
        ("settings", "Ayarlar / API anahtarları", ctrl.open_settings),
        ("exit", "Çıkış", app.quit),
    ):
        act = QAction(QIcon(icon_pixmap(key, 16, dpr=menu.devicePixelRatioF())), text, menu)
        act.triggered.connect(fn)
        menu.addAction(act)
    tray.setContextMenu(menu)
    tray._menu = menu  # çöp toplayıcıya karşı referans tut
    tray.activated.connect(
        lambda reason: ctrl.open_menu()
        if reason == QSystemTrayIcon.ActivationReason.Trigger
        else None
    )
    tray.show()
    return tray
