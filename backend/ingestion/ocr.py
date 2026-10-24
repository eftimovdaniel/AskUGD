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
    agol = cv2.minAreaRect(coords)[-1] #najmal pravoagolnik okolu tekstot, negoviot agol e kosinata na stranicata
    if agol < 0:    #normaliziranje vo mal agol okolu 0 stepeni 
        agol = -(90 + agol) if agol < -45 else -agol
    else:
        agol = -agol if agol < 45 else 90 - agol
    if abs(agol) < 0.4 or abs(agol) > 12: #premal agol ne go ispravuvame, se uci kako sto e predvideno, a pregolem se smeta za nekoj greska 
        return arr
    h, w = arr.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), agol, 1.0)
    return cv2.warpAffine(arr, M, (w, h), flags=cv2.INTER_CUBIC, borderValue=255) #prazninite posle rotacijata se poblat so bela pozadina

#podgotovka na slikata, dva cekori vo try blok za da ne si poprecuvaat eden na drug pri greska
def _preprocess(img):
    try:
        arr = np.array(img.convert("L")) #L ni gi pretstavuva sivite tonovi
        arr = cv2.fastNlMeansDenoising(arr, None, 10, 7, 21)
    except Exception as greska:
        logger.debug("Preprocess preskoknat: %s", greska)
        return img
    try:
        arr = _ispravi_agol(arr)
    except Exception as greska:
        logger.debug("Ispravuvanjeto na agolot e preskoknato: %s", greska)
    return Image.fromarray(arr)

# gi podreduva 4te teminja na listot 
def _redosled_tocki(tocki):
    tocki = tocki.reshape(4,2).astype("float32")
    zbir = tocki.sum(axis=1)    #x+y
    razlika = np.diff(tocki, axis=1).reshape(4) #y-x
                    # gorena leva               # gorna desna              #dolna desna             #dolna leva
    return np.array([ tocki[np.argmin(zbir)], tocki[np.argmin(razlika)], tocki[np.argmax(zbir)], tocki[np.argmax(razlika)],], dtype="float32")

#go seci listot od slikata i go isprava, kako da e fotografiran so telefon, kamera
def _izvleci_list(arr, tocki):
    red = _redosled_tocki(tocki)
    (tl,tr,br,bl) = red
    # sirina i visina na noviot list = podolgata od dvete sprotivni strani
    sirina = int(max(np.linalg.norm(br - bl), np.linalg.norm(tr - tl))) 
    visina = int(max(np.linalg.norm(tr - br), np.linalg.norm(tl - bl)))
    if sirina < 40 or visina < 40:  #premal regionot ne e list, najverojatno nekoj drug format 
        return None
    cel = np.array([[0, 0],[sirina - 1, 0],[sirina - 1, visina - 1], [0, visina - 1],], dtype="float32")    #celnite teminja: ispraven pravoagolnik so istite dimenzii
    M = cv2.getPerspectiveTransform(red, cel)
    izvlecen = cv2.warpPerspective(arr, M, (sirina, visina), borderValue=255)
    return Image.fromarray(izvlecen)

#kolku dva provoagolnika se preklopuvaat eden so drug, vraka vrednost od 0 do 1 
def _preklop(a,b) -> float:
    x1 = max(a[0], b[0])
    y1 = max(a[1], b[1])
    x2 = min(a[2], b[2])
    y2 = min(a[3], b[3])
    if x2 <= x1 or y2 <= y1:
        return 0.0  #dokolku ne se dopiraat
    presek = (x2-x1) * (y2-y1)
    pomala = min((a[2]-a[0]) * (a[3]-a[1]),(b[2]-b[0]) * (b[3]-b[1]),)
    return presek/pomala if pomala else 0.0

