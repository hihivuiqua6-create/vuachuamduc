"""
Bộ giải Captcha tự động cho Zefoy.

Ưu tiên pytesseract (offline, không cần API key). Nếu không có sẵn tesseract
trên máy, hàm sẽ raise và server sẽ trả về ảnh cho user nhập tay.

Captcha Zefoy là chữ cái thường/hoa trên nền sáng. Ta tiền xử lý bằng Pillow:
chuyển grayscale, tăng tương phản, nhị phân hoá — rồi cho tesseract giới hạn
whitelist ký tự chữ cái.
"""
from __future__ import annotations

import io
import re


def _preprocess(img_bytes: bytes):
    from PIL import Image, ImageFilter, ImageOps

    img = Image.open(io.BytesIO(img_bytes)).convert("L")
    # phóng to giúp OCR chính xác hơn
    img = img.resize((img.width * 3, img.height * 3), Image.LANCZOS)
    img = ImageOps.autocontrast(img, cutoff=5)
    img = img.filter(ImageFilter.MedianFilter(3))
    # nhị phân hoá
    img = img.point(lambda p: 0 if p < 140 else 255, mode="1")
    return img


def solve_captcha_image(img_bytes: bytes) -> str:
    """Trả về chuỗi captcha (chỉ chữ cái, đã lowercase). Raise nếu không giải được."""
    if not img_bytes:
        raise RuntimeError("captcha rỗng")
    try:
        import pytesseract  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError(f"pytesseract chưa được cài: {e}") from e

    img = _preprocess(img_bytes)
    config = "--psm 8 -c tessedit_char_whitelist=abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    try:
        text = pytesseract.image_to_string(img, config=config)
    except Exception as e:
        raise RuntimeError(f"tesseract lỗi: {e}") from e

    text = re.sub(r"[^A-Za-z]", "", text or "").lower()
    if not text:
        raise RuntimeError("OCR không đọc được ký tự")
    return text