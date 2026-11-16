"""Generates assets/aidesk.ico from the app's own icon drawing."""
import io
import sys
from pathlib import Path

from PIL import Image
from PyQt6.QtCore import QBuffer, QIODevice
from PyQt6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

app = QApplication(sys.argv)
from aidesk.ui import app_pixmap  # noqa: E402

buf = QBuffer()
buf.open(QIODevice.OpenModeFlag.WriteOnly)
app_pixmap(256).save(buf, "PNG")
img = Image.open(io.BytesIO(bytes(buf.data())))

out = ROOT / "assets" / "aidesk.ico"
out.parent.mkdir(exist_ok=True)
img.save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("icon:", out)
