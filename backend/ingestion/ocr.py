from __future__ import annotations
import io
import logging
import numpy as np
import pytesseract
import cv2
from PIL import Image
from app.config import settings

logger = logging.getLogger(__name__)

#proverka dali stranicata e izvrtena se proveruva za 90 180 270 stepeni, go detektira agolot i ja vraka vo normalna polozba
def _auto_rotate(img):
    try:
        osd = pytesseract.image_to_osd(img, output_type=pytesseract.Output.DICT)
        if float(osd.get("orientation_conf", 0)) <= 0: #dokolku ne e siguren, ne ja obrabotuva slikata
            return img
        agol = int(osd.get("rotate", 0)) % 360
        if agol:
            img = img.rotate(-agol, expand=True) #-agol raboti vo obratna nasoka od strelkite na casovnikot a expand za da ne ja isece slikata pri obrabotka
    except Exception as greska:
        logger.debug("OCR ja preskokna rotacijata: %s", greska)
    return img

#ispravka na mali gresk, primer slikata e skenirana pod nekoj agol
def _ispravi_agol(arr):
    ys, xs = np.where(arr < 200) #koordinati na site temni pikseli, kaj nas tekst
    if ys.size < 500:
        return arr
    coords = np.column_stack((xs, ys)).astype(np.float32)
    agol = cv2.minAreaRect(coords)[-1]
    if agol < 0:
        agol = -(90 + agol) if agol < -45 else -agol
    else:
        agol = -agol if agol < 45 else 90 - agol
    if abs(agol) < 0.4 or abs(agol) > 12:
        return arr
    h, w = arr.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), agol, 1.0)
    return cv2.warpAffine(arr, M, (w, h), flags=cv2.INTER_CUBIC, borderValue=255)

def _preprocess(img):
    try:
        arr = np.array(img.convert("L"))
        arr = cv2.fastNlMeansDenoising(arr, None, 10, 7, 21)
    except Exception as greska:
        logger.debug("Preprocess preskoknat: %s", greska)
        return img
    try:
        arr = _ispravi_agol(arr)
    except Exception as greska:
        logger.debug("Ispravuvanjeto na agolot e preskoknato: %s", greska)
    return Image.fromarray(arr)

def _redosled_tocki(tocki):
    tocki = tocki.reshape(4,2).astype("float32")
    zbir = tocki.sum(axis=1)
    razlika = np.diff(tocki, axis=1).reshape(4)
    return np.array([ tocki[np.argmin(zbir)], tocki[np.argmin(razlika)], tocki[np.argmax(zbir)], tocki[np.argmax(razlika)],], dtype="float32")

def _izvleci_list(arr, tocki):
    red = _redosled_tocki(tocki)
    (tl,tr,br,bl) = red
    sirina = int(max(np.linalg.norm(br - bl), np.linalg.norm(tr - tl)))
    visina = int(max(np.linalg.norm(tr - br), np.linalg.norm(tl - bl)))
    if sirina < 40 or visina < 40:
        return None
    cel = np.array([[0, 0],[sirina - 1, 0],[sirina - 1, visina - 1], [0, visina - 1],], dtype="float32")
    M = cv2.getPerspectiveTransform(red, cel)
    izvlecen = cv2.warpPerspective(arr, M, (sirina, visina), borderValue=255)
    return Image.fromarray(izvlecen)

def _preklop(a,b) -> float:
    x1 = max(a[0], b[0])
    y1 = max(a[1], b[1])
    x2 = min(a[2], b[2])
    y2 = min(a[3], b[3])
    if x2 <= x1 or y2 <= y1:
        return 0.0
    presek = (x2-x1) * (y2-y1)
    pomala = min((a[2]-a[0]) * (a[3]-a[1]),(b[2]-b[0]) * (b[3]-b[1]),)
    return presek/pomala if pomala else 0.0

