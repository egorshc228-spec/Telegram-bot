import base64
import io

from PIL import Image

from app.config import MAX_IMAGE_SIDE


def image_block(raw: bytes) -> dict:
    """Фото из Telegram -> блок изображения для Claude (уменьшаем и сжимаем в JPEG)."""
    img = Image.open(io.BytesIO(raw))
    img = img.convert("RGB")
    img.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/jpeg",
            "data": base64.b64encode(buf.getvalue()).decode(),
        },
    }
