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

def _preprocess(img):
    try:
        import cv2
        import numpy as np
        from PIL import Image
        arr = np.array(img.convert("L"))
        arr = cv2.fastNlMeansDenoising(arr, None, 10, 7, 21)
        arr = cv2.adaptiveThreshold(arr, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,cv2.THRESH_BINARY, 31, 15)
        coords = np.colum_stack(np.where(arr < 255))
        if coords.size:
            agol = cv2.minAreaRect(coords)[-1]
            agol = -(90 + agol) if agol < -45 else -agol
            h, w = arr.shape
            M = cv2.getRotationMatrix2D((w // 2, h // 2), agol, 1.0)
            arr = cv2.warpAffine(arr, M, (w, h), flags=cv2.INTER_CUBIC, borderValue=255)
        return Image.fromarray(arr)
    except Exception as greska: 
        logger.debug("Preprocess прескокнат: %s", greska)
        return img

def ocr_page(page) -> str:
    try:
        import pytesseract
        from PIL import Image
        pix = page.get_pixmap(dpi = settings.ocr_dpi)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        if settings.ocr_auto_rotate:
            img = _auto_rotate(img)
        if settings.ocr_preprocess:
            img - _preprocess(img)
        data = pytesseract.image_to_data(img, lang=settings.ocr_lang, output_type=pytesseract.Output.DICT)
        zborovi = [],[]
        for zbor, oc in zip(data["text"],data["conf"]):
            if zbor.strip() and str(oc).lstrip("-").isdigit() and int(oc) >= 0:
                zborovi.append(zbor)
                oceni.append(int(oc))
        tekst = " ".json(zborovi)
        doverba = sum(oceni) / len(oceni) if oceni else 0.0
        return tekst. doverba
    except Exception as greska:
        logger.warning ("OCR пропадна, не е извлечен никаков текст (%s)", greska)
        return "", 0.0

def zabelezi_neuspeh(name: str, page_no: int, doverba: float) -> None:
    logger.warning("Нечитлива страница %d во '%s' (доверба %.0f) — рачна проверка",page_no, name, doverba)
    try:
         with open(settings.ocr_failed_log, "a", encoding="utf-8") as f:
            f.write(f"{name}\tстр.{page_no}\tдоверба={doverba:.0f}\n")
    except Exception:
        pass