def _listovi(img):
    arr = np.array(img.convert("L"))
    h, w = arr.shape[:2]
    povrsina = h * w
    zamaten = cv2.GaussianBlur(arr,(5,5),0)
    rab = cv2.Canny(zamaten, 50, 150)
    rab = cv2.dilate(rab, np.ones((5, 5), np.uint8), iterations=1)
    konturi, _ =cv2.findContours(rab, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    kandidati = []
    for kontura in konturi:
        pov = cv2.contourArea(kontura)
        if pov < povrsina * 0.12:
            continue
        peri = cv2.arcLength(kontura, True)
        pribl = cv2.approxPolyDP(kontura, 0.02 * peri, True)
        if len(pribl)!=4:
            continue
        x, y, bw, bh = cv2.boundingRect(pribl)
        kandidati.append((pov, pribl, (x, y, x + bw, y + bh)))
    kandidati.sort(key=lambda k: k[0], reverse=True)
    if not kandidati:
        return [img]
    if kandidati[0][0] > povrsina * 0.92:
        return [img]
    if len(kandidati) >= 2 and _preklop(kandidati[0][2], kandidati[1][2]) > 0.35:
        return [img]
    izvleceni = []
    for _, pribl, _ in kandidati[:2]:
        list_img = _izvleci_list(arr, pribl)
        if list_img is not None:
            izvleceni.append(list_img)
    return izvleceni or [img]

def _procitaj(img) -> tuple[str, float]:
    data = pytesseract.image_to_data(img,lang=settings.ocr_lang,output_type=pytesseract.Output.DICT,)
    linii: dict[tuple, list[tuple[str, float]]] = {}
    for i, zbor in enumerate(data["text"]):
        oc = data["conf"][i]
        try:
            ocena = float(oc)
        except (TypeError, ValueError):
            continue
        if not zbor.strip() or ocena < 0:
            continue
        kluc = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        linii.setdefault(kluc, []).append((zbor, ocena))
    redovi = []
    oceni = []
    for kluc in sorted(linii):
        redovi.append(" ".join(z for z, _ in linii[kluc]))
        oceni.extend(oc for _, oc in linii[kluc])
    tekst = "\n".join(redovi)
    doverba = sum(oceni) / len(oceni) if oceni else 0.0
    return tekst, doverba

def ocr_slika(img) -> tuple[str, float]:
    if settings.ocr_auto_rotate:
        img = _auto_rotate(img)
    listovi = _listovi(img) if settings.ocr_split_pages else [img]
    delovi = []
    doverbi = []
    for eden in listovi:
        if settings.ocr_preprocess:
            eden = _preprocess(eden)
        tekst, doverba = _procitaj(eden)
        if tekst.strip():
            delovi.append(tekst)
            doverbi.append(doverba)
    if not delovi:
        return "", 0.0
    return "\n\n".join(delovi), sum(doverbi) / len(doverbi)

def ocr_page(page) -> tuple[str, float]:
    try:
        pix = page.get_pixmap(dpi=settings.ocr_dpi)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        return ocr_slika(img)
    except Exception as greska:
        logger.warning("OCR propadna, ne e izvlecen tekst (%s)", greska)
        return "", 0.0
    
def ocr_bytes(podatoci: bytes) -> tuple[str, float]:
    try:

        img = Image.open(io.BytesIO(podatoci))
        img.load()
        return ocr_slika(img.convert("RGB"))
    except Exception as greska:
        logger.warning("OCR propadna, ne e izvlecen tekst (%s)", greska)
        return "", 0.0
def zabelezi_neuspeh(name: str, page_no: int, doverba: float) -> None:
    logger.warning("Necitlivna stranica %d vo'%s' (doverba %.0f) — potrebna e racna proverka",page_no,name,doverba,)
    try:
        with open(settings.ocr_failed_log, "a", encoding="utf-8") as f:
            f.write(f"{name}\tстр.{page_no}\tdoverba={doverba:.0f}\n")
    except Exception:
        pass