# bara listovi hartija na slikaata, ako najde 1 ili 2 gi vraka posebno, inaku se vraka celata slika
def _listovi(img):
    arr = np.array(img.convert("L"))
    h, w = arr.shape[:2]
    povrsina = h * w
    zamaten = cv2.GaussianBlur(arr,(5,5),0)
    rab = cv2.Canny(zamaten, 50, 150)
    rab = cv2.dilate(rab, np.ones((5, 5), np.uint8), iterations=1)
    konturi, _ =cv2.findContours(rab, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)   #samo nadvoresnite konturi, vnatresnite ne ni trebaat 
    kandidati = []
    for kontura in konturi:
        pov = cv2.contourArea(kontura)
        if pov < povrsina * 0.12:   # premalo za da bide list, pomalku od 12% od slikata 
            continue
        peri = cv2.arcLength(kontura, True)
        pribl = cv2.approxPolyDP(kontura, 0.02 * peri, True)
        if len(pribl)!=4:
            continue
        x, y, bw, bh = cv2.boundingRect(pribl)
        kandidati.append((pov, pribl, (x, y, x + bw, y + bh)))
    kandidati.sort(key=lambda k: k[0], reverse=True)    #najgolemiot kandidat
    if not kandidati: #ne e pronajden list -> ja koristi celata slika
        return [img]
    if kandidati[0][0] > povrsina * 0.92:   #listot ja zafaka skoro celata slika -> se zema za cist sken, nema sto da se seci
        return [img]
    if len(kandidati) >= 2 and _preklop(kandidati[0][2], kandidati[1][2]) > 0.35: #dvata najgolemi se preklopuvaat mnogu -> verojatno e isti list 
        return [img]
    izvleceni = []  # gi zemame delovite sto najmnogu odgovarat
    for _, pribl, _ in kandidati[:2]:
        list_img = _izvleci_list(arr, pribl)
        if list_img is not None:
            izvleceni.append(list_img)
    return izvleceni or [img]

#go cita tekstot so Tesseract i vraka tekst, prosecna doverba
#zborovite gi grupira po linii za da se zacuva redoslednot 
def _procitaj(img) -> tuple[str, float]:
    data = pytesseract.image_to_data(img,lang=settings.ocr_lang,output_type=pytesseract.Output.DICT,)
    #kluc (blok, paragrafi i linii) - lista od zborovi, doverba
    linii: dict[tuple, list[tuple[str, float]]] = {}
    for i, zbor in enumerate(data["text"]):
        oc = data["conf"][i]
        try:
            ocena = float(oc)
        except (TypeError, ValueError):
            continue
        if not zbor.strip() or ocena < 0:   #prani zborovi i doverba -1 se preskoknuvaat
            continue
        kluc = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        linii.setdefault(kluc, []).append((zbor, ocena))
    # sortiranjeto po klic gi dava liniite po redoslednot na citanje
    redovi = []
    oceni = []
    for kluc in sorted(linii):
        redovi.append(" ".join(z for z, _ in linii[kluc]))
        oceni.extend(oc for _, oc in linii[kluc])
    tekst = "\n".join(redovi)
    doverba = sum(oceni) / len(oceni) if oceni else 0.0
    return tekst, doverba

#glavna funkcija, za tekot na obrabotka na nekoja slika
#rotacija - delenje na listovi - predorabotka - citanje 
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
        if tekst.strip():   #listovi bez tekst ne vleguvaat ni vo rezultatot ni vo doverbata 
            delovi.append(tekst)
            doverbi.append(doverba)
    if not delovi:
        return "", 0.0
    return "\n\n".join(delovi), sum(doverbi) / len(doverbi) #listovite se odvoeni so prazen red, doverbata e prosek od site listovi

#OCR na stranicata od PDF: ja renderira vo slikata i ja cita, ne frla greska i pri neuspeh vraka prazen tekst 
def ocr_page(page) -> tuple[str, float]:
    try:
        pix = page.get_pixmap(dpi=settings.ocr_dpi)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        return ocr_slika(img)
    except Exception as greska:
        logger.warning("OCR propadna, ne e izvlecen tekst (%s)", greska)
        return "", 0.0

#OCR na slikata dobiena kako bajti
def ocr_bytes(podatoci: bytes) -> tuple[str, float]:
    try:

        img = Image.open(io.BytesIO(podatoci))
        img.load()  #ja cita slikata vednas, za greskata da se fati tuka
        return ocr_slika(img.convert("RGB"))
    except Exception as greska:
        logger.warning("OCR propadna, ne e izvlecen tekst (%s)", greska)
        return "", 0.0

#Zapisuva stranica so nivka doverba vo log datotekata za da se racno proverat od administratorot, toj sto ke e zadolzen
def zabelezi_neuspeh(name: str, page_no: int, doverba: float) -> None:
    logger.warning("Necitlivna stranica %d vo'%s' (doverba %.0f) — potrebna e racna proverka",page_no,name,doverba,)
    try:
        with open(settings.ocr_failed_log, "a", encoding="utf-8") as f:
            f.write(f"{name}\tстр.{page_no}\tdoverba={doverba:.0f}\n")
    except Exception:
        pass    #neuspehot npri obrabotka ne smee da ja prekine obrabotkata na drugite sliki