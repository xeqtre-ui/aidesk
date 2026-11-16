"""Desktop user interface.

- RadialMenu  : a small, fully circular wheel that opens at the mouse cursor.
- CommandBar  : a small pill-shaped input box for a typed command.
- Toast       : a small bubble for messages like a result / "listening".
- AppController: the class that manages all of them and runs background jobs safely.

IMPORTANT: Background threads never touch the UI directly; results are carried to
the main (GUI) thread via signals. Otherwise Qt would crash the application.
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

from . import config, context, intents, permissions, tools
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
    """Resolution-independent 24 × 24 line icons."""
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
    """Windows prevents a background application from coming to the front.
    The ALT trick actually brings the window forward when opened via a global shortcut."""
    widget.raise_()
    widget.activateWindow()
    if os.name != "nt":
        return
    try:
        import ctypes

        user32 = ctypes.windll.user32
        user32.keybd_event(0x12, 0, 0, 0)        # press ALT
        user32.keybd_event(0x12, 0, 0x0002, 0)   # release ALT
        user32.SetForegroundWindow(int(widget.winId()))
    except Exception:  # noqa: BLE001
        log.debug("force_foreground failed", exc_info=True)


def _clamp_to_screen(x: int, y: int, w: int, h: int, at: QPoint) -> tuple[int, int]:
    screen = QGuiApplication.screenAt(at) or QGuiApplication.primaryScreen()
    g = screen.availableGeometry()
    x = max(g.left() + 4, min(x, g.right() - w - 4))
    y = max(g.top() + 4, min(y, g.bottom() - h - 4))
    return x, y


# ===========================================================================
# Radial menu
# ===========================================================================
class RadialMenu(QWidget):
    triggered = pyqtSignal(str)
    SCALE = 0.6

    R_OUT = 154   # outer radius of the wheel
    R_IN = 55     # radius of the center button
    PAD = 12

    def __init__(self, items: list[tuple[str, str, str]]) -> None:
        super().__init__(
            None,
            Qt.WindowType.Popup
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint,
        )
        self.items = items  # (key, short label, full label)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        d = round(2 * (self.R_OUT + self.PAD) * self.SCALE)
        self.setFixedSize(d, d)
        self.setMouseTracking(True)
        self._hover: int | None = None   # -1 = center
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

    # --- Hit testing -------------------------------------------------------
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

    # --- Painting ----------------------------------------------------------
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
                       Qt.AlignmentFlag.AlignCenter, "Type a command" if center_active else "aidesk")
        else:
            key, _, label = self.items[self._hover]
            draw_icon(p, key, QPointF(0, -15), 19, ACCENT)
            p.setFont(QFont(TEXT_FONT, 8, QFont.Weight.DemiBold))
            p.setPen(QColor(INK))
            p.drawText(QRectF(-inner + 9, -1, inner * 2 - 18, 36),
                       Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, label)
        p.end()


# ===========================================================================
# Small text box (pill shaped)
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
        self.edit.setPlaceholderText("What should I do?")
        self.edit.setStyleSheet(
            f"QLineEdit{{background:transparent; border:none; color:{INK}; selection-background-color:#386951;"
            f"font-family:'{TEXT_FONT}'; font-size:15px;}}"
        )
        self.edit.returnPressed.connect(self._submit)
        self.edit.setAccessibleName("Typed command")
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
        # Close when clicked elsewhere.
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
# Small info bubble
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
        self.label.setFont(font)  # font set directly for measurement (not stylesheet)
        self.label.setStyleSheet(f"color:{INK}; background:transparent;")
        self._icon = "brand"
        self._level: float | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)
        self._anchor = QPoint()

    def show_message(self, text: str, anchor: QPoint, persistent: bool = False, meter: bool = False) -> None:
        text = re.sub(r"\*\*|__|`|^#+\s*", "", text, flags=re.MULTILINE).strip()  # strip markdown marks
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
# Background worker
# ===========================================================================
class _Worker(QObject):
    # (callback, result) — carried over to be run on the main thread
    finished = pyqtSignal(object, object)

    def __init__(self, fn: Callable[[], Any], on_done: Callable, on_fail: Callable) -> None:
        super().__init__()
        self._fn, self._on_done, self._on_fail = fn, on_done, on_fail

    def run(self) -> None:
        try:
            result = self._fn()
            self.finished.emit(self._on_done, result)
        except Exception as e:  # noqa: BLE001
            log.exception("Background job failed")
            self.finished.emit(self._on_fail, e)


# ===========================================================================
# Controller
# ===========================================================================
MENU_ITEMS = [
    ("type", "Command", "Type a command"),
    ("voice", "Voice", "Voice command"),
    ("toggle", "Play", "Play / Pause"),
    ("next", "Next", "Next track"),
    ("prev", "Previous", "Previous track"),
    ("playing", "Now", "What's playing?"),
    ("shot", "Screen", "Screenshot"),
    ("settings", "Settings", "Settings"),
]


class AppController(QObject):
    progress_sig = pyqtSignal(str)
    confirm_sig = pyqtSignal(str, object, str)
    level_sig = pyqtSignal(float)
    orb_level_sig = pyqtSignal(float)
    wake_sig = pyqtSignal(str, object)
    overlay_sig = pyqtSignal(bool)     # True: hide our own windows for a screenshot

    def __init__(self, settings: config.Settings) -> None:
        super().__init__()
        self.settings = settings
        tools.load_all()
        self.assistant = Assistant(settings=settings)
        self.assistant.confirm = self._confirm_blocking
        self.assistant.on_progress = self.progress_sig.emit
        self._stt = None
        self._heard: str | None = None       # last sentence heard by voice (shown in the bubble)
        self._listening: str | None = None   # None | "recording" | "transcribing"
        self._jobs: list[tuple[QThread, _Worker]] = []
        self._busy = False
        self._anchor = QPoint()
        self._confirm_event = threading.Event()
        self._confirm_ok = False
        # Jarvis (voice conversation) state
        self.orb = None
        self._speaker = None
        self._jarvis = False
        self._silent_rounds = 0
        self._wake = None
        self._think_token = None
        self._followup = False   # True: the "continue" listen after an answer

        self.menu = RadialMenu(MENU_ITEMS)
        self.menu.triggered.connect(self._on_menu)
        self.bar = CommandBar()
        self.bar.submitted.connect(self.run_text)
        self.toast = Toast()
        self.toast.clicked.connect(self._on_toast_clicked)

        self.progress_sig.connect(self._on_progress)
        self.confirm_sig.connect(self._on_confirm)
        self.level_sig.connect(self.toast.set_level)
        self.wake_sig.connect(self._on_wake)
        self.overlay_sig.connect(self._set_overlays_hidden)
        from .tools import vision

        vision.OVERLAY_HOOK = self.overlay_sig.emit   # can be called safely from a thread

    # --- Background jobs (safe) --------------------------------------------
    def _run(self, fn: Callable[[], Any], on_done: Callable, on_fail: Callable | None = None) -> None:
        th = QThread()
        w = _Worker(fn, on_done, on_fail or self._on_error)
        w.moveToThread(th)
        th.started.connect(w.run)
        w.finished.connect(self._dispatch)   # runs on the main thread
        w.finished.connect(th.quit)
        th.finished.connect(self._cleanup_jobs)
        self._jobs.append((th, w))
        th.start()

    @pyqtSlot(object, object)
    def _dispatch(self, callback: Callable, result: Any) -> None:
        try:
            callback(result)
        except Exception:  # noqa: BLE001
            log.exception("Callback error")

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
        """Writes to the bubble; for a voice command the heard sentence always stays on top."""
        if self._heard:
            msg = f"🗣 “{self._heard}”\n{msg}"
        self.toast.show_message(msg, self._anchor, persistent, meter)

    # --- Menu --------------------------------------------------------------
    @pyqtSlot(bool)
    def _set_overlays_hidden(self, hide: bool) -> None:
        """While taking a screenshot, don't let the orb/bubble/menu cover the click target."""
        for w in (self.orb, self.toast, self.bar, self.menu):
            if w is not None and w.isVisible():
                w.setWindowOpacity(0.0 if hide else 1.0)

    def capture_context(self) -> None:
        """At the MOMENT of the shortcut/menu/wake, capture the foreground window and start
        gathering context in the background (so it's ready while the user is speaking)."""
        snap = context.foreground_snapshot()
        if snap is not None and (not snap["title"] or snap["exe"].lower() == "explorer.exe"
                                 and snap["title"] in ("", "Program Manager")):
            snap = None                    # taskbar / desktop: not meaningful context
        if snap is None and getattr(self, "_snapshot", None):
            snap = self._snapshot          # if we have focus (menu/orb) use the last valid window
        self._snapshot = snap
        self._ctx = context.start(snap)

    def _context_text(self) -> str:
        """Called on a background thread: get the prepared context (wait at most 2.5 s)."""
        fut = getattr(self, "_ctx", None)
        try:
            return fut.result(timeout=2.5) if fut else context.build(None, include_media=False)
        except Exception:  # noqa: BLE001
            return context.build(getattr(self, "_snapshot", None), include_media=False)

    def open_menu(self) -> None:
        self.capture_context()
        self.bar.hide()
        self.menu.popup_at(QCursor.pos())

    def _on_menu(self, key: str) -> None:
        self._anchor = self.menu.center_global()
        self._heard = None
        if key == "type":
            self.bar.open_at(self._anchor)
        elif key == "voice":
            self.voice_entry(self._anchor)
        elif key in ("toggle", "next", "prev"):
            action = {"toggle": "toggle", "next": "next", "prev": "previous"}[key]
            self.direct("media_control", {"action": action})
        elif key == "playing":
            self.direct("now_playing", {})
        elif key == "shot":
            self.direct("screenshot", {})
        elif key == "settings":
            self.open_settings()

    def _permitted(self, name: str, args: dict) -> str | None:
        """Permission check (on the main thread). Returns an explanation if blocked."""
        level = permissions.tool_level(self.settings, name)
        if level == permissions.DENY:
            return "You haven't allowed this action (Settings > Permissions)."
        if level == permissions.ASK and not self._ask_gui(name, args, "medium"):
            return "You didn't approve the action."
        return None

    def direct(self, name: str, args: dict, label: str = "…", command: str | None = None) -> None:
        """Runs the tool directly without going to the AI (fast path)."""
        blocked = self._permitted(name, args)
        if blocked:
            self._show(blocked)
            return
        self._show(f"⏳ {label}" if label != "…" else label, persistent=True)

        def done(r: Any) -> None:
            context.remember_command(command or f"[menu] {name}", str(r))
            self._show(str(r))

        self._run(lambda: tools.execute(name, args), done)

    # --- Typed / voice command ---------------------------------------------
    def run_text(self, text: str, heard: bool = False) -> None:
        self._heard = text if heard else None
        # 1) Fast path: known music commands without the AI, instantly
        intent = intents.match(text)
        if intent is not None:
            log.info("Fast path: %r -> %s %s", text, intent.tool, intent.args)
            self.direct(intent.tool, intent.args, f"{intent.label}…", command=text)
            return
        # 2) Everything else goes to the AI
        if self._busy:
            self._show("Still working on the previous command…")
            return
        self._busy = True
        self._show("⏳ Thinking…", persistent=True)

        def done(r: Any) -> None:
            self._busy = False
            context.remember_command(text, str(r))
            self._show(str(r))

        self._run(lambda: self.assistant.ask(text, context=self._context_text()), done)

    @pyqtSlot(str)
    def _on_progress(self, msg: str) -> None:
        self._show(f"… {msg}", persistent=True)

    # --- Confirmation ------------------------------------------------------
    def _confirm_blocking(self, name: str, args: dict, risk: str) -> bool:
        """Called from a background thread; asks the question on the main thread."""
        self._confirm_event.clear()
        self.confirm_sig.emit(name, args, risk)
        self._confirm_event.wait()
        return self._confirm_ok

    @pyqtSlot(str, object, str)
    def _on_confirm(self, name: str, args: object, risk: str) -> None:
        if self._jarvis and self.orb is not None:
            self.orb.set_caption("Waiting for your approval — look at the window on screen.")
        self._confirm_ok = self._ask_gui(name, args, risk)
        self._confirm_event.set()

    def _ask_gui(self, name: str, args: object, risk: str) -> bool:
        from .assistant import TOOL_LABELS

        box = QMessageBox()
        box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        box.setWindowIcon(app_icon())
        box.setStyleSheet(DIALOG_STYLE)
        box.setIconPixmap(icon_pixmap("warning", 36, "#ffd094", box.devicePixelRatioF()))
        box.setWindowTitle("aidesk — Confirm")
        box.setText(f"The assistant wants to do this: {TOOL_LABELS.get(name, name)}")
        box.setInformativeText(f"{name}\n{args}\n\nTo turn off this prompt: Settings > Permissions")
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        force_foreground(box)
        return box.exec() == QMessageBox.StandardButton.Yes

    # --- Voice -------------------------------------------------------------
    def _get_stt(self):
        if self._stt is None:
            from .voice import CloudTranscriber, SpeechToText

            cloud = None
            if self.settings.stt_mode in ("auto", "cloud"):
                # First the selected provider, otherwise another voice-capable one that has a key
                for prov in (self.settings.provider, "gemini", "openai"):
                    key = config.get_api_key(prov) if prov in ("gemini", "openai") else None
                    if key:
                        cloud = CloudTranscriber(prov, key, self.settings.language)
                        break
            log.info("Speech recognition: %s", f"cloud ({cloud.provider})" if cloud else f"local ({self.settings.whisper_model})")
            self._stt = SpeechToText(self.settings.whisper_model, self.settings.language, cloud,
                                     mic_name=self.settings.mic_name)
        return self._stt

    def preload_voice(self) -> None:
        try:
            stt = self._get_stt()
        except Exception:  # noqa: BLE001 — if voice packages are missing, skip silently
            log.warning("Could not load voice module", exc_info=True)
            return
        # When cloud is available the local model is only a fallback: prepare it in the background anyway.
        self._run(stt.preload, lambda r: log.info(r), lambda e: log.warning("Voice model: %s", e))

    def start_voice(self, anchor: QPoint | None = None) -> None:
        self._anchor = anchor or QCursor.pos()
        try:
            stt = self._get_stt()
        except Exception as e:  # noqa: BLE001
            self.toast.show_message(f"⚠ Voice module unavailable: {e}", self._anchor)
            return
        if self._listening == "recording":  # second press = finish recording
            stt.stop()
            return
        if self._listening == "transcribing":
            return  # already being transcribed, wait
        if self._busy:
            self.toast.show_message("Still working on the previous command…", self._anchor)
            return
        self._listening = "recording"  # mark immediately, on the main thread
        self._heard = None
        stt.arm()  # don't lose an early "finish" press
        hint = "" if (stt.ready or stt.cloud) else "\n(first use: preparing voice model)"
        self._show(f"🎤 Listening… click to finish{hint}", persistent=True, meter=True)

        def failed(e: Exception) -> None:
            self._listening = None
            self._show(f"⚠ Voice error: {e}")

        def recorded(audio: Any) -> None:
            self._listening = "transcribing"
            self._show("⏳ Understanding…", persistent=True)
            self._run(lambda: stt.transcribe(audio), heard, failed)

        def heard(text: Any) -> None:
            self._listening = None
            text = str(text or "").strip()
            if not text:
                self._show("I didn't catch anything. Speak a bit closer to the mic.")
                return
            self.run_text(text, heard=True)  # the heard sentence stays in the bubble

        self._run(lambda: stt.record(on_level=self.level_sig.emit), recorded, failed)

    # --- Jarvis: voice conversation mode -------------------------------------
    # Goodbye: the WHOLE sentence must be a goodbye phrase ("Spotify'ı kapat" is NOT a goodbye).
    # The sets below are Turkish because they match the user's spoken goodbye; kept as-is.
    GOODBYES = {
        "görüşürüz", "görüşmek üzere", "hoşça kal", "hoşçakal", "bu kadar", "şimdilik bu kadar",
        "kendini kapat", "kapat kendini", "kapan", "sen kapan", "çıkış", "iyi geceler", "bay bay",
        "bye", "sus", "sus artık", "tamam kapat", "jarvis kapan", "konuşmayı kapat", "konuşmayı bitir",
        "bitir", "yeter",
    }
    GOODBYE_FILLER = {"tamam", "efendim", "jarvis", "teşekkürler", "teşekkür", "ederim", "sağ", "ol",
                      "sağol", "hadi", "o", "zaman", "peki", "şimdi", "artık", "lütfen", "kanka", "usta",
                      "ustam", "abi", "ve", "de", "da"}

    @classmethod
    def is_goodbye(cls, text: str) -> bool:
        words = re.sub(r"[^\wçğıöşü ]", " ", text.replace("I", "ı").replace("İ", "i").lower()).split()
        core = " ".join(w for w in words if w not in cls.GOODBYE_FILLER)
        return core in cls.GOODBYES or (not core and any(w in ("teşekkürler", "sağol") for w in words))

    def voice_entry(self, anchor: QPoint | None = None) -> None:
        """Voice command shortcut / menu: the orb if Jarvis is on, otherwise the bubble."""
        if not self._jarvis:
            self.capture_context()
        if not self.settings.jarvis_enabled:
            self.start_voice(anchor)
            return
        if self._jarvis:  # while a session is open: interrupt speech or close
            if self._speaker is not None and self._speaker.speaking:
                self._speaker.stop()
            elif self._listening == "recording" and self._stt is not None:
                self._stt.stop()
            else:
                self.end_jarvis()
            return
        self.start_jarvis()

    def _get_orb(self):
        if self.orb is None:
            from .orb import JarvisOrb

            self.orb = JarvisOrb()
            self.orb.clicked.connect(self._jarvis_click)
            self.orb.closed.connect(self.end_jarvis)
            self.orb.geometry_changed.connect(self._save_orb_geometry)
            self.orb_level_sig.connect(self.orb.set_level)
            self.orb.set_scale(self.settings.orb_scale)
        return self.orb

    def _save_orb_geometry(self, x: int, y: int, scale: float) -> None:
        s = config.load_settings()
        s.orb_x, s.orb_y, s.orb_scale = x, y, round(scale, 3)
        config.save_settings(s)
        self.settings.orb_x, self.settings.orb_y, self.settings.orb_scale = s.orb_x, s.orb_y, s.orb_scale

    def _get_speaker(self):
        if self._speaker is None:
            from .tts import Speaker

            s = self.settings
            self._speaker = Speaker(engine=s.tts_engine, voice=s.tts_voice, language=s.language,
                                    openai_key=config.get_api_key("openai"), rate=s.tts_rate)
        return self._speaker

    def start_jarvis(self, initial: str | None = None) -> None:
        try:
            self._get_stt()
        except Exception as e:  # noqa: BLE001
            self.toast.show_message(f"⚠ Voice module unavailable: {e}", QCursor.pos())
            return
        self._jarvis = True
        self._silent_rounds = 0
        self._followup = False
        self.toast.hide()
        orb = self._get_orb()
        orb.set_caption("Listening…")
        orb.set_mode("listening")
        saved = self.settings.orb_x != -10000
        orb.show_center(QPoint(self.settings.orb_x, self.settings.orb_y) if saved else None)
        if initial:
            self._jarvis_handle(initial)
        else:
            self._jarvis_listen()

    def end_jarvis(self, delay: int = 0) -> None:
        def _end() -> None:
            self._jarvis = False
            if self._speaker is not None:
                self._speaker.stop()
            if self._listening == "recording" and self._stt is not None:
                self._stt.stop()
            if self.orb is not None:
                self.orb.set_mode("idle")
                self.orb.hide_animated()

        if delay:
            QTimer.singleShot(delay, _end)
        else:
            _end()

    def _mic_level(self, level: float) -> None:      # called from the audio thread
        self.orb_level_sig.emit(min(1.0, (max(level, 0.0) / 0.05) ** 0.5))

    def _tts_level(self, level: float) -> None:      # called from the audio thread
        self.orb_level_sig.emit(min(1.0, level * 4.5))

    def _jarvis_listen(self) -> None:
        if not self._jarvis or self._listening is not None:
            return
        stt = self._get_stt()
        self._listening = "recording"
        stt.arm()
        self.orb.set_mode("listening")
        self.orb.set_caption("Listening…")

        def failed(e: Exception) -> None:
            self._listening = None
            self._jarvis_fail(e)

        def recorded(audio: Any) -> None:
            if not self._jarvis:
                self._listening = None
                return
            self._listening = "transcribing"
            self.orb.set_mode("thinking")
            self.orb.set_caption("…")
            self._run(lambda: stt.transcribe(audio), heard, failed)

        def heard(text: Any) -> None:
            self._listening = None
            if not self._jarvis:
                return
            text = str(text or "").strip()
            if not text:
                # Silence: keep listening until the configured time is up (0 = never close)
                self._silent_rounds += 1
                limit = int(getattr(self.settings, "jarvis_idle_close", 60) or 0)
                if limit and self._silent_rounds * 15 >= limit:
                    self.orb.set_caption("Görüşmek üzere.")
                    self.end_jarvis(delay=700)
                else:
                    self.orb.set_caption("Listening… (say \"görüşürüz\" to close)")
                    self._jarvis_listen()
                return
            self._silent_rounds = 0
            self._followup = False
            self._jarvis_handle(text)

        # 15 s to start speaking; don't cut off during in-sentence pauses (up to 1.5 s);
        # record at most 30 s for long requests.
        self._run(lambda: stt.record(on_level=self._mic_level, no_speech_timeout=15.0,
                                     silence_duration=1.3, max_seconds=30.0), recorded, failed)

    def _jarvis_handle(self, text: str) -> None:
        log.info("Jarvis heard: %r", text)
        self.orb.set_caption(f"“{text}”")
        if self.is_goodbye(text):
            self._jarvis_say("Görüşmek üzere efendim.", then="end")
            return
        intent = intents.match(text)
        if intent is not None:
            blocked = self._permitted(intent.tool, intent.args)
            if blocked:
                self._jarvis_say(blocked)
                return

            def run() -> str:
                r = tools.execute(intent.tool, intent.args)
                context.remember_command(text, r)
                return r

            if intent.tool in ("play_music", "play_song"):
                # Speak first, then play and close (if left open the mic would pick up the music)
                def played(r: Any) -> None:
                    self.orb.set_caption(str(r))
                    self.end_jarvis(delay=1600)

                def after_say() -> None:
                    self.orb.set_mode("thinking")
                    self._run(run, played, self._jarvis_fail)

                self._jarvis_say("Hemen açıyorum.", then=after_say)
                return
            self.orb.set_mode("thinking")

            def done(r: Any) -> None:
                if intent.tool == "media_control" and intent.args.get("action") in ("next", "previous", "play"):
                    self.orb.set_caption(str(r))   # music is playing: don't talk over it, close
                    self.end_jarvis(delay=1600)
                else:
                    self._jarvis_say(str(r))

            self._run(run, done, self._jarvis_fail)
            return
        if self._busy:
            # Previous request still running: instead of getting stuck, say so and go back to listening
            self._jarvis_say("Bir saniye, önceki isteğin üzerinde çalışıyorum.")
            return
        self._busy = True
        self.orb.set_mode("thinking")
        token = object()
        self._think_token = token

        def watchdog() -> None:    # if no answer within 45 s, don't appear frozen
            if self._jarvis and self._busy and self._think_token is token:
                self._busy = False
                self._think_token = None
                self._jarvis_say("Bu biraz uzun sürdü, isteği iptal ettim. Tekrar dener misin?")

        QTimer.singleShot(45_000, watchdog)
        # If the answer doesn't arrive within 0.8 s, don't wait silently: say a short acknowledgement
        QTimer.singleShot(800, lambda: self._filler(token))

        def answered(r: Any) -> None:
            if self._think_token is not token:
                return              # timed out, the answer is too late now
            self._think_token = None
            self._busy = False
            self._jarvis_say(str(r))

        def failed(e: Exception) -> None:
            if self._think_token is not token:
                return
            self._think_token = None
            self._busy = False
            self._jarvis_fail(e)

        def ask() -> str:
            r = self.assistant.ask(text, voice=True, context=self._context_text())
            context.remember_command(text, r)
            return r

        self._run(ask, answered, failed)

    FILLERS = ("Bakıyorum efendim.", "Hemen bakıyorum.", "Bir saniye.", "Hallediyorum.")

    def _filler(self, token: object) -> None:
        """While the AI thinks, say a short 'looking into it' (the real answer follows in order)."""
        if not (self._jarvis and self._busy and self._think_token is token):
            return
        import random

        speaker = self._get_speaker()
        self._filler_done = threading.Event()
        done = self._filler_done
        text = random.choice(self.FILLERS)
        self._run(lambda: speaker.speak(text, on_level=self._tts_level), lambda _r: done.set(),
                  lambda _e: done.set())

    def _jarvis_fail(self, e: Exception) -> None:
        from .apierrors import humanize

        self._jarvis_say(humanize(e), then="end")

    def _jarvis_say(self, text: str, then: Any = "listen") -> None:
        """Speaks; then: "listen" (keep chatting), "end" or a function."""
        if not self._jarvis:
            return
        speaker = self._get_speaker()
        filler = getattr(self, "_filler_done", None)
        if filler is not None and not filler.is_set():
            # The "looking into it" filler is still being said: wait for it, then say the answer
            QTimer.singleShot(120, lambda: self._jarvis_say(text, then))
            return
        self._filler_done = None
        self.orb.set_caption(text)
        self.orb.set_mode("speaking")

        def spoken(completed: Any) -> None:
            if not self._jarvis:
                return
            self.orb.set_mode("idle")
            if callable(then):
                then()
            elif then == "end":
                self.end_jarvis(delay=500)
            elif self.settings.jarvis_continuous or completed is False:
                self._followup = completed is not False   # follow-up question: wait briefly
                self._jarvis_listen()   # if speech was interrupted, listen right away
            else:
                self.end_jarvis(delay=1200)

        def failed(e: Exception) -> None:
            log.warning("Text-to-speech failed: %s", e)
            spoken(True)

        self._run(lambda: speaker.speak(text, on_level=self._tts_level), spoken, failed)

    # --- Wake word -------------------------------------------------------------
    def _assistant_busy(self) -> bool:
        """The wake listener (background) asks this: no detection while busy."""
        sp = self._speaker
        return bool(self._jarvis or self._listening is not None or (sp is not None and sp.speaking))

    def start_wake(self) -> None:
        self.stop_wake()
        s = self.settings
        if not s.wake_enabled:
            return
        try:
            from .wake import WakeListener
        except Exception as e:  # noqa: BLE001
            log.warning("Could not load wake word listener: %s", e)
            return
        self._wake = WakeListener(on_wake=self.wake_sig.emit, word=s.wake_word, phrase=s.wake_phrase,
                                  sensitivity=s.wake_sensitivity, mic_name=s.mic_name,
                                  is_busy=self._assistant_busy)
        self._wake.start()
        QTimer.singleShot(8000, self._check_wake)

    def _check_wake(self) -> None:
        if self._wake is not None and self._wake.error:
            self.toast.show_message(f"⚠ Wake word not working: {self._wake.error}", QCursor.pos())

    def stop_wake(self) -> None:
        if self._wake is not None:
            self._wake.stop()
            self._wake = None

    @pyqtSlot(str, object)
    def _on_wake(self, rest: str, audio: object = None) -> None:
        if self._assistant_busy():
            return
        self.capture_context()
        rest = (rest or "").strip()
        if rest and audio is not None:
            # A command was spoken after the wake phrase: transcribe the command accurately with
            # the real speech recognition (cloud / configured local model) and then process it.
            self._listening = "transcribing"
            stt = self._get_stt()

            def accurate() -> str:
                from .wake import match_phrase

                text = stt.transcribe(audio)
                cmd = match_phrase(text, self.settings.wake_phrase, min_ratio=0.6)
                return cmd if cmd is not None else text

            def done(cmd: Any) -> None:
                self._listening = None
                self._dispatch_wake(str(cmd or "").strip())

            def failed(_e: Exception) -> None:
                self._listening = None
                self._dispatch_wake(rest)

            self._run(accurate, done, failed)
            return
        self._dispatch_wake(rest)

    def _dispatch_wake(self, rest: str) -> None:
        log.info("Woken by voice; command: %r", rest)
        if self.settings.jarvis_enabled:
            self.start_jarvis(initial=rest or None)
        elif rest:
            self._anchor = QCursor.pos()
            self.run_text(rest, heard=True)
        else:
            self.start_voice(QCursor.pos())

    def _jarvis_click(self) -> None:
        if self._speaker is not None and self._speaker.speaking:
            self._speaker.stop()
        elif self._listening == "recording" and self._stt is not None:
            self._stt.stop()

    def _on_toast_clicked(self) -> None:
        if self._listening == "recording" and self._stt is not None:
            self._stt.stop()
        else:
            self.toast.hide()

    # --- Settings ----------------------------------------------------------
    def open_settings(self) -> None:
        dlg = SetupDialog(self.settings)
        if dlg.exec():
            self.settings = config.load_settings()
            self.assistant.settings = self.settings
            self.assistant._provider = None   # rebuild with the new key/provider
            self.assistant.reset()
            self._speaker = None                 # the voice engine / rate may have changed
            self.start_wake()                    # the wake settings may have changed
            if self._jarvis:
                self.end_jarvis()
            if self._listening is None:  # voice settings/keys may have changed
                self._stt = None
                self.preload_voice()


# ===========================================================================
# Tray icon
# ===========================================================================
def make_tray(app: QApplication, ctrl: AppController) -> QSystemTrayIcon:
    tray = QSystemTrayIcon(app_icon(), app)
    tray.setToolTip("aidesk — AI desktop assistant")
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
        ("brand", "Open menu", ctrl.open_menu),
        ("type", "Typed command", lambda: ctrl.bar.open_at(QCursor.pos())),
        ("voice", "Voice command / Jarvis", lambda: ctrl.voice_entry(QCursor.pos())),
        ("settings", "Settings / API keys", ctrl.open_settings),
        ("exit", "Exit", app.quit),
    ):
        act = QAction(QIcon(icon_pixmap(key, 16, dpr=menu.devicePixelRatioF())), text, menu)
        act.triggered.connect(fn)
        menu.addAction(act)
    tray.setContextMenu(menu)
    tray._menu = menu  # keep a reference against the garbage collector
    tray.activated.connect(
        lambda reason: ctrl.open_menu()
        if reason == QSystemTrayIcon.ActivationReason.Trigger
        else None
    )
    tray.show()
    return tray


from .settings import SetupDialog  # noqa: E402,F401  (at the end to avoid a circular import)
