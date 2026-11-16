"""Jarvis orb — a sound-reactive 3D hologram in the center of the screen.

Real 3D points (numpy) are projected to 2D with perspective and drawn with an
"additive" blend via QPainter, producing the golden glow.

Layers: a particle shell, ring arcs rotating on different axes, outer data
fragments, a vortex-like spinning core, and a central glow.

Interaction:
- Sound level (speaking/listening) -> the orb grows, glows, rings speed up.
- Left drag -> move.  Wheel -> size.  Right drag -> rotate in 3D (with inertia).
- Hover -> particles flee the cursor.
- Click -> `clicked` (interrupt speech).  Double click / Esc -> `closed`.  Right click -> menu.
"""
from __future__ import annotations

import math
import time

import numpy as np
from PyQt6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer, QVariantAnimation, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter
from PyQt6.QtWidgets import QWidget

GOLD = (255, 176, 64)
HOT = (255, 226, 150)
DEEP = (255, 120, 24)


def _rot_x(a: float) -> np.ndarray:
    c, s = math.cos(a), math.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def _rot_y(a: float) -> np.ndarray:
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def _random_basis(rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    """Two orthogonal unit vectors spanning a random plane."""
    a = rng.normal(size=3)
    a /= np.linalg.norm(a)
    b = rng.normal(size=3)
    b -= a * (a @ b)
    b /= np.linalg.norm(b)
    return a, b


class JarvisOrb(QWidget):
    clicked = pyqtSignal()
    closed = pyqtSignal()
    geometry_changed = pyqtSignal(int, int, float)   # x, y, scale (to save)

    ORB = 340          # the square area the orb is drawn in
    CAPTION_H = 92     # the caption area at the bottom

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.NoDropShadowWindowHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(self.ORB + 60, self.ORB + self.CAPTION_H)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        rng = np.random.default_rng(7)
        # 1) Particle shell (Fibonacci sphere + slight roughness)
        n = 1100
        i = np.arange(n) + 0.5
        phi = np.arccos(1 - 2 * i / n)
        th = math.pi * (1 + 5 ** 0.5) * i
        self._shell = np.stack([np.cos(th) * np.sin(phi), np.sin(th) * np.sin(phi), np.cos(phi)], 1)
        self._shell *= rng.uniform(0.9, 1.05, (n, 1))
        self._shell_phase = rng.uniform(0, 2 * math.pi, n)
        # 2) Core: a dense cloud spinning on its own axis
        m = 320
        d = rng.normal(size=(m, 3))
        d /= np.linalg.norm(d, axis=1, keepdims=True)
        self._core = d * (rng.uniform(0.05, 1.0, (m, 1)) ** 1.6 * 0.55)
        # 3) Ring arcs: random axes, partial arcs, different speeds
        self._rings = []
        for _ in range(11):
            u, v = _random_basis(rng)
            arcs = [(rng.uniform(0, 2 * math.pi), rng.uniform(0.6, 2.6)) for _ in range(rng.integers(1, 4))]
            self._rings.append({
                "u": u, "v": v, "r": rng.uniform(0.45, 1.22), "arcs": arcs,
                "speed": rng.uniform(-0.9, 0.9), "w": rng.uniform(0.8, 2.0),
            })
        # 4) Outer data fragments (short arcs)
        self._frags = []
        for _ in range(70):
            u, v = _random_basis(rng)
            self._frags.append({
                "u": u, "v": v, "r": rng.uniform(1.05, 1.42), "a": rng.uniform(0, 2 * math.pi),
                "len": rng.uniform(0.08, 0.45), "speed": rng.uniform(-1.4, 1.4),
            })

        # State
        self.mode = "idle"            # idle | listening | thinking | speaking
        self.caption = ""
        self.hint = "Drag: move · Wheel: size · Right click: menu"
        self.scale = 1.0
        self._press_button = Qt.MouseButton.NoButton
        self._press_global = QPointF()
        self._win_start = QPoint()
        self._target_level = 0.0
        self._level = 0.0
        self._yaw, self._pitch = 0.4, -0.25
        self._vyaw = self._vpitch = 0.0
        self._t = 0.0
        self._last = time.perf_counter()
        self._mouse: QPointF | None = None
        self._press: QPointF | None = None
        self._dragged = False
        self._appear = 0.0

        self._timer = QTimer(self)
        self._timer.setInterval(16)   # ~60 fps
        self._timer.timeout.connect(self._tick)
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(380)
        self._anim.valueChanged.connect(self._on_appear)
        self._anim.finished.connect(self._on_anim_done)

    # --- Public interface ----------------------------------------------------
    def set_scale(self, scale: float) -> None:
        """Orb size (0.55x – 1.8x). Stays centered while visible."""
        scale = max(0.55, min(1.8, float(scale)))
        center = self.geometry().center() if self.isVisible() else None
        self.scale = scale
        self.ORB = int(340 * scale)
        self.setFixedSize(self.ORB + 60, self.ORB + self.CAPTION_H)
        if center is not None:
            self.move(center.x() - self.width() // 2, center.y() - self.height() // 2)
        self.update()

    def _default_pos(self) -> QPoint:
        screen = QGuiApplication.primaryScreen().availableGeometry()
        return QPoint(screen.center().x() - self.width() // 2,
                      screen.center().y() - self.ORB // 2 - 30)

    def _on_screen(self, pos: QPoint) -> bool:
        """Is the orb's center inside any screen? (no if a monitor was removed)"""
        center = QPoint(pos.x() + self.width() // 2, pos.y() + self.ORB // 2)
        return QGuiApplication.screenAt(center) is not None

    def show_center(self, pos: QPoint | None = None) -> None:
        """Opens at the saved position (if valid) or in the center of the screen."""
        self.move(pos if (pos is not None and self._on_screen(pos)) else self._default_pos())
        self._last = time.perf_counter()
        self._timer.start()
        if not self.isVisible():
            self._appear = 0.0
            self.show()
        self._anim.stop()
        self._anim.setStartValue(self._appear)
        self._anim.setEndValue(1.0)
        self._anim.start()

    def recenter(self) -> None:
        self.move(self._default_pos())
        self._emit_geometry()

    def _emit_geometry(self) -> None:
        self.geometry_changed.emit(self.x(), self.y(), self.scale)

    def hide_animated(self) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._appear)
        self._anim.setEndValue(0.0)
        self._anim.start()

    def _on_appear(self, v) -> None:
        self._appear = float(v)

    def _on_anim_done(self) -> None:
        if self._appear <= 0.01:
            self._timer.stop()
            self.hide()

    @pyqtSlot(str)
    def set_mode(self, mode: str) -> None:
        self.mode = mode
        if mode in ("idle", "thinking"):
            self._target_level = 0.0

    @pyqtSlot(float)
    def set_level(self, level: float) -> None:
        """Sound intensity between 0..1 (speech or microphone)."""
        self._target_level = max(0.0, min(1.0, level))

    @pyqtSlot(str)
    def set_caption(self, text: str) -> None:
        self.caption = text
        self.update()

    # --- Animation -----------------------------------------------------------
    def _tick(self) -> None:
        now = time.perf_counter()
        dt = min(0.05, now - self._last)
        self._last = now
        self._t += dt
        # Level: fast rise, slow fall
        k = 0.45 if self._target_level > self._level else 0.12
        self._level += (self._target_level - self._level) * k
        self._target_level *= 0.92
        # Self-rotation + drag inertia
        spin = {"idle": 0.25, "listening": 0.35, "thinking": 1.1, "speaking": 0.45}.get(self.mode, 0.3)
        self._yaw += (spin + self._vyaw) * dt
        self._pitch += self._vpitch * dt
        self._pitch = max(-1.2, min(1.2, self._pitch))
        self._vyaw *= 0.94
        self._vpitch *= 0.94
        self.update()

    # --- Mouse -------------------------------------------------------------
    # Left drag: move · Right drag: rotate in 3D · Wheel: size
    # Left click: interrupt speech · Double click: close · Right click: menu
    def mousePressEvent(self, e) -> None:  # noqa: N802
        self._press = e.position()
        self._press_global = e.globalPosition()
        self._press_button = e.button()
        self._win_start = self.pos()
        self._mouse = e.position()
        self._dragged = False

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        pos = e.position()
        if self._press is not None:
            if abs(pos.x() - self._press.x()) + abs(pos.y() - self._press.y()) > 4:
                self._dragged = True
            if self._dragged and self._press_button == Qt.MouseButton.LeftButton:
                self.move(self._win_start + (e.globalPosition() - self._press_global).toPoint())
            elif self._dragged and self._press_button == Qt.MouseButton.RightButton and self._mouse:
                self._vyaw = (pos.x() - self._mouse.x()) * 0.6
                self._vpitch = (pos.y() - self._mouse.y()) * 0.6
        self._mouse = pos

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        if self._press is not None:
            if not self._dragged:
                if self._press_button == Qt.MouseButton.LeftButton:
                    self.clicked.emit()
                elif self._press_button == Qt.MouseButton.RightButton:
                    self._context_menu(e.globalPosition().toPoint())
            elif self._press_button == Qt.MouseButton.LeftButton:
                self._emit_geometry()   # save the new position
        self._press = None

    def leaveEvent(self, e) -> None:  # noqa: N802
        self._mouse = None

    def wheelEvent(self, e) -> None:  # noqa: N802
        steps = e.angleDelta().y() / 120.0
        if steps:
            self.set_scale(self.scale * (1.08 ** steps))
            self._emit_geometry()

    def mouseDoubleClickEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self.closed.emit()

    def keyPressEvent(self, e) -> None:  # noqa: N802
        if e.key() == Qt.Key.Key_Escape:
            self.closed.emit()

    def _context_menu(self, at: QPoint) -> None:
        from PyQt6.QtGui import QAction
        from PyQt6.QtWidgets import QMenu

        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu{background:#141210;color:#ffe8c4;border:1px solid #6b4a1e;padding:4px;}"
            "QMenu::item{padding:6px 20px;border-radius:4px;}"
            "QMenu::item:selected{background:#3d2a10;}"
        )
        for text, fn in (
            ("Center it", self.recenter),
            ("Reset size", lambda: (self.set_scale(1.0), self._emit_geometry())),
            ("Close", self.closed.emit),
        ):
            act = QAction(text, menu)
            act.triggered.connect(fn)
            menu.addAction(act)
        menu.exec(at)

    # --- Rendering -----------------------------------------------------------
    # All light points are added to a single "light buffer" with numpy (bilinear),
    # blurred to produce the glow (bloom), then mapped to a single image with the
    # golden palette and blitted to the screen. A few ms per frame.
    def _project(self, pts: np.ndarray, rot: np.ndarray, radius_px: float, cx: float, cy: float):
        p = pts @ rot.T
        f = 3.4
        s = f / (f - p[:, 2])
        x = cx + p[:, 0] * s * radius_px
        y = cy - p[:, 1] * s * radius_px
        depth = np.clip((p[:, 2] + 1.25) / 2.5, 0.0, 1.0)  # 0 = back, 1 = front
        return x, y, depth

    def _ensure_buffers(self) -> None:
        w = self.width() // 2 * 2
        h = (self.ORB + 10) // 2 * 2
        if getattr(self, "_buf_shape", None) == (h, w):
            return
        self._buf_shape = (h, w)
        cx, cy = w / 2, self.ORB / 2 + 4
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        self._r2 = (xx - cx) ** 2 + (yy - cy) ** 2
        # A mask that softly fades toward the edges (so no square box shows)
        rr = np.sqrt(self._r2) / (min(w, h) / 2)
        self._vignette = np.clip((1.0 - rr) / 0.22, 0.0, 1.0) ** 2
        # Palette: deep orange -> gold -> warm white; premultiplied BGRA
        lut = np.zeros((256, 4), np.float32)
        stops = [(0.0, (255, 90, 10), 0.0), (0.18, (255, 110, 20), 0.35), (0.45, (255, 170, 50), 0.75),
                 (0.75, (255, 215, 130), 0.95), (1.0, (255, 248, 230), 1.0)]
        xs = np.linspace(0, 1, 256)
        for c in range(3):
            lut[:, c] = np.interp(xs, [s[0] for s in stops], [s[1][c] for s in stops])
        lut[:, 3] = np.interp(xs, [s[0] for s in stops], [s[2] for s in stops])
        lut[:, :3] *= lut[:, 3:4]
        self._lut = np.zeros((256, 4), np.uint8)
        self._lut[:, 0] = lut[:, 2]   # B
        self._lut[:, 1] = lut[:, 1]   # G
        self._lut[:, 2] = lut[:, 0]   # R
        self._lut[:, 3] = lut[:, 3] * 255

    @staticmethod
    def _blur(a: np.ndarray, r: int) -> np.ndarray:
        """Separable box blur (via cumulative sum, O(n))."""
        k = 2 * r + 1
        c = np.cumsum(np.pad(a, ((r + 1, r), (0, 0))), axis=0)
        a = (c[k:] - c[:-k]) / k
        c = np.cumsum(np.pad(a, ((0, 0), (r + 1, r))), axis=1)
        return (c[:, k:] - c[:, :-k]) / k

    def _arc_points(self, items, t: float, mul: float, n: int, rscale: float = 1.0):
        pts = []
        for it in items:
            for start, length in it.get("arcs", [(it.get("a", 0.0), it.get("len", 0.3))]):
                a = np.linspace(start, start + length, n) + it["speed"] * t * mul
                pts.append(it["r"] * rscale * (np.cos(a)[:, None] * it["u"] + np.sin(a)[:, None] * it["v"]))
        return np.concatenate(pts)

    def _render(self) -> np.ndarray:
        self._ensure_buffers()
        h, w = self._buf_shape
        lvl, t, appear = self._level, self._t, self._appear
        cx, cy = w / 2, self.ORB / 2 + 4
        breathe = 0.025 * math.sin(t * 1.6)
        radius = self.ORB * 0.30 * (0.86 + 0.14 * appear) * (1 + breathe + 0.22 * lvl)
        rot = _rot_y(self._yaw) @ _rot_x(self._pitch)
        spin_mul = 1 + 2.2 * lvl + (1.5 if self.mode == "thinking" else 0)

        xs, ys, ws = [], [], []

        def add(x, y, wgt):
            xs.append(x)
            ys.append(y)
            ws.append(wgt)

        # Particle shell (vibrates with sound, flees the cursor)
        jitter = 1 + (0.035 + 0.12 * lvl) * np.sin(t * 7 + self._shell_phase)
        shell = self._shell * jitter[:, None]
        x, y, d = self._project(shell, rot, radius, cx, cy)
        if self._mouse is not None and self._press is None:
            dist = np.hypot(x - self._mouse.x(), y - self._mouse.y())
            push = np.clip(1 - dist / 70.0, 0, 1) ** 2 * (d > 0.45)
            if push.any():
                x, y, d = self._project(shell * (1 + 0.35 * push)[:, None], rot, radius, cx, cy)
        add(x, y, (0.15 + 0.85 * d ** 1.5) * (0.9 + 0.5 * lvl))
        # Ring arcs (densely sampled = continuous line)
        x, y, d = self._project(self._arc_points(self._rings, t, spin_mul, 140), rot, radius, cx, cy)
        add(x, y, (0.08 + 0.42 * d ** 1.3) * (0.8 + 0.6 * lvl))
        # Outer data fragments
        x, y, d = self._project(self._arc_points(self._frags, t, 1 + lvl, 18, 1 + 0.12 * lvl), rot, radius, cx, cy)
        add(x, y, (0.06 + 0.4 * d) * 0.9)
        # Core cloud (rotates the other way)
        core_rot = rot @ _rot_y(-t * 1.4 * (1 + lvl)) @ _rot_x(t * 0.6)
        x, y, d = self._project(self._core * (1 + 0.3 * lvl), core_rot, radius, cx, cy)
        add(x, y, 0.45 + 0.5 * d)

        x = np.concatenate(xs)
        y = np.concatenate(ys)
        wgt = np.concatenate(ws)
        x0 = np.floor(x).astype(np.int32)
        y0 = np.floor(y).astype(np.int32)
        ok = (x0 >= 0) & (y0 >= 0) & (x0 < w - 1) & (y0 < h - 1)
        x0, y0, fx, fy, wgt = x0[ok], y0[ok], (x - x0)[ok], (y - y0)[ok], wgt[ok]
        i = y0 * w + x0
        idx = np.concatenate([i, i + 1, i + w, i + w + 1])
        wts = np.concatenate([wgt * (1 - fx) * (1 - fy), wgt * fx * (1 - fy), wgt * (1 - fx) * fy, wgt * fx * fy])
        sharp = np.bincount(idx, wts, minlength=h * w).reshape(h, w).astype(np.float32)

        # Glow: two different-width blurs at half resolution
        small = sharp.reshape(h // 2, 2, w // 2, 2).sum(axis=(1, 3))
        glow = self._blur(small, 2) * 0.5 + self._blur(self._blur(small, 7), 7) * (0.45 + 0.45 * lvl)
        glow = np.repeat(np.repeat(glow, 2, axis=0), 2, axis=1)
        # Central glow (pulses like a heartbeat while thinking)
        pulse = 0.25 * (0.5 + 0.5 * math.sin(t * 6)) if self.mode == "thinking" else 0.0
        rc = radius * (0.26 + 0.10 * lvl)
        core = (0.75 + 0.45 * lvl + pulse) * np.exp(-self._r2 / (rc * rc)) \
            + (0.07 + 0.08 * lvl) * np.exp(-self._r2 / ((radius * 1.05) ** 2))

        light = (sharp * 1.35 + glow * 0.7 + core) * self._vignette
        light = (1.0 - np.exp(-light * 1.1)) * appear       # soft saturation
        return self._lut[(np.clip(light, 0, 1) * 255).astype(np.uint8)]

    def paintEvent(self, e) -> None:  # noqa: N802
        p = QPainter(self)
        img_data = np.ascontiguousarray(self._render())
        h, w = self._buf_shape
        img = QImage(img_data.data, w, h, w * 4, QImage.Format.Format_ARGB32_Premultiplied)
        p.drawImage(0, 0, img)
        appear = self._appear
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        # Caption
        if self.caption:
            font = QFont("Segoe UI")
            font.setPixelSize(15)
            p.setFont(font)
            rect = QRectF(14, self.ORB + 2, self.width() - 28, self.CAPTION_H - 24)
            flags = Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap
            p.setPen(QColor(0, 0, 0, int(170 * appear)))
            p.drawText(rect.translated(0, 1), flags, self.caption)
            p.setPen(QColor(255, 232, 190, int(255 * appear)))
            p.drawText(rect, flags, self.caption)
        small = QFont("Segoe UI")
        small.setPixelSize(11)
        p.setFont(small)
        p.setPen(QColor(255, 210, 150, int(120 * appear)))
        hint = p.fontMetrics().elidedText(self.hint, Qt.TextElideMode.ElideRight, self.width() - 12)
        p.drawText(QRectF(0, self.height() - 18, self.width(), 16), Qt.AlignmentFlag.AlignCenter, hint)
        p.end()
