from __future__ import annotations
import io
import logging
from app.config import settings

logger = logging.getLogger(__name__)

#proverka dali stranicata e izvrtena, dokolku ne e vo prirodna forma Tesseract ja rotira za da se obrabotuva
def _auto_rotate(img):
    try:
        import pytesseract
        osd = pytesseract.image_to_osd(img, output_type = pytesseract.Output.DICT)
        agol = int(osd.get("rotate", 0))
        if agol:
            img = img.rotate(-agol, expand = True)
    except Exception as greska:
        logger.debug("OSD (ориентација) прескокнат: %s", greska)
    return img

def ocr_page(page) -> str:
    try:
        import pytesseract
        from PIL import Image
        pix = page.get_pixmap(dpi = settings.ocr_dpi)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        if settings.ocr_auto_rotate:
            img = _auto_rotate(img)
        return pytesseract.image_to_string(img, lang=settings.ocr_lang)
    except Exception as greska:
        logger.warning ("OCR пропадна, не е извлечен никаков текст (%s)", greska)
        return ""
