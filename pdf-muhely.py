#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PDF Műhely – egyesített offline eszköztár.
Fülek: Arckép elhelyezés | Összefűzés | Összeállító | Raszterizálás | Iktató |
       Áttekintő
Függőség: pymupdf (a tkinter a Python része). Semmilyen hálózati műveletet nem végez.

Öntesztek GUI nélkül:  python pdf-muhely.py --test
"""

import os
import re
import tempfile
import csv
import sys
import hashlib
import json
import math
import queue
import shutil
import ctypes
import threading
import subprocess
import locale
import inspect
import copy
import datetime
import traceback
import subprocess
import unicodedata
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog, colorchooser
from tkinter import font as tkfont
from dataclasses import dataclass, field, asdict, replace as dataclasses_replace

import pymupdf

IMG_EXT = (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp")
DEF_W_RATIO = 0.22          # a kép alapértelmezett szélessége a lap szélességéhez képest
DEF_H_RATIO = 0.25          # ...magassága a lap magasságához képest


# ────────────────────────── közös segédfüggvények ──────────────────────────
def script_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def tkimg(pix, fmt="png") -> tk.PhotoImage:
    """Pixmap -> tk.PhotoImage. A formátumot expliciten megadjuk, különben Tk PNG-t feltételez."""
    if fmt == "ppm":
        if pix.alpha:
            pix = pymupdf.Pixmap(pix, 0)
        return tk.PhotoImage(data=pix.tobytes("ppm"), format="ppm")
    return tk.PhotoImage(data=pix.tobytes("png"), format="png")


def natural_key(name: str):
    """fajl2.pdf < fajl10.pdf"""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def safe_stem(name: str) -> str:
    """Windowson tiltott karakterek cseréje."""
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).rstrip(" .")
    return s or "dokumentum"


def list_files(folder: str, exts) -> list:
    try:
        return sorted((f for f in os.listdir(folder) if f.lower().endswith(exts)),
                      key=natural_key)
    except OSError:
        return []


def list_files_in(folder: str, exts, subdirs=()) -> list:
    """A mappa fájljai, utánuk az almappáié relatív úttal (01_Elokeszitett\\x.pdf) —
    a dolgozó mappájában az iratok a két alkönyvtárban élnek, nem a gyökerében."""
    out = list_files(folder, exts)
    for sd in subdirs:
        out += [os.path.join(sd, f) for f in list_files(os.path.join(folder, sd), exts)]
    return out


def open_checked(path: str):
    """PDF megnyitása jelszó-ellenőrzéssel."""
    doc = pymupdf.open(path)
    if doc.needs_pass:
        doc.close()
        raise RuntimeError(f"{os.path.basename(path)} jelszóval védett.")
    return doc


# ── felületi paletta (kepek-pdf-terv.md 13.7) ───────────────────────────────
# Egy helyen minden szín: a ttk-téma, a vásznak és a mátrix is ebből él, így nem
# csúszhat szét a kétféle rajzolás (widget vs. canvas).
UI = {
    "bg":        "#f5f7fb",   # oldal háttér
    "card":      "#ffffff",   # panel, csempe, mátrix
    "line":      "#e0e6f0",   # vonalak, keretek
    "line_soft": "#eef2f8",
    "ink":       "#1b2430",   # szöveg
    "ink_soft":  "#616d80",   # másodlagos szöveg
    "accent":    "#2563eb",   # elsődleges művelet
    "accent_hi": "#1d4ed8",
    "accent_lo": "#1e40af",
    "accent_bg": "#e8efff",   # akcentus halvány háttér (kijelölés)
    "hover":     "#f1f5fd",
    "ok":        "#157347",
    "warn":      "#c62828",
    # A munkaterület (bélyegképek, előnézet) VILÁGOS: a sötét „fotós” háttér
    # szép, de egy egész napos irodai munkához fárasztó és kevésbé átlátható.
    "dark":      "#e9edf5",   # az előnézeti vászon („világítóasztal”)
    "head":      "#ffffff",   # fejlécsáv
    "head_hi":   "#f2f5fb",   # fejléc: kiemelt felület (mező)
    "head_ink":  "#1b2430",
    "head_mute": "#67748a",
    "shadow":    "#2a3b63",   # a lágy árnyék alapszíne (kis átlátszósággal)
    "shade1":    "#dde3ef",   # vászon-árnyék, világos háttéren
    "shade2":    "#e7ecf5",
}
# Ráhagyás a GDI-skálázott (DPI-unaware) szövegrajzolásnak: 150%-nál a GDI kb.
# feleannyival szélesebb glifákat rajzol, mint amennyit a Tk logikai pixelben
# kimért — a fix méretű feliratok vége enélkül levágódik.
DPI_SLACK = 14
SB_THICK = 12             # a görgetősáv vastagsága (képpont) — a téma ennyit kér
FONT_UI = ("Segoe UI", 10)
FONT_SB = ("Segoe UI Semibold", 10)
FONT_SM = ("Segoe UI", 9)
FONT_H1 = ("Segoe UI Semibold", 14)

CLEAN_META = {"producer": "pdf-muhely", "creator": "", "title": "",
              "author": "", "subject": "", "keywords": ""}

# ── bélyeg: dolgozó és doktípus a PDF metaadatában (kepek-pdf-terv.md 13.5) ──
# A /Keywords mezőbe írjuk, mert az átnevezést túléli, és a tömörítést is (mért
# tulajdonság, 12.7). A fájlnév marad az ELSŐDLEGES igazság: a bélyeg csak ott
# szólal meg, ahol a név nem ismerhető fel.
STAMP_KEY = "pdf-muhely"
STAMP_FIELDS = (STAMP_KEY, "dolgozo", "tipus", "szabaly", "hely", "datum")


def stamp_keywords(who: str, doc_type: str, rule_id: str = "", sub: str = "",
                   old: str = "") -> str:
    """A bélyeg szövege. A más eredetű kulcsszavak megmaradnak — a DocGen-bélyeg
    is (azt a producer és a keywords együtt hordozza, has_docgen_stamp)."""
    def clean(v):
        return re.sub(r"[;=]", " ", str(v or "")).strip()
    parts = [f"{STAMP_KEY}=1", f"dolgozo={clean(who)}", f"tipus={clean(doc_type)}"]
    if rule_id:
        parts.append(f"szabaly={clean(rule_id)}")
    if sub:
        parts.append(f"hely={clean(sub)}")
    parts.append("datum=" + datetime.date.today().isoformat())
    keep = [t.strip() for t in (old or "").split(";")
            if t.strip() and t.split("=")[0].strip() not in STAMP_FIELDS]
    return ";".join(keep + parts)


def parse_stamp(keywords: str) -> dict:
    """A kulcsszavakból a bélyeg; üres dict, ha nincs benne."""
    d = {}
    for t in (keywords or "").split(";"):
        k, sep, v = t.partition("=")
        if sep:
            d[k.strip()] = v.strip()
    return d if STAMP_KEY in d else {}


def read_stamp(path: str) -> dict:
    """Egy PDF bélyege (dolgozo, tipus, szabaly, hely, datum); {} ha nincs."""
    try:
        d = pymupdf.open(path)
    except Exception:
        return {}
    try:
        return parse_stamp((d.metadata or {}).get("keywords") or "")
    finally:
        d.close()


def set_stamp(doc, who: str, doc_type: str, rule_id: str = "", sub: str = ""):
    """Bélyeg egy megnyitott dokumentumra, mentés előtt."""
    m = dict(doc.metadata or {})
    m["keywords"] = stamp_keywords(who, doc_type, rule_id, sub, m.get("keywords"))
    doc.set_metadata(m)


def stamp_pdf_file(path: str, who: str, doc_type: str, rule_id: str = "",
                   sub: str = "") -> bool:
    """Bélyeg egy már kiírt PDF-re, NÖVEKMÉNYES mentéssel: a fájl eddigi bájtjai
    érintetlenek, a bélyeg függelékként kerül rá. -> sikerült-e (az oldalszámmal
    és a visszaolvasott bélyeggel igazolva). Hiba esetén False, a hívó dönt —
    a bélyeg kényelmi adat, nem iktatási feltétel."""
    try:
        d = pymupdf.open(path)
        try:
            pages = d.page_count
            set_stamp(d, who, doc_type, rule_id, sub)
            d.save(path, incremental=True, encryption=pymupdf.PDF_ENCRYPT_KEEP)
        finally:
            d.close()
        d = pymupdf.open(path)
        try:
            ok = (d.page_count == pages and
                  parse_stamp((d.metadata or {}).get("keywords") or "").get("dolgozo")
                  == re.sub(r"[;=]", " ", who or "").strip())
        finally:
            d.close()
        return ok
    except Exception:
        return False

VERZIO_FILE = "verzio.json"          # a tools/verzio.py írja minden commitnál


def app_version() -> str:
    """„v1.4 (2026-09-25)” — a szkript melletti verzio.json-ból; git nem kell hozzá."""
    try:
        with open(os.path.join(script_dir(), VERZIO_FILE), encoding="utf-8") as f:
            v = json.load(f)
        return f"v{v['verzio']} ({v['datum']})"
    except Exception:
        return "ismeretlen verzió"


def missing_features() -> list:
    """A PyMuPDF azon képességei, amelyek ezen a gépen hiányoznak (régi verzió)."""
    out = []
    if not hasattr(pymupdf.Document, "rewrite_images"):
        out.append("PDF-tömörítés 5 MB alá (Document.rewrite_images)")
    if "jpg_quality" not in inspect.signature(pymupdf.Pixmap.tobytes).parameters:
        out.append("Összeállító (képoldalak), JPEG-minőség (Pixmap.tobytes jpg_quality)")
    return out

# ponytail: tizedes 5 MB (5 000 000 bájt) — szigorúbb az 5 MiB-nál, így a portál
# bármelyiket érti is alatta, átmegy. Ha kiderül, hogy MiB, lazítható 5 * 1024 * 1024-re.
UPLOAD_LIMIT = 5_000_000
SHRINK_STEPS = ((200, 75), (150, 65), (120, 55), (100, 45))   # (DPI, JPEG-minőség)


def mb(n: int) -> str:
    return f"{n / 1_000_000:.1f} MB"


def size_note(path: str) -> str:
    """Üres, ha a fájl feltölthető méretű; különben figyelmeztetés."""
    n = os.path.getsize(path)
    if n <= UPLOAD_LIMIT:
        return ""
    return f"⚠ {mb(n)} — a feltöltési korlát {mb(UPLOAD_LIMIT)}, tömöríteni kell (Iktatóban iktatáskor)"


def shrink_steps(data: bytes, limit: int = UPLOAD_LIMIT):
    """A beágyazott képek újratömörítése egyre erősebb lépcsőkön, amíg a PDF
    a korlát alá nem fér. A szöveg és a vektoros tartalom érintetlen marad.
    Generátor: minden lépcső ELŐTT (DPI, minőség)-et ad — így a felület a
    lépcsők között frissülhet. A végeredmény a StopIteration értéke:
    (PDF-bájtok, (DPI, minőség) | None) — None: így sem fért be, ilyenkor a
    legkisebb változat jön vissza."""
    if not hasattr(pymupdf.Document, "rewrite_images"):
        raise RuntimeError("A tömörítéshez újabb PyMuPDF kell (rewrite_images).")
    best = data
    for dpi, q in SHRINK_STEPS:
        yield dpi, q
        doc = pymupdf.open("pdf", data)
        try:
            doc.rewrite_images(dpi_threshold=dpi + 10, dpi_target=dpi, quality=q)
            out = doc.tobytes(garbage=4, deflate=True)
        finally:
            doc.close()
        if len(out) < len(best):
            best = out
        if len(out) <= limit:
            return out, (dpi, q)
    return best, None


def shrink_pdf(data: bytes, limit: int = UPLOAD_LIMIT):
    """shrink_steps egyben, felület nélkül (öntesztekhez)."""
    g = shrink_steps(data, limit)
    try:
        while True:
            next(g)
    except StopIteration as s:
        return s.value


def shrink_cli(argv) -> int:
    """`--tomorit <be.pdf> <ki.pdf> [korlát]` — ez fut a KÜLÖN FOLYAMATBAN.
    A lépcsőket a kimenetre írja, hogy a felület vissza tudja olvasni."""
    try:
        be, ki = argv[0], argv[1]
        limit = int(argv[2]) if len(argv) > 2 else UPLOAD_LIMIT
        with open(be, "rb") as f:
            data = f.read()
        g = shrink_steps(data, limit)
        try:
            while True:
                dpi, q = next(g)
                print(f"LEPCSO {dpi} {q}", flush=True)
        except StopIteration as st:
            out, lepcso = st.value
        with open(ki, "wb") as f:
            f.write(out)
        print(f"KESZ {lepcso[0]} {lepcso[1]}" if lepcso else "KESZ - -", flush=True)
        return 0
    except Exception as e:
        print(f"HIBA {type(e).__name__}: {e}", flush=True)
        return 1


def shrink_process(widget, data: bytes, on_done, on_step=None):
    """Ugyanaz, mint a shrink_later, de KÜLÖN FOLYAMATBAN (13.10).

    Miért nem szál: a PyMuPDF a tömörítés alatt végig fogja a GIL-t — mérve a
    főszál 4,5%-ot kap, tehát a felület szálakkal MÉG jobban befagyna. Külön
    folyamattal 92%-ot kap. Ha a folyamat nem indítható (pl. furcsa környezet),
    visszaesünk a régi, after()-láncos útra, hogy a funkció ne vesszen el."""
    try:
        be = tempfile.mktemp(suffix=".be.pdf")
        ki = tempfile.mktemp(suffix=".ki.pdf")
        with open(be, "wb") as f:
            f.write(data)
        proc = subprocess.Popen(
            [sys.executable, os.path.abspath(__file__), "--tomorit", be, ki,
             str(UPLOAD_LIMIT)],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:
        return shrink_later(widget, data, on_done, on_step)

    def takarit():
        for f in (be, ki):
            try:
                os.remove(f)
            except OSError:
                pass

    # A gyermek a lépcsőket soronként írja ki; egy olvasószál továbbítja őket.
    # Szálat ITT szabad: a csővezeték olvasása I/O, ott a GIL nincs lefogva.
    sorok = queue.Queue()

    def olvas():
        try:
            for sor in proc.stdout:
                sorok.put(sor.strip())
        except Exception:
            pass
        finally:
            sorok.put(None)

    threading.Thread(target=olvas, daemon=True).start()
    allapot = {"lepcso": None, "err": None, "vege": False}

    def tick():
        while True:
            try:
                sor = sorok.get_nowait()
            except queue.Empty:
                break
            if sor is None:
                allapot["vege"] = True
            elif sor.startswith("LEPCSO") and on_step:
                r = sor.split()
                on_step(int(r[1]), int(r[2]))
            elif sor.startswith("KESZ"):
                r = sor.split()
                allapot["lepcso"] = None if r[1] == "-" else (int(r[1]), int(r[2]))
            elif sor.startswith("HIBA"):
                allapot["err"] = RuntimeError(sor[5:])
        if not (allapot["vege"] and proc.poll() is not None):
            widget.after(80, tick)
            return
        out, err = None, allapot["err"]
        try:
            if err is None:
                with open(ki, "rb") as f:
                    out = f.read()
        except OSError as e:
            err = e
        takarit()
        on_done(out, allapot["lepcso"], err)

    widget.after(50, tick)


def shrink_later(widget, data: bytes, on_done, on_step=None):
    """shrink_steps after()-láncban: lépcsőnként egy kör, közben a felület él.
    on_step(dpi, q) a lépcső előtt; on_done(bájtok, lépcső | None, hiba | None).
    ponytail: egy lépcsőn belül (nagy fájlnál 1–3 s) a felület még áll — teljesen
    csak külön folyamatban lehetne, az a PyMuPDF miatt jóval bonyolultabb."""
    g = shrink_steps(data)

    def tick():
        try:
            dpi, q = next(g)
        except StopIteration as s:
            on_done(*s.value, None)
            return
        except Exception as e:
            on_done(None, None, e)
            return
        if on_step:
            on_step(dpi, q)
        widget.after(1, tick)          # a lépcső munkája a KÖVETKEZŐ next()-ben fut

    widget.after(1, tick)


def write_pdf_verified(data: bytes, dst: str, pages: int, stamp=None):
    """PDF-bájtok kiírása .part néven, oldalszám-ellenőrzés, majd atomi átnevezés.
    `stamp`: (dolgozó, doktípus, szabály-id, alkönyvtár) — ha a bélyegzés nem
    sikerül, a tiszta bájtok mennek ki, az iktatás nem bukhat el tőle."""
    tmp = dst + ".part"
    try:
        with open(tmp, "wb") as f:
            f.write(data)
        if stamp and not stamp_pdf_file(tmp, *stamp):
            with open(tmp, "wb") as f:
                f.write(data)
        d = pymupdf.open(tmp)
        n = d.page_count
        d.close()
        if n != pages:
            raise IOError(f"A kiírt PDF oldalszáma eltér ({n} ≠ {pages}).")
        os.replace(tmp, dst)
    except Exception:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        raise


def rasterize_doc(doc, dpi: int, pages=None):
    """Új dokumentum, amelyben a megadott oldalak képpé égetve szerepelnek."""
    flat = pymupdf.open()
    for i in range(doc.page_count):
        src = doc[i]
        new = flat.new_page(width=src.rect.width, height=src.rect.height)
        if pages is None or i in pages:
            new.insert_image(src.rect, pixmap=src.get_pixmap(dpi=dpi, annots=True))
        else:
            new.show_pdf_page(src.rect, doc, i)
    flat.set_metadata(dict(CLEAN_META))
    return flat


def level_lut(brightness: int = 0, contrast: int = 0) -> bytes:
    """256 bájtos átalakító tábla a fényerőhöz és a kontraszthoz (-100..100).
    Táblával dolgozunk, mert a `bytes.translate()` C-sebességgel alkalmazza —
    pixelenkénti Python-ciklus egy 2000×3000-es fotón másodpercekig tartana."""
    br = max(-100, min(100, int(brightness)))
    ct = max(-100, min(100, int(contrast)))
    f = (100.0 + ct) / 100.0 if ct >= 0 else 100.0 / (100.0 - ct)
    off = br * 1.28
    return bytes(max(0, min(255, round((i - 128) * f + 128 + off))) for i in range(256))


def apply_levels(pix, lut: bytes):
    """Új pixmap a táblával átszámolt képpontokkal (alfa nélkül)."""
    if pix.alpha:
        pix = pymupdf.Pixmap(pix, 0)
    cs = pymupdf.csGRAY if pix.n == 1 else pymupdf.csRGB
    return pymupdf.Pixmap(cs, pix.width, pix.height,
                          bytes(pix.samples).translate(lut), False)


def image_px_scale(doc) -> float:
    """px/pt a beágyazott kép valódi felbontásából. A get_pixmap() alap 72 DPI-je
    a szkennelt fotó felbontásának egy részét eldobná."""
    try:
        imgs = doc[0].get_images()
        if imgs:
            w = doc.extract_image(imgs[0][0])["width"]
            return max(1.0, w / doc[0].mediabox.width)
    except Exception:
        pass
    return 96.0 / 72.0                     # a convert_to_pdf szokásos aránya


def open_image_pdf(path, crop=None, levels=None):
    """A kép egylapos PDF-ként (így helyezhető, forgatható, méretezhető).
    `crop`: a megtartandó rész a lap koordinátáiban — elég a cropbox szűkítése,
    mert a lap rect-je ezzel együtt szűkül, és a show_pdf_page is csak ezt teszi
    le. A kép fájlja így soha nem változik, a vágás visszavonható.
    `levels`: (fényerő, kontraszt) — ez viszont ÚJRAKÓDOLJA a képet (a képpontokat
    kell átszámolni), ezért csak akkor fut, ha tényleg állítottak rajta."""
    src = pymupdf.open(path)
    try:
        doc = pymupdf.open("pdf", src.convert_to_pdf())
    finally:
        src.close()
    if crop:
        r = pymupdf.Rect(crop) & doc[0].rect          # a lapon kívüli részt levágja
        if r.width > 1 and r.height > 1:
            doc[0].set_cropbox(r)
    if not levels or not any(levels):
        return doc
    try:
        z = image_px_scale(doc)                       # natív felbontáson számolunk
        pix = doc[0].get_pixmap(matrix=pymupdf.Matrix(z, z))
        jpeg = apply_levels(pix, level_lut(*levels)).tobytes("jpeg", jpg_quality=92)
        img = pymupdf.open("jpg", jpeg)
        try:
            out = pymupdf.open("pdf", img.convert_to_pdf())
        finally:
            img.close()
    except Exception:
        return doc                                    # szintezés nélkül, de működik
    doc.close()
    return out


# A görgetéssel saját dolga van (lista, rács, nagyítás): ezeken a vásznon átívelő
# panelgörgetés nem lép közbe.
_NO_WHEEL = ("Listbox", "Treeview", "Text", "Canvas", "TCombobox", "Spinbox", "TSpinbox")

# ── nagyított kijelző: a feliratok vége ne vágódjon le (kepek-pdf-terv.md 19.2) ──
# Az app GDI-skálázással fut (DPI-unaware, lásd a __main__-t): a Tk a szöveget a
# logikai (96 DPI-s) betűvel MÉRI, a Windows viszont a valódi felbontás betűjével
# RAJZOLJA, ami 125–200%-on néhány százalékkal szélesebb. A rádiógomb, a jelölő és a
# címke pontosan a kimért szélességet kapja, ezért a felirat vége lecsúszik
# (bejelentve: „Szöveg és X” — az X fele, „Kitakarás” — az s fele látszott).
TEXT_SLACK = 0.08         # ennyivel szélesebb lehet a rajzolt szöveg a kimértnél
# A nagyítás az App indulásakor kerül ide (screen_scale), a fülek építése ELŐTT: a
# fix szélességű oldalpanelek ennyivel szélesebbek, különben a ráhagyással
# megnőtt sorok (pl. a négy igazítás-rádiógomb) a panel szélén csúsznának le.
_SCALE = [1.0]


def screen_scale() -> float:
    """A Windows-nagyítás (1.0 = 100%). A folyamat DPI-unaware, ezért a saját DPI-je
    mindig 96: a valódit a szálat egy pillanatra DPI-tudatosra állítva kérdezzük le.
    Próbához és teszthez felülírható: PDF_MUHELY_SKALA=1.5."""
    env = os.environ.get("PDF_MUHELY_SKALA", "").replace(",", ".").strip()
    if env:
        try:
            return max(1.0, float(env))
        except ValueError:
            pass
    try:
        u = ctypes.windll.user32
        u.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
        u.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        old = u.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))   # per-monitor v2
        try:
            dpi = u.GetDpiForSystem()
        finally:
            if old:
                u.SetThreadDpiAwarenessContext(ctypes.c_void_p(old))
        return max(1.0, dpi / 96.0)
    except Exception:
        return 1.0


class TextSlack:
    """Arányos jobb oldali ráhagyás a feliratoknak nagyított kijelzőn. Csak azok a
    címkék, jelölők és rádiógombok kapják, amelyeket a geometriakezelő NEM feszít
    ki — a kifeszítettnek van helye, ott a ráhagyás csak a sort szélesítené.
    Osztályszintű <Configure>-kötés: a később (dialógusban, frissítéskor) készülő
    widgetekre is hat, és a textvariable-ös címke új szövegére is újraszámol.
    100%-on ki sem kapcsol be — ott a mért és a rajzolt szélesség egyezik."""

    CLASSES = ("TLabel", "TCheckbutton", "TRadiobutton")

    def __init__(self, root, scale: float):
        self.root, self.on = root, scale > 1.0
        self.st = ttk.Style(root)
        self.fonts = {}
        self.mine = {}                    # widget -> az általunk adott padding
        if self.on:
            for cls in self.CLASSES:
                root.bind_class(cls, "<Configure>", self._fix, add="+")
            # A keretek címe (LabelFrame) külön elem, widgetenként nem párnázható:
            # a stílusa kap egy padding-elemet és fix ráhagyást.
            self.st.layout("TLabelframe.Label", [("Label.padding", {
                "sticky": "nswe", "children": [("Label.text", {"sticky": "nswe"})]})])
            self.st.configure("TLabelframe.Label", padding=(0, 0, 16, 0))

    def _fix(self, e):
        try:
            self.apply(e.widget)
        except (tk.TclError, AttributeError):
            pass

    def apply(self, w):
        key = str(w)
        if str(w.cget("padding")) and key not in self.mine:
            return                        # a kód adott neki paddinget (fejléc)
        want = None
        if not self._stretched(w):
            text = self._text(w)
            if text.strip():
                l, t, r, b = self._style_pad(w)
                want = (l, t, r + math.ceil(self._measure(w, text) * TEXT_SLACK) + 2, b)
        if want is None:
            if key in self.mine:
                del self.mine[key]
                w.configure(padding="")   # vissza a stílus paddingjére
        elif self.mine.get(key) != want:
            self.mine[key] = want
            w.configure(padding=want)

    @staticmethod
    def _stretched(w) -> bool:
        mgr = w.winfo_manager()
        if mgr == "pack":
            return str(w.pack_info().get("fill")) in ("x", "both")
        if mgr == "grid":
            s = str(w.grid_info().get("sticky", ""))
            return "e" in s and "w" in s
        return False

    @staticmethod
    def _text(w) -> str:
        tv = str(w.cget("textvariable"))
        if tv:
            try:
                return str(w.getvar(tv))
            except tk.TclError:
                return ""
        return str(w.cget("text"))

    def _measure(self, w, text) -> int:
        try:
            spec = str(w.cget("font"))    # a jelölőnek és a rádiógombnak nincs ilyen
        except tk.TclError:
            spec = ""
        spec = (spec or self.st.lookup(str(w.cget("style")) or w.winfo_class(), "font")
                or self.st.lookup(".", "font") or "TkDefaultFont")
        f = self.fonts.get(spec)
        if f is None:
            f = self.fonts[spec] = tkfont.Font(root=self.root, font=spec)
        width = max(f.measure(ln) for ln in text.split("\n"))
        try:
            wl = int(float(str(w.cget("wraplength")) or 0))
        except (tk.TclError, ValueError):
            wl = 0
        return min(width, wl) if wl > 0 else width

    def _style_pad(self, w) -> tuple:
        """A stílus paddingje négy elemre bontva (a Tk szabálya szerint: a hiányzó
        alsó = felső, jobb = bal, felső = bal)."""
        p = self.st.lookup(str(w.cget("style")) or w.winfo_class(), "padding")
        try:
            v = [int(float(str(x))) for x in
                 (p if isinstance(p, (tuple, list)) else str(p).split())]
        except ValueError:
            v = []
        v = v[:4] or [0]
        if len(v) == 1:
            v = v * 4
        elif len(v) == 2:
            v = [v[0], v[1], v[0], v[1]]
        elif len(v) == 3:
            v = [v[0], v[1], v[2], v[1]]
        return tuple(v)


def scroll_panel(parent, width: int = 340, side: str = "left", padx=(8, 0)):
    """Fix szélességű oldalpanel, amely SZÜKSÉG ESETÉN görget.

    Visszatér: ``(shell, inner)``. A tartalom az ``inner``-be megy; a ``shell``
    gridelt, így fix alsó sáv az 1. sorba tehető (Szerkesztés: „Alkalmaz”).
    Alacsony ablakban a panel alja eddig egyszerűen levágódott — az Arcképnél a
    Mentés és az Iktatás gomb MINDEN ablakméretben kint volt (990 px kellett,
    658 jutott; mérve). A görgetősáv csak akkor jelenik meg, ha tényleg kell.
    """
    if _SCALE[0] > 1.0:                       # nagyított kijelzőn: TextSlack
        width = round(width * (1 + TEXT_SLACK))
    shell = ttk.Frame(parent, width=width + 22)
    shell.pack(side=side, fill="y", padx=padx, pady=8)
    shell.pack_propagate(False)
    c = tk.Canvas(shell, width=width, highlightthickness=0, bd=0,
                  background=ttk.Style().lookup("TFrame", "background"))
    sb = ttk.Scrollbar(shell, orient="vertical", command=c.yview)
    c.configure(yscrollcommand=sb.set)
    # Griddel, nem packkel: a kiterjedő vászon elvenné a görgetősáv helyét, és az
    # sosem jelenne meg (mérve).
    shell.rowconfigure(0, weight=1)
    shell.columnconfigure(0, weight=1)
    shell.columnconfigure(1, minsize=16)      # a görgetősáv ne nyomódjon össze
    c.grid(row=0, column=0, sticky="nsew")
    sb.grid(row=0, column=1, sticky="nsew")   # a téma sávja 1 px-et kér: ki kell feszíteni
    sb.grid_remove()
    inner = ttk.Frame(c)
    win = c.create_window(0, 0, anchor="nw", window=inner, width=width)
    bound = set()

    def wheel(e):
        c.yview_scroll(-1 if e.delta > 0 else 1, "units")
        return "break"

    def sync(_e=None):
        req, have = inner.winfo_reqheight(), c.winfo_height()
        # Ha van hely, a panel kifeszül: így az expand=True-s részek (Kimenet,
        # fájllisták) nagy ablakban is kitöltik az aljat, mint görgetés előtt.
        c.itemconfigure(win, height=max(req, have))
        c.configure(scrollregion=(0, 0, width, max(req, have)))
        if req > have:
            sb.grid()
        else:
            sb.grid_remove()
            c.yview_moveto(0)
        # A görgő a panel BÁRMELY pontján működjön: a Tk az esemény célwidgetjéhez
        # viszi, és az nem bugyborékol a szülőhöz — ezért widgetenként kötjük.
        # A tartalom építés közben nő, ezért itt (a <Configure>-ben), nem egyszer.
        stack = [inner]
        while stack:
            w = stack.pop()
            stack.extend(w.winfo_children())
            if w not in bound and w.winfo_class() not in _NO_WHEEL:
                bound.add(w)
                w.bind("<MouseWheel>", wheel)

    inner.bind("<Configure>", sync)
    c.bind("<Configure>", sync)
    c.bind("<MouseWheel>", wheel)
    return shell, inner


class CropDialog(tk.Toplevel):
    """Minimális képszerkesztő: húzz téglalapot a megtartandó rész köré.
    Vágás és fényerő/kontraszt; forgatni az elhelyezésnél amúgy lehet."""

    MAX_PX = 760                       # a nagyobb oldal legfeljebb ennyi képpont

    def __init__(self, master, path, crop, on_crop, levels=None):
        super().__init__(master)
        self.title("Arckép körülvágása — " + os.path.basename(path))
        self.transient(master.winfo_toplevel())
        self.grab_set()
        self.on_crop = on_crop
        self.doc = open_image_pdf(path)                # mindig a teljes képből
        r = self.doc[0].rect
        self.z = min(self.MAX_PX / max(r.width, r.height), 4.0)
        pix = self.doc[0].get_pixmap(matrix=pymupdf.Matrix(self.z, self.z))
        self.img = tkimg(pix, "ppm")
        self.w, self.h = pix.width, pix.height
        self.msg = tk.StringVar(value="")
        self.box = None                                # (x0, y0, x1, y1) a vásznon
        self._from = None
        self.base_pix = pix                            # a szintezés nélküli előnézet
        self.br = tk.IntVar(value=levels[0] if levels else 0)
        self.ct = tk.IntVar(value=levels[1] if levels else 0)

        ttk.Label(self, text="Húzz téglalapot a megtartandó rész köré. "
                             "A kép fájlja nem változik.").pack(anchor="w", padx=10,
                                                                pady=(10, 4))
        self.canvas = tk.Canvas(self, width=self.w, height=self.h, bg=UI["dark"],
                                highlightthickness=0, cursor="crosshair")
        self.canvas.pack(padx=10)
        self.canvas.create_image(0, 0, anchor="nw", image=self.img, tags="img")
        self.canvas.bind("<ButtonPress-1>", lambda e: setattr(self, "_from", (e.x, e.y)))
        self.canvas.bind("<B1-Motion>", self._motion)
        self.canvas.bind("<ButtonRelease-1>", self._motion)
        ttk.Label(self, textvariable=self.msg).pack(anchor="w", padx=10, pady=4)

        lv = ttk.Frame(self)
        lv.pack(fill="x", padx=10)
        for i, (txt, var) in enumerate((("Fényerő", self.br), ("Kontraszt", self.ct))):
            ttk.Label(lv, text=txt).grid(row=i, column=0, sticky="w")
            ttk.Scale(lv, from_=-100, to=100, variable=var, length=240,
                      command=lambda _e: self._levels_changed()).grid(row=i, column=1,
                                                                      sticky="ew", padx=6)
            ttk.Label(lv, textvariable=var, width=5).grid(row=i, column=2, sticky="w")
        lv.columnconfigure(1, weight=1)
        ttk.Button(lv, text="Szintek alaphelyzetbe", command=self._levels_reset).grid(
            row=0, column=3, rowspan=2, padx=8)

        foot = ttk.Frame(self)
        foot.pack(fill="x", padx=10, pady=(0, 10))
        self.btn = ttk.Button(foot, text="Körülvág", command=self._apply, state="disabled")
        self.btn.pack(side="left")
        ttk.Button(foot, text="Teljes kép, alaphelyzet",
                   command=self._reset_all).pack(side="left", padx=6)
        ttk.Button(foot, text="Mégsem", command=self.destroy).pack(side="right")
        if crop:
            self.box = tuple(v * self.z for v in (crop.x0, crop.y0, crop.x1, crop.y1))
            self._draw()
        if levels and any(levels):
            self._levels_changed()
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Return>", lambda e: self._apply())

    # -- fényerő / kontraszt --
    def _levels(self):
        v = (int(self.br.get()), int(self.ct.get()))
        return v if any(v) else None

    def _levels_changed(self):
        """Élő előnézet: a tábla a KICSI (megjelenített) pixmapra fut, ezért
        azonnali — a natív felbontású átszámolás csak az alkalmazásnál kell."""
        lv = self._levels()
        pix = self.base_pix if lv is None else apply_levels(self.base_pix, level_lut(*lv))
        self.img = tkimg(pix, "ppm")
        self.canvas.delete("img")
        self.canvas.create_image(0, 0, anchor="nw", image=self.img, tags="img")
        self.canvas.tag_lower("img")
        if self.box is None:                   # vágás nélkül is lehet alkalmazni
            self.btn.configure(text="Alkalmaz",
                               state="normal" if lv else "disabled")

    def _levels_reset(self):
        self.br.set(0)
        self.ct.set(0)
        self._levels_changed()

    def _reset_all(self):
        self.on_crop(None, None)
        self.destroy()

    def destroy(self):
        if self.doc:
            self.doc.close()
            self.doc = None
        super().destroy()

    def _motion(self, e):
        if not self._from:
            return
        x0, y0 = self._from
        x, y = max(0, min(self.w, e.x)), max(0, min(self.h, e.y))
        self.box = (min(x0, x), min(y0, y), max(x0, x), max(y0, y))
        self._draw()

    def _draw(self):
        self.btn.configure(text="Körülvág")
        x0, y0, x1, y1 = self.box
        self.canvas.delete("box")
        self.canvas.create_rectangle(x0, y0, x1, y1, outline=COL_CROP, width=2, tags="box")
        w, h = (x1 - x0) / self.z, (y1 - y0) / self.z
        ok = w > 5 and h > 5
        self.msg.set(f"kijelölés: {w:.0f} × {h:.0f} pt "
                     f"({w / 72 * 25.4:.0f} × {h / 72 * 25.4:.0f} mm)"
                     if ok else "a kijelölés túl kicsi")
        self.btn.configure(state="normal" if ok else "disabled")

    def _apply(self):
        if not self.box:                      # csak szintezés, vágás nélkül
            if self._levels():
                self._done(None)
            return
        x0, y0, x1, y1 = (v / self.z for v in self.box)
        if x1 - x0 > 5 and y1 - y0 > 5:
            self._done(pymupdf.Rect(x0, y0, x1, y1))

    def _done(self, rect):
        self.on_crop(rect, self._levels())
        self.destroy()


class CheckList(ttk.Frame):
    """Jelölőnégyzetes lista: soronként egy művelet, „Mind” és „Egyiket se” gombbal.

    Treeview egy „☑/☐” oszloppal, nem sok ttk.Checkbutton egy görgetett vásznon:
    több száz sornál (150 dolgozó × több irat) az érezhetően lassú, a Treeview
    viszont virtualizál. Kattintás a soron vagy Szóköz vált.

    A hívó `fill(rows)`-zal tölt és `selected()`-del kérdez; a `count_var`
    szövegváltozó mindig a kijelöltek számát mutatja (ebből tiltható a gomb).
    """

    def __init__(self, master, headings, widths, height=14, on_change=None):
        super().__init__(master)
        self.on_change = on_change
        self._keys = {}            # iid -> a hívó kulcsa (a `keys` a Tk metódusa!)
        self.on = {}
        cols = ("_ck",) + tuple(f"c{i}" for i in range(len(headings)))
        self.tv = ttk.Treeview(self, columns=cols, show="headings", height=height,
                               selectmode="browse")
        self.tv.heading("_ck", text="✓")
        self.tv.column("_ck", width=34, stretch=False, anchor="center")
        for c, h, w in zip(cols[1:], headings, widths):
            self.tv.heading(c, text=h)
            self.tv.column(c, width=w, stretch=(w >= 240))
        sb = ttk.Scrollbar(self, orient="vertical", command=self.tv.yview)
        self.tv.configure(yscrollcommand=sb.set)
        self.tv.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tv.bind("<Button-1>", self._click)
        self.tv.bind("<space>", lambda e: (self._toggle(self.tv.focus()), "break")[1])
        # A „tipp” sorok halványan: a biztos és a bizonytalan eset ránézésre váljon el.
        self.tv.tag_configure("tipp", foreground=COL_WARN)

    def fill(self, rows, checked=True):
        """rows: [(kulcs, (cella, …), tipp-e)] — a kulcsot adja vissza a selected()."""
        self.tv.delete(*self.tv.get_children())
        self._keys, self.on = {}, {}
        for i, (key, cells, tipp) in enumerate(rows):
            iid = str(i)
            self._keys[iid] = key
            self.on[iid] = checked
            self.tv.insert("", "end", iid=iid, tags=("tipp",) if tipp else (),
                           values=(("☑" if checked else "☐"),) + tuple(cells))
        self._changed()

    def _click(self, e):
        iid = self.tv.identify_row(e.y)
        if iid and self.tv.identify_region(e.x, e.y) != "heading":
            self._toggle(iid)

    def _toggle(self, iid):
        if iid not in self.on:
            return
        self.on[iid] = not self.on[iid]
        self.tv.set(iid, "_ck", "☑" if self.on[iid] else "☐")
        self._changed()

    def set_all(self, val: bool):
        for iid in self.on:
            self.on[iid] = val
            self.tv.set(iid, "_ck", "☑" if val else "☐")
        self._changed()

    def selected(self):
        return [self._keys[i] for i in self.tv.get_children() if self.on[i]]

    def _changed(self):
        if self.on_change:
            self.on_change(len(self.selected()))


class HitList(CheckList):
    """Találatlista (keresés, személyes adat): a ✓ oszlopra kattintva vált, a sorra
    kattintva a találatra ugrik — a CheckList-tel szemben, ahol a sor bármely
    pontja vált (ott nincs mire ugrani)."""

    def __init__(self, master, headings, widths, height=8, on_change=None, on_select=None):
        super().__init__(master, headings, widths, height, on_change)
        self.on_select = on_select
        self.tv.bind("<<TreeviewSelect>>", self._sel)
        self.tv.tag_configure("baj", foreground=COL_WARN)

    def _click(self, e):
        iid = self.tv.identify_row(e.y)
        if (iid and self.tv.identify_region(e.x, e.y) != "heading"
                and self.tv.identify_column(e.x) == "#1"):
            self._toggle(iid)
            return "break"
        return None

    def _sel(self, _e=None):
        f = self.tv.selection()
        if f and self.on_select and f[0] in self._keys:
            self.on_select(self._keys[f[0]])

    def fill_rows(self, rows):
        """rows: [(kulcs, (cella, …), kijelölve-e, baj-e)]"""
        self.tv.delete(*self.tv.get_children())
        self._keys, self.on = {}, {}
        for i, (key, cells, on, baj) in enumerate(rows):
            iid = str(i)
            self._keys[iid], self.on[iid] = key, bool(on)
            self.tv.insert("", "end", iid=iid, tags=("baj",) if baj else (),
                           values=(("☑" if on else "☐"),) + tuple(cells))
        self._changed()

    def show_key(self, key):
        """A kulcs sora kijelölve és látható (a vászonról visszafelé)."""
        for iid, k in self._keys.items():
            if k == key:
                self.tv.selection_set(iid)
                self.tv.see(iid)
                return


class Tip:
    """Súgóbuborék: ha az egér fél másodpercig a widget fölött marad, rövid
    magyarázat jelenik meg alatta. Az ikonos gombokhoz kell (lapozás, eszközök):
    felirat nélkül a jelentésüket csak így lehet megtudni."""

    def __init__(self, widget, text: str, delay: int = 450):
        self.w, self.text, self.delay = widget, text, delay
        self.job = self.win = None
        widget.bind("<Enter>", self._enter, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _enter(self, _e=None):
        self._hide()
        self.job = self.w.after(self.delay, self._show)

    def _show(self):
        self.job = None
        if not self.text or not self.w.winfo_ismapped():
            return
        x = self.w.winfo_rootx() + 10
        y = self.w.winfo_rooty() + self.w.winfo_height() + 6
        self.win = tw = tk.Toplevel(self.w)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        tk.Label(tw, text=self.text, justify="left", wraplength=320,
                 background=UI["head_ink"], foreground="#ffffff", font=FONT_SM,
                 padx=9, pady=5).pack()

    def _hide(self, _e=None):
        if self.job:
            self.w.after_cancel(self.job)
            self.job = None
        if self.win is not None:
            self.win.destroy()
            self.win = None


def checklist_box(parent, headings, widths, height=14, on_change=None):
    """CheckList + „Mind kijelöl” / „Egyiket se” gombsor. -> a CheckList."""
    cl = CheckList(parent, headings, widths, height, on_change)
    cl.pack(fill="both", expand=True, padx=14)
    row = ttk.Frame(parent)
    row.pack(fill="x", padx=14, pady=(4, 0))
    ttk.Button(row, text="Mind kijelöl", command=lambda: cl.set_all(True)).pack(side="left")
    ttk.Button(row, text="Egyiket se", command=lambda: cl.set_all(False)).pack(side="left", padx=6)
    return cl


class WorkerPicker(ttk.Frame):
    """Dolgozóválasztó: legördülő a munkamappa dolgozói mappáival + visszajelzés.

    Egy helyen, mert két fülön kell ugyanaz (Összeállító, Arckép elhelyezés). Az
    Arckép fülön eddig sima szövegmező volt: a nevet fejből kellett tudni, vagy a
    munkamappát átállítani a dolgozó mappájára — pedig a lista ott volt a kezünkben.

    A beírt részlet szűkíti a legördülőt; ha a mező már EGY dolgozót jelöl, újra
    mindenkit mutat — különben váltani csak visszatörölve lehetne. Enter kiegészíti
    a nevet a teljesre.

    `arrow_suffix`: a találat mögé írt cél (az Arckép fülön a „\\02_Feltoltheto”).
    """

    def __init__(self, master, arrow_suffix: str = "", on_change=None,
                 on_select=None, wraplength: int = 0):
        super().__init__(master)
        self.arrow_suffix = arrow_suffix
        self.on_change, self.on_select = on_change, on_select
        self.dirs = []
        self.who = None
        self.var = tk.StringVar(value="")
        self.msg = tk.StringVar(value="")
        self.cb = ttk.Combobox(self, textvariable=self.var, postcommand=self._fill)
        self.cb.pack(fill="x")
        self.lbl = ttk.Label(self, textvariable=self.msg, wraplength=wraplength)
        self.lbl.pack(anchor="w", pady=(2, 0))
        self.cb.bind("<Return>", lambda e: self._enter())
        self.cb.bind("<<ComboboxSelected>>", lambda e: self._selected())
        self.var.trace_add("write", lambda *a: self.refresh())

    def set_dirs(self, dirs):
        self.dirs = dirs
        self.refresh()

    def _fill(self):
        who, hits = resolve_worker(self.var.get(), self.dirs)
        self.cb.configure(values=self.dirs if who else hits)

    def refresh(self):
        self.who, hits = resolve_worker(self.var.get(), self.dirs)
        if self.who:
            msg, col = f"→ {self.who}{self.arrow_suffix}", COL_OK
        elif not self.var.get().strip():
            msg, col = "válaszd a listából, vagy írd be a nevét (elég egy részlete)", ""
        else:
            msg, col = (f"{len(hits)} találat — pontosíts" if hits
                        else "nincs ilyen dolgozói mappa"), COL_WARN
        self.msg.set(msg)
        self.lbl.configure(foreground=col)
        if self.on_change:
            self.on_change()

    def warn(self, text):
        """Külső hibaüzenet a mező alá (pl. „előbb válaszd ki a dolgozót”)."""
        self.msg.set(text)
        self.lbl.configure(foreground=COL_WARN)

    def _enter(self):
        if self.who:
            self.var.set(self.who)      # a részletből a teljes név
        self._selected()

    def _selected(self):
        if self.on_select:
            self.on_select()


class FileList(ttk.Frame):
    """Listbox + görgetősáv + Frissítés/Tallózás gombpár."""

    def __init__(self, master, title, exts, on_pick, height=7, memory_key=""):
        super().__init__(master)
        self.exts, self.on_pick, self.folder = exts, on_pick, script_dir()
        self.subdirs = ()                     # dolgozói mappánál: 01_…, 02_…
        self.title = title
        self.memory_key = memory_key          # a Tallózás megjegyzett mappája
        self._ok = False

        self.box = box = ttk.LabelFrame(self, text=title)
        box.pack(fill="both", expand=True)
        inner = ttk.Frame(box)
        inner.pack(fill="both", expand=True, padx=6, pady=6)
        self.lb = tk.Listbox(inner, height=height, exportselection=False, selectmode="browse")
        sb = ttk.Scrollbar(inner, orient="vertical", command=self.lb.yview)
        self.lb.configure(yscrollcommand=sb.set)
        self.lb.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.lb.bind("<<ListboxSelect>>", self._select)

        row = ttk.Frame(box)
        row.pack(fill="x", padx=6, pady=(0, 6))
        ttk.Button(row, text="Frissítés", command=self.refresh).pack(side="left")
        ttk.Button(row, text="Tallózás…", command=self._browse).pack(side="left", padx=6)

    def set_folder(self, folder, subdirs=()):
        """`subdirs`: ezek tartalma is a listába kerül (a dolgozó két alkönyvtára);
        ilyenkor a keret címe a dolgozó nevét is mutatja."""
        self.folder, self.subdirs = folder, tuple(subdirs)
        self.box.configure(text=f"{self.title} — {os.path.basename(os.path.normpath(folder))}"
                           if self.subdirs else self.title)
        self.refresh()

    def refresh(self):
        keep = self.selected_names()
        files = list_files_in(self.folder, self.exts, self.subdirs)
        self._ok = bool(files)
        self.lb.delete(0, tk.END)
        for f in files or ["(nincs megfelelő fájl a mappában)"]:
            self.lb.insert(tk.END, f)
        for i, f in enumerate(files):
            if f in keep:
                self.lb.selection_set(i)

    def selected_names(self):
        if not self._ok:
            return []
        return [self.lb.get(i) for i in self.lb.curselection()]

    def selected_paths(self):
        return [os.path.join(self.folder, n) for n in self.selected_names()]

    def _select(self, _e=None):
        if self._ok and self.on_pick:
            p = self.selected_paths()
            if p:
                self.on_pick(p[0])

    def _browse(self):
        pat = " ".join("*" + e for e in (self.exts if isinstance(self.exts, tuple) else (self.exts,)))
        start = recall(self.memory_key, self.folder) if self.memory_key else self.folder
        p = filedialog.askopenfilename(title="Fájl kiválasztása", initialdir=start,
                                       filetypes=[("Támogatott", pat), ("Minden fájl", "*.*")])
        if p and self.on_pick:
            if self.memory_key:
                remember(self.memory_key, p)
            self.on_pick(p)


# ───────────────────────────── 1. fül: elhelyezés ─────────────────────────────
class PlacerTab(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.src_path = self.doc = self.imgpdf = self.img_path = None
        self.img_crop = None             # a körülvágás a kép lapkoordinátáiban
        self.img_levels = None           # (fényerő, kontraszt) vagy None
        self.page_no = 0
        self.base_scale = 1.0
        self.max_scale = 400.0
        self.fit_zoom = self.view_zoom = self.zoom = 1.0
        self.cx_pt = self.cy_pt = 0.0
        self.scale = tk.DoubleVar(value=100.0)
        self.angle = tk.DoubleVar(value=0.0)
        self.raster = tk.BooleanVar(value=False)
        self.dpi = tk.IntVar(value=300)
        self.pos_info = tk.StringVar(value="")
        self.page_tk = self.photo_tk = None
        self.pw_px = self.ph_px = 0
        self._drag = self._job = None
        # iktatás (a fotóval ellátott irat a 02_Feltoltheto mappába)
        self.parent_dir = script_dir()
        self.dirs = []
        self.who = None
        self.who_text = tk.StringVar(value="")
        self.who_msg = tk.StringVar(value="")
        self.doc_type = tk.StringVar(value="")
        self._build()
        self.refresh()

    def _build(self):
        # A bal panel görgethető: a tartalma 990 px-et kér, és a legnagyobb ablakban
        # is csak 658 jutott — a Mentés és az Iktatás gomb EDDIG MINDIG levágódott.
        self.shell, left = scroll_panel(self, 340, padx=8)

        self.pdfs = FileList(left, "PDF nyomtatványok", (".pdf",), self._open_pdf, height=4,
                             memory_key="nyomtatvanyok")
        # A görgethető panelen a listák NEM nyúlnak: expand=True-val ketten elvitték
        # a teljes magasságot, és minden más a látható rész alá csúszott.
        self.pdfs.pack(fill="x")
        self.imgs = FileList(left, "Arcképek", IMG_EXT, self._load_img, height=4,
                             memory_key="arckepek")
        self.imgs.pack(fill="x", pady=(8, 0))
        self.img_lbl = ttk.Label(left, text="(nincs kép)", foreground="#555", wraplength=320)
        self.img_lbl.pack(anchor="w", pady=(4, 0))
        ttk.Button(left, text="Körülvágás, fényerő…",
                   command=self._crop_dialog).pack(anchor="w", pady=(2, 0))

        c = ttk.LabelFrame(left, text="Igazítás")
        c.pack(fill="x", pady=8)
        ttk.Label(c, text="Méret (%)").grid(row=0, column=0, sticky="w", padx=6, pady=2)
        self.scale_sl = ttk.Scale(c, from_=5, to=400, variable=self.scale,
                                  command=lambda _e: self._schedule())
        self.scale_sl.grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Spinbox(c, from_=5, to=400, textvariable=self.scale, width=6,
                    command=self._schedule).grid(row=0, column=2, padx=6)
        ttk.Label(c, text="Forgatás (°)").grid(row=1, column=0, sticky="w", padx=6, pady=2)
        ttk.Scale(c, from_=-180, to=180, variable=self.angle,
                  command=lambda _e: self._schedule()).grid(row=1, column=1, sticky="ew", padx=6)
        ttk.Spinbox(c, from_=-180, to=180, increment=0.5, textvariable=self.angle, width=6,
                    command=self._schedule).grid(row=1, column=2, padx=6)
        c.columnconfigure(1, weight=1)
        q = ttk.Frame(c)
        q.grid(row=2, column=0, columnspan=3, sticky="w", padx=6, pady=4)
        for txt, d in (("−90°", -90), ("−1°", -1), ("+1°", 1), ("+90°", 90)):
            ttk.Button(q, text=txt, width=6, command=lambda d=d: self._rotate_by(d)).pack(side="left", padx=2)
        ttk.Button(q, text="Alaphelyzet", command=self._reset).pack(side="left", padx=8)

        p = ttk.LabelFrame(left, text="Oldal / nézet")
        p.pack(fill="x", pady=4)
        self.page_var = tk.StringVar(value="1")
        ttk.Label(p, text="Oldal:").pack(side="left", padx=6)
        self.page_spin = ttk.Spinbox(p, from_=1, to=1, textvariable=self.page_var, width=5,
                                     command=self._change_page)
        self.page_spin.pack(side="left")
        ttk.Button(p, text="−", width=3, command=lambda: self._view_zoom(1 / 1.25)).pack(side="left", padx=(12, 2))
        ttk.Button(p, text="+", width=3, command=lambda: self._view_zoom(1.25)).pack(side="left")
        ttk.Button(p, text="Illeszt", command=lambda: self._view_zoom(0)).pack(side="left", padx=6)

        o = ttk.LabelFrame(left, text="Mentés")
        o.pack(fill="x", pady=8)
        ttk.Checkbutton(o, text="Oldalak raszterizálása (beégetés)",
                        variable=self.raster).pack(anchor="w", padx=6, pady=2)
        dd = ttk.Frame(o)
        dd.pack(anchor="w", padx=6, pady=2)
        ttk.Label(dd, text="DPI:").pack(side="left")
        ttk.Spinbox(dd, from_=72, to=1200, textvariable=self.dpi, width=6).pack(side="left", padx=6)
        ttk.Label(o, text="a mentés és az iktatás a panel alján",
                  foreground=UI["ink_soft"]).pack(anchor="w", padx=6, pady=(0, 6))

        # Iktatás: a kész (fotóval ellátott) irat mindig a feltölthető mappába megy —
        # a fotó épp most került rá. Ez zárja be a kört 01 → fotó → 02.
        ik = ttk.LabelFrame(left, text=f"Iktatás a {DIR_UP} mappába")
        ik.pack(fill="x", pady=(0, 8))
        ttk.Label(ik, text="Dolgozó:").pack(anchor="w", padx=6, pady=(4, 0))
        # Ugyanaz a választó, mint az Összeállítón (WorkerPicker): legördülő a
        # munkamappa dolgozói mappáival. Eddig itt sima szövegmező volt.
        self.picker = WorkerPicker(ik, arrow_suffix=f"\\{DIR_UP}",
                                   on_change=self._who_changed, wraplength=300)
        self.picker.pack(fill="x", padx=6)
        self.who_text, self.who_msg = self.picker.var, self.picker.msg
        self.who_lbl, self.who_cb = self.picker.lbl, self.picker.cb
        tr = ttk.Frame(ik)
        tr.pack(fill="x", padx=6, pady=2)
        ttk.Label(tr, text="Típus:").pack(side="left")
        self.type_cbo = ttk.Combobox(tr, textvariable=self.doc_type, width=24,
                                     state="readonly")
        self.type_cbo.pack(side="left", padx=4)

        ttk.Label(left, textvariable=self.pos_info, foreground="#333", wraplength=320).pack(anchor="w")

        # A fül két záró művelete a görgethető részen KÍVÜL, fix alsó sávban: ezekért
        # ne kelljen görgetni (a Szerkesztés „Alkalmaz” sávjának mintájára).
        bar = ttk.Frame(self.shell)
        bar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Button(bar, text="Mentés másként…", command=self._save).pack(fill="x")
        self.btn_iktat = ttk.Button(bar, text="Iktatás a feltölthetőbe", command=self._iktat)
        self.btn_iktat.pack(fill="x", pady=(4, 0))

        right = ttk.Frame(self)
        right.pack(side="right", fill="both", expand=True, padx=(0, 8), pady=8)
        self.canvas = tk.Canvas(right, bg=COL_CANVAS, highlightthickness=0,
                                cursor="fleur", takefocus=1, height=180)
        hb = ttk.Scrollbar(right, orient="horizontal", command=self.canvas.xview)
        vb = ttk.Scrollbar(right, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=hb.set, yscrollcommand=vb.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        vb.grid(row=0, column=1, sticky="ns")
        hb.grid(row=1, column=0, sticky="ew")
        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)

        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._motion)
        self.canvas.bind("<ButtonRelease-1>", lambda e: setattr(self, "_drag", None))
        self.canvas.bind("<Enter>", lambda e: self.canvas.focus_set())
        self.canvas.bind("<Configure>", lambda e: self._schedule(full=True))
        # Külön binding modifikátoronként – a state-bit vizsgálata Windowson megbízhatatlan
        for w in (self.canvas, self):
            w.bind("<MouseWheel>", self._wheel_size)
            w.bind("<Shift-MouseWheel>", self._wheel_rotate)
            w.bind("<Control-MouseWheel>", self._wheel_view)
        for w in (self.canvas,):
            w.bind("<Left>", lambda e: self._nudge(-1, 0, e))
            w.bind("<Right>", lambda e: self._nudge(1, 0, e))
            w.bind("<Up>", lambda e: self._nudge(0, -1, e))
            w.bind("<Down>", lambda e: self._nudge(0, 1, e))
        top = self.winfo_toplevel()
        top.bind_all("<Control-Left>", lambda e: self._guard(self._rotate_by, -1))
        top.bind_all("<Control-Right>", lambda e: self._guard(self._rotate_by, 1))
        top.bind_all("<Control-Shift-Left>", lambda e: self._guard(self._rotate_by, -90))
        top.bind_all("<Control-Shift-Right>", lambda e: self._guard(self._rotate_by, 90))

    # -- segédek --
    def _guard(self, fn, *a):
        """Globális gyorsbillentyű csak akkor, ha ez a fül aktív."""
        if self.app.active_tab() is self:
            fn(*a)
        return "break"

    def set_folder(self, folder):
        self._lists_at = None                 # a listák mindenképp frissüljenek
        # Honnan tudjuk, hogy a kapott mappa a MUNKAMAPPA vagy egy DOLGOZÓÉ? A
        # felső sáv munkamappája az egyetlen biztos jel: a refresh_all azt adja
        # át, az Áttekintő „Arckép elhelyezése” menüje pedig a dolgozó mappáját.
        #
        # Korábban ezt találgatás döntötte el (benne van-e a mappa a szülője
        # almappái között) — ez viszont szinte MINDEN mappára igaz, a
        # munkamappára is. Következmény: a munkamappa szülője lett a parent_dir,
        # és a dolgozóválasztóba a munkamappa neve került a dolgozók helyett
        # (mérve: a legördülő egyetlen eleme „gyujto” volt).
        work = getattr(self.app, "folder", None)
        work = work.get() if work is not None else folder
        if os.path.normpath(folder) != os.path.normpath(work):
            self.parent_dir = os.path.dirname(os.path.normpath(folder))
            self.refresh()
            self.who_text.set(os.path.basename(os.path.normpath(folder)))
            return
        self.parent_dir = folder
        self.refresh()

    def set_worker(self, name, force=False):
        """Az alapértelmezett dolgozó (a fülsor választója): váltáskor átvesszük,
        frissítéskor csak az üres mezőbe — a fülön kézzel választott megmarad."""
        if name and (force or not self.who_text.get().strip()):
            self.who_text.set(name)
        self._point_lists()

    def _point_lists(self):
        """A két fájllista a kiválasztott dolgozó mappáját mutatja (a nyomtatvány és
        az arckép a 01_Elokeszitett-ben él), dolgozó nélkül a munkamappát."""
        if self.who and os.path.isdir(os.path.join(self.parent_dir, self.who)):
            at = (os.path.join(self.parent_dir, self.who), WORK_DIRS)
        else:
            at = (self.parent_dir, ())
        if at != getattr(self, "_lists_at", None):
            self._lists_at = at
            self.pdfs.set_folder(*at)
            self.imgs.set_folder(*at)

    # -- iktatás --
    def refresh(self):
        """Dolgozói mappák és típuslista — fülváltáskor és mappaváltáskor."""
        try:
            self.dirs = worker_dirs(self.parent_dir)
        except OSError:
            self.dirs = []
        self.picker.set_dirs(self.dirs)
        ikt = getattr(self.app, "tabs", {}).get("Iktató")
        types = ikt.types if ikt else load_types()
        self.type_cbo.configure(values=types)
        if self.doc_type.get() not in types:
            # A fotóigényes típus az alapértelmezés — ezért van ez a fül.
            rules = self._rules()
            pick = next((t for t in types
                         if (doc_type_rule(t, rules) or Rule("", "", "")).arckep), None)
            self.doc_type.set(pick or (types[0] if types else ""))

    def _rules(self) -> list:
        att = getattr(self.app, "tabs", {}).get("Áttekintő")
        return att.rules if att else rules_from(default_settings())

    def _who_changed(self):
        self.who = self.picker.who
        if hasattr(self, "pdfs"):
            self._point_lists()

    def _iktat(self):
        """A fotóval ellátott irat a dolgozó 02_Feltoltheto mappájába, az Iktató
        közös magjával: szabványos név, ütközéskezelés, 5 MB, napló."""
        if not (self.doc and self.imgpdf):
            messagebox.showwarning("Hiányzik", "PDF és kép is kell az iktatáshoz.")
            return
        if not self.who:
            self.picker.warn("Előbb válaszd ki a dolgozót.")
            return
        dt = self.doc_type.get()
        if not dt:
            messagebox.showwarning("Hiányzik", "Válassz dokumentumtípust.")
            return
        r = doc_type_rule(dt, self._rules())
        folder = os.path.join(self.parent_dir, self.who, DIR_UP)
        # A fotó épp most került rá: a fotóigényes nyomtatvány nevébe ez bekerül.
        name = target_name(self.who, dt, SUFFIX if (r is None or r.generated) else "",
                           photo=bool(r and r.arckep))
        dst = os.path.join(folder, name)
        backup = None
        try:
            check_path_len(dst)
            os.makedirs(folder, exist_ok=True)
            if os.path.exists(dst):
                if not messagebox.askyesno(
                        "A fájl már létezik",
                        f"{name}\n\nFelülírjuk? Az előző példány a dolgozó "
                        f"{DIR_PREP}\\ mappájába kerül.\n\n"
                        "Nem = új név (2), (3) …"):
                    name = unique_name(folder, name)[0]
                    dst = os.path.join(folder, name)
                else:
                    backup = backup_existing(dst)
            self.app.status("Iktatás…")
            self.update_idletasks()
            self._write(dst, (self.who, dt, r.id if r else "", DIR_UP))
        except Exception as e:
            traceback.print_exc()
            if backup and os.path.exists(backup):
                try:
                    os.replace(backup, dst)
                except OSError:
                    pass
            log_row(self.parent_dir, self.src_path or "", os.path.join(self.who, DIR_UP),
                    name, dt, "HIBA: " + str(e)[:120])
            messagebox.showerror("Az iktatás nem sikerült", f"{type(e).__name__}: {e}")
            self.app.status("Hiba.")
            return
        note = size_note(dst)
        log_row(self.parent_dir, self.src_path or "", os.path.join(self.who, DIR_UP),
                name, dt, "FELULIRVA (elozo: " + DIR_PREP + ")" if backup else "OK")
        self.app.status(f"Iktatva: {name} {note}")
        messagebox.showinfo("Iktatva", f"{self.who}\\{DIR_UP}\\{name}" +
                            (f"\n\n{note}" if note else "") +
                            ("\n\nAz 5 MB-os korlát fölött van — az Iktató fülön "
                             "tömöríthető." if note else ""))
        self.app.refresh_all()

    # -- betöltés --
    def _open_pdf(self, path):
        try:
            doc = open_checked(path)
        except Exception as e:
            messagebox.showerror("Hiba", f"A PDF nem nyitható meg:\n{e}")
            return
        if self.doc:
            self.doc.close()
        self.doc, self.src_path, self.page_no = doc, path, 0
        self.page_spin.configure(to=doc.page_count)
        self.page_var.set("1")
        self.view_zoom = 1.0
        self._center()
        self._fit_base_scale()
        self.app.status(f"{os.path.basename(path)} – {doc.page_count} oldal")
        self.after(50, self._render_all)

    def _load_img(self, path):
        self.img_crop = self.img_levels = None   # új kép: a korábbi állítás nem öröklődik
        self._set_img(path)

    def _crop_dialog(self):
        if not self.img_path:
            messagebox.showwarning("Hiányzik", "Előbb válassz arcképet.")
            return
        CropDialog(self, self.img_path, self.img_crop, self._apply_crop, self.img_levels)

    def _apply_crop(self, rect, levels=None):
        self.img_crop, self.img_levels = rect, levels
        self._set_img(self.img_path)

    def _set_img(self, path):
        try:
            imgpdf = open_image_pdf(path, self.img_crop, self.img_levels)
        except Exception as e:
            messagebox.showerror("Hiba", f"A kép nem tölthető be:\n{e}")
            return
        if self.imgpdf:
            self.imgpdf.close()
        self.imgpdf, self.img_path = imgpdf, path
        r = imgpdf[0].rect
        self.img_lbl.configure(
            text=f"{os.path.basename(path)}  ({r.width:.0f}×{r.height:.0f} pt)" +
                 (" · körülvágva" if self.img_crop else "") +
                 (" · szintezve" if self.img_levels else ""))
        self.scale.set(100.0)
        self.angle.set(0.0)
        self._center()
        self._fit_base_scale()
        self._render_photo()

    def _center(self):
        if self.doc:
            r = self.doc[self.page_no].rect
            self.cx_pt, self.cy_pt = r.width / 2, r.height / 2

    def _fit_base_scale(self):
        """100% = a lapnál biztosan kisebb alapméret; a csúszka ehhez arányosít."""
        if not (self.doc and self.imgpdf):
            return
        pr, ir = self.doc[self.page_no].rect, self.imgpdf[0].rect
        self.base_scale = min(pr.width * DEF_W_RATIO / ir.width,
                              pr.height * DEF_H_RATIO / ir.height)
        limit = min(pr.width / (ir.width * self.base_scale),
                    pr.height / (ir.height * self.base_scale)) * 100.0
        self.max_scale = max(20.0, min(400.0, limit))
        self.scale_sl.configure(to=self.max_scale)
        if float(self.scale.get()) > self.max_scale:
            self.scale.set(self.max_scale)

    def _change_page(self):
        if not self.doc:
            return
        try:
            n = max(1, min(self.doc.page_count, int(self.page_var.get())))
        except ValueError:
            return
        self.page_no = n - 1
        self._fit_base_scale()
        self._render_all()

    # -- rajzolás --
    def _schedule(self, full=False):
        if self._job:
            self.after_cancel(self._job)
        self._job = self.after(40, self._render_all if full else self._render_photo)

    def _view_zoom(self, factor):
        self.view_zoom = 1.0 if not factor else max(0.2, min(6.0, self.view_zoom * factor))
        self._render_all()

    def _render_all(self):
        self._job = None
        if not self.doc:
            return
        page = self.doc[self.page_no]
        cw = max(50, self.canvas.winfo_width())
        ch = max(50, self.canvas.winfo_height())
        r = page.rect
        self.fit_zoom = min(cw / r.width, ch / r.height)
        self.zoom = self.fit_zoom * self.view_zoom
        pix = page.get_pixmap(matrix=pymupdf.Matrix(self.zoom, self.zoom), annots=True)
        self.page_tk = tkimg(pix, "ppm")
        self.canvas.delete("page")
        self.canvas.create_image(0, 0, anchor="nw", image=self.page_tk, tags="page")
        self.canvas.configure(scrollregion=(0, 0, pix.width, pix.height))
        self.canvas.tag_lower("page")
        self._render_photo()

    def _size_pt(self):
        ir = self.imgpdf[0].rect
        f = self.base_scale * float(self.scale.get()) / 100.0
        return ir.width * f, ir.height * f

    def _render_photo(self):
        self._job = None
        if not (self.doc and self.imgpdf):
            return
        s = max(5.0, min(self.max_scale, float(self.scale.get())))
        if s != float(self.scale.get()):
            self.scale.set(s)
        z = self.zoom * self.base_scale * s / 100.0
        m = pymupdf.Matrix(z, z).prerotate(float(self.angle.get()))
        pix = self.imgpdf[0].get_pixmap(matrix=m, alpha=True)
        self.photo_tk = tkimg(pix, "png")
        self.pw_px, self.ph_px = pix.width, pix.height
        self.canvas.delete("photo")
        self.canvas.create_image(self.cx_pt * self.zoom, self.cy_pt * self.zoom,
                                 anchor="center", image=self.photo_tk, tags="photo")
        self._info()

    def _info(self):
        w, h = self._size_pt()
        self.pos_info.set(f"közép: {self.cx_pt:.0f} × {self.cy_pt:.0f} pt   "
                          f"kép: {w:.0f} × {h:.0f} pt ({w/72*25.4:.0f} × {h/72*25.4:.0f} mm)   "
                          f"{float(self.angle.get()):.1f}°")

    # -- interakció --
    def _press(self, e):
        self.canvas.focus_set()
        self._drag = (self.canvas.canvasx(e.x), self.canvas.canvasy(e.y))

    def _motion(self, e):
        if not (self._drag and self.imgpdf):
            return
        x, y = self.canvas.canvasx(e.x), self.canvas.canvasy(e.y)
        dx, dy = x - self._drag[0], y - self._drag[1]
        self._drag = (x, y)
        self.cx_pt += dx / self.zoom
        self.cy_pt += dy / self.zoom
        self.canvas.move("photo", dx, dy)
        self._info()

    def _wheel_size(self, e):
        if not self.imgpdf:
            return "break"
        k = 1.08 if e.delta > 0 else 1 / 1.08
        self.scale.set(max(5.0, min(self.max_scale, float(self.scale.get()) * k)))
        self._schedule()
        return "break"

    def _wheel_rotate(self, e):
        self._rotate_by(1.0 if e.delta > 0 else -1.0)
        return "break"

    def _wheel_view(self, e):
        self._view_zoom(1.25 if e.delta > 0 else 1 / 1.25)
        return "break"

    def _rotate_by(self, d):
        if not self.imgpdf:
            return "break"
        self.angle.set(round((float(self.angle.get()) + d + 180) % 360 - 180, 1))
        self._schedule()
        return "break"

    def _nudge(self, dx, dy, e):
        if not self.imgpdf:
            return "break"
        k = 10 if (e.state & 0x0001) else 1
        self.cx_pt += dx * k
        self.cy_pt += dy * k
        self._render_photo()
        return "break"

    def _reset(self):
        self.scale.set(100.0)
        self.angle.set(0.0)
        self._center()
        self._fit_base_scale()
        self._render_photo()

    # -- mentés --
    def _save(self):
        if not (self.doc and self.imgpdf):
            messagebox.showwarning("Hiányzik", "PDF és kép is kell a mentéshez.")
            return
        stem = os.path.splitext(os.path.basename(self.src_path))[0]
        dst = filedialog.asksaveasfilename(title="Mentés másként",
                                           initialdir=os.path.dirname(self.src_path),
                                           initialfile=add_mark(stem, MARK_PHOTO) + ".pdf",
                                           defaultextension=".pdf",
                                           filetypes=[("PDF fájlok", "*.pdf")])
        if not dst:
            return
        if os.path.abspath(dst) == os.path.abspath(self.src_path):
            messagebox.showerror("Felülírás", "Ne írd felül az eredetit – adj más nevet.")
            return
        try:
            self.app.status("Mentés…")
            self.update_idletasks()
            self._write(dst)
        except Exception as e:
            traceback.print_exc()
            messagebox.showerror("Hiba", f"{type(e).__name__}: {e}")
            self.app.status("Hiba.")
            return
        note = size_note(dst)
        self.app.status(f"Kész: {os.path.basename(dst)} {note}")
        messagebox.showinfo("Kész", f"Elmentve:\n{dst}" + (f"\n\n{note}" if note else ""))
        self.app.refresh_all()

    def _write(self, dst, stamp=None):
        w, h = self._size_pt()
        a = math.radians(float(self.angle.get()))
        bw = abs(w * math.cos(a)) + abs(h * math.sin(a))     # forgatott befoglaló doboz
        bh = abs(w * math.sin(a)) + abs(h * math.cos(a))
        rect = pymupdf.Rect(self.cx_pt - bw / 2, self.cy_pt - bh / 2,
                            self.cx_pt + bw / 2, self.cy_pt + bh / 2)
        out = open_checked(self.src_path)
        try:
            page = out[self.page_no]
            rot = page.rotation
            target = rect * page.derotation_matrix if rot else rect
            # Az előnézet (y lefelé) pozitív szöge óramutató szerinti, a show_pdf_page-é
            # (PDF-tér, y felfelé) ellentétes – ezért kivonjuk, különben ±90° 180°-ot tévedne.
            page.show_pdf_page(target, self.imgpdf, 0,
                               rotate=rot - float(self.angle.get()), keep_proportion=True)
            if not self.raster.get():
                if stamp:
                    set_stamp(out, *stamp)
                out.save(dst, garbage=4, deflate=True)
                return
            flat = rasterize_doc(out, self.dpi.get())      # ez CLEAN_META-t tesz rá
            if stamp:
                set_stamp(flat, *stamp)
            flat.save(dst, garbage=4, deflate=True)
            flat.close()
        finally:
            out.close()


# ───────────────────────────── 2. fül: összefűzés ─────────────────────────────
class MergeTab(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.folder = script_dir()
        self.bookmarks = tk.BooleanVar(value=True)
        self.outname = tk.StringVar(value="merged.pdf")
        self._build()

    def _build(self):
        top = ttk.Frame(self)
        top.pack(fill="both", expand=True, padx=10, pady=10)
        box = ttk.LabelFrame(top, text="Összefűzendő PDF-ek (a sorrend a lista sorrendje)")
        box.pack(fill="both", expand=True)
        inner = ttk.Frame(box)
        inner.pack(fill="both", expand=True, padx=6, pady=6)
        self.lb = tk.Listbox(inner, selectmode="extended", exportselection=False)
        sb = ttk.Scrollbar(inner, orient="vertical", command=self.lb.yview)
        self.lb.configure(yscrollcommand=sb.set)
        self.lb.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        r = ttk.Frame(box)
        r.pack(fill="x", padx=6, pady=(0, 6))
        ttk.Button(r, text="Frissítés", command=self.refresh).pack(side="left")
        ttk.Button(r, text="Mind kijelöl", command=lambda: self.lb.selection_set(0, tk.END)).pack(side="left", padx=4)
        ttk.Button(r, text="▲", width=3, command=lambda: self._move(-1)).pack(side="left", padx=(16, 2))
        ttk.Button(r, text="▼", width=3, command=lambda: self._move(1)).pack(side="left")

        opt = ttk.Frame(top)
        opt.pack(fill="x", pady=8)
        ttk.Checkbutton(opt, text="Könyvjelző fájlnevenként", variable=self.bookmarks).pack(side="left")
        ttk.Label(opt, text="Kimenet:").pack(side="left", padx=(20, 4))
        ttk.Entry(opt, textvariable=self.outname, width=30).pack(side="left")
        ttk.Button(opt, text="Összefűzés…", command=self._run).pack(side="right")

        self.log = tk.Text(top, height=12, wrap="none", state="disabled", bg="#f7f7f7")
        self.log.pack(fill="both", expand=True)

    def set_folder(self, folder, subdirs=()):
        self.folder, self.subdirs = folder, tuple(subdirs)
        self.refresh()

    def set_worker(self, name, force=False):
        self.set_folder(*self.app.list_target())

    def refresh(self):
        self.lb.delete(0, tk.END)
        for f in list_files_in(self.folder, (".pdf",), getattr(self, "subdirs", ())):
            self.lb.insert(tk.END, f)

    def _move(self, d):
        sel = list(self.lb.curselection())
        if not sel:
            return
        for i in (sel if d < 0 else reversed(sel)):
            j = i + d
            if 0 <= j < self.lb.size():
                v = self.lb.get(i)
                self.lb.delete(i)
                self.lb.insert(j, v)
                self.lb.selection_set(j)

    def _write_log(self, txt):
        self.log.configure(state="normal")
        self.log.insert(tk.END, txt + "\n")
        self.log.see(tk.END)
        self.log.configure(state="disabled")
        self.update_idletasks()

    def _run(self):
        names = [self.lb.get(i) for i in self.lb.curselection()] or list(self.lb.get(0, tk.END))
        if not names:
            messagebox.showwarning("Nincs fájl", "Nincs összefűzhető PDF.")
            return
        dst = filedialog.asksaveasfilename(title="Összefűzött PDF mentése",
                                           initialdir=self.folder,
                                           initialfile=self.outname.get() or "merged.pdf",
                                           defaultextension=".pdf",
                                           filetypes=[("PDF fájlok", "*.pdf")])
        if not dst:
            return
        self.log.configure(state="normal")
        self.log.delete("1.0", tk.END)
        self.log.configure(state="disabled")

        out = pymupdf.open()
        toc, expected = [], 0
        try:
            for n in names:
                path = os.path.join(self.folder, n)
                if os.path.abspath(path) == os.path.abspath(dst):
                    continue                                   # a kimenetet sose fűzzük bele
                src = open_checked(path)
                start = out.page_count
                out.insert_pdf(src)
                toc.append([1, os.path.splitext(os.path.basename(n))[0], start + 1])
                expected += src.page_count
                self._write_log(f"  + {n}: {src.page_count} oldal")
                src.close()
            if self.bookmarks.get() and toc:
                out.set_toc(toc)
            out.set_metadata(dict(CLEAN_META, title=os.path.splitext(os.path.basename(dst))[0]))
            out.save(dst, garbage=4, deflate=True)
        except Exception as e:
            traceback.print_exc()
            out.close()
            messagebox.showerror("Hiba", f"{type(e).__name__}: {e}")
            return
        out.close()

        chk = pymupdf.open(dst)
        ok = chk.page_count == expected
        self._write_log(f"\n{os.path.basename(dst)} kész – {chk.page_count}/{expected} oldal, "
                        f"{mb(os.path.getsize(dst))} [{'OK' if ok else 'ELTÉRÉS!'}] {size_note(dst)}")
        chk.close()
        self.app.status(f"Összefűzve: {os.path.basename(dst)}")
        self.app.refresh_all()


# ──────────────────────────── 4. fül: raszterizálás ────────────────────────────
class RasterTab(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.dpi = tk.IntVar(value=300)
        self.pages = tk.StringVar(value="")
        self.path = None
        self._build()

    def _build(self):
        top = ttk.Frame(self)
        top.pack(fill="both", expand=True, padx=10, pady=10)
        # Képet is: eddig csak PDF látszott a listában és a Tallózás ablakában, a
        # képeket kézzel kellett átállítani a „Minden fájl” szűrőre.
        self.files = FileList(top, "Raszterizálandó PDF vagy kép",
                              (".pdf",) + IMG_EXT, self._pick, height=8)
        self.files.pack(fill="both", expand=True)
        self.lbl = ttk.Label(top, text="(nincs kiválasztva)", foreground="#555")
        self.lbl.pack(anchor="w", pady=(6, 0))

        opt = ttk.LabelFrame(top, text="Beállítások")
        opt.pack(fill="x", pady=8)
        ttk.Label(opt, text="DPI:").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        ttk.Spinbox(opt, from_=72, to=1200, textvariable=self.dpi, width=6).grid(row=0, column=1, sticky="w")
        ttk.Label(opt, text="Oldalak (üres = mind, pl. 1,3-5):").grid(row=0, column=2, sticky="w", padx=(20, 6))
        ttk.Entry(opt, textvariable=self.pages, width=18).grid(row=0, column=3, sticky="w")
        ttk.Button(top, text="Raszterizálás és mentés…", command=self._run).pack(anchor="e", pady=6)

    def set_folder(self, folder):
        self.files.set_folder(folder)

    def set_worker(self, name, force=False):
        self.files.set_folder(*self.app.list_target())

    def _pick(self, path):
        self.path = path
        self.lbl.configure(text=os.path.basename(path))

    def _parse_pages(self, count):
        txt = self.pages.get().strip()
        if not txt:
            return None
        out = set()
        for part in txt.split(","):
            part = part.strip()
            if "-" in part:
                a, b = part.split("-", 1)
                out.update(range(int(a) - 1, int(b)))
            elif part:
                out.add(int(part) - 1)
        return {i for i in out if 0 <= i < count}

    def _run(self):
        if not self.path:
            messagebox.showwarning("Nincs fájl", "Válassz ki egy PDF-et vagy képet.")
            return
        stem = os.path.splitext(os.path.basename(self.path))[0]
        dst = filedialog.asksaveasfilename(title="Mentés másként",
                                           initialdir=os.path.dirname(self.path),
                                           initialfile=f"{stem}_raszter.pdf",
                                           defaultextension=".pdf",
                                           filetypes=[("PDF fájlok", "*.pdf")])
        if not dst or os.path.abspath(dst) == os.path.abspath(self.path):
            if dst:
                messagebox.showerror("Felülírás", "Ne írd felül az eredetit – adj más nevet.")
            return
        try:
            self.app.status("Raszterizálás…")
            self.update_idletasks()
            # A kép egyoldalas PDF-ként nyílik — onnantól a lépés ugyanaz.
            doc = (open_image_pdf(self.path)
                   if self.path.lower().endswith(IMG_EXT) else open_checked(self.path))
            flat = rasterize_doc(doc, self.dpi.get(), self._parse_pages(doc.page_count))
            flat.save(dst, garbage=4, deflate=True)
            flat.close()
            doc.close()
        except Exception as e:
            traceback.print_exc()
            messagebox.showerror("Hiba", f"{type(e).__name__}: {e}")
            self.app.status("Hiba.")
            return
        note = size_note(dst)
        self.app.status(f"Kész: {os.path.basename(dst)} {note}")
        messagebox.showinfo("Kész", f"Elmentve:\n{dst}" + (f"\n\n{note}" if note else ""))
        self.app.refresh_all()


# ─────────────────────── Eszközök: MD → DOCX ───────────────────────
# Markdown-fájlból szerkeszthető Word-irat (szerkeszto-terv.md 24.). A Markdownt saját,
# kicsi elemző olvassa (címsor, bekezdés, félkövér/dőlt/áthúzott, kód, lista beágyazva,
# táblázat, idézet, vízszintes vonal, link); a .docx-et a python-docx írja, a Word
# saját stílusaival (Heading 1…, List Bullet…), hogy a kész irat tovább szerkeszthető
# legyen. Kép nem kerül át: a helyén „[kép: …]” jelölő áll.
MD_EXT = (".md", ".markdown")
MD_FONT, MD_SIZE, MD_MONO = "Calibri", 11, "Consolas"

_MD_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_MD_HEAD = re.compile(r"^ {0,3}(#{1,6})(?:\s+(.*?))?\s*$")
_MD_HR = re.compile(r"^ {0,3}([-*_])(?:\s*\1){2,}\s*$")
_MD_ITEM = re.compile(r"^(\s*)([-*+]|\d{1,9}[.)])(\s+|$)(.*)$")
_MD_QUOTE = re.compile(r"^ {0,3}> ?(.*)$")
_MD_TSEP = re.compile(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$")
_MD_SETEXT = re.compile(r"^ {0,3}(=+|-+)\s*$")
_MD_INLINE = re.compile(
    r"\\(?P<esc>[\\`*_{}\[\]()#+\-.!|~<>])"
    r"|(?P<tick>`+)(?P<code>.+?)(?P=tick)"
    r"|!\[(?P<alt>[^\]]*)\]\([^)]*\)"
    r"|\[(?P<ltxt>(?:[^\[\]]|\[[^\]]*\])*)\]\(\s*<?(?P<url>[^)\s>]*)>?(?:\s+\"[^\"]*\")?\s*\)"
    r"|<(?P<auto>(?:https?://|mailto:)[^>\s]+)>"
    r"|(?P<bare>https?://[^\s<>()]*[^\s<>().,;:!?'\"])"
    r"|\*\*\*(?P<bi>\S(?:.*?\S)??)\*\*\*"
    r"|(?<!\w)___(?P<bi2>\S(?:.*?\S)??)___(?!\w)"
    r"|\*\*(?P<b>\S(?:.*?\S)??)\*\*"
    r"|(?<!\w)__(?P<b2>\S(?:.*?\S)??)__(?!\w)"
    r"|~~(?P<s>\S(?:.*?\S)??)~~"
    # Dőlt: a belsejében félkövér is lehet (*… **x** …*); a záró * nem egy ** fele.
    r"|\*(?P<i>[^\s*](?:\*\*.+?\*\*|[^*])*?(?<!\s))\*(?!\*)"
    r"|(?<!\w)_(?P<i2>[^\s_](?:.*?[^\s_])??)_(?!\w)"
    r"|(?P<br><br\s*/?>)", re.IGNORECASE)


def md_inline(text: str, fmt: dict = None) -> list:
    """Sorközi jelölés -> [(szöveg, formátum)]. A formátum kulcsai: b, i, s (áthúzott),
    code, link (URL), img (kép helye). A sortörés „\\n” a szövegben."""
    fmt = fmt or {}
    out, pos = [], 0
    for m in _MD_INLINE.finditer(text):
        if m.start() > pos:
            out.append((text[pos:m.start()], fmt))
        pos = m.end()
        g = m.groupdict()
        if g["esc"] is not None:
            out.append((g["esc"], fmt))
        elif g["tick"]:
            out.append((g["code"].strip() or g["code"], {**fmt, "code": True}))
        elif g["alt"] is not None:
            out.append((f"[kép: {g['alt'] or 'kép'}]", {**fmt, "img": True}))
        elif g["ltxt"] is not None:
            out += md_inline(g["ltxt"], {**fmt, "link": g["url"]})
        elif g["auto"] or g["bare"]:
            u = g["auto"] or g["bare"]
            out.append((u[7:] if u.startswith("mailto:") else u, {**fmt, "link": u}))
        elif g["bi"] or g["bi2"]:
            out += md_inline(g["bi"] or g["bi2"], {**fmt, "b": True, "i": True})
        elif g["b"] or g["b2"]:
            out += md_inline(g["b"] or g["b2"], {**fmt, "b": True})
        elif g["s"]:
            out += md_inline(g["s"], {**fmt, "s": True})
        elif g["i"] or g["i2"]:
            out += md_inline(g["i"] or g["i2"], {**fmt, "i": True})
        else:
            out.append(("\n", fmt))
    if pos < len(text):
        out.append((text[pos:], fmt))
    return out


def _md_cells(line: str) -> list:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", s)]


def _md_starts_block(line: str) -> bool:
    """Félbeszakítja-e ez a sor a bekezdést."""
    return bool(_MD_FENCE.match(line) or _MD_HEAD.match(line) or _MD_HR.match(line)
                or _MD_QUOTE.match(line) or _MD_ITEM.match(line))


def md_blocks(lines: list) -> list:
    """Sorok -> blokkok:
      ("h", szint, szöveg) · ("p", szöveg) · ("code", szöveg) · ("hr",)
      ("quote", blokkok) · ("table", fejléc, igazítások, sorok)
      ("list", számozott, kezdő, [(szöveg, al-blokkok), …])"""
    out, i, n = [], 0, len(lines)
    while i < n:
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        m = _MD_FENCE.match(line)
        if m:
            fence, body, i = m.group(1), [], i + 1
            while i < n and not lines[i].strip().startswith(fence):
                body.append(lines[i])
                i += 1
            out.append(("code", "\n".join(body)))
            i += 1
            continue
        if line.startswith(("    ", "\t")):            # behúzott kódblokk
            body = []
            while i < n and (lines[i].startswith(("    ", "\t")) or not lines[i].strip()):
                body.append(lines[i][4:] if lines[i].startswith("    ") else lines[i][1:])
                i += 1
            out.append(("code", "\n".join(body).rstrip("\n")))
            continue
        m = _MD_HEAD.match(line)
        if m:
            out.append(("h", len(m.group(1)), re.sub(r"\s+#+$", "", m.group(2) or "")))
            i += 1
            continue
        if _MD_HR.match(line):
            out.append(("hr",))
            i += 1
            continue
        if _MD_QUOTE.match(line):
            body = []
            while i < n and lines[i].strip():
                q = _MD_QUOTE.match(lines[i])
                body.append(q.group(1) if q else lines[i])
                i += 1
            out.append(("quote", md_blocks(body)))
            continue
        if "|" in line and i + 1 < n and _MD_TSEP.match(lines[i + 1]) and "-" in lines[i + 1]:
            head = _md_cells(line)
            aligns = []
            for c in _md_cells(lines[i + 1]):
                aligns.append("center" if c.startswith(":") and c.endswith(":") else
                              "right" if c.endswith(":") else "left")
            rows, i = [], i + 2
            while i < n and lines[i].strip() and "|" in lines[i]:
                rows.append(_md_cells(lines[i]))
                i += 1
            out.append(("table", head, aligns, rows))
            continue
        m = _MD_ITEM.match(line)
        if m:
            i = _md_list(lines, i, out)
            continue
        para, i = [line], i + 1                    # bekezdés
        while i < n and lines[i].strip() and not _md_starts_block(lines[i]) \
                and not _MD_SETEXT.match(lines[i]):
            para.append(lines[i])
            i += 1
        if i < n and _MD_SETEXT.match(lines[i]) and len(para) and lines[i].strip():
            level = 1 if lines[i].strip()[0] == "=" else 2
            out.append(("h", level, " ".join(p.strip() for p in para)))
            i += 1
            continue
        text = ""
        for p in para:                              # két szóköz / \ a sor végén: sortörés
            hard = p.endswith("  ") or p.rstrip().endswith("\\")
            p = p.strip()
            if p.endswith("\\"):
                p = p[:-1]
            text += p + ("\n" if hard else " ")
        out.append(("p", text.strip()))
    return out


def _md_list(lines: list, i: int, out: list) -> int:
    """Egy lista a(z) i. sortól; a tételeket rekurzívan bontja (beágyazott lista,
    több bekezdés). -> a lista utáni sor indexe."""
    m = _MD_ITEM.match(lines[i])
    ordered = m.group(2)[0].isdigit()
    start = int(m.group(2)[:-1]) if ordered else 1
    indent = len(m.group(1).expandtabs(4))
    items, n = [], len(lines)
    while i < n:
        m = _MD_ITEM.match(lines[i])
        if not m or len(m.group(1).expandtabs(4)) != indent \
                or m.group(2)[0].isdigit() != ordered:
            break
        content = indent + len(m.group(2)) + max(1, min(len(m.group(3)), 4))
        body, i = [m.group(4)], i + 1
        while i < n:
            ln = lines[i]
            lead = len(ln.expandtabs(4)) - len(ln.expandtabs(4).lstrip())
            if not ln.strip():
                # Üres sor után csak a behúzott folytatás tartozik a tételhez.
                j = i + 1
                while j < n and not lines[j].strip():
                    j += 1
                if j < n and len(lines[j].expandtabs(4)) - len(lines[j].expandtabs(4).lstrip()) >= content:
                    body.append("")
                    i += 1
                    continue
                break
            if lead >= content or (lead > indent and _MD_ITEM.match(ln)):
                body.append(ln.expandtabs(4)[min(lead, content):])
            elif not _md_starts_block(ln) and body[-1].strip():
                body.append(ln.strip())             # „lusta” folytatósor
            else:
                break
            i += 1
        sub = md_blocks(body)
        text = sub.pop(0)[1] if sub and sub[0][0] == "p" else ""
        items.append((text, sub))
        while i < n and not lines[i].strip():       # üres sor a tételek között
            j = i
            while j < n and not lines[j].strip():
                j += 1
            mm = _MD_ITEM.match(lines[j]) if j < n else None
            # Üres sor után az „1.” új számozott listát kezd (a CommonMark szerint
            # folytatná, de a szerző ilyenkor újrakezdést ír).
            if mm and len(mm.group(1).expandtabs(4)) == indent \
                    and not (ordered and mm.group(2)[:-1] == "1"):
                i = j
            break
    out.append(("list", ordered, start, items))
    return i


def md_read(path: str) -> str:
    """Markdown-fájl szövege: UTF-8 (BOM-mal is), különben a Windows régi kódlapja."""
    with open(path, "rb") as f:
        raw = f.read()
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1250", errors="replace")


# A Word a pPr/rPr gyerekeinek SORRENDJÉRE szigorú (sémasorrend): a végére fűzött
# w:shd után álló w:tabs vagy w:jc már „olvashatatlan tartalom”. Ezért a beszúrás az
# első, sémában utána következő elem elé történik.
_MD_PPR_AFTER_SHD = (
    "w:tabs", "w:suppressAutoHyphens", "w:kinsoku", "w:wordWrap", "w:overflowPunct",
    "w:topLinePunct", "w:autoSpaceDE", "w:autoSpaceDN", "w:bidi", "w:adjustRightInd",
    "w:snapToGrid", "w:spacing", "w:ind", "w:contextualSpacing", "w:mirrorIndents",
    "w:suppressOverlap", "w:jc", "w:textDirection", "w:textAlignment",
    "w:textboxTightWrap", "w:outlineLvl", "w:divId", "w:cnfStyle", "w:rPr", "w:sectPr",
    "w:pPrChange")
_MD_RPR_AFTER_SHD = ("w:fitText", "w:vertAlign", "w:rtl", "w:cs", "w:em", "w:lang",
                     "w:eastAsianLayout", "w:specVanish", "w:oMath")


def _md_put(parent, el, after: tuple):
    """`el` a `parent`-be, az `after` elemei közül az első meglévő elé."""
    parent.insert_element_before(el, *after)


def _md_runs(par, runs):
    """A sorközi darabok futamokként; a link valódi hivatkozás (w:hyperlink)."""
    from docx.opc.constants import RELATIONSHIP_TYPE as RT
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt, RGBColor
    for text, fmt in runs:
        if not text:
            continue
        url = fmt.get("link") or ""
        web = url.startswith(("http://", "https://", "mailto:"))
        r = par.add_run()
        for k, part in enumerate(text.split("\n")):
            if k:
                r.add_break()
            if part:
                r.add_text(part)
        f = r.font
        f.bold = fmt.get("b") or None
        f.italic = fmt.get("i") or fmt.get("img") or None
        f.strike = fmt.get("s") or None
        if fmt.get("code"):
            f.name = MD_MONO
            f.size = Pt(MD_SIZE - 1)
            shd = OxmlElement("w:shd")
            shd.set(qn("w:val"), "clear")
            shd.set(qn("w:fill"), "F2F2F2")
            _md_put(r._r.get_or_add_rPr(), shd, _MD_RPR_AFTER_SHD)
        if fmt.get("img"):
            f.color.rgb = RGBColor(0x80, 0x80, 0x80)
        if web:
            f.color.rgb = RGBColor(0x05, 0x63, 0xC1)
            f.underline = True
            rid = par.part.relate_to(url, RT.HYPERLINK, is_external=True)
            link = OxmlElement("w:hyperlink")
            link.set(qn("r:id"), rid)
            r._r.addprevious(link)
            link.append(r._r)


def _md_shade(par, fill="F2F2F2"):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:fill"), fill)
    _md_put(par._p.get_or_add_pPr(), shd, _MD_PPR_AFTER_SHD)


def _md_hr(par):
    """Vízszintes vonal: a bekezdés alsó szegélye."""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    bdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    for k, v in (("val", "single"), ("sz", "6"), ("space", "1"), ("color", "A6A6A6")):
        bottom.set(qn(f"w:{k}"), v)
    bdr.append(bottom)
    _md_put(par._p.get_or_add_pPr(), bdr, ("w:shd",) + _MD_PPR_AFTER_SHD)


def _md_numbering(doc, style: str, start: int) -> int:
    """Új számozás a stílus listájára — minden számozott lista 1-től (vagy a
    Markdownban megadott számtól) indul, nem folytatja az előzőt."""
    numbering = doc.part.numbering_part.element
    num_id = doc.styles[style].element.pPr.numPr.numId.val
    abstract = numbering.num_having_numId(num_id).abstractNumId.val
    num = numbering.add_num(abstract)
    num.add_lvlOverride(ilvl=0).add_startOverride(start)
    return num.numId


def _md_write(doc, blocks, depth: int = 0, quote: bool = False):
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt
    sfx = "" if depth <= 1 else f" {min(depth, 3)}"
    for b in blocks:
        kind = b[0]
        if kind == "h":
            _md_runs(doc.add_paragraph(style=f"Heading {b[1]}"), md_inline(b[2]))
        elif kind == "p":
            style = "Quote" if quote else (f"List Continue{sfx}" if depth else None)
            _md_runs(doc.add_paragraph(style=style), md_inline(b[1]))
        elif kind == "code":
            p = doc.add_paragraph()
            p.paragraph_format.space_after = Pt(6)
            _md_shade(p)
            r = p.add_run()
            r.font.name, r.font.size = MD_MONO, Pt(MD_SIZE - 1.5)
            for k, ln in enumerate(b[1].split("\n")):
                if k:
                    r.add_break()
                r.add_text(ln)
        elif kind == "hr":
            _md_hr(doc.add_paragraph())
        elif kind == "quote":
            _md_write(doc, b[1], depth, quote=True)
        elif kind == "table":
            head, aligns, rows = b[1], b[2], b[3]
            cols = len(head)
            t = doc.add_table(rows=1 + len(rows), cols=cols)
            t.style = "Table Grid"
            al = {"left": WD_ALIGN_PARAGRAPH.LEFT, "center": WD_ALIGN_PARAGRAPH.CENTER,
                  "right": WD_ALIGN_PARAGRAPH.RIGHT}
            for ri, row in enumerate([head] + rows):
                for ci in range(cols):
                    cell = t.cell(ri, ci)
                    p = cell.paragraphs[0]
                    p.alignment = al[aligns[ci] if ci < len(aligns) else "left"]
                    txt = row[ci] if ci < len(row) else ""
                    _md_runs(p, md_inline(txt, {"b": True} if ri == 0 else None))
                    if ri == 0:
                        _md_shade(cell.paragraphs[0], "E7E6E6")
            doc.add_paragraph()                     # a következő bekezdés ne tapadjon rá
        elif kind == "list":
            ordered, start, items = b[1], b[2], b[3]
            lvl = min(depth + 1, 3)
            style = ("List Number" if ordered else "List Bullet") + ("" if lvl == 1 else f" {lvl}")
            num_id = _md_numbering(doc, style, start) if ordered else None
            for text, sub in items:
                p = doc.add_paragraph(style=style)
                if num_id is not None:
                    numpr = p._p.get_or_add_pPr().get_or_add_numPr()
                    numpr.get_or_add_ilvl().val = 0
                    numpr.get_or_add_numId().val = num_id
                m = re.match(r"\[([ xX])\]\s+", text)  # feladatlista: ☐ / ☒
                if m:
                    text = ("☒ " if m.group(1) != " " else "☐ ") + text[m.end():]
                _md_runs(p, md_inline(text))
                _md_write(doc, sub, depth + 1, quote)


def md_to_docx(md_text: str, dst: str) -> dict:
    """Markdown-szöveg -> .docx. -> számlálók a visszajelzéshez (címsor, táblázat, kép)."""
    import docx
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt
    text = re.sub(r"<!--.*?-->", "", md_text.replace("\r\n", "\n").replace("\r", "\n"),
                  flags=re.S)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)   # XML-ben tiltott vezérlőjel
    m = re.match(r"---\n.*?\n---\n", text, re.S)     # YAML-előfej: nem tartalom
    if m:
        text = text[m.end():]
    blocks = md_blocks(text.split("\n"))

    doc = docx.Document()
    sec = doc.sections[0]                           # A4, 2,5 cm-es margó (nem Letter)
    sec.page_width, sec.page_height = Cm(21), Cm(29.7)
    for side in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
        setattr(sec, side, Cm(2.5))
    normal = doc.styles["Normal"]
    normal.font.name, normal.font.size = MD_FONT, Pt(MD_SIZE)
    rpr = normal.element.get_or_add_rPr()
    fonts = rpr.find(qn("w:rFonts"))
    for k in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        fonts.set(qn(k), MD_FONT)
    lang = OxmlElement("w:lang")                    # magyar helyesírás-ellenőrzés
    lang.set(qn("w:val"), "hu-HU")
    _md_put(rpr, lang, ("w:eastAsianLayout", "w:specVanish", "w:oMath"))

    _md_write(doc, blocks)
    title = next((b[2] for b in blocks if b[0] == "h"), "")
    doc.core_properties.title = "".join(t for t, _ in md_inline(title))
    doc.save(dst)

    stat = {"h": 0, "table": 0, "list": 0, "img": 0}

    def count(bs):
        for b in bs:
            if b[0] in stat:
                stat[b[0]] += 1
            if b[0] == "quote":
                count(b[1])
            if b[0] == "list":
                for _, sub in b[3]:
                    count(sub)
    count(blocks)
    stat["img"] = len(re.findall(r"!\[[^\]]*\]\(", text))
    return stat


def docx_available() -> bool:
    try:
        import docx  # noqa: F401
        return True
    except ImportError:
        return False


class MdDocxTab(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.path = None
        self.open_after = tk.BooleanVar(value=True)
        self._build()

    def _build(self):
        top = ttk.Frame(self)
        top.pack(fill="both", expand=True, padx=10, pady=10)
        self.files = FileList(top, "Átalakítandó Markdown-fájl (.md)", MD_EXT, self._pick,
                              height=8, memory_key="md_mappa")
        self.files.pack(fill="both", expand=True)
        self.lbl = ttk.Label(top, text="(nincs kiválasztva)", foreground="#555")
        self.lbl.pack(anchor="w", pady=(6, 0))
        ttk.Label(top, foreground="#555", justify="left", text=(
            "Átkerül: címsorok, bekezdések, félkövér / dőlt / áthúzott, kód, listák "
            "(beágyazva is), táblázatok, idézet, vízszintes vonal, linkek.\n"
            "A képek helyén „[kép: …]” jelölő áll. A Word saját stílusait kapja "
            "(Címsor 1…, Felsorolás…), A4-es lapon.")).pack(anchor="w", pady=(4, 0))
        if not docx_available():
            ttk.Label(top, foreground="#b00020", text=(
                "A python-docx nincs telepítve — parancssorból: pip install python-docx"
            )).pack(anchor="w", pady=(6, 0))
        row = ttk.Frame(top)
        row.pack(fill="x", pady=6)
        ttk.Checkbutton(row, text="Megnyitás mentés után",
                        variable=self.open_after).pack(side="left")
        self.btn = ttk.Button(row, text="Átalakítás és mentés…", command=self._run)
        self.btn.pack(side="right")

    def set_folder(self, folder):
        self.files.set_folder(folder)

    def set_worker(self, name, force=False):
        self.files.set_folder(*self.app.list_target())

    def _pick(self, path):
        self.path = path
        self.lbl.configure(text=os.path.basename(path))

    def _run(self, dst=None):
        if not self.path:
            messagebox.showwarning("Nincs fájl", "Válassz ki egy Markdown-fájlt.")
            return
        if not docx_available():
            messagebox.showerror("Hiányzó csomag", "A Word-irat írásához kell a python-docx.\n\n"
                                 "Telepítés parancssorból:\n  pip install python-docx")
            return
        stem = os.path.splitext(os.path.basename(self.path))[0]
        dst = dst or filedialog.asksaveasfilename(
            title="Mentés másként", initialdir=os.path.dirname(self.path),
            initialfile=f"{stem}.docx", defaultextension=".docx",
            filetypes=[("Word-irat", "*.docx")])
        if not dst:
            return
        try:
            self.app.status("Átalakítás…")
            stat = md_to_docx(md_read(self.path), dst)
        except PermissionError:
            messagebox.showerror("Nem írható", f"{dst}\n\nNyitva van a Wordben? Zárd be, "
                                 "és próbáld újra.")
            self.app.status("Hiba.")
            return
        except Exception as e:
            traceback.print_exc()
            messagebox.showerror("Hiba", f"{type(e).__name__}: {e}")
            self.app.status("Hiba.")
            return
        note = f"{stat['h']} címsor, {stat['list']} lista, {stat['table']} táblázat"
        if stat["img"]:
            note += f" · {stat['img']} kép csak jelölőként"
        self.app.refresh_all()                      # előbb: a frissítés is állapotot ír
        self.app.status(f"Kész: {os.path.basename(dst)} — {note}")
        if self.open_after.get():
            open_path(dst)
        return dst


# ─────────────────────── Eszközök: szerkesztés (PDF-szerkesztő) ───────────────────────
# Általános szerkesztő kész PDF-ekhez (szerkeszto-terv.md 16.): szöveg átírása, új
# szöveg és X, űrlapmezők (a DocGen PDF-sablonjához), kitakarás. Szöveg mindig
# TextWriterrel kerül a lapra: az insert_text(fontname="helv") elrontja az ő/ű-t (0.2).
# ponytail: forgatott lapot (/Rotate) nem szerkesztünk — a fül szól; ha kell, a
# koordinátákat a page.derotation_matrix-szal kell átváltani, mint a PlacerTab-ban.

EDIT_FONTS = {"Helvetica": None, "Calibri": "calibri.ttf", "Arial": "arial.ttf",
              "Times New Roman": "times.ttf"}
# A négy betűváltozat fájlja: sima, félkövér, dőlt, félkövér dőlt. A Helveticának
# nincs fájlja: a PDF beépített base14 neveit használjuk (HELV14).
EDIT_VARIANTS = {
    "Calibri":         ("calibri.ttf", "calibrib.ttf", "calibrii.ttf", "calibriz.ttf"),
    "Arial":           ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"),
    "Times New Roman": ("times.ttf", "timesbd.ttf", "timesi.ttf", "timesbi.ttf"),
}
HELV14 = ("helv", "hebo", "heit", "hebi")
# A PDF-betűnév nem mindig a család neve; a gyakori végződéseket névvel oldjuk fel.
# A „NimbusSans” a beépített Helvetica beágyazott neve (a PyMuPDF ezt teszi a lapra a
# `helv` betűnél) — ugyanazzal a metrikával mérhető vissza, ezért pontos. A NimbusRoman
# és a NimbusMonoPS szándékosan NEM szerepel: azokat a rendszer Times-ával mérnénk, ami
# más szélességeket adna. Ismeretlen családnál a formázás inkább megtagadja magát, mint
# hogy rossz szélességgel írjon (szerkeszto-terv.md 19.2).
FONT_ALIAS = {"arialmt": "Arial", "timesnewromanpsmt": "Times New Roman",
              "timesnewromanps": "Times New Roman", "nimbussans": "Helvetica"}
STYLE_WORDS = {"regular", "normal", "bold", "italic", "oblique", "bolditalic",
               "boldoblique"}
LINE_MAX = 1.6            # ennél vékonyabb kitöltött téglalap vonalnak számít (pt)
SNAP_MAX = 60             # a kattintástól legfeljebb ennyire keresünk vonalat (pt)
BOX_MIN, BOX_MAX = 6, 16  # a jelölőnégyzet oldala (pt)
UNDERLINE_H = 14          # aláhúzásos rovat: ilyen magas sáv a vonal fölött

# ── bekezdés-formázás (szerkeszto-terv.md 19.) ──────────────────────────────
PARA_GAP_TOL = 0.25       # az alapvonal-távolság ennyivel térhet el a mediántól
PARA_SIZE_TOL = 0.3       # a betűméret eltérése egy bekezdésen belül (pt)
# A betűméret ennyiszeresénél nagyobb alapvonal-távolság már nem sortávolság, hanem
# bekezdések közti térköz. Egysoros bekezdésnél ez a kapu kell: ott nincs saját
# sortávolság, és a becslés a KÖVETKEZŐ bekezdésig mérne, összevonva a kettőt.
PARA_MAX_GAP = 3.0
# A sor bekezdést zár, ha a hasáb szélességének ennyi részét sem éri el. Mérve a
# TAJ-meghatalmazás 7 soros bekezdésén: a belső sorok 88–100%-ig érnek, a valódi
# utolsó sor 36%-ig — a kettő között bőven van hely (szerkeszto-terv.md 19.5).
PARA_RAGGED = 0.65
# Sorkizártnál csak azt a sort nyújtjuk, amelyik a hasáb ennyi részét kitölti. Nem a
# hézag nagyságát korlátozzuk: egy hosszú magyar szó („Társadalombiztosítási”, 10,5
# pt-on ~100 pt) legitim lyukat hagy a sor végén, amit a Word is megnyújt. A mért
# értékek ugyanazon a bekezdésen: belső sorok 82–100%, a valódi utolsó sor 36%.
JUSTIFY_MIN_FILL = 0.6
PARA_ALIGNS = (("left", "Balra"), ("center", "Középre"), ("right", "Jobbra"),
               ("justify", "Sorkizárt"))
UNCHANGED = "(változatlan)"   # a betűcsalád-lista első eleme: ne nyúljunk a betűhöz


def _font_idx(bold: bool, italic: bool) -> int:
    return (2 if italic else 0) + (1 if bold else 0)


def _font_path(name: str, bold: bool = False, italic: bool = False) -> str:
    v = EDIT_VARIANTS.get(name)
    f = v[_font_idx(bold, italic)] if v else EDIT_FONTS.get(name)
    return os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", f) if f else ""


def edit_fonts() -> list:
    """A választható betűk: a beépített Helvetica és a gépen meglévő rendszerbetűk."""
    return [n for n in EDIT_FONTS if not EDIT_FONTS[n] or os.path.exists(_font_path(n))]


_FONT_CACHE = {}


def edit_font(name: str, bold: bool = False, italic: bool = False) -> "pymupdf.Font":
    """A betű objektuma, gyorsítótárból: a valós idejű formázás minden
    billentyűre újrarajzol, és egy TTF megnyitása (a Calibri 1,5 MB) önmagában
    érezhető késés lenne. A Font objektum bármelyik dokumentumhoz használható."""
    p = _font_path(name, bold, italic)
    key = (p if p and os.path.exists(p) else "", _font_idx(bold, italic))
    if key not in _FONT_CACHE:
        _FONT_CACHE[key] = (pymupdf.Font(fontfile=key[0]) if key[0]
                            else pymupdf.Font(HELV14[key[1]]))
    return _FONT_CACHE[key]


def page_lines(drawings) -> tuple:
    """A lap vonalai: vízszintes [(y, x0, x1)] és függőleges [(x, y0, y1)]. Vonal a
    vékony kitöltött téglalap (a Word így rajzolja a táblázatot), a szakasz és a
    keretes téglalap négy oldala."""
    H, V = [], []
    for g in drawings:
        for it in g["items"]:
            if it[0] == "l":
                a, b = it[1], it[2]
                if abs(a.y - b.y) < 0.5:
                    H.append((a.y, min(a.x, b.x), max(a.x, b.x)))
                elif abs(a.x - b.x) < 0.5:
                    V.append((a.x, min(a.y, b.y), max(a.y, b.y)))
            elif it[0] in ("re", "qu"):
                r = it[1] if it[0] == "re" else it[1].rect
                if "f" in g["type"] and min(r.width, r.height) < LINE_MAX:
                    if r.height < LINE_MAX:
                        H.append(((r.y0 + r.y1) / 2, r.x0, r.x1))
                    else:
                        V.append(((r.x0 + r.x1) / 2, r.y0, r.y1))
                elif "s" in g["type"]:
                    H += [(r.y0, r.x0, r.x1), (r.y1, r.x0, r.x1)]
                    V += [(r.x0, r.y0, r.y1), (r.x1, r.y0, r.y1)]
    return H, V


def snap_cell(lines, x: float, y: float):
    """A pontot közrefogó cella a vonalakból; aláhúzásos rovatnál (alatta vonal,
    fölötte nincs közel) a vonal fölötti sáv. None, ha nincs a közelben vonal."""
    H, V = lines
    over = [h for h in H if h[1] - 1 <= x <= h[2] + 1]
    below = [h for h in over if 0 < h[0] - y <= SNAP_MAX]
    if not below:
        return None
    y1 = min(h[0] for h in below)
    above = [h[0] for h in over if 0 < y - h[0] <= SNAP_MAX]
    if not above:
        h = min((h for h in below if h[0] == y1), key=lambda h: h[2] - h[1])
        return pymupdf.Rect(h[1], y1 - UNDERLINE_H, h[2], y1)
    y0 = max(above)
    mid = (y0 + y1) / 2
    cross = [v[0] for v in V if v[1] - 1 <= mid <= v[2] + 1]
    left = [vx for vx in cross if vx < x - 0.5]
    right = [vx for vx in cross if vx > x + 0.5]
    edge = [h for h in over if abs(h[0] - y1) < 0.5]
    x0 = max(left) if left else min(h[1] for h in edge)
    x1 = min(right) if right else max(h[2] for h in edge)
    return pymupdf.Rect(x0, y0, x1, y1)


def snap_cells(lines, rect) -> list:
    """Egy kijelölt sáv betűnkénti cellái balról jobbra: a sáv közepén átérő
    függőleges vonalak határolják őket. Üres lista, ha nincs legalább két cella."""
    mid = snap_cell(lines, (rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2)
    if mid is None:
        return []
    ym = (mid.y0 + mid.y1) / 2
    cross = sorted({round(v[0], 2) for v in lines[1] if v[1] - 1 <= ym <= v[2] + 1})
    # A sáv két végén lévő cella is teljes: a bal határ a kezdőpont előtti vonal.
    lo = max([x for x in cross if x <= rect.x0 + 0.5], default=rect.x0)
    hi = min([x for x in cross if x >= rect.x1 - 0.5], default=rect.x1)
    xs = [x for x in cross if lo <= x <= hi]
    cells = [pymupdf.Rect(a, mid.y0, b, mid.y1) for a, b in zip(xs, xs[1:]) if b - a > 2]
    return cells if len(cells) >= 2 else []


def snap_box(drawings, x: float, y: float):
    """A pontot tartalmazó kis keretes négyzet (jelölőnégyzet), vagy None. A rajz-
    csoporton belül téglalaponként nézzük: egy csoportban több alakzat is lehet."""
    for g in drawings:
        if "s" not in g["type"]:
            continue
        for it in g["items"]:
            if it[0] not in ("re", "qu"):
                continue
            r = it[1] if it[0] == "re" else it[1].rect
            if (BOX_MIN <= r.width <= BOX_MAX and BOX_MIN <= r.height <= BOX_MAX
                    and abs(r.width - r.height) < 2 and r.contains(pymupdf.Point(x, y))):
                return r
    return None


def span_at(page, x: float, y: float):
    """A pont alatti szövegdarab (span: szöveg, betű, méret, alapvonal), vagy None."""
    for b in page.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            for s in ln["spans"]:
                if s["text"].strip() and pymupdf.Rect(s["bbox"]).contains(pymupdf.Point(x, y)):
                    return s
    return None


def span_font(doc, page, span, text: str, fallback):
    """A span saját beágyazott betűje, ha az új szöveg minden betűje megvan benne.
    -> (betű, saját-e). A részhalmazos betűből a hiányzó betű nem rajzolható."""
    want = span["font"].split("+")[-1]
    for f in page.get_fonts():
        if f[3].split("+")[-1] != want:
            continue
        try:
            _n, ext, _t, buf = doc.extract_font(f[0])
            if ext == "n/a" or not buf:
                break
            font = pymupdf.Font(fontbuffer=buf)
            if all(font.has_glyph(ord(c)) for c in text if not c.isspace()):
                return font, True
        except Exception:
            pass
        break
    return fallback, False


def add_text(page, origin, text: str, font, size: float, color=(0, 0, 0)):
    """Szöveg a lapra. A szóközt nem írjuk ki: egyes TrueType betűknél (Calibri,
    Arial) a szövegréteg nem-törő szóközt (U+00A0) adna vissza, ami keresésnél,
    másolásnál és a szövegrétegből címkézésnél zavar. Szavanként írunk, a szóköz
    szélességével léptetve — a kinyerés a hézagból rendes szóközt tesz."""
    tw = pymupdf.TextWriter(page.rect, color=color)
    x, y = origin
    sp = font.text_length(" ", size)
    for w in text.split(" "):
        if w:
            tw.append((x, y), w, font=font, fontsize=size)
        x += font.text_length(w, size) + sp
    tw.write_text(page)


def _redact(page, rects, fill=False, images=pymupdf.PDF_REDACT_IMAGE_NONE,
            graphics=pymupdf.PDF_REDACT_LINE_ART_NONE):
    """Egy téglalap vagy több: az alkalmazás egyszer fut (a lap tartalmát írja újra)."""
    for r in [rects] if isinstance(rects, pymupdf.Rect) else rects:
        page.add_redact_annot(r, fill=fill)
    page.apply_redactions(images=images, graphics=graphics)


def rewrite_span(doc, page, span, text: str, fallback) -> bool:
    """A span szövegének cseréje: a régi TÉNYLEGESEN törlődik (redakció — a vonalak
    és a képek maradnak), az új ugyanarra az alapvonalra, ugyanakkora betűvel és
    színnel. Üres szöveg = törlés. -> a saját betűjével írtuk-e (False: fallback)."""
    font, own = span_font(doc, page, span, text, fallback)
    r = pymupdf.Rect(span["bbox"])
    d = r.height * 0.15                  # a szomszéd sor betűi ne essenek bele
    _redact(page, pymupdf.Rect(r.x0, r.y0 + d, r.x1, r.y1 - d))
    if text.strip():
        add_text(page, span["origin"], text, font, span["size"],
                 color=pymupdf.sRGB_to_pdf(span["color"]))
    return own


def toggle_x(page, box, font) -> bool:
    """Jelölőnégyzet: ha van benne X, törli; ha nincs, ráírja. -> bejelölt-e most."""
    inner = pymupdf.Rect(box.x0 + 1, box.y0 + 1, box.x1 - 1, box.y1 - 1)
    if any(pymupdf.Rect(w[:4]).intersects(inner) and w[4].strip().lower() in ("x", "✓", "✔")
           for w in page.get_text("words")):
        _redact(page, inner)
        return False
    s = box.height * 0.9
    add_text(page, (box.x0 + (box.width - font.text_length("X", s)) / 2,
                    box.y0 + box.height / 2 + s * 0.35), "X", font, s)
    return True


def erase_area(page, rect):
    """Kitakarás: a terület szövege, képpontjai és teljesen benne lévő vonalai
    végleg törlődnek, a helye fehér."""
    _redact(page, rect, fill=(1, 1, 1), images=pymupdf.PDF_REDACT_IMAGE_PIXELS,
            graphics=pymupdf.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED)


def add_field(page, rect, name: str, check: bool = False):
    """Űrlapmező a DocGen PDF-sablonjához: a név a DocGen-jelölő (DocGen/TERV-pdf-
    nyomtatvany.md 11.). Keret és háttér nélkül, automatikus betűmérettel."""
    w = pymupdf.Widget()
    w.field_type = pymupdf.PDF_WIDGET_TYPE_CHECKBOX if check else pymupdf.PDF_WIDGET_TYPE_TEXT
    w.field_name = name
    w.rect = pymupdf.Rect(rect)
    w.border_width = 0
    w.text_fontsize = 0
    return page.add_widget(w)


def rename_field(doc, widget, name: str):
    """A mező átnevezése: a /T kulcs közvetlenül — a Widget.update() a nevet nem írja."""
    doc.xref_set_key(widget.xref, "T", pymupdf.get_pdf_str(name))


UPPER_KW = "docgen-nagybetu"     # a DocGen-sablon kulcsszava: nagybetűvel kitöltendő


def _kw_tokens(doc) -> list:
    return [t.strip() for t in ((doc.metadata or {}).get("keywords") or "").split(";") if t.strip()]


def get_upper(doc) -> bool:
    """Nagybetűs kitöltést kér-e a sablon (pl. „nyomtatott nagybetűkkel kell kitölteni”)."""
    return UPPER_KW in _kw_tokens(doc)


def set_upper(doc, on: bool):
    """A jelölő a /Keywords-ben, a többi kulcsszó (bélyeg, DocGen-jel) megmarad. A DocGen
    ennek láttán minden értéket nagybetűvel ír (DocGen/TERV-pdf-nyomtatvany.md 12.)."""
    t = [x for x in _kw_tokens(doc) if x != UPPER_KW] + ([UPPER_KW] if on else [])
    m = dict(doc.metadata or {})
    m["keywords"] = ";".join(t)
    doc.set_metadata(m)


def field_at(page, x: float, y: float):
    for w in page.widgets():
        if w.rect.contains(pymupdf.Point(x, y)):
            return w
    return None


def field_name_error(name: str) -> str:
    """Üres szöveg, ha a mezőnév jó; különben a hiba oka."""
    if not name.strip():
        return "A mezőnév nem lehet üres."
    if "." in name:
        return "A mezőnévben nem lehet pont (a PDF a pontot szintjelnek olvassa)."
    return ""


# ── bekezdés-formázás (szerkeszto-terv.md 19.) ──────────────────────────────
def span_style(span) -> tuple:
    """A span stílusa: (betűcsalád, félkövér, dőlt). A családot a PDF-betűnévből
    olvassuk (a `ABCDEF+` részhalmaz-előtag és a stílusvégződés levágva), a
    vastagságot és a dőlést a MuPDF már kiszámolt flagjeiből. A család None, ha
    nincs hozzá rendszerbetűnk."""
    name = span["font"].split("+")[-1].split(",")[0].split("-")[0]
    # A mentés (subset_fonts) után a PyMuPDF a betűt „Calibri Regular”, „Calibri
    # Bold Italic” néven teszi vissza: a szóközzel írt stílusszó nem a család része.
    # Enélkül a saját mentett iratunk bekezdését sem lehetett újra formázni.
    words = name.split()
    while len(words) > 1 and words[-1].lower() in STYLE_WORDS:
        words.pop()
    key = "".join(words).lower()
    fam = FONT_ALIAS.get(key) or next(
        (f for f in EDIT_FONTS if f.lower().replace(" ", "") == key), None)
    return fam, bool(span["flags"] & 16), bool(span["flags"] & 2)


def style_font(span):
    """A span stílusához tartozó betű (rendszerbetű, Helveticánál a PDF beépítettje),
    vagy None, ha a családot nem tudjuk pontosan mérni. A beágyazott betűt szándékosan
    nem használjuk: Identity-H cmap-pel a has_glyph minden karakterre hamis, a
    text_length pedig 17%-ot téved — mérve a TAJ-meghatalmazáson (19.2)."""
    fam, b, i = span_style(span)
    if not fam:
        return None
    p = _font_path(fam, b, i)
    return edit_font(fam, b, i) if not p or os.path.exists(p) else None


def line_words(line) -> list:
    """A sor szavai: [[(részszöveg, span), …], …]. Egy szó több span-ból is állhat
    (félkövér szótag a szó közepén), ezért részenként tartjuk meg a stílust — így
    marad meg a vegyes formázás az eltolásos úton."""
    out, cur = [], []
    for s in line["spans"]:
        for c in s["text"]:
            if c.isspace():
                if cur:
                    out.append(cur)
                    cur = []
            elif cur and cur[-1][1] is s:
                cur[-1] = (cur[-1][0] + c, s)
            else:
                cur.append((c, s))
    if cur:
        out.append(cur)
    return out


def _baseline(line) -> float:
    return line["spans"][0]["origin"][1]


def _line_size(line) -> float:
    return max(s["size"] for s in line["spans"])


def text_lines(page) -> list:
    """A lap összes szövegsora alapvonal szerint rendezve. Szándékosan NEM a MuPDF
    szövegblokkjait használjuk: formázás után a MuPDF ugyanazt a bekezdést soronként
    külön blokkba teszi (mérve: 1,5-es sortávolságnál mind a 7 sor külön blokk lett),
    így a bekezdés nem lenne újra felismerhető, és a második művelet elbukna rajta."""
    return sorted((ln for b in page.get_text("dict")["blocks"] for ln in b.get("lines", [])
                   if any(s["text"].strip() for s in ln["spans"])), key=_baseline)


def _overlaps(a, b) -> bool:
    """Két sor egy hasábban van-e: fedik-e egymást vízszintesen."""
    return min(a["bbox"][2], b["bbox"][2]) > max(a["bbox"][0], b["bbox"][0])


def paragraph_at(page, x: float, y: float):
    """A pontot tartalmazó bekezdés. A kattintott sorral egy hasábban lévő sorokat
    addig fűzzük össze, amíg az alapvonal-távolság a bekezdés távolságának
    ±PARA_GAP_TOL-ján belül van és a betűméret ugyanaz; a futamot aztán ott vágjuk,
    ahol egy sor bekezdést zár (a hasáb PARA_RAGGED részénél hamarabb véget ér).
    -> szótár, vagy None, ha a pont nem szövegen van."""
    allp = text_lines(page)
    i = None
    for k, ln in enumerate(allp):
        b = ln["bbox"]
        if (b[0] - 2 <= x <= b[2] + 2 and b[1] - 2 <= y <= b[3] + 2
                and (i is None or abs(_baseline(ln) - y) < abs(_baseline(allp[i]) - y))):
            i = k
    if i is None:
        return None
    # Csak a kattintott sorral egy hasábban lévő sorok: hasábos lapon a másik hasáb
    # sorai alapvonal szerint közéjük keverednének, és elvágnák a bekezdést.
    hit = allp[i]
    lines = [ln for ln in allp if _overlaps(ln, hit)]
    i = lines.index(hit)

    def fits(a, b, gap) -> bool:
        return (abs(_line_size(b) - _line_size(a)) <= PARA_SIZE_TOL
                and abs((_baseline(b) - _baseline(a)) - gap) <= gap * PARA_GAP_TOL)

    def gap_to(d):
        j = i + d
        return (abs(_baseline(lines[j]) - _baseline(hit)) if 0 <= j < len(lines)
                and abs(_line_size(lines[j]) - _line_size(hit)) <= PARA_SIZE_TOL else None)

    big = _line_size(hit) * PARA_MAX_GAP
    cand = [g for g in (gap_to(-1), gap_to(1)) if g and g <= big]
    gap = min(cand) if cand else _line_size(hit) * 1.2
    # Első kör: a méret- és távolságtartó futam — ebből becsüljük a hasáb jobb szélét.
    lo = hi = i
    while lo > 0 and fits(lines[lo - 1], lines[lo], gap):
        lo -= 1
    while hi < len(lines) - 1 and fits(lines[hi], lines[hi + 1], gap):
        hi += 1
    col = max(lines[k]["bbox"][2] for k in range(lo, hi + 1))

    def closes(ln) -> bool:            # rövid sor: itt ért véget a bekezdés
        b = ln["bbox"]
        return b[2] - b[0] < (col - b[0]) * PARA_RAGGED

    a = b = i                          # Második kör: vágás a bekezdést záró sorokon
    while a > lo and not closes(lines[a - 1]):
        a -= 1
    while b < hi and not closes(lines[b]):
        b += 1
    ls = lines[a:b + 1]
    bases = [_baseline(ln) for ln in ls]
    gaps = sorted(q - p for p, q in zip(bases, bases[1:]))
    # A bal szél a nem-első sorokból: így az első sor behúzása nem rontja el.
    left = min(ln["bbox"][0] for ln in ls[1:]) if len(ls) > 1 else ls[0]["bbox"][0]
    styles = {(s["font"], round(s["size"], 1)) for ln in ls for s in ln["spans"]}
    bb = [ln["bbox"] for ln in ls]
    return {"lines": ls, "words": [line_words(ln) for ln in ls],
            "left": left, "right": max(q[2] for q in bb),
            "gap": gaps[len(gaps) // 2] if gaps else gap,
            "indent": ls[0]["bbox"][0] - left, "size": _line_size(ls[0]),
            "mixed": len(styles) > 1,
            "bbox": pymupdf.Rect(min(q[0] for q in bb), min(q[1] for q in bb),
                                 max(q[2] for q in bb), max(q[3] for q in bb))}


def guess_align(para) -> str:
    """A bekezdés mai igazítása a sorok széleiből — csak a panel előtöltéséhez, a
    felhasználó felülírhatja.

    Legalább három sor kell hozzá. A bekezdés jobb széle ugyanis magukból a soraiból
    jön, így a leghosszabb sor MINDIG a jobb szélen van: két sornál az egyetlen
    vizsgálható sor (az utolsó előtti) éppen ez lehet, és a balra zárt bekezdés is
    sorkizártnak látszana. Kevés sornál ezért „left” — az nem változtat semmit, ha a
    felhasználó nem állítja át."""
    ls = para["lines"]
    if len(ls) < 3:
        return "left"
    body, L, R = ls[:-1], para["left"], para["right"]   # az utolsó sor mindig rövid
    tol = para["size"] * 0.3
    if all(abs(ln["bbox"][2] - R) <= tol for ln in body):
        return "justify" if all(abs(ln["bbox"][0] - L) <= tol for ln in body) else "right"
    if all(abs((ln["bbox"][0] + ln["bbox"][2]) / 2 - (L + R) / 2) <= tol for ln in body):
        return "center"
    return "left"


def line_positions(widths, x0: float, x1: float, space_w: float, align: str,
                   last: bool = False) -> list:
    """Egy sor szavainak kezdő x-pozíciói — tiszta függvény. Sorkizártnál a szóközök
    nyúlnak, hogy az utolsó szó a jobb szélen érjen véget; az utolsó sort és az
    egyszavas sort nem nyújtjuk. Üres lista: a sort nem szabad sorkizárttá tenni."""
    n = len(widths)
    if not n:
        return []
    total, gap = sum(widths), space_w
    if align == "justify" and not last and n > 1:
        gap = (x1 - x0 - total) / (n - 1)
        if total < (x1 - x0) * JUSTIFY_MIN_FILL or gap < space_w * 0.5:
            return []                  # félreismert bekezdésvég vagy túltömött sor
    span = total + gap * (n - 1)
    x = x0 if align in ("left", "justify") else (
        x1 - span if align == "right" else (x0 + x1 - span) / 2)
    out = []
    for w in widths:
        out.append(x)
        x += w + gap
    return out


def wrap_words(widths, space_w: float, width: float, first_width: float = None) -> list:
    """Tördelés: a szavak indexei sorokra osztva. Az első sor szélessége külön adható
    meg (első sor behúzása). Elválasztás nincs — a szó egészben mozog (19.8)."""
    out, cur, x = [], [], 0.0
    for i, w in enumerate(widths):
        lim = width if out else (width if first_width is None else first_width)
        add = w + (space_w if cur else 0)
        if cur and x + add > lim:
            out.append(cur)
            cur, x, add = [], 0.0, w
        cur.append(i)
        x += add
    if cur:
        out.append(cur)
    return out


# Ezek a kulcsok újratördelést kényszerítenek: a szóhatárok megváltoznak, ezért a
# bekezdésen belüli vegyes formázás nem tartható meg (szerkeszto-terv.md 19.6).
REFLOW_KEYS = ("family", "size", "bold", "italic", "text",
               "indent_left", "indent_right", "indent_first")


def para_reflows(fmt: dict) -> bool:
    return bool(fmt.get("reflow")) or any(k in fmt for k in REFLOW_KEYS)


def para_text(para) -> str:
    """A bekezdés szövege egy sorban, a sorokat szóközzel fűzve. Az elválasztást nem
    oldjuk fel: a kötőjeles sorvég kötőjellel marad (szerkeszto-terv.md 19.8)."""
    return " ".join(" ".join("".join(t for t, _ in w) for w in ln) for ln in para["words"])


def _font_jobs(para, fmt: dict) -> list:
    """(betű, szöveg) párok, amiket a kiírás tényleg használni fog — ebből derül ki,
    hogy minden karakter kirajzolható-e."""
    fam = fmt.get("family")
    if fam:
        f = edit_font(fam, bool(fmt.get("bold")), bool(fmt.get("italic")))
        return [(f, fmt.get("text", para_text(para)))]
    if "text" in fmt:
        return [(style_font(para["lines"][0]["spans"][0]), fmt["text"])]
    return [(style_font(s), s["text"]) for ln in para["lines"] for s in ln["spans"]]


def para_font_error(para, fmt: dict) -> str:
    """Üres szöveg, ha a bekezdés formázható; különben miért nem.

    Két kapu. (1) Ha a bekezdés betűcsaládja nincs meg a gépen, nem nyúlunk hozzá: a
    beágyazott részhalmazzal nem lehet pontosan mérni, a csendes helyettesítés pedig
    láthatóan elrontaná a lapot (mérve: 17% szélességhiba — 19.2). (2) Ha a kiírásra
    használt betűből hiányzik egy karakter, az CSENDBEN eltűnne a lapról — az Arial
    Bold például nem ismeri a nem-törő kötőjelet (U+2010), amit a magyar iratok
    cégjegyzékszáma és címe használ (mérve a TAJ-meghatalmazáson)."""
    jobs = _font_jobs(para, fmt)
    if any(f is None for f, _ in jobs):
        bad = sorted({span_style(s)[0] or s["font"].split("+")[-1]
                      for ln in para["lines"] for s in ln["spans"] if style_font(s) is None})
        return ("A bekezdés betűje nincs meg a gépen: " + ", ".join(bad) +
                ". A formázás pontatlan lenne, ezért nem nyúlok hozzá. Válassz betűt a "
                "Betűcsalád listából, ha mégis át akarod formázni.")
    miss = sorted({c for f, t in jobs for c in t
                   if not c.isspace() and not f.has_glyph(ord(c))})
    if miss:
        return ("A választott betűben nincs meg ez a karakter: "
                + " ".join(f"{c} (U+{ord(c):04X})" for c in miss) +
                ". Csendben eltűnne a lapról, ezért nem formázok át.")
    return ""


def para_format(doc, page, para, fmt: dict) -> str:
    """A bekezdés formázása: a régi sorok redakcióval TÉNYLEGESEN törlődnek (a
    vonalak és a képek maradnak), az új elrendezés a helyükre kerül. Az fmt kulcsai
    mind elhagyhatók — csak a megváltoztatott értékeket add meg: align, reflow, gap,
    dy, family, size, bold, italic, underline, color, indent_left, indent_right,
    indent_first, text. -> figyelmeztetés a felhasználónak („” ha minden rendben)."""
    err = para_font_error(para, fmt)
    if err:
        return err
    align = fmt.get("align") or guess_align(para)
    size = float(fmt.get("size") or para["size"])
    fam = fmt.get("family")
    uni = edit_font(fam, bool(fmt.get("bold")), bool(fmt.get("italic"))) if fam else None
    gap = float(fmt.get("gap") or para["gap"])
    x0 = para["left"] + float(fmt.get("indent_left", 0))
    x1 = para["right"] - float(fmt.get("indent_right", 0))
    first = x0 + float(fmt.get("indent_first", para["indent"]))
    base0 = _baseline(para["lines"][0]) + float(fmt.get("dy", 0))
    color = fmt.get("color")
    resize = uni is not None or "size" in fmt

    cache = {}

    def sysfont(s):                    # egy betűfájl megnyitása szavanként drága
        k = (s["font"], s["flags"])
        if k not in cache:
            cache[k] = style_font(s)
        return cache[k]

    def parts_of(w):
        return [(t, uni or sysfont(s), size if resize else s["size"],
                 color if color is not None else pymupdf.sRGB_to_pdf(s["color"]))
                for t, s in w]

    if "text" in fmt:                  # a bekezdés szövegének átírása
        proto = para["lines"][0]["spans"][0]
        rows = [[[(w, proto)] for w in fmt["text"].split()]]
    else:
        rows = para["words"]
    words = [w for ln in rows for w in ln]
    if not words:
        return ""
    parts = [parts_of(w) for w in words]
    widths = [sum(f.text_length(t, sz) for t, f, sz, _ in p) for p in parts]
    ref = parts[0][0]
    space_w = ref[1].text_length(" ", ref[2])

    if para_reflows(fmt):
        idx = wrap_words(widths, space_w, x1 - x0, x1 - first)
    else:
        idx, k = [], 0
        for ln in rows:
            idx.append(list(range(k, k + len(ln))))
            k += len(ln)

    skipped, place, rules = 0, [], []
    for r, row in enumerate(idx):
        lx0 = first if r == 0 else x0
        ws = [widths[i] for i in row]
        xs = line_positions(ws, lx0, x1, space_w, align, last=(r == len(idx) - 1))
        if not xs:                     # sorkizártként nem megy: balra zárva írjuk
            xs = line_positions(ws, lx0, x1, space_w, "left")
            skipped += 1
        base = base0 + r * gap
        rules.append((base, xs[0], xs[-1] + ws[-1]))
        for i, x in zip(row, xs):
            place.append((x, base, parts[i]))

    # A régi sorok törlése: soronként, a rewrite_span 15%-os beljebb húzásával — a
    # szomszéd sor betűi ne essenek a redakcióba (16.4).
    _redact(page, [pymupdf.Rect(b[0], b[1] + (b[3] - b[1]) * 0.15,
                                b[2], b[3] - (b[3] - b[1]) * 0.15)
                   for b in (ln["bbox"] for ln in para["lines"])])

    writers = {}
    for x, base, ps in place:
        for t, f, sz, col in ps:
            writers.setdefault(col, pymupdf.TextWriter(page.rect)).append(
                (x, base), t, font=f, fontsize=sz)
            x += f.text_length(t, sz)
    for col, w in writers.items():
        w.write_text(page, color=col)
    if fmt.get("underline"):           # a PDF-ben nincs „aláhúzott szöveg”: vonal
        for base, a, b in rules:
            y = base + size * 0.12
            page.draw_line((a, y), (b, y), width=max(0.4, size * 0.05),
                           color=color or (0, 0, 0))

    msg = []
    if para_reflows(fmt) and para["mixed"]:
        msg.append("a bekezdés vegyes formázása egységes lett")
    if skipped:
        msg.append(f"{skipped} sor nem lett sorkizárt (a hézag túl nagy lett volna)")
    return "; ".join(msg)


# ── elhelyezett szöveg: élő objektum a mentésig (szerkeszto-terv.md 21.) ────
# Az új szöveg NEM íródik azonnal a PDF-be: a futás alatt objektum marad, ezért
# húzható, nyilakkal mozgatható, és a betűje, mérete, stílusa, színe, sőt a
# szövege is élőben állítható. A PDF-be a mentés írja (`write_placed`), ugyanazzal
# a TextWriter-úttal, amivel a vászon előnézete is készül — amit látsz, az kerül
# a lapra. A mentés után is élő marad (ugyanabban a futásban), csak a fájl
# újranyitásakor válik a lap tartalmává.
@dataclass(eq=False)             # azonosság szerint: a visszavonás másolatokat tart
class PlacedText:
    page: int
    x: float                  # az alapvonal kezdőpontja (pt)
    y: float
    text: str
    family: str = "Helvetica"
    size: float = 10.5
    bold: bool = False
    italic: bool = False
    underline: bool = False
    color: tuple = (0.0, 0.0, 0.0)
    uid: int = 0


def placed_font(t: PlacedText):
    return edit_font(t.family, t.bold, t.italic)


def placed_bbox(t: PlacedText) -> "pymupdf.Rect":
    """A szöveg befoglaló téglalapja a lapon: a betű felső és alsó kiterjedése, az
    aláhúzás vonalával. Üres szövegnél is van szélessége — kijelölhető maradjon."""
    f = placed_font(t)
    w = max(f.text_length(t.text, t.size), t.size * 0.6)
    top = t.y - f.ascender * t.size
    bot = t.y - f.descender * t.size
    if t.underline:
        bot = max(bot, t.y + t.size * 0.12 + max(0.4, t.size * 0.05))
    return pymupdf.Rect(t.x, top, t.x + w, bot)


def placed_missing(t: PlacedText) -> str:
    """A választott betűből hiányzó karakterek — csendben eltűnnének a lapról."""
    f = placed_font(t)
    return "".join(sorted({c for c in t.text if not c.isspace()
                           and not f.has_glyph(ord(c))}))


def write_placed(page, t: PlacedText, dx: float = 0.0, dy: float = 0.0):
    """Az elhelyezett szöveg kiírása a lapra (mentéskor; dx/dy-nal az előnézethez).
    Az aláhúzás rajzolt vonal, ugyanúgy, mint a bekezdés-formázásnál (19.9)."""
    if not t.text.strip():
        return
    f = placed_font(t)
    x, y = t.x + dx, t.y + dy
    add_text(page, (x, y), t.text, f, t.size, color=t.color)
    if t.underline:
        uy = y + t.size * 0.12
        page.draw_line((x, uy), (x + f.text_length(t.text, t.size), uy),
                       width=max(0.4, t.size * 0.05), color=t.color)


def placed_pixmap(t: PlacedText, zoom: float):
    """Az elhelyezett szöveg képe átlátszó háttérrel, a vászon nagyításán: egy
    befoglaló méretű ideiglenes lapon rajzolja a MuPDF, a valódi betűvel. ->
    (pixmap, a kép bal felső sarka a lapon pt-ban)."""
    r = placed_bbox(t)
    r = pymupdf.Rect(r.x0 - 1, r.y0 - 1, r.x1 + 1, r.y1 + 1)
    d = pymupdf.open()
    try:
        pg = d.new_page(width=r.width, height=r.height)
        write_placed(pg, t, -r.x0, -r.y0)
        pix = pg.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=True)
    finally:
        d.close()
    return pix, (r.x0, r.y0)


def bake_placed(doc, texts):
    """Az élő szövegek kiírása a dokumentumba (a mentés másolatába)."""
    for t in texts:
        if 0 <= t.page < doc.page_count:
            write_placed(doc[t.page], t)


# ── szövegdoboz: többsoros, szavanként formázott szöveg (szerkeszto-terv.md 23.2) ──
# Saját tördelő, NEM a PyMuPDF insert_htmlbox-a. Mérve: (1) a HTML-motor a betű
# ligatúráit („tt”, „ti”) alkalmazza, és a szövegrétegből \x82 jön vissza — a
# keresés, a csere és a „Címke a szövegből” elromlana rajta; CSS-sel nem kapcsolható
# ki. (2) Ha a szöveg nem fér a dobozba, scale_low=1 mellett SEMMIT nem ír. A
# TextWriter-út ugyanaz, amit a bekezdés-formázás használ (wrap_words,
# line_positions): ligatúra nincs, a túlcsordulás mérhető, a betű egyezik.
BOX_ALIGNS = (("left", "Balra"), ("center", "Középre"), ("right", "Jobbra"),
              ("justify", "Sorkizárt"))
BOX_LINES = (("1,0", 1.0), ("1,15", 1.15), ("1,5", 1.5), ("2,0", 2.0))
BOX_PAD = 2.0             # belső margó a doboz széle és a szöveg között (pt)
BOX_FIT_MIN = 0.5         # „illesztés”: legfeljebb a méret feléig kicsinyít


@dataclass(eq=False)
class PlacedBox:
    """Többsoros szövegdoboz, mint a PlacedText: a mentésig élő objektum. A
    tartalom bekezdések listája, a bekezdés futamoké: (szöveg, félkövér, dőlt,
    aláhúzott) — így a szavanként vegyes formázás megmarad."""
    page: int
    rect: tuple                   # (x0, y0, x1, y1) pt
    paras: list                   # [[(szöveg, b, i, u), …], …]
    family: str = "Helvetica"
    size: float = 10.5
    color: tuple = (0.0, 0.0, 0.0)
    align: str = "left"
    line: float = 1.15            # sortáv a betűméret szorzójaként
    fit: bool = True              # ha nem fér ki: kicsinyít (BOX_FIT_MIN-ig)
    uid: int = 0


def box_plain(b: PlacedBox) -> str:
    return "\n".join("".join(r[0] for r in p) for p in b.paras)


def norm_paras(paras) -> list:
    """A futamok egyszerűsítve: az üres futam kimarad, az azonos stílusú szomszédok
    összeolvadnak — így két tartalom összevethető (a beíró másként darabolhat)."""
    out = []
    for runs in paras:
        cur = []
        for t, b, i, u in runs:
            if not t:
                continue
            if cur and cur[-1][1:] == (bool(b), bool(i), bool(u)):
                cur[-1] = (cur[-1][0] + t,) + cur[-1][1:]
            else:
                cur.append((t, bool(b), bool(i), bool(u)))
        out.append(cur)
    return out or [[]]


def _box_words(runs):
    """Egy bekezdés szavai részenként: [[(szöveg, b, i, u), …], …]. A szóköz
    választ el; egy szó több futamból is állhat (félkövér szótag)."""
    out, cur = [], []
    for text, b, i, u in runs:
        for ch in text:
            if ch.isspace():
                if cur:
                    out.append(cur)
                    cur = []
            elif cur and cur[-1][1:] == (b, i, u):
                cur[-1] = (cur[-1][0] + ch, b, i, u)
            else:
                cur.append((ch, b, i, u))
    if cur:
        out.append(cur)
    return out


def box_layout(b: PlacedBox, size: float = None):
    """A doboz tördelése a megadott méreten. -> (elhelyezések, aláhúzások,
    a szöveg alja pt-ban). Elhelyezés: (x, alapvonal, szöveg, betű, méret);
    aláhúzás: (x0, x1, y)."""
    size = size or b.size
    x0, y0, x1, _y1 = b.rect
    x0, x1 = x0 + BOX_PAD, x1 - BOX_PAD
    reg = edit_font(b.family)
    asc, desc = reg.ascender, reg.descender
    lh = size * b.line
    base = y0 + BOX_PAD + asc * size
    place, under = [], []
    for runs in b.paras:
        words = _box_words(runs)
        if not words:                       # üres bekezdés: üres sor
            base += lh
            continue
        fonts = [[edit_font(b.family, pb, pi) for _t, pb, pi, _u in w] for w in words]
        widths = [sum(f.text_length(t, size) for (t, *_), f in zip(w, fs))
                  for w, fs in zip(words, fonts)]
        sp = reg.text_length(" ", size)
        rows = wrap_words(widths, sp, max(1.0, x1 - x0))
        for r, row in enumerate(rows):
            ws = [widths[k] for k in row]
            xs = line_positions(ws, x0, x1, sp, b.align, last=(r == len(rows) - 1))
            if not xs:                      # sorkizártként nem megy: balra
                xs = line_positions(ws, x0, x1, sp, "left")
            for n, (k, x) in enumerate(zip(row, xs)):
                for (t, _pb, _pi, pu), f in zip(words[k], fonts[k]):
                    w = f.text_length(t, size)
                    place.append((x, base, t, f, size))
                    if pu:
                        # a szavak közötti szóköz is aláhúzott, ha a következő szó is az
                        nxt = n + 1 < len(row) and words[row[n + 1]][0][3]
                        last = (t, _pb, _pi, pu) == words[k][-1]
                        end = xs[n + 1] if (nxt and last) else x + w
                        under.append((x, end, base + size * 0.12))
                    x += w
            base += lh
    bottom = base - lh - desc * size if place or b.paras else y0
    return place, under, bottom


def box_fit(b: PlacedBox):
    """A doboz tördelése a végleges méreten. Illesztésnél (fit) a legnagyobb
    méret, amelyen a szöveg kifér (felezéses kereséssel, legfeljebb a méret
    feléig). -> (elhelyezések, aláhúzások, méret, kifér-e)"""
    limit = b.rect[3] - BOX_PAD
    place, under, bottom = box_layout(b)
    if bottom <= limit + 0.01 or not b.fit:
        return place, under, b.size, bottom <= limit + 0.01
    lo, hi = b.size * BOX_FIT_MIN, b.size
    best = None
    if box_layout(b, lo)[2] > limit + 0.01:
        p, u, _bt = box_layout(b, lo)
        return p, u, lo, False
    for _ in range(9):
        mid = (lo + hi) / 2
        p, u, bt = box_layout(b, mid)
        if bt <= limit + 0.01:
            lo, best = mid, (p, u)
        else:
            hi = mid
    if best is None:
        best = box_layout(b, lo)[:2]
    return best[0], best[1], round(lo, 2), True


def write_box(page, b: PlacedBox, dx: float = 0.0, dy: float = 0.0) -> tuple:
    """A szövegdoboz kiírása a lapra (mentéskor; dx/dy-nal az előnézethez).
    -> (a használt betűméret, kifér-e)."""
    place, under, size, ok = box_fit(b)
    tw = pymupdf.TextWriter(page.rect)
    for x, y, t, f, sz in place:
        tw.append((x + dx, y + dy), t, font=f, fontsize=sz)
    if place:
        tw.write_text(page, color=b.color)
    for ux0, ux1, uy in under:
        page.draw_line((ux0 + dx, uy + dy), (ux1 + dx, uy + dy),
                       width=max(0.4, size * 0.05), color=b.color)
    return size, ok


def box_pixmap(b: PlacedBox, zoom: float):
    """A doboz képe átlátszó háttérrel (mint a placed_pixmap). A túlcsorduló sorok
    is látszanak, a dobozon túl — az előnézet nem rejti el a hibát."""
    place, _u, _s, _ok = box_fit(b)
    x0, y0, x1, y1 = b.rect
    bottom = max([y1] + [y + sz * 0.4 for _x, y, _t, _f, sz in place])
    r = pymupdf.Rect(x0 - 1, y0 - 1, x1 + 1, bottom + 1)
    d = pymupdf.open()
    try:
        pg = d.new_page(width=r.width, height=r.height)
        write_box(pg, b, -r.x0, -r.y0)
        pix = pg.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=True)
    finally:
        d.close()
    return pix, (r.x0, r.y0)


def box_missing(b: PlacedBox) -> str:
    """A doboz betűiből hiányzó karakterek (csendben eltűnnének)."""
    out = set()
    for runs in b.paras:
        for t, pb, pi, _u in runs:
            f = edit_font(b.family, pb, pi)
            out |= {c for c in t if not c.isspace() and not f.has_glyph(ord(c))}
    return "".join(sorted(out))


# ── keresés: a lap szövegrétegében, karakterpontos téglalappal (23.3) ────────
def page_text_lines(page) -> list:
    """A lap szövegsorai karakterenként: [{"text", "chars": [(c, Rect, span, origin)],
    "right"}]. A rawdict karaktereiből — így egy találat téglalapja és betűje pontos,
    és a span-határon átnyúló találat is megtalálható (félkövér szótag a szóban).
    `right`: a sor hasábjának jobb széle (a blokk legszélesebb sora; egysoros
    blokknál a lap jobb margója) — a csere eddig tolhatja a sor végét."""
    out = []
    margin = page.rect.x1 - 28
    for blk in page.get_text("rawdict")["blocks"]:
        lines = []
        for ln in blk.get("lines", []):
            chars = []
            for sp in ln["spans"]:
                info = {k: sp[k] for k in ("font", "size", "flags", "color")}
                for ch in sp["chars"]:
                    chars.append((ch["c"], pymupdf.Rect(ch["bbox"]), info, ch["origin"]))
            if chars:
                lines.append({"text": "".join(c[0] for c in chars), "chars": chars})
        if not lines:
            continue
        right = max(c[1].x1 for ln in lines for c in ln["chars"])
        for ln in lines:
            ln["right"] = max(right, margin) if len(lines) == 1 else right
            ln["block"] = blk.get("number", 0)
        out += lines
    return out


def has_text_layer(doc) -> bool:
    return any(p.get_text("text").strip() for p in doc)


def search_regex(text: str, regex=False, case=False, whole=False):
    """A felület keresőmezőjéből fordított minta, vagy None (üres / hibás)."""
    if not text:
        return None
    pat = text if regex else re.escape(text)
    if whole:
        pat = rf"(?<!\w)(?:{pat})(?!\w)"
    try:
        return re.compile(pat, 0 if case else re.IGNORECASE)
    except re.error:
        return None


def find_hits(doc, rx, pages=None, kind="", check=None, cache=None) -> list:
    """Minden találat a megadott lapokon. Egy találat: {page, line, a, b, rect,
    text, ctx (előtte, találat, utána), kind}. A `line`/`a`/`b` a page_text_lines
    sora és karakterindexe — a csere ebből számol. `check(szöveg)`: a hívó
    ellenőrzője (pl. TAJ-ellenőrzőszám) — False: kimarad. `cache`: lapszám →
    page_text_lines; a felület adja, amíg az irat nem változik (élő keresés)."""
    hits = []
    if rx is None:
        return hits
    for pno in (range(doc.page_count) if pages is None else pages):
        if cache is not None and pno in cache:
            lines = cache[pno]
        else:
            lines = page_text_lines(doc[pno])
            if cache is not None:
                cache[pno] = lines
        # A blokk sorait szóközzel fűzzük össze: a sortörésen átnyúló adat (egy
        # tördelt telefonszám, egy név a sor végén) is megtalálható. Az ilyen
        # találat téglalapja soronként egy (`rects`); cserélni nem lehet (a sor
        # vége nem csúszhat át a következő sorba), kitakarni igen.
        groups = {}
        for li, ln in enumerate(lines):
            groups.setdefault(ln["block"], []).append(li)
        for lis in groups.values():
            text, where = "", []
            for k, li in enumerate(lis):
                if k:
                    text += " "
                    where.append(None)
                text += lines[li]["text"]
                where += [(li, ci) for ci in range(len(lines[li]["text"]))]
            for m in rx.finditer(text):
                a, b = m.span()
                if a == b or (check and not check(m.group(0))):
                    continue
                spots = [w for w in where[a:b] if w is not None]
                if not spots:
                    continue
                rects = {}
                for li, ci in spots:
                    r = lines[li]["chars"][ci][1]
                    rects[li] = rects[li] | r if li in rects else pymupdf.Rect(r)
                li0, ci0 = spots[0]
                rect = pymupdf.Rect(rects[li0])
                for r in rects.values():
                    rect |= r
                hits.append({"page": pno, "line": li0, "a": ci0, "b": spots[-1][1] + 1,
                             "rect": rect, "rects": list(rects.values()),
                             "multi": len(rects) > 1, "text": m.group(0), "kind": kind,
                             "ctx": (text[max(0, a - 24):a], m.group(0), text[b:b + 24])})
    hits.sort(key=lambda h: (h["page"], round(h["rect"].y0, 1), h["rect"].x0))
    return hits


REPLACE_MIN = 0.6         # a csere legfeljebb ennyire kicsinyíti a betűt (pdfedit)


def _char_font(doc, page, info, text, fallback):
    """A karakter betűje az íráshoz: a beágyazott, ha minden betű megvan benne; a
    gépen lévő azonos család; végül a tartalék. -> (betű, saját-e)"""
    sp = dict(info, text=text)
    f, own = span_font(doc, page, sp, text, None)
    if f is None:
        f, own = style_font(sp), True
    if f is None or any(not c.isspace() and not f.has_glyph(ord(c)) for c in text):
        return fallback, False
    return f, own


def _line_words(chars, a, b):
    """A sor [a, b) karakterei szavakra bontva: [(szöveg, x0, info, origin)]."""
    out, cur = [], None
    for c, r, info, org in chars[a:b]:
        if c.isspace():
            cur = None
            continue
        if cur and cur[2] is info:
            cur[0] += c
        else:
            cur = [c, r.x0, info, org]
            out.append(cur)
    return [tuple(w) for w in out]


def replace_plan(doc, hits, repl: str, fallback) -> list:
    """A csere terve találatonként, MÉG ÍRÁS ELŐTT — a felület ezt mutatja.

    Ha az új szöveg más szélességű, a sor többi része a helyére csúszik (mint egy
    szövegszerkesztőben), amíg a hasáb jobb szélén belül marad és a sor betűi
    megvannak a gépen. Ha nem, a betű legfeljebb REPLACE_MIN-ig kicsinyül; ha így
    sem fér el: „nem fér el” — alapból nincs kijelölve.
    -> [{hit, font, size, shift, note, ok}]; `shift`: a sor vége eltolódik."""
    out, cache, grow = [], {}, {}
    for h in sorted(hits, key=lambda h: (h["page"], h["line"], h["a"])):
        pno = h["page"]
        if pno not in cache:
            cache[pno] = page_text_lines(doc[pno])
        ln = cache[pno][h["line"]]
        key = (pno, h["line"])            # egy sor több cseréje összeadódik
        if h.get("multi"):
            out.append({"hit": h, "font": None, "size": 0, "shift": False,
                        "note": "sortörésen átnyúlik", "ok": False})
            continue
        chars, page = ln["chars"], doc[pno]
        info, size = chars[h["a"]][2], chars[h["a"]][2]["size"]
        f = None
        note, ok, shift = "", True, False
        if repl.strip():
            f, _own = _char_font(doc, page, info, repl, fallback)
        new_w = f.text_length(repl, size) if f is not None else 0.0
        old_w = h["rect"].width
        after = next((c[1].x0 for c in chars[h["b"]:] if not c[0].isspace()), None)
        if after is None:                   # a sor végén: a hasáb széléig nőhet
            room = ln["right"] - h["rect"].x0
            if new_w > room + 0.01:
                k = room / new_w
                if k >= REPLACE_MIN:
                    size, note = size * k, f"kicsinyítve {round(k * 100)}%"
                else:
                    ok, note = False, "nem fér el"
        elif abs(new_w - old_w) > 0.3:
            words = _line_words(chars, h["b"], len(chars))
            end = max(c[1].x1 for c in chars)
            movable = all(_char_font(doc, page, w[2], w[0], None)[0] is not None
                          for w in words)
            if movable and end + grow.get(key, 0.0) + (new_w - old_w) <= ln["right"] + 0.5:
                shift = True
                grow[key] = grow.get(key, 0.0) + new_w - old_w
                if new_w > old_w + 0.3:
                    note = "a sor vége jobbra csúszik"
            elif new_w > after - 1.0 - h["rect"].x0:
                room = after - 1.0 - h["rect"].x0
                k = room / new_w if new_w else 1
                if k >= REPLACE_MIN:
                    size, note = size * k, f"kicsinyítve {round(k * 100)}%"
                else:
                    ok, note = False, "nem fér el"
        if f is fallback and repl.strip():
            note = (note + " · " if note else "") + "más betűvel (az eredeti nincs meg)"
        out.append({"hit": h, "font": f, "size": size, "shift": shift,
                    "note": note or "rendben", "ok": ok})
    order = {id(h): i for i, h in enumerate(hits)}       # a hívó sorrendjében
    return sorted(out, key=lambda it: order[id(it["hit"])])


def plan_short(note: str) -> str:
    """A terv megjegyzésének rövid alakja a találatlista keskeny oszlopába."""
    out = []
    for part in note.split(" · "):
        if part == "a sor vége jobbra csúszik":
            part = "jobbra csúszik"
        elif part.startswith("kicsinyítve "):
            part = "betű " + part.split(" ")[1]
        elif part.startswith("más betűvel"):
            part = "más betű"
        out.append(part)
    return " · ".join(out)


def apply_replace(doc, plan, repl: str):
    """A csere: a régi szöveg redakcióval TÉNYLEGESEN törlődik (a téglalap 15%-kal
    beljebb — a szomszéd sor betűi ne essenek bele, 16.4), az új a helyére kerül,
    ugyanarra az alapvonalra, a saját színével. Eltolásnál a sor vége is
    újraíródik, a saját betűivel, eredeti közökkel. Laponként egy redakció."""
    by_page = {}
    for it in plan:
        by_page.setdefault(it["hit"]["page"], []).append(it)
    for pno, items in by_page.items():
        page = doc[pno]
        lines = page_text_lines(page)
        rects, draws = [], []             # draws: (x, y, szöveg, betű, méret, szín)
        by_line = {}
        for it in items:
            by_line.setdefault(it["hit"]["line"], []).append(it)
        for li, its in by_line.items():
            chars = lines[li]["chars"]
            its.sort(key=lambda it: it["hit"]["a"])
            shifting = any(it["shift"] for it in its)
            start = its[0]["hit"]["a"]
            stop = len(chars) if shifting else None
            delta, pos = 0.0, start
            for it in its:
                h = it["hit"]
                if shifting:                # a két találat közti szöveg, eltolva
                    for w, x, info, org in _line_words(chars, pos, h["a"]):
                        f, _ = _char_font(doc, page, info, w, edit_font("Helvetica"))
                        draws.append((x + delta, org[1], w, f, info["size"],
                                      pymupdf.sRGB_to_pdf(info["color"])))
                else:
                    r = h["rect"]
                    d = r.height * 0.15
                    rects.append(pymupdf.Rect(r.x0, r.y0 + d, r.x1, r.y1 - d))
                c0 = chars[h["a"]]
                col = pymupdf.sRGB_to_pdf(c0[2]["color"])
                x, y = c0[1].x0 + delta, c0[3][1]
                if repl.strip() and it["font"] is not None:
                    sp = it["font"].text_length(" ", it["size"])
                    for w in repl.split(" "):       # mint az add_text: szavanként (16.4)
                        if w:
                            draws.append((x, y, w, it["font"], it["size"], col))
                        x += it["font"].text_length(w, it["size"]) + sp
                    x -= sp
                new_w = (it["font"].text_length(repl, it["size"])
                         if repl.strip() and it["font"] is not None else 0.0)
                if it["shift"]:
                    delta += new_w - h["rect"].width
                pos = h["b"]
            if shifting:
                for w, x, info, org in _line_words(chars, pos, len(chars)):
                    f, _ = _char_font(doc, page, info, w, edit_font("Helvetica"))
                    draws.append((x + delta, org[1], w, f, info["size"],
                                  pymupdf.sRGB_to_pdf(info["color"])))
                r = pymupdf.Rect(chars[start][1])
                for c in chars[start:stop]:
                    r |= c[1]
                d = r.height * 0.15
                rects.append(pymupdf.Rect(r.x0, r.y0 + d, r.x1, r.y1 - d))
        _redact(page, rects)
        writers = {}
        for x, y, t, f, sz, col in draws:
            writers.setdefault(col, pymupdf.TextWriter(page.rect)).append(
                (x, y), t, font=f, fontsize=sz)
        for col, tw in writers.items():
            tw.write_text(page, color=col)


# ── személyes adatok: minták ellenőrzőszámmal (23.4) ────────────────────────
def _digits(s: str) -> list:
    return [int(c) for c in s if c.isdigit()]


def taj_ok(s: str) -> bool:
    """TAJ-szám: 9 jegy, a 9. az ellenőrző (páratlan helyen 3-mal, párosan 7-tel
    szorozva, összeg mod 10)."""
    d = _digits(s)
    return len(d) == 9 and sum(v * (3 if i % 2 == 0 else 7)
                               for i, v in enumerate(d[:8])) % 10 == d[8]


def adoaz_ok(s: str) -> bool:
    """Adóazonosító jel: 10 jegy, 8-cal kezdődik; a 10. a helyiértékkel szorzott
    első kilenc összege mod 11."""
    d = _digits(s)
    return (len(d) == 10 and d[0] == 8
            and sum(v * (i + 1) for i, v in enumerate(d[:9])) % 11 == d[9])


def iban_ok(s: str) -> bool:
    t = re.sub(r"\s", "", s).upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{8,30}", t):
        return False
    n = "".join(str(int(c, 36)) for c in t[4:] + t[:4])
    return int(n) % 97 == 1


def bankszamla_ok(s: str) -> bool:
    """Belföldi számlaszám (2×8 vagy 3×8): blokkonként 9-7-3-1 súlyú ellenőrzés."""
    blocks = re.findall(r"\d{8}", s)
    return bool(blocks) and all(
        sum(int(c) * w for c, w in zip(b, (9, 7, 3, 1) * 2)) % 10 == 0 for b in blocks)


# (kulcs, felirat, minta, ellenőrző, alapból be)
PII_PATTERNS = (
    ("taj", "TAJ-szám", r"(?<!\d)\d{3}[ -]?\d{3}[ -]?\d{3}(?!\d)", taj_ok, True),
    ("adoaz", "Adóazonosító", r"(?<!\d)8\d{9}(?!\d)", adoaz_ok, True),
    ("utlevel", "Útlevélszám", r"(?<![A-Z0-9])[A-Z]{1,2}\d{6,8}[A-Z]?(?![A-Z0-9])", None, True),
    ("szemelyi", "Személyi ig.", r"(?<![A-Z0-9])\d{6}[A-Z]{2}(?![A-Z0-9])", None, True),
    ("bank", "Bankszámla, IBAN",
     r"(?<![\dA-Z])(?:\d{8}-\d{8}(?:-\d{8})?|[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){3,7}(?: ?[A-Z0-9]{1,4})?)(?![\dA-Z])",
     lambda s: iban_ok(s) if s[:2].isalpha() else bankszamla_ok(s), True),
    ("tel", "Telefonszám",
     r"(?<!\d)(?:\+36|06)[ /-]?\(?\d{1,2}\)?[ /-]?\d{3}[ /-]?\d{3,4}(?!\d)", None, True),
    ("email", "E-mail", r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", None, True),
    ("datum", "Dátum",
     r"(?<!\d)(?:(?:19|20)\d{2}\. ?\d{1,2}\. ?\d{1,2}\.?|\d{1,2}[./]\d{1,2}[./](?:19|20)\d{2})(?!\d)",
     None, False),
)


def find_pii(doc, keys, custom: str = "", cache=None) -> list:
    """A kijelölt mintatípusok találatai, típus szerint címkézve. Ahol a típusnak
    ellenőrzőszáma van (TAJ, adóazonosító, számlaszám, IBAN), csak a hibátlan
    kerül a listába — így a „9 jegyű szám” nem fut be minden iktatószámra."""
    hits = []
    for key, label, pat, check, _on in PII_PATTERNS:
        if key in keys:
            hits += find_hits(doc, re.compile(pat), kind=label, check=check, cache=cache)
    if custom.strip():
        hits += find_hits(doc, search_regex(custom.strip()), kind="Saját", cache=cache)
    # Átfedő találatokból egy marad (a dátum és a telefonszám ugyanazt a jegysort
    # is megfoghatja) — a hosszabbik.
    # (Soronkénti téglalapokkal: a két sorra törő találat befoglalója a köztes
    # szöveget is lefedné.)
    def over(x, y):
        return x["page"] == y["page"] and any(
            r.intersects(q) for r in x["rects"] for q in y["rects"])
    hits.sort(key=lambda h: (h["page"], -len(h["text"])))
    out = []
    for h in hits:
        if not any(over(h, k) for k in out):
            out.append(h)
    out.sort(key=lambda h: (h["page"], round(h["rect"].y0, 1), h["rect"].x0))
    return out


def redact_hits(doc, hits, black: bool = True):
    """Kitakarás: a terület szövege és képpontjai végleg törlődnek (mint az
    erase_area), a helye fekete sáv — vagy fehér, ha úgy kérik. Laponként egy
    redakció. Szkennelt lapon (OCR után) a kép képpontjai is törlődnek."""
    fill = (0, 0, 0) if black else (1, 1, 1)
    by_page = {}
    for h in hits:
        for r in h.get("rects") or [h["rect"]]:
            by_page.setdefault(h["page"], []).append(
                pymupdf.Rect(r.x0 - 0.5, r.y0 - 0.5, r.x1 + 0.5, r.y1 + 0.5))
    for pno, rects in by_page.items():
        _redact(doc[pno], rects, fill=fill, images=pymupdf.PDF_REDACT_IMAGE_PIXELS,
                graphics=pymupdf.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED)


def clean_metadata(doc):
    """A metaadat tisztítása (pdf-redactor tanulsága: a kitakarás különben csak
    látszat). A Műhely bélyege (/Keywords) MARAD — abból ismeri fel az Áttekintő
    az iratot; az XMP-csomag törlődik."""
    keep = (doc.metadata or {}).get("keywords", "")
    doc.set_metadata(dict(CLEAN_META, keywords=keep))
    try:
        doc.del_xml_metadata()
    except Exception:
        pass


# ── fejléc, lábléc, oldalszám, bélyeg, vízjel (23.5) ─────────────────────────
DECOR_VARS = (("{oldal}", "az oldal sorszáma"), ("{összes}", "az oldalak száma"),
              ("{dátum}", "a mai dátum"), ("{dolgozó}", "a dolgozó neve"),
              ("{doktípus}", "az irat típusa"), ("{fájlnév}", "a fájl neve"))
PAGENO_FORMATS = ("{oldal}/{összes}", "{oldal}. oldal", "{oldal}. oldal / {összes}",
                  "– {oldal} –", "{oldal}")
DECOR_POS = (("bal", "left"), ("közép", "center"), ("jobb", "right"))
STAMP_COLORS = (("Piros", (0.78, 0.13, 0.13)), ("Kék", (0.12, 0.30, 0.75)),
                ("Fekete", (0.0, 0.0, 0.0)))


@dataclass
class Decor:
    """A lapok díszítése: élő beállítás, a mentés égeti be minden lapra. A
    szöveg változókat tartalmazhat ({oldal}, {dátum} …)."""
    header_on: bool = False
    header: str = "{dolgozó} — {doktípus}"
    header_align: str = "left"
    footer_on: bool = False
    footer: str = "{fájlnév}"
    footer_align: str = "left"
    pageno_on: bool = False
    pageno: str = "{oldal}/{összes}"
    pageno_align: str = "center"
    pageno_skip_first: bool = False
    stamp_on: bool = False
    stamp: str = "Iktatva: {dátum}"
    stamp_xy: tuple = (0.0, 0.0)      # a bélyeg bal felső sarka; (0, 0): jobb felső sarok
    stamp_color: str = "Piros"
    stamp_first_only: bool = True
    wm_on: bool = False
    wm: str = "MÁSOLAT"
    wm_opacity: float = 0.15
    size: float = 9.0
    margin: float = 22.0
    family: str = "Helvetica"

    def any_on(self) -> bool:
        return any((self.header_on, self.footer_on, self.pageno_on, self.stamp_on,
                    self.wm_on))


def fill_vars(text: str, ctx: dict) -> str:
    for k, v in ctx.items():
        text = text.replace("{" + k + "}", str(v))
    return text


def decor_ctx(doc, path: str, pno: int, worker: str = "") -> dict:
    st = parse_stamp((doc.metadata or {}).get("keywords", ""))
    return {"oldal": pno + 1, "összes": doc.page_count,
            "dátum": datetime.date.today().strftime("%Y. %m. %d."),
            "dolgozó": st.get("dolgozo") or worker or "",
            "doktípus": st.get("tipus") or "",
            "fájlnév": os.path.splitext(os.path.basename(path or ""))[0]}


def stamp_rect(page_rect, dec: Decor, ctx: dict) -> "pymupdf.Rect":
    """A bélyeg kerete (keretes szöveg). (0, 0) helyen a jobb felső sarokba."""
    f = edit_font(dec.family, True)
    sz = dec.size + 3
    t = fill_vars(dec.stamp, ctx)
    w = f.text_length(t, sz) + 12
    h = sz * 1.9
    x, y = dec.stamp_xy
    if (x, y) == (0.0, 0.0):
        x, y = page_rect.x1 - dec.margin - w, page_rect.y0 + dec.margin + 14
    return pymupdf.Rect(x, y, x + w, y + h)


def decor_items(page_rect, dec: Decor, ctx: dict, pno: int) -> list:
    """A lapra kerülő díszítések: [(fajta, szöveg, téglalap, betű, méret, szín)].
    A téglalap az ütközésvizsgálathoz és a vászon kereteihez kell."""
    items = []
    f = edit_font(dec.family)
    m = dec.margin

    def line(kind, text, align, y_base, size, color=(0.25, 0.25, 0.25)):
        t = fill_vars(text, ctx)
        if not t.strip():
            return
        w = f.text_length(t, size)
        x = (page_rect.x0 + m if align == "left" else page_rect.x1 - m - w
             if align == "right" else (page_rect.x0 + page_rect.x1 - w) / 2)
        items.append((kind, t, pymupdf.Rect(x, y_base - size * f.ascender, x + w,
                                            y_base - size * f.descender), f, size, color))

    top = page_rect.y0 + m + dec.size
    bot = page_rect.y1 - m
    if dec.header_on:
        line("fejléc", dec.header, dec.header_align, top, dec.size)
    if dec.footer_on:
        line("lábléc", dec.footer, dec.footer_align, bot, dec.size)
    if dec.pageno_on and not (dec.pageno_skip_first and pno == 0):
        # Ha a lábléc ugyanabba a sarokba kerülne, az oldalszám fölé lép.
        same = dec.footer_on and dec.footer_align == dec.pageno_align
        line("oldalszám", dec.pageno, dec.pageno_align,
             bot - (dec.size * 1.4 if same else 0), dec.size)
    if dec.stamp_on and not (dec.stamp_first_only and pno > 0):
        col = dict(STAMP_COLORS).get(dec.stamp_color, STAMP_COLORS[0][1])
        r = stamp_rect(page_rect, dec, ctx)
        items.append(("bélyeg", fill_vars(dec.stamp, ctx), r, edit_font(dec.family, True),
                      dec.size + 3, col))
    if dec.wm_on and dec.wm.strip():
        t = fill_vars(dec.wm, ctx)
        fb = edit_font(dec.family, True)
        diag = math.hypot(page_rect.width, page_rect.height)
        size = min(140.0, diag * 0.7 / max(1.0, fb.text_length(t, 1)))
        items.append(("vízjel", t, page_rect, fb, size, (0.45, 0.45, 0.45)))
    return items


def write_decor(page, dec: Decor, ctx: dict, pno: int):
    """A díszítés kiírása a lapra (mentéskor, illetve az előnézet másolatára)."""
    for kind, t, r, f, size, col in decor_items(page.rect, dec, ctx, pno):
        tw = pymupdf.TextWriter(page.rect)
        if kind == "vízjel":
            w = f.text_length(t, size)
            c = page.rect.tl + (page.rect.br - page.rect.tl) * 0.5
            tw.append((c.x - w / 2, c.y + size * 0.35), t, font=f, fontsize=size)
            tw.write_text(page, color=col, opacity=dec.wm_opacity,
                          morph=(c, pymupdf.Matrix(45 if page.rect.height >= page.rect.width else 30)))
        elif kind == "bélyeg":
            page.draw_rect(r, color=col, width=1.2, radius=0.12)
            tw.append((r.x0 + 6, r.y0 + r.height / 2 + size * 0.35), t, font=f, fontsize=size)
            tw.write_text(page, color=col)
        else:
            tw.append((r.x0, r.y0 + size * f.ascender), t, font=f, fontsize=size)
            tw.write_text(page, color=col)


def decor_overlaps(page, dec: Decor, ctx: dict, pno: int) -> list:
    """Mely díszítés esne a lap meglévő szövegére (a vízjel szándékosan átfed)."""
    blocks = [pymupdf.Rect(b[:4]) for b in page.get_text("blocks") if b[4].strip()]
    return [kind for kind, _t, r, *_ in decor_items(page.rect, dec, ctx, pno)
            if kind != "vízjel" and any(r.intersects(b) for b in blocks)]


# ── űrlap: kitöltés és beégetés saját rajzolóval (23.6) ──────────────────────
# Mérve: a PyMuPDF mező-megjelenítése (Helv, WinAnsi) az ő/ű-t tartalmazó értéket
# EGYÁLTALÁN nem rajzolja ki — a „Kőműves Győző” üres mezőnek látszik, és így
# égne be. A beégetés ezért a szöveges mezőt mi írjuk a lapra (TextWriter,
# Unicode-betű); a jelölőnégyzetet és a rádiógombot a saját megjelenése égeti be.
FIELD_TEXT_TYPES = (pymupdf.PDF_WIDGET_TYPE_TEXT, pymupdf.PDF_WIDGET_TYPE_COMBOBOX,
                    pymupdf.PDF_WIDGET_TYPE_LISTBOX)
FIELD_CHECK_TYPES = (pymupdf.PDF_WIDGET_TYPE_CHECKBOX, pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON)


def form_fields(doc) -> list:
    """A kitölthető mezők laponként, olvasási sorrendben: [{page, xref, name,
    label, type, value, choices, rect, on}]."""
    out = []
    for pno, page in enumerate(doc):
        for w in page.widgets():
            if w.field_type not in FIELD_TEXT_TYPES + FIELD_CHECK_TYPES:
                continue
            out.append({"page": pno, "xref": w.xref, "name": w.field_name or "",
                        "label": (w.field_label or "").strip(), "type": w.field_type,
                        "value": w.field_value, "rect": pymupdf.Rect(w.rect),
                        "choices": list(w.choice_values or []),
                        "on": w.on_state() if w.field_type in FIELD_CHECK_TYPES else None})
    out.sort(key=lambda f: (f["page"], round(f["rect"].y0 / 4), f["rect"].x0))
    return out


def set_field(doc, pno: int, xref: int, value):
    """Egy mező értéke. A megjelenést a PyMuPDF frissíti (az ő/ű-t ott nem tudja),
    ezért a NeedAppearances jelző is be: a külső olvasó maga rajzolja újra."""
    page = doc[pno]
    w = next((w for w in page.widgets() if w.xref == xref), None)
    if w is None:
        return
    if w.field_type in FIELD_CHECK_TYPES:
        w.field_value = w.on_state() if value else "Off"
    else:
        w.field_value = value
    w.update()
    try:
        doc.need_appearances(True)
    except Exception:
        pass


def _field_q(doc, xref) -> int:
    """A mező igazítása (/Q): 0 balra, 1 középre, 2 jobbra."""
    try:
        t, v = doc.xref_get_key(xref, "Q")
        return int(v) if t == "int" else 0
    except Exception:
        return 0


def draw_field_value(page, rect, value: str, family: str = "Helvetica", size: float = 0,
                     q: int = 0, multiline: bool = False, comb: int = 0, color=(0, 0, 0)):
    """Egy szöveges mező értéke a lapra: függőlegesen középre, a megadott méreten
    vagy (0) a mező magasságához igazítva, és ha szélesebb, kicsinyítve. Fésűs
    (comb) mezőnél betűnként a cellák közepére."""
    value = (value or "").replace("\r", "")
    if not value.strip():
        return
    font = edit_font(family)
    pad = 2.0
    tw = pymupdf.TextWriter(page.rect)
    if comb and not multiline:
        cw = rect.width / comb
        sz = size or min(rect.height * 0.7, cw * 1.2, 12.0)
        y = rect.y0 + rect.height / 2 + sz * 0.35
        for i, ch in enumerate(value[:comb]):
            w = font.text_length(ch, sz)
            tw.append((rect.x0 + cw * i + (cw - w) / 2, y), ch, font=font, fontsize=sz)
        tw.write_text(page, color=color)
        return
    if multiline:
        write_box(page, PlacedBox(page.number, tuple(rect),
                                  [[(ln, False, False, False)] for ln in value.split("\n")],
                                  family=family, size=size or 10.0, fit=True, color=color,
                                  align={1: "center", 2: "right"}.get(q, "left")))
        return
    value = value.replace("\n", " ")
    sz = size or min(rect.height * 0.7, 11.0)
    w = font.text_length(value, sz)
    if w > rect.width - 2 * pad and w > 0:
        sz *= (rect.width - 2 * pad) / w
        w = font.text_length(value, sz)
    x = (rect.x0 + pad if q == 0 else rect.x1 - pad - w if q == 2
         else (rect.x0 + rect.x1 - w) / 2)
    tw.append((x, rect.y0 + rect.height / 2 + sz * 0.35), value, font=font, fontsize=sz)
    tw.write_text(page, color=color)


def flatten_form(doc, family: str = "Helvetica") -> int:
    """Beégetés: a mezők a lap tartalmává válnak (a portál így biztosan látja az
    értéket, és nem szerkeszthető tovább). -> hány mező égett be."""
    n = 0
    for page in doc:
        texts = [w for w in page.widgets() if w.field_type in FIELD_TEXT_TYPES]
        for w in texts:
            flags = w.field_flags or 0
            comb = (w.text_maxlen or 0) if flags & (1 << 24) else 0
            draw_field_value(page, pymupdf.Rect(w.rect), str(w.field_value or ""), family,
                             w.text_fontsize or 0, _field_q(doc, w.xref),
                             multiline=bool(flags & (1 << 12)), comb=comb)
        for w in texts:
            page.delete_widget(w)
            n += 1
        n += sum(1 for w in page.widgets() if w.field_type in FIELD_CHECK_TYPES)
    try:
        doc.bake(annots=False, widgets=True)   # jelölőnégyzet, rádió: a saját képe
    except TypeError:
        doc.bake()
    return n


# ── szövegfelismerés: a PyMuPDF beépített OCR-motorja (23.7) ────────────────
# Tesseract-telepítés NEM kell: a PyMuPDF a MuPDF-be épített Tesseract-motort
# hívja, ehhez csak a nyelvi adatfájl kell (tessdata\hun.traineddata, 5 MB, a
# programmal együtt szállítva). Mérve: magyar szkennelt lap hibátlanul, 1,5 s/oldal.
OCR_DPI = 300
TESSDATA = "tessdata"


def tessdata_dir() -> str:
    """A nyelvi adatok mappája: a program mellett, a TESSDATA_PREFIX, vagy egy
    telepített Tesseract. "" ha nincs magyar nyelvi fájl."""
    cands = [os.path.join(script_dir(), TESSDATA), os.environ.get("TESSDATA_PREFIX", "")]
    for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                 os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")):
        cands.append(os.path.join(base, "Tesseract-OCR", "tessdata"))
    for d in cands:
        if d and os.path.isfile(os.path.join(d, "hun.traineddata")):
            return d
    return ""


def ocr_langs(tessdata: str) -> str:
    """A felismerés nyelve: magyar, és ha megvan, angol is (a külföldi iratok
    angol szavaihoz)."""
    return "hun+eng" if os.path.isfile(os.path.join(tessdata, "eng.traineddata")) else "hun"


def page_is_scan(page) -> bool:
    """Szkennelt lap: van rajta kép, de nincs szövegrétege."""
    return not page.get_text("text").strip() and bool(page.get_images())


def ocr_words(page, tessdata: str, lang: str = "hun") -> list:
    """Egy lap felismert szavai: [(x0, y0, x1, y1, szó)].
    A beépített Tesseract ANSI-fopen-nel nyit: ékezetes abszolút útvonalon
    (…\\Dániel\\…) „Tesseract language initialisation failed”. A relatív utat a
    Windows a munkakönyvtárhoz Unicode-ban oldja fel — ezért a tessdata mappából,
    „.”-ként adjuk át (23.7). A munkakönyvtár folyamatszintű: csak a külön
    folyamatból (`--ocr`) és az öntesztből hívjuk, felületi szál nem fut mellette."""
    cwd = os.getcwd()
    os.chdir(tessdata)
    try:
        tp = page.get_textpage_ocr(language=lang, dpi=OCR_DPI, full=True, tessdata=".")
    finally:
        os.chdir(cwd)
    return [tuple(w[:5]) for w in page.get_text("words", textpage=tp) if w[4].strip()]


def apply_ocr_words(page, words):
    """Láthatatlan szövegréteg a lapra (render_mode=3): kereshető, kijelölhető,
    kitakarható lesz — a kép érintetlen, így a fájl alig nő (nem újrakódolás).
    A betűméret a szó szélességéhez igazodik: a kijelölés így fedi a szót."""
    if not words:
        return
    f = edit_font("Helvetica")
    tw = pymupdf.TextWriter(page.rect)
    for x0, y0, x1, y1, t in words:
        w1 = f.text_length(t, 1)
        if w1 <= 0:
            continue
        sz = max(1.0, min((x1 - x0) / w1, (y1 - y0) * 1.6))
        tw.append((x0, y1 - (y1 - y0) * 0.2), t, font=f, fontsize=sz)
    tw.write_text(page, render_mode=3)


def ocr_word_rects(page) -> list:
    """A lap FELISMERT (láthatatlan, render_mode=3) szavainak téglalapjai. A lap
    eredeti, látható szövegét kihagyja: a „Felismert szavak mutatása” különben a
    szöveges lapon minden szót bekeretezett — mintha azt is a felismerés adta volna."""
    hidden = [pymupdf.Rect(t["bbox"]) for t in page.get_texttrace() if t.get("type") == 3]
    out = []
    for w in page.get_text("words") if hidden else ():
        r = pymupdf.Rect(w[:4])
        mid = pymupdf.Point((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)
        if any(h.contains(mid) for h in hidden):
            out.append(r)
    return out


def ocr_cli(argv) -> int:
    """`--ocr <be.pdf> <ki.json> <tessdata> <nyelv> <lapok>` — KÜLÖN FOLYAMATBAN
    fut (mint a tömörítés, 13.10): laponként „OLDAL i n” sort ír, a végén JSON."""
    try:
        be, ki, tess, lang, lapok = argv[:5]
        doc = pymupdf.open(be)
        pages = [int(p) for p in lapok.split(",") if p != ""]
        out = {}
        for i, pno in enumerate(pages):
            print(f"OLDAL {i + 1} {len(pages)} {pno}", flush=True)
            out[str(pno)] = ocr_words(doc[pno], tess, lang)
        with open(ki, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False)
        print("KESZ", flush=True)
        return 0
    except Exception as e:
        print(f"HIBA {type(e).__name__}: {e}", flush=True)
        return 1


def ocr_process(widget, data: bytes, pages, tess: str, lang: str, on_done, on_step=None):
    """A felismerés külön folyamatban; a felület közben él, és megszakítható.
    on_step(hányadik, összes, lap); on_done(szavak lapszám szerint | None, hiba).
    -> a megszakító függvény."""
    be = tempfile.mktemp(suffix=".ocr.pdf")
    ki = tempfile.mktemp(suffix=".ocr.json")
    with open(be, "wb") as f:
        f.write(data)
    proc = subprocess.Popen(
        [sys.executable, os.path.abspath(__file__), "--ocr", be, ki, tess, lang,
         ",".join(str(p) for p in pages)],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
        encoding="utf-8", errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    sorok = queue.Queue()
    st = {"err": None, "vege": False, "megszakitva": False}

    def olvas():
        try:
            for sor in proc.stdout:
                sorok.put(sor.strip())
        except Exception:
            pass
        finally:
            sorok.put(None)

    threading.Thread(target=olvas, daemon=True).start()

    def takarit():
        for f in (be, ki):
            try:
                os.remove(f)
            except OSError:
                pass

    def tick():
        while True:
            try:
                sor = sorok.get_nowait()
            except queue.Empty:
                break
            if sor is None:
                st["vege"] = True
            elif sor.startswith("OLDAL") and on_step:
                r = sor.split()
                on_step(int(r[1]), int(r[2]), int(r[3]))
            elif sor.startswith("HIBA"):
                st["err"] = RuntimeError(sor[5:])
        if not (st["vege"] and proc.poll() is not None):
            widget.after(100, tick)
            return
        out = None
        if st["megszakitva"]:
            st["err"] = st["err"] or RuntimeError("megszakítva")
        elif st["err"] is None:
            try:
                with open(ki, encoding="utf-8") as f:
                    out = {int(k): [tuple(w) for w in v] for k, v in json.load(f).items()}
            except (OSError, ValueError) as e:
                st["err"] = e
        takarit()
        on_done(out, st["err"])

    def cancel():
        st["megszakitva"] = True
        try:
            proc.kill()
        except Exception:
            pass

    widget.after(100, tick)
    return cancel


# ── a Szerkesztés eszközei: egy-egy rész (mixin) eszközönként (szerkeszto-terv.md 23.) ──
# Az EditorTab ezekből áll össze. Mindegyik rész ugyanazt a mintát követi: _init_x
# (állapot), _build_x (panel + műveletsáv), _enter_x (az eszközre váltáskor),
# _draw_x (a vászon jelei), és ha a vásznon is dolgozik: _x_down/_x_drag/_x_up.
def text_widget_runs(t) -> list:
    """A formázott beíró (tk.Text) tartalma bekezdésekre és futamokra bontva —
    a b / i / u címke a félkövér / dőlt / aláhúzott."""
    on, paras = set(), [[]]
    for key, val, _idx in t.dump("1.0", "end-1c", tag=True, text=True):
        if key == "tagon":
            on.add(val)
        elif key == "tagoff":
            on.discard(val)
        elif key == "text":
            for k, part in enumerate(val.split("\n")):
                if k:
                    paras.append([])
                if part:
                    paras[-1].append((part, "b" in on, "i" in on, "u" in on))
    return paras


def text_widget_fill(t, paras):
    t.delete("1.0", "end")
    for n, runs in enumerate(paras):
        if n:
            t.insert("end", "\n")
        for text, b, i, u in runs:
            t.insert("end", text, tuple(k for k, v in (("b", b), ("i", i), ("u", u)) if v))


class _BoxTool:
    """Szövegdoboz: többsoros, szavanként formázható szöveg (23.2)."""

    HANDLE = 5                    # a fogantyú fél oldala (képpont)

    def _init_box(self, fonts):
        self.boxes = []
        self.sel_box = None
        self._bimgs, self._bfit = {}, {}
        self._bdrag = None
        self.b_family = tk.StringVar(value="Calibri" if "Calibri" in fonts else fonts[0])
        self.b_size = tk.DoubleVar(value=10.5)
        self.b_align = tk.StringVar(value="left")
        self.b_line = tk.StringVar(value="1,15")
        self.b_fit = tk.BooleanVar(value=True)
        self.b_bold = tk.BooleanVar(value=False)
        self.b_italic = tk.BooleanVar(value=False)
        self.b_under = tk.BooleanVar(value=False)
        self.b_color = (0.0, 0.0, 0.0)
        for v in (self.b_family, self.b_size, self.b_align, self.b_line, self.b_fit):
            v.trace_add("write", lambda *a: self._bstyle_changed())

    def _build_box(self, left, fonts):
        p = ttk.LabelFrame(left, text="Szövegdoboz")
        r = ttk.Frame(p)
        r.pack(fill="x", padx=6, pady=(6, 0))
        ttk.Combobox(r, textvariable=self.b_family, values=fonts, state="readonly",
                     width=13).pack(side="left")
        ttk.Spinbox(r, from_=4, to=72, increment=0.5, textvariable=self.b_size,
                    width=5).pack(side="left", padx=(4, 1))
        ttk.Label(r, text="pt", foreground="#555").pack(side="left")
        self.b_swatch = ttk.Button(r, text="Szín…", command=self._pick_bcolor)
        self.b_swatch.pack(side="right")
        self._swatch(self.b_swatch, self.b_color)
        Tip(self.b_swatch, "A doboz szövegének színe")

        f = ttk.Frame(p)
        f.pack(fill="x", padx=6, pady=(6, 0))
        for key, var, txt, tip in (("b", self.b_bold, "F", "Félkövér (Ctrl+B)"),
                                   ("i", self.b_italic, "D", "Dőlt (Ctrl+I)"),
                                   ("u", self.b_under, "A", "Aláhúzott (Ctrl+U)")):
            cb = ttk.Checkbutton(f, text=txt, variable=var, style=f"{key.upper()}.Tile.TCheckbutton",
                                 command=lambda k=key: self._btoggle(k))
            cb.pack(side="left", padx=(0, 2))
            Tip(cb, tip + " — a kijelölt szövegre, vagy ha nincs kijelölés, a "
                          "következő gépelt betűkre")
        ttk.Frame(f, width=8).pack(side="left")
        for val, ic, tip in (("left", "al_left", "Balra zárt"), ("center", "al_center", "Középre"),
                             ("right", "al_right", "Jobbra zárt"), ("justify", "al_justify", "Sorkizárt")):
            rb = ttk.Radiobutton(f, image=ui_icon(ic), value=val, variable=self.b_align,
                                 style="Icon.Tile.TRadiobutton")
            rb.pack(side="left", padx=(0, 2))
            Tip(rb, tip)

        g = ttk.Frame(p)
        g.pack(fill="x", padx=6, pady=(6, 0))
        ttk.Label(g, text="Sortáv:").pack(side="left")
        ttk.Combobox(g, textvariable=self.b_line, values=[t for t, _v in BOX_LINES],
                     state="readonly", width=5).pack(side="left", padx=(4, 10))
        fit = ttk.Checkbutton(g, text="Kicsinyít, ha nem fér", variable=self.b_fit)
        fit.pack(side="left")
        Tip(fit, "Ha a szöveg nem fér a dobozba, a betű legfeljebb a felére kisebbedik. "
                 "Kikapcsolva a túlcsorduló sorok a doboz alá lógnak (piros jelzés).")

        self.b_text = t = tk.Text(p, height=7, wrap="word", undo=True, font=FONT_UI,
                                  padx=6, pady=4)
        t.pack(fill="x", padx=6, pady=(6, 0))
        base = tkfont.Font(font=FONT_UI)
        fam, size = base.actual("family"), base.actual("size")
        t.tag_configure("b", font=(fam, size, "bold"))
        t.tag_configure("i", font=(fam, size, "italic"))
        t.tag_configure("bi", font=(fam, size, "bold italic"))
        t.tag_configure("u", underline=True)
        t.tag_raise("bi")
        t.bind("<<Modified>>", self._btext_modified)
        t.bind("<KeyPress>", self._btext_key)
        for ev in ("<ButtonRelease-1>", "<KeyRelease-Left>", "<KeyRelease-Right>",
                   "<KeyRelease-Up>", "<KeyRelease-Down>", "<KeyRelease-Home>",
                   "<KeyRelease-End>"):
            t.bind(ev, lambda e: self._btext_caret(), add="+")
        for k, key in (("b", "b"), ("i", "i"), ("u", "u")):
            t.bind(f"<Control-{key}>", lambda e, k=k: (self._btoggle(k, flip=True), "break")[1])
        t.mark_set("typ", "insert")
        t.mark_gravity("typ", "left")
        self.b_note = ttk.Label(p, foreground="#555", wraplength=330)
        self.b_note.pack(anchor="w", fill="x", padx=6, pady=(4, 6))

        a = self._abar("box")
        self.b_del = ttk.Button(a, text="Doboz törlése", command=self._delete_box)
        self.b_del.pack(side="left")
        self._bpanel_state()
        return p

    # -- a beíró: tartalom, formázás, gépelési stílus --
    def _btext_modified(self, _e=None):
        t = self.b_text
        if not t.edit_modified():
            return
        t.edit_modified(False)
        if not self._quiet:
            self._btext_changed()

    def _btext_key(self, e):
        """Gépeléskor a beírt betű a beíró gépelési stílusát kapja (F/D/A gombok) —
        a Tk magától csak a két szomszédban közös címkét adná."""
        if e.char and (e.char.isprintable() or e.char == "\r"):
            self.b_text.mark_set("typ", "insert")
            self.after_idle(self._btext_typed)

    def _btext_typed(self):
        t = self.b_text
        try:
            a, b = t.index("typ"), t.index("insert")
        except tk.TclError:
            return
        if t.compare(a, ">=", b):
            return
        for k, var in (("b", self.b_bold), ("i", self.b_italic), ("u", self.b_under)):
            (t.tag_add if var.get() else t.tag_remove)(k, a, b)
        self._btext_changed()

    def _btext_caret(self):
        """A kurzor előtti betű stílusa a gombokon — így folytatódik a gépelés is."""
        t = self.b_text
        if t.tag_ranges("sel"):
            idx = "sel.first"
        elif t.compare("insert", ">", "insert linestart"):
            idx = "insert-1c"
        else:
            idx = "insert"
        tags = t.tag_names(idx)
        self._quiet = True
        try:
            self.b_bold.set("b" in tags)
            self.b_italic.set("i" in tags)
            self.b_under.set("u" in tags)
        finally:
            self._quiet = False

    def _btoggle(self, key, flip=False):
        """F / D / A: a kijelölt szövegre hat; kijelölés nélkül a gépelés stílusa."""
        var = {"b": self.b_bold, "i": self.b_italic, "u": self.b_under}[key]
        if flip:
            var.set(not var.get())
        t = self.b_text
        if t.tag_ranges("sel"):
            (t.tag_add if var.get() else t.tag_remove)(key, "sel.first", "sel.last")
            self._btext_changed()
        t.focus_set()

    def _btext_changed(self):
        t = self.b_text
        t.tag_remove("bi", "1.0", "end")          # a félkövér dőlt külön betű a beíróban
        b, i = t.tag_ranges("b"), t.tag_ranges("i")
        for k in range(0, len(b), 2):
            for m in range(0, len(i), 2):
                lo = b[k] if t.compare(b[k], ">", i[m]) else i[m]
                hi = b[k + 1] if t.compare(b[k + 1], "<", i[m + 1]) else i[m + 1]
                if t.compare(lo, "<", hi):
                    t.tag_add("bi", lo, hi)
        if self._bsel() is not None:
            debounce(self, "_btext_job", self._bcontent_apply, self.LIVE_MS)

    def _bcontent_apply(self):
        b = self._bsel()
        if b is None:
            return
        paras = norm_paras(text_widget_runs(self.b_text))
        if paras == norm_paras(b.paras):
            return
        self._tchange(lambda: setattr(b, "paras", paras), key=("box", b.uid))
        self._bnote()

    # -- stílus --
    def _bstyle(self, b=None) -> dict:
        try:
            size = float(self.b_size.get())
        except (tk.TclError, ValueError):
            size = 0
        if not 3 <= size <= 300:
            size = b.size if b else 10.5
        return {"family": self.b_family.get(), "size": size, "color": tuple(self.b_color),
                "align": self.b_align.get(), "line": dict(BOX_LINES).get(self.b_line.get(), 1.15),
                "fit": self.b_fit.get()}

    def _bstyle_changed(self):
        if self._quiet or self._bsel() is None:
            return
        debounce(self, "_bstyle_job", self._bstyle_apply, self.LIVE_MS)

    def _bstyle_apply(self):
        b = self._bsel()
        if b is None:
            return
        new = self._bstyle(b)
        if all(getattr(b, k) == v for k, v in new.items()):
            return
        self._tchange(lambda: [setattr(b, k, v) for k, v in new.items()],
                      key=("box", b.uid))
        self._bnote()

    def _pick_bcolor(self):
        rgb = colorchooser.askcolor(title="A doboz szövegének színe", parent=self)[0]
        if rgb:
            self.b_color = tuple(v / 255 for v in rgb)
            self._swatch(self.b_swatch, self.b_color)
            self._bstyle_changed()

    def _flush_box(self):
        for attr, fn in (("_btext_job", self._bcontent_apply),
                         ("_bstyle_job", self._bstyle_apply)):
            job = getattr(self, attr, None)
            if job:
                try:
                    self.after_cancel(job)
                except Exception:
                    pass
                setattr(self, attr, None)
                fn()

    # -- kijelölés --
    def _bfind(self, uid):
        return next((b for b in self.boxes if b.uid == uid), None)

    def _bsel(self):
        return self._bfind(self.sel_box) if self.sel_box is not None else None

    def _box_at(self, x, y):
        for b in reversed(self.boxes):
            if b.page == self.page_no:
                x0, y0, x1, y1 = b.rect
                if x0 - 2 <= x <= x1 + 2 and y0 - 2 <= y <= y1 + 2:
                    return b
        return None

    def _select_box(self, b, focus=False):
        self._flush_box()
        self.sel_box = b.uid if b is not None else None
        self._undo_key = None
        if b is not None:
            self._quiet = True
            try:
                self.b_family.set(b.family)
                self.b_size.set(b.size)
                self.b_align.set(b.align)
                self.b_line.set(next((t for t, v in BOX_LINES if abs(v - b.line) < 0.01), "1,15"))
                self.b_fit.set(b.fit)
                self.b_color = b.color
                self._swatch(self.b_swatch, b.color)
                self.b_text.configure(state="normal")
                text_widget_fill(self.b_text, b.paras)
                self.b_text.edit_reset()
                self.b_text.edit_modified(False)
            finally:
                self._quiet = False
            self._btext_changed()
            if focus:
                self.b_text.focus_set()
                self.b_text.mark_set("insert", "end-1c")
        self._bpanel_state()
        self._draw_layers()
        self._bnote()

    def _deselect_box(self):
        if self.sel_box is None:
            return
        self._flush_box()
        b = self._bsel()
        self.sel_box = None
        if b is not None and not box_plain(b).strip():
            # Üres doboz nem marad a lapon (a létrehozása visszavonható maradt).
            self.boxes = [x for x in self.boxes if x.uid != b.uid]
        self._quiet = True
        try:
            self.b_text.delete("1.0", "end")
        finally:
            self._quiet = False
        self._bpanel_state()
        self._draw_layers()

    def _bpanel_state(self):
        on = self._bsel() is not None
        self.b_text.configure(state="normal" if on else "disabled",
                              background=UI["card"] if on else "#f4f6fb")
        self.b_del.state(["!disabled"] if on else ["disabled"])
        if not on:
            self.b_note.configure(
                text="Húzz egy téglalapot a lapon — ott lesz a doboz. Kattintással a "
                     "cellába illeszkedik. Meglévő dobozra kattintva itt szerkesztheted.",
                foreground="#555")

    def _bnote(self):
        b = self._bsel()
        if b is None:
            return
        _p, _u, size, ok = box_fit(b)
        miss = box_missing(b)
        if miss:
            txt, col = f"A betűből hiányzik: {' '.join(miss)} — válassz másik betűt.", COL_WARN
        elif not ok:
            txt, col = ("A szöveg nem fér a dobozba — húzd nagyobbra a sarkánál, vagy "
                        "kapcsold be a kicsinyítést."), COL_WARN
        elif size < b.size - 0.05:
            txt, col = f"Kicsinyítve {str(round(size, 1)).replace('.', ',')} pt-ra, hogy kiférjen.", "#555"
        else:
            txt, col = ("Élőben látszik a lapon. A doboz húzható, a sarkainál és az oldalain "
                        "átméretezhető; nyilakkal 1 pt, Shift-tel 10 pt."), "#555"
        self.b_note.configure(text=txt, foreground=col)

    def _delete_box(self):
        uid = self.sel_box
        if uid is None:
            return
        self._flush_box()
        self._tchange(lambda: setattr(self, "boxes", [b for b in self.boxes if b.uid != uid]),
                      "Doboz törölve.")
        self.sel_box = None
        self._quiet = True
        try:
            self.b_text.delete("1.0", "end")
        finally:
            self._quiet = False
        self._bpanel_state()
        self._draw_layers()

    def _new_box(self, rect):
        self._uid += 1
        b = PlacedBox(self.page_no, (rect.x0, rect.y0, rect.x1, rect.y1), [[]],
                      uid=self._uid, **self._bstyle())
        self._tchange(lambda: self.boxes.append(b),
                      "Doboz a lapon — gépelj a panelen; a szöveg élőben megjelenik.")
        self._select_box(b, focus=True)

    # -- vászon --
    def _draw_boxes(self):
        c = self.canvas
        c.delete("pbox")
        self._bimgs, self._bfit = {}, {}
        for b in self.boxes:
            if b.page == self.page_no:
                self._draw_box(b)

    def _draw_box(self, b):
        c, z = self.canvas, self.zoom
        tag = f"pb{b.uid}"
        c.delete(tag)
        ok = box_fit(b)[3]
        self._bfit[b.uid] = ok
        if box_plain(b).strip():
            pix, (x0, y0) = box_pixmap(b, z)
            self._bimgs[b.uid] = img = tkimg(pix, "png")
            c.create_image(round(x0 * z), round(y0 * z), anchor="nw", image=img,
                           tags=("pbox", tag))
        x0, y0, x1, y1 = b.rect
        if self.mode.get() == "box" and b.uid != self.sel_box:
            # a többi doboz halvány kerete: az üres doboz is látsszon
            c.create_rectangle(x0 * z, y0 * z, x1 * z, y1 * z, outline="#9fb4dc",
                               dash=(2, 3), tags=("pbox", tag))

    def _draw_bsel(self):
        c, z, h = self.canvas, self.zoom, self.HANDLE
        c.delete("bsel")
        b = self._bsel()
        if b is None or b.page != self.page_no:
            return
        x0, y0, x1, y1 = (v * z for v in b.rect)
        bad = not self._bfit.get(b.uid, True)
        c.create_rectangle(x0, y0, x1, y1, outline=UI["accent"], dash=(4, 2), width=1.5,
                           tags="bsel")
        if bad:
            c.create_line(x0, y1, x1, y1, fill=UI["warn"], width=3, tags="bsel")
        for hx, hy in self._handles(x0, y0, x1, y1).values():
            c.create_rectangle(hx - h, hy - h, hx + h, hy + h, fill="#ffffff",
                               outline=UI["accent"], width=1.5, tags="bsel")

    @staticmethod
    def _handles(x0, y0, x1, y1):
        xm, ym = (x0 + x1) / 2, (y0 + y1) / 2
        return {"nw": (x0, y0), "n": (xm, y0), "ne": (x1, y0), "e": (x1, ym),
                "se": (x1, y1), "s": (xm, y1), "sw": (x0, y1), "w": (x0, ym)}

    def _handle_at(self, b, ex, ey):
        c, z = self.canvas, self.zoom
        px, py = c.canvasx(ex), c.canvasy(ey)
        for name, (hx, hy) in self._handles(*(v * z for v in b.rect)).items():
            if abs(px - hx) <= self.HANDLE + 2 and abs(py - hy) <= self.HANDLE + 2:
                return name
        return None

    CURSORS = {"nw": "size_nw_se", "se": "size_nw_se", "ne": "size_ne_sw",
               "sw": "size_ne_sw", "n": "sb_v_double_arrow", "s": "sb_v_double_arrow",
               "e": "sb_h_double_arrow", "w": "sb_h_double_arrow"}

    def _box_cursor(self, e, pt):
        b = self._bsel()
        hd = self._handle_at(b, e.x, e.y) if b is not None and b.page == self.page_no else None
        if hd:
            return self.CURSORS[hd]
        return "fleur" if self._box_at(*pt) is not None else "crosshair"

    def _box_down(self, e, pt) -> bool:
        """Lenyomás doboz-módban: fogantyú → átméretezés, doboz → mozgatás. -> kezeltük-e"""
        b = self._bsel()
        hd = self._handle_at(b, e.x, e.y) if b is not None and b.page == self.page_no else None
        if hd is None:
            b = self._box_at(*pt)
            if b is None:
                return False
            if b.uid != self.sel_box:
                self._select_box(b)
        self._bdrag = {"uid": b.uid, "mode": hd or "move", "x": e.x, "y": e.y,
                       "rect": tuple(b.rect), "moved": False}
        return True

    def _box_drag(self, e):
        d = self._bdrag
        b = self._bfind(d["uid"])
        if b is None:
            return
        dx, dy = e.x - d["x"], e.y - d["y"]
        if not d["moved"] and abs(dx) + abs(dy) < 3:
            return
        d["moved"] = True
        z = self.zoom
        x0, y0, x1, y1 = d["rect"]
        m = d["mode"]
        if m == "move":
            nr = (x0 + dx / z, y0 + dy / z, x1 + dx / z, y1 + dy / z)
        else:
            if "w" in m:
                x0 = min(x0 + dx / z, x1 - 20)
            if "e" in m:
                x1 = max(x1 + dx / z, x0 + 20)
            if "n" in m:
                y0 = min(y0 + dy / z, y1 - 12)
            if "s" in m:
                y1 = max(y1 + dy / z, y0 + 12)
            nr = (x0, y0, x1, y1)
        d["new"] = nr
        b.rect = nr                       # ideiglenesen: a végén egy lépésként rögzül
        if m == "move":
            self.canvas.move(f"pb{b.uid}", dx - d.get("adx", 0), dy - d.get("ady", 0))
            d["adx"], d["ady"] = dx, dy
            self._draw_bsel()
        else:
            self._draw_bsel()
            debounce(self, "_bresize_job", lambda: (self._draw_box(b), self._draw_bsel()), 30)

    def _box_up(self, e):
        d, self._bdrag = self._bdrag, None
        b = self._bfind(d["uid"])
        if b is None or not d["moved"]:
            return
        new = d.get("new", d["rect"])
        b.rect = d["rect"]                # a lépés előtti állapot kerüljön a verembe
        self._tchange(lambda: setattr(b, "rect", new),
                      "Átméretezve." if d["mode"] != "move" else "Áthelyezve.")
        self._bnote()

    def _box_click_empty(self, page, rect, drag):
        """Üres helyen: húzás → doboz a téglalapba; kattintás → a cellába (vagy
        alapméretben)."""
        if self.sel_box is not None and not drag:
            self._deselect_box()
            return
        if not drag:
            cell = snap_cell(self._lines, rect.x1, rect.y1)
            rect = (pymupdf.Rect(cell.x0 + 1, cell.y0 + 1, cell.x1 - 1, cell.y1 - 1) if cell
                    else pymupdf.Rect(rect.x1, rect.y1, rect.x1 + 220, rect.y1 + 60))
        if rect.width < 20 or rect.height < 12:
            rect = pymupdf.Rect(rect.x0, rect.y0, max(rect.x1, rect.x0 + 20),
                                max(rect.y1, rect.y0 + 12))
        self._new_box(rect)


class _SearchTool:
    """Keresés és csere az egész iratban, előnézettel (23.3)."""

    def _init_search(self):
        self.s_text = tk.StringVar(value="")
        self.s_repl = tk.StringVar(value="")
        self.s_case = tk.BooleanVar(value=False)
        self.s_whole = tk.BooleanVar(value=False)
        self.s_regex = tk.BooleanVar(value=False)
        self.hits, self.plan, self.hit_sel = [], [], None
        for v in (self.s_text, self.s_case, self.s_whole, self.s_regex):
            v.trace_add("write", lambda *a: debounce(self, "_search_job", self._search_run, 250))
        self.s_repl.trace_add("write", lambda *a: debounce(self, "_plan_job", self._search_plan, 200))

    def _build_search(self, left):
        p = ttk.LabelFrame(left, text="Keresés és csere")
        g = ttk.Frame(p)
        g.pack(fill="x", padx=6, pady=(6, 0))
        ttk.Label(g, text="Keresett:").grid(row=0, column=0, sticky="w")
        self.s_entry = ttk.Entry(g, textvariable=self.s_text)
        self.s_entry.grid(row=0, column=1, sticky="ew", padx=(4, 2))
        self.s_entry.bind("<Return>", lambda e: self._hit_step(1))
        self.s_entry.bind("<Shift-Return>", lambda e: self._hit_step(-1))
        for col, (ic, d, tip) in enumerate((("up", -1, "Előző találat (Shift+F3)"),
                                            ("down", 1, "Következő találat (F3, Enter)")), 2):
            bt = ttk.Button(g, image=ui_icon(ic), command=lambda d=d: self._hit_step(d))
            bt.grid(row=0, column=col, padx=(0, 1))
            Tip(bt, tip)
        ttk.Label(g, text="Csere:").grid(row=1, column=0, sticky="w", pady=(4, 0))
        re_ = ttk.Entry(g, textvariable=self.s_repl)
        re_.grid(row=1, column=1, columnspan=3, sticky="ew", padx=(4, 0), pady=(4, 0))
        Tip(re_, "Üresen hagyva a találat törlődik.")
        g.columnconfigure(1, weight=1)
        o = ttk.Frame(p)
        o.pack(fill="x", padx=6, pady=(4, 0))
        ttk.Checkbutton(o, text="Kis-/nagybetű", variable=self.s_case).pack(side="left")
        ttk.Checkbutton(o, text="Egész szó", variable=self.s_whole).pack(side="left", padx=6)
        rx = ttk.Checkbutton(o, text="Minta", variable=self.s_regex)
        rx.pack(side="left")
        Tip(rx, "Reguláris kifejezés, pl. \\d{3} ?\\d{3} ?\\d{3}")
        self.s_info = ttk.Label(p, foreground="#555")
        self.s_info.pack(anchor="w", padx=6, pady=(6, 2))
        self.s_list = HitList(p, ("Old.", "Találat", "Csere"), (34, 170, 112), height=7,
                              on_change=self._hits_counted, on_select=self._hit_pick)
        self.s_list.pack(fill="x", padx=6)
        r = ttk.Frame(p)
        r.pack(fill="x", padx=6, pady=(4, 0))
        ttk.Button(r, text="Mind", command=lambda: self.s_list.set_all(True)).pack(side="left")
        ttk.Button(r, text="Egyiket se", command=lambda: self.s_list.set_all(False)).pack(
            side="left", padx=4)
        self.s_note = ttk.Label(p, foreground="#555", wraplength=330)
        self.s_note.pack(anchor="w", fill="x", padx=6, pady=(4, 6))
        a = self._abar("search")
        self.s_go = ttk.Button(a, text="Csere a kijelöltekre", style="Accent.TButton",
                               command=self._do_replace)
        self.s_go.pack(fill="x")
        self._search_empty()
        return p

    def _enter_search(self):
        self.s_entry.focus_set()
        self.s_entry.select_range(0, "end")
        self._search_run()

    def _search_empty(self):
        self.s_info.configure(text="Írd be, mit keresel — a találatok azonnal látszanak.",
                              foreground="#555")
        self.s_go.state(["disabled"])
        self.s_note.configure(text="")

    def _search_run(self):
        self._search_job = None
        if not self.doc:
            return
        txt = self.s_text.get()
        rx = search_regex(txt, self.s_regex.get(), self.s_case.get(), self.s_whole.get())
        self.hits, self.hit_sel = [], None
        if not txt:
            self._search_empty()
            self.s_list.fill_rows([])
        elif rx is None:
            self.s_info.configure(text="Hibás minta — nézd meg a zárójeleket.",
                                  foreground=COL_WARN)
            self.s_list.fill_rows([])
        else:
            self.hits = find_hits(self.doc, rx, cache=self._tcache())
            if not self.hits and not has_text_layer(self.doc):
                self.s_info.configure(text="Az iratnak nincs szövegrétege (szkennelt) — "
                                           "előbb Szövegfelismerés.", foreground=COL_WARN)
            self._search_plan()
        self._draw_hits()

    def _search_plan(self):
        """A csere előnézete: minden sorban, mi lesz belőle — még írás előtt."""
        self._plan_job = None
        if not self.doc:
            return
        repl = self.s_repl.get()
        self.plan = replace_plan(self.doc, self.hits, repl, edit_font(self.font_name.get())) \
            if self.hits else []
        rows = []
        for i, it in enumerate(self.plan):
            h = it["hit"]
            b, m, a = h["ctx"]
            ctx = f"…{b[-9:]}«{m}»{a[:14]}"
            # A teljes megjegyzés kiválasztáskor az állapotsorban (_show_hit); a keskeny
            # oszlopba a rövid alakja, és ahol nem cserélünk, csak az ok.
            note = ("törlés" if not repl and it["ok"] else
                    plan_short(it["note"] if it["ok"] else it["note"].split(" · ")[0]))
            rows.append((i, (h["page"] + 1, ctx, note), it["ok"], not it["ok"]))
        self.s_list.fill_rows(rows)
        bad = sum(1 for it in self.plan if not it["ok"])
        if self.hits:
            # A „nem fér el” ide is: a lenti magyarázat alacsony ablakban görgetés mögött van.
            pages = len({h["page"] for h in self.hits})
            self.s_info.configure(text=f"{len(self.hits)} találat {pages} oldalon"
                                       + (f" · {bad} nem fér el" if bad else ""),
                                  foreground=COL_WARN if bad else "#555")
        self.s_note.configure(
            text=(f"{bad} helyen az új szöveg nem fér el a sorban: ezek nincsenek kijelölve. "
                  "Ott a Bekezdés eszköz „Bekezdés szövege…” gombja újratördeli a bekezdést."
                  if bad else
                  "A sor többi része a helyére csúszik, ha az új szöveg más hosszú. A csere "
                  "egy lépés: Ctrl+Z visszavonja."), foreground=COL_WARN if bad else "#555")

    def _hits_counted(self, n):
        if hasattr(self, "s_go"):
            self.s_go.configure(text=f"Csere a kijelöltekre ({n})" if n else "Csere a kijelöltekre")
            self.s_go.state(["!disabled"] if n else ["disabled"])
        self._draw_hits()

    def _hit_list(self):
        """Az aktív eszköz találatai: keresés vagy személyes adat."""
        return self.hits if self.mode.get() == "search" else self.pii_hits

    def _hit_on(self, i) -> bool:
        lst = self.s_list if self.mode.get() == "search" else self.p_list
        return any(k == i for k in lst.selected())

    def _hit_pick(self, i):
        self.hit_sel = i
        if getattr(self, "_pick_quiet", False):
            self._draw_hits()            # a vászonról jött: a nézet ne ugorjon
            return
        self._show_hit(i)

    def _hits_down(self, pt):
        """Kattintás egy kiemelt találatra: a listában is kijelölődik."""
        lst = self.s_list if self.mode.get() == "search" else self.p_list
        for i, h in enumerate(self._hit_list()):
            if h["page"] == self.page_no and any(
                    r.contains(pymupdf.Point(*pt)) for r in h.get("rects") or [h["rect"]]):
                self._pick_quiet = True
                try:
                    lst.show_key(i)
                    self.update_idletasks()
                finally:
                    self._pick_quiet = False
                self.hit_sel = i
                self._draw_hits()
                return

    def _hit_step(self, d):
        hits = self._hit_list()
        if not hits:
            return "break"
        i = 0 if self.hit_sel is None else (self.hit_sel + d) % len(hits)
        self.hit_sel = i
        (self.s_list if self.mode.get() == "search" else self.p_list).show_key(i)
        self._show_hit(i)
        return "break"

    def _show_hit(self, i):
        """A találat lapjára ugrik, és a nézetet a találatra görgeti."""
        hits = self._hit_list()
        if not (0 <= i < len(hits)):
            return
        h = hits[i]
        if h["page"] != self.page_no:
            self._goto_page(h["page"])
        c, z = self.canvas, self.zoom
        r = h["rect"]
        w, ht = self._page_px
        cx, cy = (r.x0 + r.x1) / 2 * z, (r.y0 + r.y1) / 2 * z
        if w > 0 and ht > 0:
            c.xview_moveto(max(0.0, (cx - c.winfo_width() / 2) / w))
            c.yview_moveto(max(0.0, (cy - c.winfo_height() / 2) / ht))
        self._draw_hits()
        note = ""
        if self.mode.get() == "search" and i < len(self.plan) and self.s_repl.get():
            note = " · " + self.plan[i]["note"]
        self._say(f"{i + 1}/{len(hits)}. találat · {h['page'] + 1}. oldal{note}")

    def _draw_hits(self):
        c, z = self.canvas, self.zoom
        c.delete("hit")
        if self.mode.get() not in ("search", "pii") or not self.doc:
            return
        hits = self._hit_list()
        lst = self.s_list if self.mode.get() == "search" else self.p_list
        on = set(lst.selected())
        red = self.mode.get() == "pii"
        for i, h in enumerate(hits):
            if h["page"] != self.page_no:
                continue
            sel = i == self.hit_sel
            col = UI["warn"] if red else "#e0a000"
            for r in h.get("rects") or [h["rect"]]:
                c.create_rectangle(r.x0 * z - 2, r.y0 * z - 2, r.x1 * z + 2, r.y1 * z + 2,
                                   outline=UI["accent"] if sel else col,
                                   width=2.5 if sel else 1.5, dash=() if i in on else (3, 2),
                                   fill=col if i in on else "", stipple="gray25", tags="hit")

    def _do_replace(self):
        sel = set(self.s_list.selected())
        items = [it for i, it in enumerate(self.plan) if i in sel and it["ok"]]
        if not items:
            return
        repl, find = self.s_repl.get(), self.s_text.get()
        self._change(lambda: apply_replace(self.doc, items, repl),
                     f"{len(items)} csere kész.")
        self._search_run()
        left = len(self.hits)
        rx = search_regex(find, self.s_regex.get(), self.s_case.get(), self.s_whole.get())
        if rx is not None and not rx.search(repl):
            self.s_info.configure(
                text=(f"{len(items)} csere kész — ellenőrizve: a keresett szöveg "
                      f"{'már sehol nincs' if not left else f'még {left} helyen van'}."),
                foreground=COL_OK if not left else COL_WARN)
        else:
            self.s_info.configure(text=f"{len(items)} csere kész.", foreground=COL_OK)


class _PiiTool:
    """Személyes adatok kitakarása mintákkal (23.4)."""

    def _init_pii(self):
        self.pii_hits = []
        self.p_keys = {k: tk.BooleanVar(value=on) for k, _l, _p, _c, on in PII_PATTERNS}
        self.p_custom = tk.StringVar(value="")
        self.p_black = tk.BooleanVar(value=True)
        self.p_meta = tk.BooleanVar(value=True)
        for v in list(self.p_keys.values()) + [self.p_custom]:
            v.trace_add("write", lambda *a: debounce(self, "_pii_job", self._pii_run, 250))

    def _build_pii(self, left):
        p = ttk.LabelFrame(left, text="Személyes adatok kitakarása")
        ttk.Label(p, text="Mit keressen:", foreground="#555").pack(anchor="w", padx=6, pady=(6, 0))
        g = ttk.Frame(p)
        g.pack(fill="x", padx=6)
        self.p_checks = {}
        for n, (key, label, _p, check, _on) in enumerate(PII_PATTERNS):
            cb = ttk.Checkbutton(g, text=label, variable=self.p_keys[key])
            cb.grid(row=n // 2, column=n % 2, sticky="w", padx=(0, 6))
            self.p_checks[key] = (cb, label)
            if check:
                Tip(cb, "Csak az ellenőrzőszám szerint hibátlan számot jelöli meg — "
                        "az iktatószám és társai nem kerülnek a listába.")
        g.columnconfigure(0, weight=1)
        g.columnconfigure(1, weight=1)
        c = ttk.Frame(p)
        c.pack(fill="x", padx=6, pady=(4, 0))
        ttk.Label(c, text="Saját szöveg:").pack(side="left")
        ce = ttk.Entry(c, textvariable=self.p_custom)
        ce.pack(side="left", fill="x", expand=True, padx=(4, 0))
        Tip(ce, "Például egy név vagy cím, amit szintén ki kell takarni.")
        self.p_banner = ttk.Frame(p)
        self.p_banner_lbl = ttk.Label(self.p_banner, style="Warn.TLabel", wraplength=330,
                                      text="Ez az irat szkennelt kép: nincs benne kereshető "
                                           "szöveg. Előbb ismertesd fel a szövegét.")
        self.p_banner_lbl.pack(anchor="w")
        ttk.Button(self.p_banner, text="Szövegfelismerés…",
                   command=lambda: self._switch_mode("ocr")).pack(anchor="w", pady=(2, 0))
        o = ttk.Frame(p)
        o.pack(fill="x", padx=6, pady=(6, 0))
        ttk.Label(o, text="Sáv:").pack(side="left")
        ttk.Radiobutton(o, text="fekete", value=True, variable=self.p_black).pack(side="left", padx=4)
        ttk.Radiobutton(o, text="fehér", value=False, variable=self.p_black).pack(side="left")
        mc = ttk.Checkbutton(o, text="metaadat is", variable=self.p_meta)
        mc.pack(side="right")
        Tip(mc, "A metaadatot is törli: cím, szerző, tárgy és az XMP-csomag. A Műhely "
                "bélyege (dolgozó, típus) megmarad: abból ismeri fel az Áttekintő az iratot.")
        self.p_info = ttk.Label(p, foreground="#555")
        self.p_info.pack(anchor="w", padx=6, pady=(6, 2))
        self.p_list = HitList(p, ("Old.", "Típus", "Találat"), (34, 120, 162), height=6,
                              on_change=self._pii_counted, on_select=self._hit_pick)
        self.p_list.pack(fill="x", padx=6)
        r = ttk.Frame(p)
        r.pack(fill="x", padx=6, pady=(4, 0))
        ttk.Button(r, text="Mind", command=lambda: self.p_list.set_all(True)).pack(side="left")
        ttk.Button(r, text="Egyiket se", command=lambda: self.p_list.set_all(False)).pack(
            side="left", padx=4)
        self.p_note = ttk.Label(p, foreground="#555", wraplength=330,
                                text="A kitakarás végleges: a szöveg és a kép képpontjai is "
                                     "törlődnek, nem csak le vannak takarva. Ctrl+Z a mentésig "
                                     "visszavonja.")
        self.p_note.pack(anchor="w", fill="x", padx=6, pady=(4, 6))
        a = self._abar("pii")
        self.p_go = ttk.Button(a, text="Kitakarás", style="Accent.TButton", command=self._do_pii)
        self.p_go.pack(fill="x")
        return p

    def _enter_pii(self):
        self._pii_run()

    def _pii_run(self):
        self._pii_job = None
        if not self.doc:
            return
        keys = {k for k, v in self.p_keys.items() if v.get()}
        self.pii_hits = find_pii(self.doc, keys, self.p_custom.get(), cache=self._tcache())
        self.hit_sel = None
        counts = {}
        for h in self.pii_hits:
            counts[h["kind"]] = counts.get(h["kind"], 0) + 1
        for key, (cb, label) in self.p_checks.items():
            n = counts.get(label, 0)
            cb.configure(text=f"{label} ({n})" if self.p_keys[key].get() and n else label)
        scan = not has_text_layer(self.doc)
        if scan:
            self.p_banner.pack(fill="x", padx=6, pady=(6, 0), before=self.p_info)
        else:
            self.p_banner.pack_forget()
        rows = [(i, (h["page"] + 1, h["kind"], h["text"]), True, False)
                for i, h in enumerate(self.pii_hits)]
        self.p_list.fill_rows(rows)
        pages = len({h["page"] for h in self.pii_hits})
        self.p_info.configure(
            text=(f"{len(self.pii_hits)} találat {pages} oldalon — nézd át, mielőtt kitakarod"
                  if self.pii_hits else ("Nincs találat." if not scan else "")),
            foreground="#555")
        self._draw_hits()

    def _pii_counted(self, n):
        if hasattr(self, "p_go"):
            self.p_go.configure(text=f"Kitakarás ({n})" if n else "Kitakarás")
            self.p_go.state(["!disabled"] if n else ["disabled"])
        self._draw_hits()

    def _do_pii(self):
        sel = set(self.p_list.selected())
        hits = [h for i, h in enumerate(self.pii_hits) if i in sel]
        if not hits:
            return
        texts = {h["text"] for h in hits}
        black, meta = self.p_black.get(), self.p_meta.get()

        def go():
            redact_hits(self.doc, hits, black)
            if meta:
                clean_metadata(self.doc)
        self._change(go, f"{len(hits)} adat kitakarva.")
        self._pii_run()
        left = sum(1 for h in self.pii_hits if h["text"] in texts)
        self.p_info.configure(
            text=(f"{len(hits)} adat kitakarva — ellenőrizve: "
                  + ("egyik sem maradt az iratban." if not left else f"még {left} maradt!")),
            foreground=COL_OK if not left else COL_WARN)


class _DecorTool:
    """Fejléc, lábléc, oldalszám, bélyeg, vízjel — élő réteg, a mentés égeti be (23.5)."""

    def _init_decor(self):
        self.decor = Decor()
        d = self.decor
        self.d_vars = {}
        for name, val in asdict(d).items():
            if name == "stamp_xy":
                continue
            var = (tk.BooleanVar if isinstance(val, bool) else
                   tk.DoubleVar if isinstance(val, float) else tk.StringVar)(value=val)
            var.trace_add("write", lambda *a: self._decor_changed())
            self.d_vars[name] = var
        self._d_focus = None              # a változó ide kerül beszúráskor
        self._ddrag = None

    def _build_decor(self, left, fonts):
        p = ttk.LabelFrame(left, text="Fejléc, lábléc, oldalszám, bélyeg")
        v = self.d_vars
        ttk.Label(p, text="Gyors beállítás — egy kattintás:", foreground="#555").pack(
            anchor="w", padx=6, pady=(6, 2))
        q = ttk.Frame(p)
        q.pack(fill="x", padx=6)
        for k, (txt, fn, tip) in enumerate((
                ("Oldalszám", self._preset_pageno, "„1/3” alul középen, minden lapon"),
                ("Másolat", self._preset_wm, "„MÁSOLAT” halvány, átlós vízjel minden lapon"),
                ("Iktatva", self._preset_stamp,
                 "„Iktatva: <mai dátum>” bélyeg az első lap jobb felső sarkán"))):
            bt = ttk.Button(q, text=txt, command=fn)
            bt.grid(row=0, column=k, sticky="ew", padx=(0 if k == 0 else 3, 0))
            q.columnconfigure(k, weight=1, uniform="pre")
            Tip(bt, tip)

        def head(key, label, align_key=None):
            """Az elem első sora: jelölő a nevével, jobbra az igazítás."""
            fr = ttk.Frame(p)
            fr.pack(fill="x", padx=6, pady=(8, 0))
            ttk.Checkbutton(fr, text=label, variable=v[f"{key}_on"]).pack(side="left")
            if align_key:
                for val, ic in (("right", "al_right"), ("center", "al_center"), ("left", "al_left")):
                    rb = ttk.Radiobutton(fr, image=ui_icon(ic, px=13), value=val,
                                         variable=v[align_key], style="Icon.Tile.TRadiobutton")
                    rb.pack(side="right", padx=(2, 0))
                    Tip(rb, {"left": "Balra", "center": "Középre", "right": "Jobbra"}[val])
            return fr

        def entry(var):
            e = ttk.Entry(p, textvariable=var)
            e.pack(fill="x", padx=(28, 6), pady=(2, 0))
            e.bind("<FocusIn>", lambda ev, e=e: setattr(self, "_d_focus", e))
            return e

        head("header", "Fejléc", "header_align")
        entry(v["header"])
        head("footer", "Lábléc", "footer_align")
        entry(v["footer"])
        head("pageno", "Oldalszám", "pageno_align")
        pr = ttk.Frame(p)
        pr.pack(fill="x", padx=(28, 6), pady=(2, 0))
        ttk.Combobox(pr, textvariable=v["pageno"], values=PAGENO_FORMATS, width=14).pack(
            side="left")
        ttk.Checkbutton(pr, text="az első lapon nem", variable=v["pageno_skip_first"]).pack(
            side="left", padx=(8, 0))
        sh = head("stamp", "Bélyeg")
        bt = ttk.Button(sh, text="Sarokba", command=self._stamp_home)
        bt.pack(side="right")
        Tip(bt, "A bélyeg vissza a jobb felső sarokba. A lapon húzással bárhová tehető.")
        ttk.Combobox(sh, textvariable=v["stamp_color"], values=[n for n, _c in STAMP_COLORS],
                     state="readonly", width=7).pack(side="right", padx=4)
        entry(v["stamp"])
        ttk.Checkbutton(p, text="csak az első lapon", variable=v["stamp_first_only"]).pack(
            anchor="w", padx=(28, 6), pady=(2, 0))
        wh = head("wm", "Vízjel")
        ttk.Scale(wh, from_=0.05, to=0.5, variable=v["wm_opacity"], length=110).pack(side="right")
        ttk.Label(wh, text="halvány … erős", foreground="#555").pack(side="right", padx=4)
        entry(v["wm"])

        f = ttk.Frame(p)
        f.pack(fill="x", padx=6, pady=(8, 0))
        ttk.Label(f, text="Betű:").pack(side="left")
        ttk.Combobox(f, textvariable=v["family"], values=fonts, state="readonly",
                     width=10).pack(side="left", padx=(4, 4))
        ttk.Spinbox(f, from_=6, to=24, increment=0.5, textvariable=v["size"],
                    width=4).pack(side="left")
        ttk.Label(f, text="pt").pack(side="left", padx=(2, 0))
        ttk.Spinbox(f, from_=6, to=80, increment=2, textvariable=v["margin"],
                    width=4).pack(side="right")
        ttk.Label(f, text="Margó:").pack(side="right", padx=(0, 4))
        vb = ttk.Menubutton(p, text="Változó beszúrása")
        menu = tk.Menu(vb, tearoff=False)
        for var, desc in DECOR_VARS:
            menu.add_command(label=f"{var}  —  {desc}", command=lambda t=var: self._decor_insert(t))
        vb["menu"] = menu
        vb.pack(anchor="w", padx=6, pady=(6, 0))
        Tip(vb, "A {…} helyére mentéskor a valódi érték kerül: oldalszám, dátum, a "
                "dolgozó neve az irat bélyegéből vagy az alapértelmezett dolgozóból.")
        self.d_warn = ttk.Label(p, style="Warn.TLabel", wraplength=330)
        self.d_warn.pack(anchor="w", fill="x", padx=6, pady=(4, 0))
        ttk.Label(p, foreground="#555", wraplength=330,
                  text="Élőben látszik minden lapon; a Mentés égeti be. A bélyeg a lapon "
                       "húzással mozgatható.").pack(anchor="w", fill="x", padx=6, pady=(4, 6))
        a = self._abar("decor")
        ttk.Button(a, text="Mind kikapcsolása", command=self._decor_off).pack(side="left")
        return p

    def _decor_insert(self, token):
        e = self._d_focus
        if e is None:
            self._say("Előbb kattints abba a mezőbe, ahová a változó kerüljön.")
            return
        e.insert("insert", token)
        e.focus_set()

    def _decor_from_vars(self) -> Decor:
        d = copy.copy(self.decor)
        for name, var in self.d_vars.items():
            try:
                setattr(d, name, var.get())
            except (tk.TclError, ValueError):
                pass                      # gépelés közben érvénytelen szám: a régi marad
        d.size = max(5.0, min(30.0, float(d.size)))
        d.margin = max(4.0, min(120.0, float(d.margin)))
        return d

    def _decor_to_vars(self):
        self._quiet = True
        try:
            for name, var in self.d_vars.items():
                var.set(getattr(self.decor, name))
        finally:
            self._quiet = False

    def _decor_changed(self):
        if self._quiet:
            return
        debounce(self, "_decor_job", self._decor_apply, self.LIVE_MS)

    def _decor_apply(self):
        self._decor_job = None
        new = self._decor_from_vars()
        if new == self.decor or not self.doc:
            return
        self._tchange(lambda: setattr(self, "decor", new), key=("decor",), repaint=True)
        self._decor_check()

    def _set_decor(self, **kw):
        self._decor_from_vars()
        new = copy.copy(self.decor)
        for k, val in kw.items():
            setattr(new, k, val)
        if self.doc:
            self._tchange(lambda: setattr(self, "decor", new), key=None, repaint=True)
        else:
            self.decor = new
        self._decor_to_vars()
        self._decor_check()

    def _preset_pageno(self):
        self._set_decor(pageno_on=True, pageno="{oldal}/{összes}", pageno_align="center")

    def _preset_wm(self):
        self._set_decor(wm_on=True, wm="MÁSOLAT")

    def _preset_stamp(self):
        self._set_decor(stamp_on=True, stamp="Iktatva: {dátum}", stamp_first_only=True)

    def _stamp_home(self):
        self._set_decor(stamp_xy=(0.0, 0.0))

    def _decor_off(self):
        self._set_decor(header_on=False, footer_on=False, pageno_on=False, stamp_on=False,
                        wm_on=False)

    def _decor_ctx(self, pno):
        return decor_ctx(self.doc, self.path, pno, self.app.worker_name()
                         if hasattr(self.app, "worker_name") else "")

    def _decor_check(self):
        """Ütközés a lap szövegével — oldalanként, az első 30 lapon."""
        if not self.doc or not self.decor.any_on():
            self.d_warn.configure(text="")
            return
        hits = {}
        for pno in range(min(self.doc.page_count, 30)):
            for kind in decor_overlaps(self.doc[pno], self.decor, self._decor_ctx(pno), pno):
                hits.setdefault(kind, []).append(pno + 1)
        self.d_warn.configure(text="; ".join(
            f"A {k} a {', '.join(map(str, p[:4]))}{'…' if len(p) > 4 else ''}. oldalon a lap "
            f"szövegére esik" for k, p in hits.items())
            + (" — növeld a margót, vagy tedd máshová." if hits else ""))

    def _enter_decor(self):
        self._decor_to_vars()
        self._decor_check()

    def _draw_decor(self):
        c, z = self.canvas, self.zoom
        c.delete("dec")
        if self.mode.get() != "decor" or not self.doc or not self.decor.any_on():
            return
        page = self._page()
        for kind, _t, r, *_ in decor_items(page.rect, self.decor, self._decor_ctx(self.page_no),
                                           self.page_no):
            if kind == "vízjel":
                continue
            c.create_rectangle(r.x0 * z - 3, r.y0 * z - 3, r.x1 * z + 3, r.y1 * z + 3,
                               outline=UI["accent"], dash=(3, 2), tags="dec")
            c.create_text(r.x0 * z - 3, r.y0 * z - 5, anchor="sw", text=kind,
                          font=("Segoe UI", 7), fill=UI["accent"], tags="dec")

    def _decor_down(self, e, pt) -> bool:
        if not self.decor.stamp_on or (self.decor.stamp_first_only and self.page_no > 0):
            return False
        r = stamp_rect(self._page().rect, self.decor, self._decor_ctx(self.page_no))
        if not r.contains(pymupdf.Point(*pt)):
            return False
        self._ddrag = {"x": e.x, "y": e.y, "r": r, "moved": False}
        return True

    def _decor_drag(self, e):
        d = self._ddrag
        dx, dy = e.x - d["x"], e.y - d["y"]
        if not d["moved"] and abs(dx) + abs(dy) < 3:
            return
        d["moved"] = True
        self.canvas.move("dec", dx - d.get("adx", 0), dy - d.get("ady", 0))
        d["adx"], d["ady"] = dx, dy

    def _decor_up(self, e):
        d, self._ddrag = self._ddrag, None
        if not d["moved"]:
            return
        z = self.zoom
        r = d["r"]
        x, y = r.x0 + d.get("adx", 0) / z, r.y0 + d.get("ady", 0) / z
        self._set_decor(stamp_xy=(max(0.1, x), max(0.1, y)))
        self._say("A bélyeg áthelyezve.")


class _FormTool:
    """Űrlap kitöltése és beégetése feltöltés előtt (23.6)."""

    def _init_form(self):
        self.fields = []
        self.f_focus = None               # a kijelölt mező xref-je
        self.f_vars = {}
        self.f_rows = {}
        self.f_filter = tk.StringVar(value="")
        self.f_family = tk.StringVar(value="Helvetica")
        self.f_filter.trace_add("write", lambda *a: self._form_filter())

    def _build_form(self, left, fonts):
        p = ttk.LabelFrame(left, text="Űrlap kitöltése")
        self.f_info = ttk.Label(p, foreground="#555", wraplength=330)
        self.f_info.pack(anchor="w", fill="x", padx=6, pady=(6, 0))
        fr = ttk.Frame(p)
        fr.pack(fill="x", padx=6, pady=(4, 0))
        ttk.Label(fr, text="Szűrő:").pack(side="left")
        fe = ttk.Entry(fr, textvariable=self.f_filter)
        fe.pack(side="left", fill="x", expand=True, padx=(4, 0))
        Tip(fe, "A mező nevének vagy értékének részlete — hosszú űrlapnál")
        self.f_box = ttk.Frame(p)
        self.f_box.pack(fill="x", padx=6, pady=(6, 0))
        b = ttk.Frame(p)
        b.pack(fill="x", padx=6, pady=(6, 0))
        ttk.Label(b, text="Beégetés betűje:").pack(side="left")
        ttk.Combobox(b, textvariable=self.f_family, values=fonts, state="readonly",
                     width=13).pack(side="left", padx=4)
        ttk.Label(p, foreground="#555", wraplength=330,
                  text="A lapon a mező beégetett képe látszik — pontosan ez kerül a "
                       "feltöltött fájlba. Feltöltés előtt égesd be: a portál a kitölthető "
                       "mezőt gyakran üresnek látja, az ékezetes értéket (ő, ű) pedig "
                       "sok olvasó nem is mutatja.").pack(anchor="w", fill="x", padx=6, pady=(6, 6))
        a = self._abar("form")
        self.f_go = ttk.Button(a, text="Beégetés", style="Accent.TButton", command=self._do_flatten)
        self.f_go.pack(fill="x")
        self.f_family.trace_add("write", lambda *a: self._form_view_changed())
        return p

    def _form_view_changed(self):
        if self.mode.get() == "form" and self.doc:
            self._render()

    def _enter_form(self):
        self._form_build_rows()

    def _form_build_rows(self):
        for w in self.f_box.winfo_children():
            w.destroy()
        self.f_vars, self.f_rows = {}, {}
        self.fields = form_fields(self.doc) if self.doc else []
        if not self.fields:
            ttk.Label(self.f_box, foreground="#555", wraplength=320,
                      text="Ebben az iratban nincs kitölthető mező. Mezőt az Űrlapmező "
                           "eszközzel tehetsz rá (DocGen-sablon).").pack(anchor="w")
            self.f_info.configure(text="")
            self.f_go.state(["disabled"])
            return
        self.f_go.state(["!disabled"])
        for f in self.fields:
            row = ttk.Frame(self.f_box)
            row.pack(fill="x", pady=(0, 4))
            label = f["label"] or f["name"] or "(névtelen mező)"
            if f["page"] != 0 or self.doc.page_count > 1:
                label = f"{label}  ·  {f['page'] + 1}. o."
            x = f["xref"]
            if f["type"] in FIELD_CHECK_TYPES:
                var = tk.BooleanVar(value=f["value"] not in (None, "", "Off", False))
                w = ttk.Checkbutton(row, text=label, variable=var)
                w.pack(anchor="w")
            else:
                ttk.Label(row, text=label, foreground="#555", wraplength=320).pack(anchor="w")
                var = tk.StringVar(value=str(f["value"] or ""))
                if f["choices"]:
                    w = ttk.Combobox(row, textvariable=var, values=f["choices"])
                else:
                    w = ttk.Entry(row, textvariable=var)
                w.pack(fill="x")
            w.bind("<FocusIn>", lambda e, x=x: self._form_focus(x, from_panel=True), add="+")
            var.trace_add("write", lambda *a, x=x: debounce(
                self, f"_fjob{x}", lambda: self._form_set(x), 250))
            self.f_vars[x], self.f_rows[x] = var, (row, w)
        self._form_info()
        self._form_filter()

    def _form_info(self):
        empty = sum(1 for f in self.fields
                    if f["type"] not in FIELD_CHECK_TYPES and not str(self.f_vars[f["xref"]].get()).strip())
        self.f_info.configure(text=f"{len(self.fields)} mező" + (f" · {empty} üres" if empty else
                                                                 " · mind kitöltve"))

    def _form_filter(self):
        q = strip_accents(self.f_filter.get().strip())
        for f in self.fields:
            row, _w = self.f_rows.get(f["xref"], (None, None))
            if row is None:
                continue
            hay = strip_accents(f"{f['label']} {f['name']} {self.f_vars[f['xref']].get()}")
            if not q or q in hay:
                row.pack(fill="x", pady=(0, 4))
            else:
                row.pack_forget()

    def _form_set(self, xref):
        f = next((f for f in self.fields if f["xref"] == xref), None)
        if f is None or not self.doc:
            return
        val = self.f_vars[xref].get()
        if (val if f["type"] in FIELD_CHECK_TYPES else str(val)) == f["value"]:
            return
        self._change(lambda: set_field(self.doc, f["page"], xref, val),
                     f"Kitöltve: {f['label'] or f['name']}", key=("form", xref))
        f["value"] = val
        self._form_info()

    def _flush_form(self):
        for x in list(self.f_vars):
            job = getattr(self, f"_fjob{x}", None)
            if job:
                try:
                    self.after_cancel(job)
                except Exception:
                    pass
                setattr(self, f"_fjob{x}", None)
                self._form_set(x)

    def _form_focus(self, xref, from_panel=False):
        self.f_focus = xref
        f = next((f for f in self.fields if f["xref"] == xref), None)
        if f is None:
            return
        if f["page"] != self.page_no:
            self._goto_page(f["page"])
        if not from_panel:
            row, w = self.f_rows[xref]
            w.focus_set()
            self._scroll_left_to(row)
        self._draw_form()

    def _draw_form(self):
        c, z = self.canvas, self.zoom
        c.delete("frm")
        if self.mode.get() != "form":
            return
        for f in self.fields:
            if f["page"] != self.page_no:
                continue
            r = f["rect"]
            sel = f["xref"] == self.f_focus
            c.create_rectangle(r.x0 * z, r.y0 * z, r.x1 * z, r.y1 * z,
                               outline=UI["accent"], width=2 if sel else 1,
                               dash=() if sel else (2, 3), tags="frm")

    def _form_down(self, e, pt) -> bool:
        for f in self.fields:
            if f["page"] == self.page_no and f["rect"].contains(pymupdf.Point(*pt)):
                self._form_focus(f["xref"])
                return True
        return False

    def _do_flatten(self):
        self._flush_form()
        if not self.fields:
            return
        fam = self.f_family.get()
        out = []
        self._change(lambda: out.append(flatten_form(self.doc, fam)), "")
        n = out[0] if out else 0
        self.f_focus = None
        self._form_build_rows()
        self.f_info.configure(text=f"Beégetve: {n} mező a lap tartalma lett — a portál így "
                                   "biztosan látja. Ctrl+Z a mentésig visszavonja.",
                              foreground=COL_OK)
        self._say(f"Beégetve: {n} mező.")


class _OcrTool:
    """Szövegfelismerés a beépített motorral (23.7)."""

    def _init_ocr(self):
        self.o_scope = tk.StringVar(value="scans")
        self.o_show = tk.BooleanVar(value=True)
        self.o_cancel = None
        self.o_show.trace_add("write", lambda *a: self._draw_ocr())

    def _build_ocr(self, left):
        p = ttk.LabelFrame(left, text="Szövegfelismerés (OCR)")
        self.o_status = ttk.Label(p, wraplength=330)
        self.o_status.pack(anchor="w", fill="x", padx=6, pady=(6, 0))
        self.o_info = ttk.Label(p, foreground="#555", wraplength=330)
        self.o_info.pack(anchor="w", fill="x", padx=6, pady=(4, 0))
        s = ttk.Frame(p)
        s.pack(fill="x", padx=6, pady=(6, 0))
        self.o_r_all = ttk.Radiobutton(s, text="Minden szöveg nélküli oldal", value="scans",
                                       variable=self.o_scope)
        self.o_r_all.pack(anchor="w")
        self.o_r_one = ttk.Radiobutton(s, text="Csak ez az oldal", value="page",
                                       variable=self.o_scope)
        self.o_r_one.pack(anchor="w")
        # A haladásjelző csak futás közben látszik; utána az eredmény marad a helyén.
        # Üzenet nélkül a sor el is tűnik (üresen egy sornyi rés maradt a panelen).
        self.o_run = ttk.Frame(p)
        self.o_bar = ttk.Progressbar(self.o_run, mode="determinate")
        self.o_prog = ttk.Label(self.o_run, foreground="#555", wraplength=330)
        self.o_prog.pack(anchor="w", fill="x")
        self._ocr_last = None             # (irat, eredmény-üzenet): az eszközre visszatérve
        self.o_showcb = ttk.Checkbutton(p, text="Felismert szavak mutatása a lapon",
                                        variable=self.o_show)
        self.o_showcb.pack(anchor="w", padx=6, pady=(8, 0))
        self.o_after = ttk.Frame(p)
        ttk.Button(self.o_after, text="Keresés…", command=lambda: self._switch_mode("search")).pack(side="left")
        ttk.Button(self.o_after, text="Személyes adat…",
                   command=lambda: self._switch_mode("pii")).pack(side="left", padx=4)
        ttk.Label(p, foreground="#555", wraplength=330,
                  text="A felismert szöveg láthatatlan rétegként kerül a lap képe alá: a lap "
                       "képe nem változik, de kereshető, kijelölhető és kitakarható lesz. "
                       "Telepíteni semmit nem kell — a magyar nyelvi fájl a program "
                       "tessdata mappájában van.").pack(anchor="w", fill="x", padx=6, pady=(6, 6))
        a = self._abar("ocr")
        self.o_go = ttk.Button(a, text="Felismerés indítása", style="Accent.TButton",
                               command=self._ocr_start)
        self.o_go.pack(fill="x")
        return p

    def _ocr_say(self, text, color="#555"):
        """A haladás- és eredménysor: üres szövegnél el is tűnik."""
        self.o_prog.configure(text=text, foreground=color)
        if text:
            self.o_run.pack(fill="x", padx=6, pady=(8, 0), before=self.o_showcb)
        else:
            self.o_run.pack_forget()

    def _ocr_pages(self, scope=None):
        if not self.doc:
            return []
        if (scope or self.o_scope.get()) == "page":
            return [self.page_no] if not self._page().get_text("text").strip() else []
        return [i for i, pg in enumerate(self.doc) if page_is_scan(pg)]

    def _enter_ocr(self):
        if self.o_cancel:
            return                        # fut: a haladásjelző mutatja
        tess = tessdata_dir()
        if not tess:
            self.o_status.configure(
                text="● Hiányzik a magyar nyelvi fájl: tessdata\\hun.traineddata a program "
                     "mappájában. A Frissítés (tools\\frissit.vbs) hozza.", style="Warn.TLabel")
            self.o_go.state(["disabled"])
            return
        self.o_status.configure(text=f"● Kész a felismerésre — nyelv: "
                                     f"{'magyar és angol' if ocr_langs(tess) == 'hun+eng' else 'magyar'}",
                                style="Ok.TLabel")
        if not self.doc:
            self.o_info.configure(text="Válassz egy PDF-et.")
            self.o_go.state(["disabled"])
            return
        scans = self._ocr_pages("scans")
        here = not self._page().get_text("text").strip()
        self.o_r_all.configure(text=f"Minden szöveg nélküli oldal ({len(scans)})")
        self.o_r_one.state(["!disabled"] if here else ["disabled"])
        if not here and self.o_scope.get() == "page":
            self.o_scope.set("scans")
        n = self.doc.page_count
        self.o_info.configure(
            text=(f"Az irat {n} oldalából {len(scans)} szkennelt, szöveg nélküli."
                  if scans else f"Az irat mind a {n} oldala kereshető már — nincs mit felismerni."))
        self.o_go.state(["!disabled"] if scans or here else ["disabled"])
        self.o_bar.configure(value=0, maximum=max(1, len(scans)))
        last = self._ocr_last
        if last and last[0] is self.doc:
            self._ocr_say(last[1], COL_OK)
            self.o_after.pack(anchor="w", padx=6, pady=(4, 0), after=self.o_run)
        else:
            self._ocr_say("")
            self.o_after.pack_forget()

    def _ocr_start(self):
        if self.o_cancel:
            self.o_cancel()
            return
        tess, pages = tessdata_dir(), self._ocr_pages()
        if not tess or not pages:
            return
        self.o_bar.configure(value=0, maximum=len(pages))
        self._ocr_say(f"Indul… ({len(pages)} oldal, oldalanként pár másodperc)")
        self.o_bar.pack(fill="x", before=self.o_prog)
        self.o_go.configure(text="Mégsem", style="TButton")
        self.o_after.pack_forget()
        self._ocr_last = None
        self._ocr_doc = self.doc

        def step(i, n, pno):
            self.o_bar.configure(value=i - 1)
            self.o_prog.configure(text=f"{i}/{n}. — a {pno + 1}. oldal felismerése…")

        self.o_cancel = ocr_process(self, self.doc.tobytes(), pages, tess, ocr_langs(tess),
                                    self._ocr_done, step)

    def _ocr_done(self, out, err):
        self.o_cancel = None
        self.o_bar.pack_forget()
        self.o_go.configure(text="Felismerés indítása", style="Accent.TButton")
        if err is not None or out is None:
            msg = str(err) if err else "ismeretlen hiba"
            self._enter_ocr()
            self._ocr_say("Megszakítva — a lap nem változott." if "megszakítva" in msg
                          else f"Nem sikerült: {msg}", COL_WARN)
            return
        if self.doc is not getattr(self, "_ocr_doc", None):
            self._ocr_say("Közben másik irat nyílt meg — a felismerés eldobva.")
            return
        words = sum(len(w) for w in out.values())

        def go():
            for pno, ws in out.items():
                apply_ocr_words(self.doc[pno], ws)
        self._change(go, f"Felismerve: {words} szó {len(out)} oldalon.")
        self._ocr_last = (self.doc, f"Kész: {words} szó {len(out)} oldalon — az irat mostantól "
                                    "kereshető, kijelölhető és kitakarható.")
        self._enter_ocr()

    def _draw_ocr(self):
        c, z = self.canvas, self.zoom
        c.delete("ocrw")
        if self.mode.get() != "ocr" or not self.doc or not self.o_show.get():
            return
        for r in ocr_word_rects(self._page()):
            c.create_rectangle(r.x0 * z, r.y0 * z, r.x1 * z, r.y1 * z, outline=COL_OK,
                               tags="ocrw")


# Az eszközök: (mód, rövid felirat, teljes név, ikon, csoport, súgóbuborék). 0: a
# lapon dolgozik (kattintás, húzás), 1: az egész iraton (panel + előnézet).
EDIT_TOOLS = (
    ("text", "Szöveg", "Szöveg és X", "text", 0,
     "Szöveg átírása, új egysoros szöveg, X a jelölőnégyzetbe"),
    ("box", "Doboz", "Szövegdoboz", "textbox", 0,
     "Többsoros, szavanként formázható szöveg a megrajzolt keretben"),
    ("para", "Bekezdés", "Bekezdés formázása", "para", 0,
     "A lap egy bekezdésének igazítása, sortávja, betűje, behúzása"),
    ("field", "Mező", "Űrlapmező (DocGen-sablon)", "field", 0,
     "Kitölthető mező készítése — ebből lesz a DocGen PDF-sablonja"),
    ("erase", "Kitakarás", "Kitakarás", "eraser", 0,
     "Egy terület tartalmának végleges törlése"),
    ("search", "Keresés", "Keresés és csere", "search", 1,
     "Szöveg keresése és cseréje az egész iratban, előnézettel (Ctrl+F)"),
    ("pii", "Személyes", "Személyes adatok kitakarása", "shield", 1,
     "TAJ-szám, adóazonosító, útlevélszám és társai megkeresése és kitakarása"),
    ("decor", "Fejléc", "Fejléc, lábléc, oldalszám, bélyeg, vízjel", "header", 1,
     "Fejléc, lábléc, oldalszám, bélyeg, vízjel minden lapra"),
    ("form", "Űrlap", "Űrlap kitöltése", "form", 1,
     "A kitölthető mezők kitöltése, és beégetésük feltöltés előtt"),
    ("ocr", "Felismerés", "Szövegfelismerés (OCR)", "ocr", 1,
     "Szkennelt irat szövegének felismerése — utána kereshető, kitakarható"),
)


class EditorTab(_BoxTool, _SearchTool, _PiiTool, _DecorTool, _FormTool, _OcrTool,
                ttk.Frame):
    """Eszközök → Szerkesztés: kész PDF általános szerkesztése. Tíz eszköz két
    csoportban: a lapon (szöveg, szövegdoboz, bekezdés, űrlapmező, kitakarás) és az
    egész iraton (keresés-csere, személyes adat, fejléc-bélyeg, űrlapkitöltés,
    szövegfelismerés). Minden lépés visszavonható a mentésig; a mentés helyben
    megy, az előző példány a dolgozó 01_Elokeszitett mappájába kerül
    (szerkeszto-terv.md 16.). Az új szöveg, a szövegdoboz és a lapdíszítés a
    mentésig élő réteg, és minden formázás azonnal látszik (21., 23.)."""

    HINTS = {
        "text":  "Kattints szövegre: átírod. Üres helyre: új szöveg (húzható, nyilazható, "
                 "dupla kattintással átírható). Négyzetbe: X.",
        "box":   "Húzz téglalapot a lapon — abba kerül a szöveg. A panelen gépelj és "
                 "formázz, szavanként is.",
        "para":  "Kattints egy bekezdésre: a beállítás azonnal látszik a lapon. Ctrl+Z "
                 "visszavonja.",
        "field": "Kattintás: mező a cellába; húzás több cellán át: betűnkénti mezők. "
                 "Mezőre kattintva átnevezhető, Delete: törlés.",
        "erase": "Húzd körbe a területet: a tartalma (szöveg, kép, vonal) végleg törlődik, "
                 "a helye fehér.",
        "search": "A találatok kiemelve látszanak; a csere előtt soronként látod, mi lesz. "
                  "Ctrl+F, F3.",
        "pii":   "Megkeresi a személyes adatokat. Nézd át a listát, majd Kitakarás — "
                 "végleges törlés.",
        "decor": "Minden lapra: fejléc, lábléc, oldalszám, bélyeg, vízjel. Élőben látszik, "
                 "a Mentés égeti be.",
        "form":  "Töltsd ki a mezőket itt, vagy kattints a mezőre a lapon. Feltöltés "
                 "előtt: Beégetés.",
        "ocr":   "Szkennelt irat szövegének felismerése: utána kereshető, kijelölhető, "
                 "kitakarható.",
    }
    UNDO_MAX = 30
    LIVE_MS = 120             # a panel változása után ennyi idővel rajzolunk (gépelés)
    NUDGE, NUDGE_BIG = 1.0, 10.0       # nyíl / Shift+nyíl lépése (pt)
    # E fölött csak a látható sáv (és ráhagyás) rajzolódik: 6× nagyításon egy A4-es
    # lap 50 megapixel lenne — másodpercekig tartana, és százmegás képet tartana.
    RENDER_MAX_PX = 6_000_000

    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.path = self.doc = None
        self.log_parent = None           # az Áttekintőből nyitva: ide naplózunk
        self.page_no = 0
        self.view_zoom, self.zoom = 1.0, 1.0
        self.undo = []                   # [(PDF-bájtok | None, élő rétegek másolata)]
        self._undo_key = None            # az utolsó lépés kulcsa: az összevonáshoz
        self.dirty = False
        self.page_tk = None
        self._full = True                # az egész lap kirajzolva (nem csak a látható sáv)
        self._ver = 0                    # az irat változat-számlálója (gyorsítótárakhoz)
        self._vcache = None              # az előnézeti lapmásolat (díszítés, beégetett űrlap)
        self._tc, self._tc_ver = {}, -1  # a keresés szövegsor-gyorsítótára
        self._rendering = False
        self._painted = (0, 0, 0, 0)     # a kirajzolt sáv a vásznon (px)
        self._page_px = (0, 0)
        self._dr, self._lines = [], ([], [])
        self._press = self._entry = None
        self.sel_xref = None              # a kijelölt mező
        # -- elhelyezett szövegek (élő objektumok a mentésig) --
        self.texts = []
        self.sel_text = None              # a kijelölt szöveg uid-je
        self._uid = 0
        self._timgs, self._tbox = {}, {}  # uid -> PhotoImage / befoglaló (pt)
        self._tdrag = None                # [uid, x, y, eltolás x, eltolás y, mozdult-e]
        self._quiet = False               # a panel programból íródik: ne alkalmazzuk
        self.mode = tk.StringVar(value="text")
        fonts = edit_fonts()
        self.font_name = tk.StringVar(value="Calibri" if "Calibri" in fonts else fonts[0])
        self.font_size = tk.DoubleVar(value=10.5)
        self.t_bold = tk.BooleanVar(value=False)
        self.t_italic = tk.BooleanVar(value=False)
        self.t_under = tk.BooleanVar(value=False)
        self.t_color = (0.0, 0.0, 0.0)
        self.t_text = tk.StringVar(value="")
        self.field_name = tk.StringVar(value="")
        self.upper = tk.BooleanVar(value=False)
        self.info = tk.StringVar(value="Válassz egy PDF-et.")
        # -- bekezdés-formázás --
        self.para = None                  # a kijelölt bekezdés (paragraph_at szótára)
        self.para_pt = None               # a kattintás pontja: ide ismerjük fel újra
        self._base = {}                   # a bekezdés értékei kijelöléskor
        self._live = None                 # a futó élő formázás (lásd _live_apply)
        self._p_text = None               # a „Bekezdés szövege…” átírása
        self.p_align = tk.StringVar(value="left")
        self.p_reflow = tk.BooleanVar(value=False)
        self.p_gap = tk.DoubleVar(value=0)
        self.p_dy = tk.DoubleVar(value=0)
        self.p_family = tk.StringVar(value=UNCHANGED)
        self.p_size = tk.DoubleVar(value=0)
        self.p_bold = tk.BooleanVar(value=False)
        self.p_italic = tk.BooleanVar(value=False)
        self.p_under = tk.BooleanVar(value=False)
        self.p_il = tk.DoubleVar(value=0)
        self.p_ir = tk.DoubleVar(value=0)
        self.p_if = tk.DoubleVar(value=0)
        self.p_color = None               # None: a bekezdés mai színe marad
        self._abars = {}
        self._init_box(fonts)
        self._init_search()
        self._init_pii()
        self._init_decor()
        self._init_form()
        self._init_ocr()
        self._build(fonts)
        # Valós idejű formázás: a panel minden változása azonnal a lapra kerül.
        for v in (self.font_name, self.font_size, self.t_bold, self.t_italic,
                  self.t_under, self.t_text):
            v.trace_add("write", lambda *a: self._tstyle_changed())
        for v in (self.p_align, self.p_reflow, self.p_gap, self.p_dy, self.p_family,
                  self.p_size, self.p_bold, self.p_italic, self.p_under, self.p_il,
                  self.p_ir, self.p_if):
            v.trace_add("write", lambda *a: self._para_changed())

    def _build(self, fonts):
        # A bal panel görgethető: a bekezdéspanellel együtt 740 px-es ablakban nem
        # férne ki (mérve: 110 px hiányzott), és minden további sor újra elrontaná.
        # A görgetősáv csak akkor jelenik meg, ha tényleg kell — mint az Összeállító
        # típuspalettájánál (szerkeszto-terv.md 17.2, 19.7).
        shell, left = scroll_panel(self, 370, padx=(8, 0))
        self._lcanvas = next(w for w in shell.winfo_children() if w.winfo_class() == "Canvas")
        # Az eszköz fő művelete (Csere, Kitakarás, Beégetés …) a görgethető részen
        # KÍVÜL, fix alsó sávban: ne kelljen érte görgetni (20.3).
        self.actionbar = ttk.Frame(shell)
        self.actionbar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        # Megnyitott iratnál a fájllista egy sorra csukódik (a fájl nevével): a tíz
        # eszköz és a panelje így alacsony ablakban is görgetés nélkül látszik. Egy
        # kattintás kinyitja — másik irat választásához.
        self.filebar = fb = ttk.Frame(left)
        self.file_lbl = ttk.Label(fb, text="", font=FONT_SB)
        self.file_lbl.pack(side="left", fill="x", expand=True)
        self._file_tip = Tip(self.file_lbl, "")
        self.file_btn = ttk.Button(fb, text="Másik irat…", command=lambda: self._files_shown(True))
        self.file_btn.pack(side="right")
        self.files = FileList(left, "PDF-ek", (".pdf",), self._pick, height=3,
                              memory_key="szerkesztes")
        self.files.pack(fill="both", expand=True)

        # Az eszközök csempéken: két sor, öt oszlop — fölül a lapon dolgozók, alul az
        # egész iratra hatók. Ikon fölül, rövid felirat alul; a teljes név és a
        # magyarázat a súgóbuborékban és a panel címében. Rádiógomb-listaként a tíz
        # eszköz (és a csempe felirattal oldalt) a panel felét elvitte: alacsony
        # ablakban az eszköz saját panelje a látható részen kívülre csúszott.
        m = ttk.LabelFrame(left, text="Eszköz")
        m.pack(fill="x", pady=(6, 8))
        self.tiles_frame = m
        self.tiles = {}
        for grp in (0, 1):
            items = [t for t in EDIT_TOOLS if t[4] == grp]
            for k, (mode, short, full, icon, _g, tip) in enumerate(items):
                rb = ttk.Radiobutton(m, text=short, value=mode, variable=self.mode,
                                     command=self._mode_changed, style="VTile.TRadiobutton",
                                     image=(ui_icon(icon, px=18), "selected",
                                            ui_icon(icon, UI["accent"], px=18)),
                                     compound="top", takefocus=0)
                rb.grid(row=grp * 2 + 1, column=k, sticky="nsew", padx=(4 if k == 0 else 1, 4 if k == 4 else 1),
                        pady=(6 if grp == 0 else 2, 2))
                Tip(rb, f"{full} — {tip}")
                self.tiles[mode] = rb
            if grp == 0:
                ttk.Separator(m, orient="horizontal").grid(row=2, column=0, columnspan=5,
                                                           sticky="ew", padx=8, pady=(4, 2))
        for k in range(5):
            m.columnconfigure(k, weight=1, uniform="tile")
        self.hint = ttk.Label(m, text=self.HINTS["text"], wraplength=330, foreground="#555")
        self.hint.grid(row=5, column=0, columnspan=5, sticky="w", padx=8, pady=(6, 6))

        # Az eszközök paneljei EGYMÁS HELYÉN jelennek meg (nem egymás alatt):
        # 740 px-es ablakban együtt levágódnának (szerkeszto-terv.md 18., 19.7).
        self.textbox = self._build_text(left, fonts)
        self.fieldbox = f = ttk.LabelFrame(left, text="Kijelölt mező — a neve a DocGen-jelölő")
        ttk.Entry(f, textvariable=self.field_name).pack(fill="x", padx=6, pady=(6, 2))
        fr = ttk.Frame(f)
        fr.pack(fill="x", padx=6, pady=(0, 6))
        ttk.Button(fr, text="Átnevezés", command=self._rename).pack(side="left")
        ttk.Button(fr, text="Mező törlése", command=self._delete_field).pack(side="left", padx=6)
        ttk.Checkbutton(f, text="A DocGen nagybetűvel töltse ki (az egész sablont)",
                        variable=self.upper, command=self._upper_changed).pack(anchor="w", padx=6, pady=(0, 6))
        self.parabox = self._build_para(left, fonts)
        self.boxbox = self._build_box(left, fonts)
        self.searchbox = self._build_search(left)
        self.piibox = self._build_pii(left)
        self.decorbox = self._build_decor(left, fonts)
        self.formbox = self._build_form(left, fonts)
        self.ocrbox = self._build_ocr(left)
        self.panels = {"text": self.textbox, "box": self.boxbox, "para": self.parabox,
                       "field": self.fieldbox, "search": self.searchbox, "pii": self.piibox,
                       "decor": self.decorbox, "form": self.formbox, "ocr": self.ocrbox}
        self.textbox.pack(fill="x")
        self.actionbar.grid_remove()

        # A dokumentum műveletei a vászon fölött: a bal panel így alacsony
        # képernyőn is elfér.
        right = ttk.Frame(self)
        right.pack(side="right", fill="both", expand=True, padx=(0, 8), pady=8)
        bar = ttk.Frame(right)
        bar.grid(row=0, column=0, columnspan=2, sticky="ew")
        ttk.Button(bar, text="Visszavonás", command=self._undo).pack(side="left")
        ttk.Button(bar, text="Mentés", command=self._save).pack(side="left", padx=6)
        ttk.Button(bar, text="Mentés másként…", command=self._save_as).pack(side="left")

        # Második sor: lapozás és az állapot. Lapozógombok a beíró két oldalán — a
        # beíró apró nyilairól nem látszott, hogy lapoznak (a felhasználó legördülő
        # listának nézte). Az első sorban nem fértek el: ott a gombok összenyomták a
        # beírót, és az állapotból „nyi” maradt (ui-kep.py 6, 1280 px).
        nav = ttk.Frame(right)
        nav.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 6))
        self.btn_first = ttk.Button(nav, image=ui_icon("first"),
                                    command=lambda: self._goto_page(0))
        self.btn_prev = ttk.Button(nav, image=ui_icon("prev"),
                                   command=lambda: self._step_page(-1))
        self.btn_first.pack(side="left")
        self.btn_prev.pack(side="left", padx=(2, 6))
        Tip(self.btn_first, "Első oldal")
        Tip(self.btn_prev, "Előző oldal (PageUp)")
        ttk.Label(nav, text="Oldal").pack(side="left")
        self.page_var = tk.StringVar(value="1")
        self.page_spin = ttk.Spinbox(nav, from_=1, to=1, textvariable=self.page_var, width=4,
                                     command=self._change_page)
        self.page_spin.pack(side="left", padx=4)
        self.page_spin.bind("<Return>", lambda e: self._change_page())
        self.page_total = ttk.Label(nav, text="/ 1")
        self.page_total.pack(side="left")
        self.btn_next = ttk.Button(nav, image=ui_icon("next"),
                                   command=lambda: self._step_page(1))
        self.btn_last = ttk.Button(nav, image=ui_icon("last"),
                                   command=lambda: self._goto_page(-1))
        self.btn_next.pack(side="left", padx=(6, 2))
        self.btn_last.pack(side="left")
        Tip(self.btn_next, "Következő oldal (PageDown)")
        Tip(self.btn_last, "Utolsó oldal")
        # A nagyító is ebben a sorban, jobbra: az első sorból kis ablakban kiszorult.
        zb = ttk.Button(nav, text="Illeszt", command=lambda: self._view_zoom(0))
        zb.pack(side="right")
        Tip(zb, "Laphoz illesztés (szélességre)")
        for txt, k, tip in (("+", 1.25, "Nagyítás (Ctrl+görgő)"), ("−", 1 / 1.25, "Kicsinyítés")):
            bt = ttk.Button(nav, text=txt, width=3, command=lambda k=k: self._view_zoom(k))
            bt.pack(side="right", padx=(0, 2))
            Tip(bt, tip)
        # Az eszköz üzenetei az ablak alján, a teljes szélességű állapotsorban jelennek
        # meg (_say): ebben a sorban kis ablakban a nagyító mellől kiszorultak.
        self.canvas = tk.Canvas(right, bg=COL_CANVAS, highlightthickness=0, takefocus=1,
                                cursor="crosshair", height=180)
        self.hb = ttk.Scrollbar(right, orient="horizontal", command=self.canvas.xview)
        self.vb = ttk.Scrollbar(right, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=self._xset, yscrollcommand=self._yset)
        self.canvas.grid(row=2, column=0, sticky="nsew")
        self.vb.grid(row=2, column=1, sticky="ns")
        self.hb.grid(row=3, column=0, sticky="ew")
        right.rowconfigure(2, weight=1)
        right.columnconfigure(0, weight=1)
        c = self.canvas
        c.bind("<ButtonPress-1>", self._down)
        c.bind("<B1-Motion>", self._drag)
        c.bind("<ButtonRelease-1>", self._up)
        c.bind("<Double-Button-1>", self._dclick)
        c.bind("<Motion>", self._hover)
        c.bind("<Configure>", lambda e: debounce(self, "_cfg_job", self._render, 60))
        # Görgő: függőleges, Shift+görgő: vízszintes, Ctrl+görgő: nagyítás a kurzor
        # körül. Középső gombbal húzva a lap szabadon mozgatható.
        c.bind("<MouseWheel>", lambda e: self._wheel(e, "y"))
        c.bind("<Shift-MouseWheel>", lambda e: self._wheel(e, "x"))
        c.bind("<Control-MouseWheel>", lambda e: self._view_zoom(
            1.25 if e.delta > 0 else 1 / 1.25, anchor=(e.x, e.y)))
        c.bind("<ButtonPress-2>", lambda e: c.scan_mark(e.x, e.y))
        c.bind("<B2-Motion>", lambda e: c.scan_dragto(e.x, e.y, gain=1))
        c.bind("<Delete>", lambda e: self._delete_key())
        c.bind("<Escape>", lambda e: (self._deselect_text(), self._deselect_box()))
        for key, dx, dy in (("Left", -1, 0), ("Right", 1, 0), ("Up", 0, -1), ("Down", 0, 1)):
            c.bind(f"<{key}>", lambda e, dx=dx, dy=dy: self._nudge(dx, dy, False))
            c.bind(f"<Shift-{key}>", lambda e, dx=dx, dy=dy: self._nudge(dx, dy, True))
        c.bind("<Prior>", lambda e: (self._step_page(-1), "break")[1])     # PageUp
        c.bind("<Next>", lambda e: (self._step_page(1), "break")[1])       # PageDown
        # A vásznon, nem bind_all-lal: a globális Ctrl+Z kötés a nagyító (PageViewer)
        # billentyűit is elrontotta (a GUI-teszt mérte). A vászon kattintásra
        # amúgy is megkapja a fókuszt.
        c.bind("<Control-z>", lambda e: (self._undo(), "break")[1])
        # Gyorsbillentyűk az egész fülre — csak akkor élnek, ha ez a fül látszik.
        top = self.winfo_toplevel()
        for seq, fn in (("<Control-f>", lambda: self._switch_mode("search")),
                        ("<Control-s>", self._save),
                        ("<F3>", lambda: self._hit_step(1)),
                        ("<Shift-F3>", lambda: self._hit_step(-1))):
            top.bind_all(seq, lambda e, fn=fn: self._guard(fn), add="+")

    def _build_text(self, left, fonts):
        """Az új szöveg panelje. Kijelölt szövegnél minden beállítás AZONNAL arra hat
        (a szövege is innen írható át); kijelölés nélkül a következő új szövegre."""
        p = ttk.LabelFrame(left, text="Szöveg és X — betű, stílus")
        r = ttk.Frame(p)
        r.pack(fill="x", padx=6, pady=(6, 0))
        ttk.Label(r, text="Betű:").pack(side="left")
        ttk.Combobox(r, textvariable=self.font_name, values=fonts, state="readonly",
                     width=14).pack(side="left", padx=4)
        ttk.Spinbox(r, from_=4, to=72, increment=0.5, textvariable=self.font_size,
                    width=5).pack(side="left")
        ttk.Label(r, text="pt", foreground="#555").pack(side="left", padx=1)
        s = ttk.Frame(p)
        s.pack(fill="x", padx=6, pady=(2, 0))
        ttk.Checkbutton(s, text="Félkövér", variable=self.t_bold).pack(side="left")
        ttk.Checkbutton(s, text="Dőlt", variable=self.t_italic).pack(side="left", padx=4)
        ttk.Checkbutton(s, text="Aláhúzott", variable=self.t_under).pack(side="left")
        self.t_swatch = ttk.Button(s, text="Szín…", command=self._pick_tcolor)
        self.t_swatch.pack(side="right")
        self._swatch(self.t_swatch, self.t_color)
        ttk.Label(p, text="A kijelölt szöveg:").pack(anchor="w", padx=6, pady=(6, 0))
        e = ttk.Frame(p)
        e.pack(fill="x", padx=6)
        self.t_entry = ttk.Entry(e, textvariable=self.t_text)
        self.t_entry.pack(side="left", fill="x", expand=True)
        self.t_del = ttk.Button(e, text="Törlés", command=self._delete_text)
        self.t_del.pack(side="left", padx=(6, 0))
        self.t_note = ttk.Label(p, foreground="#555", wraplength=330)
        self.t_note.pack(anchor="w", fill="x", padx=6, pady=(2, 6))
        self._tpanel_state()
        return p

    def _build_para(self, left, fonts):
        """A bekezdéspanel. A „Kijelölt mező” panel HELYÉN jelenik meg, nem alatta:
        740 px-es ablakban a kettő együtt levágódna (szerkeszto-terv.md 19.7)."""
        p = ttk.LabelFrame(left, text="Bekezdés formázása")
        r = ttk.Frame(p)
        r.pack(fill="x", padx=6, pady=(6, 0))
        for val, txt in PARA_ALIGNS:
            ttk.Radiobutton(r, text=txt, value=val, variable=self.p_align).pack(side="left")
        ttk.Checkbutton(p, text="Újratördelés (a sortörések változhatnak)",
                        variable=self.p_reflow).pack(anchor="w", padx=6)

        g = ttk.Frame(p)
        g.pack(fill="x", padx=6, pady=(4, 0))
        ttk.Label(g, text="Sortáv.:").pack(side="left")
        ttk.Spinbox(g, from_=1, to=200, increment=0.5, textvariable=self.p_gap,
                    width=6).pack(side="left", padx=2)
        # A „×1,5” a bekezdés MAI távolságát szorozza: a PDF-ben nincs „szimpla
        # sortávolság”, amihez képest mérhetnénk.
        for k, t in ((1.15, "1,15×"), (1.5, "1,5×"), (2.0, "2×")):
            ttk.Button(g, text=t, width=4, command=lambda k=k: self.p_gap.set(
                round(self._base.get("gap", 0) * k, 2))).pack(side="left", padx=1)

        d = ttk.Frame(p)
        d.pack(fill="x", padx=6, pady=(4, 0))
        ttk.Label(d, text="Térköz előtte:").pack(side="left")
        ttk.Spinbox(d, from_=-400, to=400, increment=1, textvariable=self.p_dy,
                    width=6).pack(side="left", padx=2)
        ttk.Label(d, text="pt", foreground="#555").pack(side="left")

        i = ttk.Frame(p)
        i.pack(fill="x", padx=6, pady=(4, 0))
        ttk.Label(i, text="Behúzás b / j / első:").pack(side="left")
        for v in (self.p_il, self.p_ir, self.p_if):
            ttk.Spinbox(i, from_=-400, to=400, increment=2, textvariable=v,
                        width=4).pack(side="left", padx=1)

        b = ttk.Frame(p)
        b.pack(fill="x", padx=6, pady=(4, 0))
        ttk.Label(b, text="Betű:").pack(side="left")
        ttk.Combobox(b, textvariable=self.p_family, values=[UNCHANGED] + fonts,
                     state="readonly", width=13).pack(side="left", padx=2)
        ttk.Spinbox(b, from_=4, to=72, increment=0.5, textvariable=self.p_size,
                    width=5).pack(side="left")
        ttk.Label(b, text="pt", foreground="#555").pack(side="left", padx=1)

        s = ttk.Frame(p)
        s.pack(fill="x", padx=6, pady=(2, 6))
        ttk.Checkbutton(s, text="Félkövér", variable=self.p_bold).pack(side="left")
        ttk.Checkbutton(s, text="Dőlt", variable=self.p_italic).pack(side="left", padx=4)
        ttk.Checkbutton(s, text="Aláhúzott", variable=self.p_under).pack(side="left")
        self.p_swatch = ttk.Button(s, text="Szín…", width=7, command=self._pick_color)
        self.p_swatch.pack(side="right")

        # Alkalmaz gomb NINCS: minden változás azonnal a lapra kerül (21.). Helyette
        # az „Eredeti bekezdés” visszaállítja a kijelöléskori állapotot.
        a = self._abar("para")
        ttk.Button(a, text="Bekezdés szövege…", command=self._edit_para_text).pack(side="left")
        ttk.Button(a, text="Eredeti bekezdés", command=self._para_reset).pack(side="right")
        return p

    def _files_shown(self, show: bool):
        """A fájllista kinyitva, vagy egy sorra csukva (a megnyitott irat nevével)."""
        if show or not self.path:
            self.filebar.pack_forget()
            self.files.pack(fill="both", expand=True, before=self.tiles_frame)
        else:
            self.files.pack_forget()
            self._file_label()
            self.filebar.pack(fill="x", pady=(0, 2), before=self.tiles_frame)

    def _abar(self, mode):
        """Az eszköz saját sora a fix alsó műveletsávban."""
        if mode not in self._abars:
            self._abars[mode] = ttk.Frame(self.actionbar)
        return self._abars[mode]

    def _guard(self, fn):
        """Fülszintű gyorsbillentyű csak akkor, ha ez a fül aktív."""
        if self.app.active_tab() is self:
            fn()
            return "break"
        return None

    def _switch_mode(self, mode):
        self.mode.set(mode)
        self._mode_changed()

    def _scroll_left_to(self, w):
        """A bal panel úgy görget, hogy a widget látsszon (mező az űrlapon)."""
        c = self._lcanvas
        try:
            inner = c.nametowidget(c.itemcget(c.find_all()[0], "window"))
        except Exception:
            return
        total = max(1, inner.winfo_height())
        y = w.winfo_rooty() - inner.winfo_rooty()
        top, bot = c.canvasy(0), c.canvasy(c.winfo_height())
        if y < top or y + w.winfo_height() > bot:
            c.yview_moveto(max(0.0, (y - 40) / total))

    def _tcache(self):
        """Lapszám → szövegsorok, amíg az irat nem változik (élő keresés)."""
        if self._tc_ver != self._ver:
            self._tc, self._tc_ver = {}, self._ver
        return self._tc

    # -- fájl --
    def set_folder(self, folder):
        self.files.set_folder(folder)

    def set_worker(self, name, force=False):
        """A fájllista az alapértelmezett dolgozó mappáját mutatja (mindkét
        alkönyvtárával), dolgozó nélkül a munkamappát."""
        self.files.set_folder(*self.app.list_target())

    def _pick(self, path):
        self.open_file(path)

    def _discard_ok(self) -> bool:
        return not self.dirty or messagebox.askyesno(
            "Nincs mentve", "A módosítások nincsenek mentve. Elveted őket?")

    def open_file(self, path, log_parent=None) -> bool:
        if not self._discard_ok():
            return False
        try:
            src = open_checked(path)
            # Memóriában szerkesztünk: a fájlon nem marad zár, így helyben menthető
            # (Windowson a nyitott fájl nem cserélhető le).
            doc = pymupdf.open("pdf", src.tobytes())
            src.close()
        except Exception as e:
            messagebox.showerror("Hiba", f"A PDF nem nyitható meg:\n{e}")
            return False
        if self.doc:
            self.doc.close()
        self.doc, self.path, self.log_parent = doc, path, log_parent
        self.page_no, self.view_zoom, self.undo, self.dirty = 0, 1.0, [], False
        self._undo_key = self._live = None
        self.texts = []                    # előbb: a függő formázás ne az új iratra fusson
        self.boxes = []
        self._deselect_text()
        self._deselect_box()
        self.sel_xref = None
        if self.o_cancel:                  # a futó felismerés a régi iraté
            self.o_cancel()
        # A díszítés szövegei maradnak (jöhet a következő irat), de mind kikapcsol:
        # egy ottfelejtett „MÁSOLAT” ne kerüljön csendben a következő fájlra.
        self.decor = dataclasses_replace(self.decor, header_on=False, footer_on=False,
                                         pageno_on=False, stamp_on=False, wm_on=False)
        self._decor_to_vars()
        self.hits, self.pii_hits, self.plan, self.hit_sel = [], [], [], None
        self.f_focus = None
        self.para = self.para_pt = None
        self.field_name.set("")
        self.page_spin.configure(to=doc.page_count)
        self.page_var.set("1")
        self.canvas.xview_moveto(0)
        self.canvas.yview_moveto(0)
        self._tpanel_state()
        self._files_shown(False)
        self._render()
        enter = getattr(self, f"_enter_{self.mode.get()}", None)
        if enter:
            enter()
        return True

    def _say(self, txt=""):
        name = os.path.basename(self.path) if self.path else ""
        self.info.set(f"{name}{' — módosítva' if self.dirty else ''}" + (f" · {txt}" if txt else ""))
        if self.path:
            self.app.status(f"{'● ' if self.dirty else ''}{txt or name}")
            self._file_label()

    def _file_label(self):
        """A megnyitott irat neve a bal panel tetején; mentetlen változásnál jelölve."""
        name = os.path.basename(self.path) if self.path else ""
        mark = "● " if self.dirty else ""
        self.file_lbl.configure(text=mark + ellipsize(name, 220 if mark else 230,
                                                      tkfont.Font(font=FONT_SB).measure),
                                foreground=UI["warn"] if self.dirty else UI["ink"])
        self._file_tip.text = (self.path or "") + ("\nMentetlen változás van rajta."
                                                   if self.dirty else "")

    # -- lapozás, nagyítás, görgetés --
    def _page(self):
        return self.doc[self.page_no] if self.doc else None

    def _goto_page(self, n):
        """Lapra ugrás; -1: az utolsó lap."""
        if not self.doc:
            return
        self.page_var.set(str((self.doc.page_count - 1 if n < 0 else n) + 1))
        self._change_page()

    def _step_page(self, d):
        if self.doc:
            self._goto_page(max(0, min(self.doc.page_count - 1, self.page_no + d)))

    def _change_page(self):
        if not self.doc:
            return
        try:
            n = max(1, min(self.doc.page_count, int(self.page_var.get()))) - 1
        except ValueError:
            return
        self.page_var.set(str(n + 1))
        self._end_live()
        self._deselect_text()
        self.page_no = n
        self.sel_xref = None
        self.para = self.para_pt = None
        self._tpanel_state()
        self.canvas.yview_moveto(0)       # az új lap a tetejéről
        self._render()

    def _update_nav(self):
        n = self.doc.page_count if self.doc else 1
        self.page_total.configure(text=f"/ {n}")
        for b, ok in ((self.btn_first, self.page_no > 0), (self.btn_prev, self.page_no > 0),
                      (self.btn_next, self.page_no < n - 1),
                      (self.btn_last, self.page_no < n - 1)):
            b.state(["!disabled"] if ok else ["disabled"])

    def _view_zoom(self, k, anchor=None):
        """Nagyítás (k=0: illesztés). A kurzor (vagy a nézet közepe) alatti pont
        helyben marad — eddig a nézet minden nagyításkor a lap tetejére ugrott."""
        c = self.canvas
        keep = None
        if self._page() is not None:
            ax, ay = anchor or (c.winfo_width() / 2, c.winfo_height() / 2)
            keep = (c.canvasx(ax) / self.zoom, c.canvasy(ay) / self.zoom, ax, ay)
        self.view_zoom = 1.0 if not k else max(0.3, min(6.0, self.view_zoom * k))
        self._render(keep)

    def _wheel(self, e, axis):
        step = -1 if e.delta > 0 else 1
        (self.canvas.xview_scroll if axis == "x" else self.canvas.yview_scroll)(step, "units")
        return "break"

    def _xset(self, *a):
        self.hb.set(*a)
        self._check_cover()

    def _yset(self, *a):
        self.vb.set(*a)
        self._check_cover()

    def _check_cover(self):
        """Nagy nagyításon csak a látható sáv van kirajzolva: ha a görgetés kiért
        belőle, újrarajzoljuk (késleltetve — görgetés közben ne minden lépésre)."""
        if self._full or self.doc is None or self._rendering:
            return
        c = self.canvas
        x0, y0 = max(0, c.canvasx(0)), max(0, c.canvasy(0))
        x1 = min(self._page_px[0], x0 + c.winfo_width())
        y1 = min(self._page_px[1], y0 + c.winfo_height())
        a = self._painted
        if x0 < a[0] - 1 or y0 < a[1] - 1 or x1 > a[2] + 1 or y1 > a[3] + 1:
            debounce(self, "_cover_job", self._paint_page, 20)

    # -- rajzolás --
    def _render(self, keep=None):
        self._cancel_entry()
        page = self._page()
        if not page:
            return
        self._ver += 1                   # az irat változhatott: a gyorsítótárak lejárnak
        self._vcache = None
        # Szélességre illesztünk: egy űrlapon a betű mérete számít, nem az, hogy
        # az egész lap látsszon (függőlegesen görgethető).
        c = self.canvas
        cw = max(50, c.winfo_width())
        self.zoom = cw / page.rect.width * self.view_zoom
        w, h = page.rect.width * self.zoom, page.rect.height * self.zoom
        self._page_px = (w, h)
        c.delete("all")
        self._rendering = True         # a görgetés-visszajelzés most ne rajzoljon
        try:
            c.configure(scrollregion=(0, 0, w, h))
            if keep:                   # a megfogott pont maradjon a helyén
                px, py, ax, ay = keep
                c.xview_moveto(max(0.0, (px * self.zoom - ax) / w))
                c.yview_moveto(max(0.0, (py * self.zoom - ay) / h))
            self._full = w * h <= self.RENDER_MAX_PX
            self._paint_page()
        finally:
            self._rendering = False
        self._dr = page.get_drawings()
        self._lines = page_lines(self._dr)
        # A bekezdést a kattintás pontjából ismerjük fel újra: formázás és visszavonás
        # után is a mostani laphoz tartozó szótár kell (a régi sorai már nem élnek).
        if self.mode.get() == "para" and self.para_pt:
            self.para = self._repara(page)
        self._draw_overlays()
        n = sum(1 for _ in page.widgets())
        self.upper.set(get_upper(self.doc))          # visszavonás után is a dokumentumé
        self._update_nav()
        self._say(f"{self.page_no + 1}/{self.doc.page_count}. oldal"
                  + (f" · {n} űrlapmező" if n else ""))

    def _paint_page(self):
        """A lap képe: kis nagyításon az egész lap, nagyon csak a látható sáv
        fél képernyőnyi ráhagyással."""
        page = self._page()
        if page is None:
            return
        c, z = self.canvas, self.zoom
        clip = None
        if not self._full:
            vx, vy = c.canvasx(0), c.canvasy(0)
            vw, vh = c.winfo_width(), c.winfo_height()
            m = max(vw, vh) // 2
            clip = pymupdf.Rect((vx - m) / z, (vy - m) / z, (vx + vw + m) / z,
                                (vy + vh + m) / z) & page.rect
        pix = self._view_page().get_pixmap(matrix=pymupdf.Matrix(z, z), clip=clip,
                                           annots=True)
        self.page_tk = tkimg(pix, "ppm")
        c.delete("page")
        c.create_image(pix.x, pix.y, anchor="nw", image=self.page_tk, tags="page")
        c.tag_lower("page")
        self._painted = (pix.x, pix.y, pix.x + pix.width, pix.y + pix.height)

    def _view_page(self):
        """A vásznon látszó lap: a valódi, vagy ha díszítés van / űrlapot töltünk, egy
        egylapos MÁSOLAT, amire a mentés is ugyanígy írna — a díszítés és a beégetett
        mezők így pontosan úgy látszanak, ahogy a fájlba kerülnek. A másolat a
        következő változásig gyorsítótárban marad (görgetéskor nem készül újra)."""
        page = self._page()
        dec = self.decor.any_on()
        frm = self.mode.get() == "form" and page.first_widget is not None
        if not (dec or frm):
            return page
        key = (self._ver, self.page_no, repr(self.decor) if dec else "",
               self.f_family.get() if frm else "")
        if self._vcache is None or self._vcache[0] != key:
            tmp = pymupdf.open()
            tmp.insert_pdf(self.doc, from_page=self.page_no, to_page=self.page_no)
            if frm:
                flatten_form(tmp, self.f_family.get())
            if dec:
                write_decor(tmp[0], self.decor, self._decor_ctx(self.page_no), self.page_no)
            self._vcache = (key, tmp)
        return self._vcache[1][0]

    def _repaint(self):
        """A lap képe újra (a díszítés változott), a jelekkel együtt."""
        if self.doc:
            self._paint_page()
            self._draw_overlays()

    def _draw_overlays(self):
        self._draw_layers()
        self._draw_fields()
        self._draw_para()
        self._draw_hits()
        self._draw_decor()
        self._draw_form()
        self._draw_ocr()

    def _draw_layers(self):
        """Az élő rétegek: egysoros szövegek, szövegdobozok, a kijelölés kerete."""
        self._draw_boxes()
        self._draw_texts()
        self._draw_bsel()

    def _draw_fields(self):
        """Mező módban a mezők kerete és neve — a PDF-ben láthatatlanok."""
        c, z = self.canvas, self.zoom
        c.delete("fld")
        if self.mode.get() != "field" or self._page() is None:
            return                     # nyitott fájl nélkül is lehet eszközt váltani
        for w in self._page().widgets():
            r = w.rect
            sel = w.xref == self.sel_xref
            c.create_rectangle(r.x0 * z, r.y0 * z, r.x1 * z, r.y1 * z, tags="fld",
                               outline=UI["warn"] if sel else UI["accent"],
                               width=2 if sel else 1, dash=() if sel else (3, 2))
            c.create_text(r.x0 * z + 2, r.y0 * z + 1, anchor="nw", text=w.field_name,
                          font=("Segoe UI", 7), fill=UI["accent"], tags="fld")

    def _mode_changed(self):
        mode = self.mode.get()
        self.hint.configure(text=self.HINTS[mode])
        self._cancel_entry()
        self._end_live()
        self._flush_form()
        for box in self.panels.values():
            box.pack_forget()
        if mode in self.panels:
            self.panels[mode].pack(fill="x")
        for f in self._abars.values():
            f.pack_forget()
        if mode in self._abars:
            self._abars[mode].pack(fill="x")
            self.actionbar.grid()
        else:
            self.actionbar.grid_remove()
        if mode != "para":
            self.para = self.para_pt = None
        if mode != "text":
            self._deselect_text()
        if mode != "box":
            self._deselect_box()
        if mode not in ("search", "pii"):
            self.hit_sel = None
        self.canvas.configure(cursor="crosshair")
        self._lcanvas.yview_moveto(0)
        enter = getattr(self, f"_enter_{mode}", None)
        if enter:
            enter()
        if self.doc:
            self._render()               # az űrlap-előnézet és a jelek módfüggők

    def _draw_para(self):
        """A kijelölt bekezdés szaggatott kerete és a jobb széle: látszik, mire hat
        a formázás."""
        c, z = self.canvas, self.zoom
        c.delete("para")
        if self.mode.get() != "para" or not self.para:
            return
        r = self.para["bbox"]
        c.create_rectangle(r.x0 * z - 2, r.y0 * z - 2, r.x1 * z + 2, r.y1 * z + 2,
                           outline=UI["warn"], dash=(4, 2), width=2, tags="para")
        x = self.para["right"] * z
        c.create_line(x, r.y0 * z - 10, x, r.y1 * z + 10, fill=UI["accent"],
                      dash=(2, 2), tags="para")

    # -- elhelyezett szövegek a vásznon --
    def _draw_texts(self):
        self.canvas.delete("ptext")
        self._timgs, self._tbox = {}, {}
        for t in self.texts:
            if t.page == self.page_no:
                self._draw_text(t)
        self._draw_tsel()

    def _draw_text(self, t):
        """Egy élő szöveg képe a lap fölött: a MuPDF rajzolja a valódi betűvel, ezért
        pontosan az látszik, ami mentéskor a lapra kerül."""
        c, z = self.canvas, self.zoom
        tag = f"pt{t.uid}"
        c.delete(tag)
        self._tbox[t.uid] = placed_bbox(t)
        if not t.text.strip():
            self._timgs.pop(t.uid, None)
            return
        pix, (x0, y0) = placed_pixmap(t, z)
        self._timgs[t.uid] = img = tkimg(pix, "png")
        c.create_image(round(x0 * z), round(y0 * z), anchor="nw", image=img,
                       tags=("ptext", tag))

    def _draw_tsel(self):
        c, z = self.canvas, self.zoom
        c.delete("tsel")
        t = self._sel()
        if t is None or t.page != self.page_no:
            return
        r = self._tbox.get(t.uid) or placed_bbox(t)
        c.create_rectangle(r.x0 * z - 3, r.y0 * z - 3, r.x1 * z + 3, r.y1 * z + 3,
                           outline=UI["accent"], dash=(4, 2), width=1.5, tags="tsel")

    def _find(self, uid):
        return next((t for t in self.texts if t.uid == uid), None)

    def _sel(self):
        return self._find(self.sel_text) if self.sel_text is not None else None

    def _text_at(self, x, y):
        """A pont alatti élő szöveg (a legfelső), vagy None."""
        for t in reversed(self.texts):
            if t.page == self.page_no:
                r = self._tbox.get(t.uid) or placed_bbox(t)
                if r.x0 - 2 <= x <= r.x1 + 2 and r.y0 - 2 <= y <= r.y1 + 2:
                    return t
        return None

    # -- egér --
    def _pt(self, e):
        return (self.canvas.canvasx(e.x) / self.zoom, self.canvas.canvasy(e.y) / self.zoom)

    def _object_at(self, x, y):
        """Az élő objektum a ponton: ("text", szöveg) vagy ("box", doboz), vagy None."""
        t = self._text_at(x, y)
        if t is not None:
            return "text", t
        b = self._box_at(x, y)
        return ("box", b) if b is not None else None

    def _hover(self, e):
        if not self.doc or self._tdrag or self._bdrag or self._ddrag:
            return
        mode, pt = self.mode.get(), self._pt(e)
        if mode == "box":
            cur = self._box_cursor(e, pt)
        elif mode in ("text", "para"):
            cur = "fleur" if self._object_at(*pt) is not None else "crosshair"
        elif mode == "form":
            cur = "hand2" if any(f["page"] == self.page_no and f["rect"].contains(
                pymupdf.Point(*pt)) for f in self.fields) else "arrow"
        elif mode == "decor":
            cur = "fleur" if (self.decor.stamp_on and not (self.decor.stamp_first_only and self.page_no)
                              and stamp_rect(self._page().rect, self.decor,
                                             self._decor_ctx(self.page_no)).contains(
                                  pymupdf.Point(*pt))) else "arrow"
        elif mode in ("search", "pii", "ocr"):
            cur = "arrow"
        else:
            cur = "crosshair"
        if str(self.canvas.cget("cursor")) != cur:
            self.canvas.configure(cursor=cur)

    def _down(self, e):
        self.canvas.focus_set()
        self._press = pt = self._pt(e) if self.doc else None
        self._tdrag = self._bdrag = self._ddrag = None
        self.canvas.delete("band")
        if not pt:
            return
        mode = self.mode.get()
        if mode in ("text", "para", "box"):
            if mode == "box" and self._box_down(e, pt):
                self._press = None
                return
            obj = self._object_at(*pt)
            if obj is not None:
                kind, o = obj
                # Az élő objektumot a saját eszköze kezeli — a Bekezdés eszköz sem a
                # lap bekezdésének nézi.
                if kind == "box":
                    if mode != "box":
                        self._switch_mode("box")
                    self._select_box(o)
                    self._box_down(e, pt)
                else:
                    if mode != "text":
                        self._switch_mode("text")
                    self._select_text(o)
                    self._tdrag = [o.uid, e.x, e.y, 0, 0, False]
                self._press = None
        elif mode == "decor":
            if self._decor_down(e, pt):
                self._press = None
        elif mode == "form":
            self._form_down(e, pt)
            self._press = None
        elif mode in ("search", "pii"):
            self._hits_down(pt)
            self._press = None
        elif mode == "ocr":
            self._press = None

    def _drag(self, e):
        if self._tdrag:
            uid, x0, y0, adx, ady, moved = self._tdrag
            dx, dy = e.x - x0, e.y - y0
            if not moved and abs(dx) + abs(dy) < 3:
                return                 # remegés: még kattintás, nem húzás
            self.canvas.move(f"pt{uid}", dx - adx, dy - ady)
            self.canvas.move("tsel", dx - adx, dy - ady)
            self._tdrag[3:] = [dx, dy, True]
            return
        if self._bdrag:
            self._box_drag(e)
            return
        if self._ddrag:
            self._decor_drag(e)
            return
        if not self._press or self.mode.get() not in ("erase", "field", "box"):
            return
        (x0, y0), (x1, y1), z = self._press, self._pt(e), self.zoom
        self.canvas.delete("band")
        self.canvas.create_rectangle(x0 * z, y0 * z, x1 * z, y1 * z, tags="band",
                                     outline=UI["warn"], dash=(4, 2))

    def _up(self, e):
        if self._tdrag:
            uid, _x, _y, adx, ady, moved = self._tdrag
            self._tdrag = self._press = None
            t = self._find(uid)
            if moved and t is not None and (adx or ady):
                z = self.zoom
                self._tchange(lambda: self._move_text(t, adx / z, ady / z),
                              "Áthelyezve — a nyilakkal finomíthatsz (Shift: 10 pt).")
            return
        if self._bdrag:
            self._box_up(e)
            return
        if self._ddrag:
            self._decor_up(e)
            return
        if not self._press:
            return
        (x0, y0), (x1, y1) = self._press, self._pt(e)
        self._press = None
        self.canvas.delete("band")
        page = self._page()
        if page.rotation:
            messagebox.showwarning("Forgatott lap", "Forgatott lapot a szerkesztő nem kezel.")
            return
        rect = pymupdf.Rect(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
        drag = rect.width * self.zoom > 5 or rect.height * self.zoom > 5
        mode = self.mode.get()
        if mode == "erase":
            if drag:
                gone = {t.uid for t in self.texts
                        if t.page == self.page_no and placed_bbox(t).intersects(rect)}

                def go():
                    erase_area(page, rect)
                    self.texts = [t for t in self.texts if t.uid not in gone]
                self._change(go, "Kitakarva.")
        elif mode == "field":
            self._field_drag(page, rect) if drag else self._field_click(page, x1, y1)
        elif mode == "para":
            self._para_click(page, x1, y1)
        elif mode == "box":
            self._box_click_empty(page, rect, drag)
        elif mode != "text":
            pass
        elif self.sel_text is not None:
            self._deselect_text()      # az első kattintás csak a kijelölést oldja fel
        else:
            self._text_click(page, x1, y1)

    def _dclick(self, e):
        """Dupla kattintás egy élő szövegen: átírás a helyén; dobozon: a beíró.
        Máshol sima kattintásnak számít — a gyors második kattintás (az első csak
        feloldotta a kijelölést) különben elveszne."""
        if not self.doc:
            return
        pt = self._pt(e)
        if self.mode.get() == "box" and self._box_at(*pt) is not None:
            self._select_box(self._box_at(*pt), focus=True)
            return
        if self.mode.get() != "text" or self._text_at(*pt) is None:
            self._down(e)                 # a felengedés (_up) viszi tovább
            return
        t = self._text_at(*pt)
        if t is not None:
            self._select_text(t)
            r = placed_bbox(t)
            self._ask(r.x0, r.y1 + 2, t.text, max(r.width, 80),
                      lambda s, uid=t.uid: self._set_text(uid, s))

    # -- szöveg --
    def _text_click(self, page, x, y):
        box = snap_box(self._dr, x, y)
        if box is not None:
            font = edit_font(self.font_name.get())
            self._change(lambda: toggle_x(page, box, font), "Jelölőnégyzet átállítva.")
            return
        span = span_at(page, x, y)
        if span is not None:
            b = pymupdf.Rect(span["bbox"])
            self._ask(b.x0, b.y1, span["text"], max(b.width, 80),
                      lambda t: self._rewrite(page, span, t))
            return
        size = self._tstyle()["size"]
        cell = snap_cell(self._lines, x, y)
        origin = ((cell.x0 + 3, (cell.y0 + cell.y1) / 2 + size * 0.35) if cell else (x, y))
        width = cell.width if cell else 160
        self._ask(origin[0], origin[1] + 3, "", width,
                  lambda t: t.strip() and self._new_text(origin, t))

    def _rewrite(self, page, span, text):
        if text == span["text"]:
            return
        fb = edit_font(self.font_name.get())
        own = []
        self._change(lambda: own.append(rewrite_span(self.doc, page, span, text, fb)), "Átírva.")
        if own and not own[0] and text.strip():
            self._say(f"Az eredeti betűben nincs meg minden betű — {self.font_name.get()} betűvel írtam.")

    def _tstyle(self, t=None) -> dict:
        """A panel stílusa. Gépelés közben a méretmező átmenetileg érvénytelen lehet
        (üres, „1”): olyankor a régi méret marad."""
        try:
            size = float(self.font_size.get())
        except (tk.TclError, ValueError):
            size = 0
        if not 3 <= size <= 300:
            size = t.size if t else 10.5
        return {"family": self.font_name.get(), "size": size, "bold": self.t_bold.get(),
                "italic": self.t_italic.get(), "underline": self.t_under.get(),
                "color": tuple(self.t_color)}

    def _new_text(self, origin, text):
        self._uid += 1
        t = PlacedText(self.page_no, origin[0], origin[1], text, uid=self._uid,
                       **self._tstyle())
        self._tchange(lambda: self.texts.append(t),
                      "Szöveg elhelyezve — húzd, vagy a nyilakkal mozgasd; a panelen élőben formázható.")
        self._select_text(t, say=False)
        miss = placed_missing(t)
        if miss:
            self._say(f"A választott betűben nincs meg: {' '.join(miss)} — válassz másik betűt.")

    def _move_text(self, t, dx, dy):
        t.x += dx
        t.y += dy

    def _set_text(self, uid, s):
        t = self._find(uid)
        if t is None or s == t.text:
            return
        if not s.strip():
            self._delete_text()
            return
        self._tchange(lambda: setattr(t, "text", s), "Szöveg átírva.")
        self._load_tpanel(t)

    def _flush_tstyle(self):
        """A még függő (késleltetett) formázás most fut le — kijelölésváltás, mentés
        és visszavonás előtt, különben az előző szöveg utolsó változása elveszne."""
        job = getattr(self, "_tstyle_job", None)
        if job:
            try:
                self.after_cancel(job)
            except Exception:
                pass
            self._tstyle_job = None
            self._tstyle_apply()

    def _select_text(self, t, say=True):
        self._flush_tstyle()
        self.sel_text = t.uid if t is not None else None
        self._undo_key = None          # új kijelölés: a formázás új visszavonási lépés
        if t is not None:
            self._load_tpanel(t)
        self._draw_tsel()
        self._tpanel_state()
        if t is not None and say:
            self._say(f"Kijelölve: „{t.text}” — húzd vagy nyilazd (Shift: 10 pt) · "
                      "Delete: törlés · dupla kattintás: átírás")

    def _deselect_text(self):
        if self.sel_text is None:
            return
        self._flush_tstyle()
        self.sel_text = None
        self._quiet = True
        try:
            self.t_text.set("")
        finally:
            self._quiet = False
        self._draw_tsel()
        self._tpanel_state()

    def _load_tpanel(self, t):
        """A panel a kijelölt szöveg értékeivel — a trace-ek ne alkalmazzák vissza."""
        self._quiet = True
        try:
            self.font_name.set(t.family)
            self.font_size.set(t.size)
            self.t_bold.set(t.bold)
            self.t_italic.set(t.italic)
            self.t_under.set(t.underline)
            self.t_text.set(t.text)
            self.t_color = t.color
            self._swatch(self.t_swatch, t.color)
        finally:
            self._quiet = False

    def _tpanel_state(self):
        on = self._sel() is not None
        for w in (self.t_entry, self.t_del):
            w.state(["!disabled"] if on else ["disabled"])
        self.t_note.configure(
            text="A változás azonnal látszik a lapon (Ctrl+Z visszavonja)." if on else
            "Nincs kijelölt szöveg: a beállítás a következő új szövegre szól. "
            "Kijelöléshez kattints egy most elhelyezett szövegre.")

    def _swatch(self, btn, rgb):
        """Kis színminta a gombon — látszik, milyen színnel ír."""
        img = tk.PhotoImage(width=12, height=12)
        img.put("#%02x%02x%02x" % tuple(int(round(v * 255)) for v in rgb), to=(0, 0, 12, 12))
        btn.configure(image=img, compound="left")
        btn._swatch_img = img

    def _pick_tcolor(self):
        rgb = colorchooser.askcolor(title="A szöveg színe", parent=self)[0]
        if rgb:
            self.t_color = tuple(v / 255 for v in rgb)
            self._swatch(self.t_swatch, self.t_color)
            self._tstyle_changed()

    def _tstyle_changed(self):
        if self._quiet or self._sel() is None:
            return                     # kijelölés nélkül: a következő új szöveg stílusa
        debounce(self, "_tstyle_job", self._tstyle_apply, self.LIVE_MS)

    def _tstyle_apply(self):
        """A panel értékei a kijelölt szövegre — valós időben, Alkalmaz nélkül. Egy
        kijelölésen belül a formázás EGY visszavonási lépés."""
        t = self._sel()
        if t is None:
            return
        new = dict(self._tstyle(t), text=self.t_text.get())
        if all(getattr(t, k) == v for k, v in new.items()):
            return
        self._tchange(lambda: [setattr(t, k, v) for k, v in new.items()],
                      key=("style", t.uid))
        miss = placed_missing(t)
        self._say(f"A választott betűben nincs meg: {' '.join(miss)} — mentéskor kimaradna, "
                  "válassz másik betűt." if miss else
                  "Formázva — élőben; Ctrl+Z visszavonja.")

    def _nudge(self, dx, dy, big):
        """Nyíl: a kijelölt szöveg 1 pt-tal (Shift: 10 pt) arrébb; kijelölés nélkül a
        nézet görget. Az egymás utáni nyomások egy visszavonási lépés."""
        b = self._bsel()
        if b is not None and b.page == self.page_no and self.mode.get() == "box":
            k = self.NUDGE_BIG if big else self.NUDGE
            x0, y0, x1, y1 = b.rect
            nr = (x0 + dx * k, y0 + dy * k, x1 + dx * k, y1 + dy * k)
            self._tchange(lambda: setattr(b, "rect", nr), f"Áthelyezve: x {nr[0]:.1f} · y {nr[1]:.1f} pt",
                          key=("bmove", b.uid))
            return "break"
        t = self._sel()
        if t is None or t.page != self.page_no or self._entry is not None:
            if dx:
                self.canvas.xview_scroll(dx, "units")
            else:
                self.canvas.yview_scroll(dy, "units")
            return "break"
        k = self.NUDGE_BIG if big else self.NUDGE
        self._tchange(lambda: self._move_text(t, dx * k, dy * k),
                      f"Áthelyezve: x {t.x + dx * k:.1f} · y {t.y + dy * k:.1f} pt",
                      key=("move", t.uid))
        return "break"

    def _delete_text(self):
        uid = self.sel_text
        if uid is None:
            return
        self._tchange(lambda: setattr(self, "texts", [t for t in self.texts if t.uid != uid]),
                      "Szöveg törölve.")
        self._deselect_text()

    def _delete_key(self):
        if self.mode.get() == "box" and self.sel_box is not None:
            self._delete_box()
        elif self.mode.get() == "text" and self.sel_text is not None:
            self._delete_text()
        else:
            self._delete_field()

    # -- bekezdés --
    def _repara(self, page):
        """A kijelölt bekezdés újrafelismerése a mostani lapon. Formázás után a sorok
        elmozdulhatnak (igazítás, behúzás, sortávolság, térköz), és a kattintás pontja
        két sor közé eshet — ilyenkor a bekezdés sávjában több ponton próbálkozunk,
        hogy a kijelölés és a keret megmaradjon a következő művelethez."""
        p = paragraph_at(page, *self.para_pt)
        if p is not None or not self.para:
            return p
        r, x = self.para["bbox"], self.para_pt[0]
        for yy in (_baseline(self.para["lines"][0]) - 1, self.para_pt[1]):
            for xx in (x, (r.x0 + r.x1) / 2, r.x0 + 4):
                p = paragraph_at(page, xx, yy)
                if p is not None:
                    return p
        return None

    def _para_click(self, page, x, y):
        self._end_live()
        p = paragraph_at(page, x, y)
        if p is None:
            self.para = self.para_pt = None
            self._draw_para()
            self._say("Ott nincs szöveg — kattints egy bekezdésre.")
            return
        self.para, self.para_pt = p, (x, y)
        self._fill_para()
        self._draw_para()
        err = para_font_error(p, {})
        self._say(f"{len(p['lines'])} soros bekezdés · {dict(PARA_ALIGNS)[guess_align(p)].lower()}"
                  + (f" · {err}" if err else ""))

    def _fill_para(self):
        """A panel a bekezdés MAI értékeivel: ehhez mérjük, mit változtatott a
        felhasználó — csak a megváltoztatott kulcsok mennek át a para_format-nak, így
        a méretváltás nem kényszerít feleslegesen újratördelést."""
        p = self.para
        fam, bold, ital = span_style(p["lines"][0]["spans"][0])
        self._base = {"align": guess_align(p), "gap": round(p["gap"], 2),
                      "size": round(p["size"], 2), "family": fam or UNCHANGED,
                      "bold": bold, "italic": ital,
                      "il": 0.0, "ir": 0.0, "if": round(p["indent"], 1)}
        self._quiet = True             # a panel programból íródik: ne formázzon
        try:
            self.p_align.set(self._base["align"])
            self.p_gap.set(self._base["gap"])
            self.p_size.set(self._base["size"])
            self.p_family.set(self._base["family"])
            self.p_bold.set(bold)
            self.p_italic.set(ital)
            self.p_under.set(False)
            self.p_reflow.set(False)
            self.p_dy.set(0)
            self.p_il.set(0)
            self.p_ir.set(0)
            self.p_if.set(self._base["if"])
        finally:
            self._quiet = False
        self._p_text = None
        self.p_color = None
        self.p_swatch.configure(text="Szín…")

    def _pick_color(self):
        rgb = colorchooser.askcolor(title="A bekezdés szövegszíne", parent=self)[0]
        if rgb:
            self.p_color = tuple(v / 255 for v in rgb)
            self.p_swatch.configure(text="Szín ✓")
            self._para_changed()

    def _para_fmt(self):
        """A panelon megváltoztatott értékek — ennyit adunk a para_format-nak.
        None: egy számmező épp érvénytelen (gépelés közben)."""
        b, fmt = self._base, {}
        if self.p_align.get() != b["align"]:
            fmt["align"] = self.p_align.get()
        if self.p_reflow.get():
            fmt["reflow"] = True
        try:
            for key, var, base in (("gap", self.p_gap, b["gap"]),
                                   ("indent_left", self.p_il, b["il"]),
                                   ("indent_right", self.p_ir, b["ir"]),
                                   ("indent_first", self.p_if, b["if"]),
                                   ("dy", self.p_dy, 0.0),
                                   ("size", self.p_size, b["size"])):
                if abs(float(var.get()) - base) > 0.01:
                    fmt[key] = float(var.get())
        except (tk.TclError, ValueError):
            return None
        if fmt.get("size", 1) <= 0 or fmt.get("gap", 1) <= 0:
            return None
        if self.p_under.get():
            fmt["underline"] = True
        if self.p_color is not None:
            fmt["color"] = self.p_color
        fam = self.p_family.get()
        if (fam != b["family"] or self.p_bold.get() != b["bold"]
                or self.p_italic.get() != b["italic"]):
            # A félkövér/dőlt változathoz tudnunk kell a családot: abból választjuk a
            # betűfájlt (calibrib.ttf, calibriz.ttf …).
            if fam == UNCHANGED:
                return {"__err": "A félkövérhez és a dőlthöz válassz betűcsaládot."}
            fmt.update(family=fam, bold=self.p_bold.get(), italic=self.p_italic.get())
        if self._p_text is not None:
            fmt["text"] = self._p_text
        return fmt

    def _para_changed(self):
        if self._quiet or not self.para or self.mode.get() != "para":
            return
        debounce(self, "_para_job", self._live_apply, self.LIVE_MS)

    def _cancel_para_job(self) -> bool:
        job = getattr(self, "_para_job", None)
        if job:
            try:
                self.after_cancel(job)
            except Exception:
                pass
            self._para_job = None
        return bool(job)

    def _live_apply(self):
        """Valós idejű formázás. A kijelöléskori állapotból (pillanatkép) indulunk, és
        a panel TELJES eltérését alkalmazzuk rá — így az eredmény csak a panel mostani
        állapotától függ: a 10 → 8 → 10 pt ugyanazt a lapot adja vissza, nem egy kétszer
        újratördelt változatot. Minden alkalmazás külön visszavonási lépés."""
        self._para_job = None
        if not self.para or not self.doc:
            return
        fmt = self._para_fmt()
        if fmt is None:
            return
        if "__err" in fmt:
            self._say(fmt["__err"])
            return
        live = self._live
        if live is None:
            if not fmt:
                return
            live = self._live = {"snap": self.doc.tobytes(), "para": self.para,
                                 "pt": self.para_pt, "asked": None}
        err = para_font_error(live["para"], fmt) if fmt else ""
        if not err and para_reflows(fmt) and live["para"]["mixed"]:
            if live["asked"] is None:
                live["asked"] = messagebox.askyesno(
                    "Vegyes formázás",
                    "A bekezdésben többféle betű vagy méret van (például félkövér szavak).\n\n"
                    "Ez a beállítás újratördeli a bekezdést, ezért a formázása EGYSÉGES "
                    "lesz — a kiemelések elvesznek. A lépés visszavonható (Ctrl+Z).\n\n"
                    "Folytassuk?")
            if not live["asked"]:
                err = ("A vegyes formázású bekezdést nem tördelem újra — ezt a beállítást "
                       "állítsd vissza, vagy válaszd az „Eredeti bekezdés” gombot.")
        if err:
            self._say(err)             # a lap az utolsó jó állapotában marad
            return
        self._push(doc=True)
        old, self.doc = self.doc, pymupdf.open("pdf", live["snap"])
        old.close()
        # a bekezdés eltolódik: a felismerés pontja is vele megy
        self.para_pt = (live["pt"][0], live["pt"][1] + float(fmt.get("dy", 0)))
        out = ""
        try:
            if fmt:
                out = para_format(self.doc, self.doc[self.page_no], live["para"], fmt)
        except Exception as e:
            traceback.print_exc()
            self._restore(self.undo.pop())
            self._live = None
            messagebox.showerror("Hiba", f"{type(e).__name__}: {e}")
            return
        self.dirty = True
        self._render()
        self._say(("Bekezdés formázva" + (f" — {out}" if out else "") +
                   " · élőben, Ctrl+Z visszavonja") if fmt else "A bekezdés az eredeti formájában.")

    def _apply_para(self, text=None):
        """Azonnali alkalmazás, a késleltetés kivárása nélkül (a „Bekezdés szövege…”
        párbeszéd hívja). A panel változásai maguktól is a lapra kerülnek."""
        if not self.para:
            messagebox.showinfo("Bekezdés", "Előbb kattints egy bekezdésre.")
            return
        self._cancel_para_job()
        if text is not None:
            self._p_text = text
        self._live_apply()

    def _end_live(self):
        """Az élő formázás vége (másik bekezdés, lap, eszköz, mentés): a függő
        változás még a lapra kerül, és a panel a mostani állapotot veszi alapnak."""
        if self._cancel_para_job():
            self._live_apply()
        if self._live is not None:
            self._live = None
            if self.para:
                self._fill_para()

    def _para_reset(self):
        """„Eredeti bekezdés”: vissza a kijelöléskori állapotra (visszavonható)."""
        self._cancel_para_job()
        live = self._live
        if live is None:
            self._say("Ezen a bekezdésen nincs mit visszaállítani.")
            return
        self._push(doc=True)
        old, self.doc = self.doc, pymupdf.open("pdf", live["snap"])
        old.close()
        self.para_pt, self._live = live["pt"], None
        self._render()
        if self.para:
            self._fill_para()
        self._say("A bekezdés az eredeti formájában.")

    def _edit_para_text(self):
        """A bekezdés szövegének átírása: a program a hasáb szélességére tördeli újra."""
        if not self.para:
            messagebox.showinfo("Bekezdés", "Előbb kattints egy bekezdésre.")
            return
        win = tk.Toplevel(self)
        win.title("A bekezdés szövege")
        win.transient(self.winfo_toplevel())
        ttk.Label(win, text="A program a hasáb szélességére tördeli újra, a panelon beállított "
                            "igazítással. A bekezdésen belüli vegyes formázás egységes lesz.",
                  wraplength=470, foreground="#555").pack(anchor="w", padx=10, pady=(10, 6))
        t = tk.Text(win, width=64, height=10, wrap="word", font=("Segoe UI", 10))
        t.pack(fill="both", expand=True, padx=10)
        t.insert("1.0", self._p_text if self._p_text is not None else para_text(self.para))
        t.focus_set()
        bar = ttk.Frame(win)
        bar.pack(fill="x", padx=10, pady=8)

        def ok():
            txt = " ".join(t.get("1.0", "end").split())
            win.destroy()
            if txt:
                self._apply_para(text=txt)
        ttk.Button(bar, text="Alkalmaz", command=ok).pack(side="right")
        ttk.Button(bar, text="Mégsem", command=win.destroy).pack(side="right", padx=6)

    # -- mező --
    def _field_click(self, page, x, y):
        w = field_at(page, x, y)
        if w is not None:
            self.sel_xref = w.xref
            self.field_name.set(w.field_name)
            self._draw_fields()
            return
        self.sel_xref = None
        box = snap_box(self._dr, x, y)
        rect = box or snap_cell(self._lines, x, y) or pymupdf.Rect(x, y - 12, x + 140, y + 3)
        self._ask(rect.x0, rect.y1, "", max(rect.width, 140),
                  lambda n: self._new_fields(page, [rect], n, check=box is not None))

    def _field_drag(self, page, rect):
        cells = snap_cells(self._lines, rect)
        self._ask(rect.x0, rect.y1, "", max(rect.width, 140),
                  lambda n: self._new_fields(page, cells or [rect], n, many=bool(cells)))

    def _new_fields(self, page, rects, name, check=False, many=False):
        name = name.strip()
        err = field_name_error(name)
        if err:
            messagebox.showwarning("Mezőnév", err)
            return
        def go():
            for i, r in enumerate(rects, 1):
                add_field(page, r, f"{name}#{i}" if many else name, check=check)
        self._change(go, f"{len(rects)} mező: {name}{'#1…#%d' % len(rects) if many else ''}")

    def _upper_changed(self):
        on = self.upper.get()
        if not self.doc:
            self.upper.set(False)
            return
        self._change(lambda: set_upper(self.doc, on),
                     "A DocGen nagybetűvel tölti ki." if on else "Nagybetűs kitöltés kikapcsolva.")

    def _sel_widget(self, page):
        """A kijelölt mező — ugyanazon a lapobjektumon, amelyiken dolgozunk: másik
        Page-példány mezőjét a PyMuPDF „laphoz nem kötött”-nek látja."""
        return next((w for w in page.widgets() if w.xref == self.sel_xref), None) if page else None

    def _rename(self):
        w = self._sel_widget(self._page())
        name = self.field_name.get().strip()
        err = field_name_error(name)
        if w is None or err:
            messagebox.showwarning("Mező", err or "Előbb jelölj ki egy mezőt (Űrlapmező eszköz).")
            return
        self._change(lambda: rename_field(self.doc, w, name), f"Átnevezve: {name}")

    def _delete_field(self):
        page = self._page()
        w = self._sel_widget(page)
        if w is None:
            return
        self._change(lambda: page.delete_widget(w), "Mező törölve.")
        self.sel_xref = None
        self.field_name.set("")
        self._render()

    # -- beírómező a vásznon --
    def _ask(self, x, y, text, width_pt, on_ok):
        self._cancel_entry()
        e = ttk.Entry(self.canvas, width=max(8, int(width_pt * self.zoom / 7)))
        e.insert(0, text)
        self.canvas.create_window(x * self.zoom, y * self.zoom, anchor="nw", window=e, tags="entry")
        self._entry = e
        e.focus_set()
        e.select_range(0, tk.END)

        def ok(_e=None):
            t = e.get()
            self._cancel_entry()
            on_ok(t)
            return "break"
        e.bind("<Return>", ok)
        e.bind("<Escape>", lambda _e: (self._cancel_entry(), "break")[1])

    def _cancel_entry(self):
        if self._entry is not None:
            self.canvas.delete("entry")
            self._entry.destroy()
            self._entry = None

    # -- módosítás, visszavonás, mentés --
    def _layers(self):
        """Az élő rétegek másolata a visszavonáshoz: szövegek, dobozok, díszítés."""
        return ([copy.copy(t) for t in self.texts], [copy.deepcopy(b) for b in self.boxes],
                copy.copy(self.decor))

    def _push(self, doc=True, key=None):
        """Visszavonási pont. `doc=False`: csak az élő rétegek változnak — a PDF
        bájtjait nem kell lemásolni. Az azonos kulcsú egymás utáni lépések (nyíllal
        léptetés, egy kijelölés formázása, egy mező gépelése) egy lépésnek számítanak."""
        if key is not None and key == self._undo_key and self.undo:
            return
        self.undo.append((self.doc.tobytes() if doc else None, self._layers()))
        del self.undo[:-self.UNDO_MAX]
        self._undo_key = key

    def _change(self, fn, msg="", key=None):
        """Egy lépés a PDF-en: előtte a dokumentum bájtjai a visszavonási verembe."""
        if not self.doc:
            return None
        self._end_live()
        self._push(doc=True, key=key)
        try:
            out = fn()
        except Exception as e:
            traceback.print_exc()
            self._restore(self.undo.pop())
            messagebox.showerror("Hiba", f"{type(e).__name__}: {e}")
            return None
        self.dirty = True
        self._render()
        if self.para:              # a _render újra felismerte: a panel is kövesse
            self._fill_para()
        self._say(msg)
        return out

    def _tchange(self, fn, msg="", key=None, repaint=False):
        """Egy lépés az élő rétegeken: a lapot nem kell újrarajzolni, csak őket —
        kivéve a díszítést, ami a lap képének része (repaint)."""
        if not self.doc:
            return
        self._push(doc=False, key=key)
        fn()
        self.dirty = True
        if self._sel() is None:
            self.sel_text = None
        if self._bsel() is None:
            self.sel_box = None
        if repaint:
            self._repaint()
        else:
            self._draw_layers()
        if msg:
            self._say(msg)

    def _restore(self, entry):
        data, (texts, boxes, decor) = entry
        if data is not None:
            self.doc.close()
            self.doc = pymupdf.open("pdf", data)
        self.texts, self.boxes = texts, boxes
        changed = decor != self.decor
        self.decor = decor
        if changed:
            self._decor_to_vars()

    def _undo(self):
        self._flush_tstyle()             # a függő változás is visszavonható legyen
        self._flush_box()
        self._flush_form()
        if self._cancel_para_job():
            self._live_apply()
        if not self.undo:
            self._say("Nincs mit visszavonni.")
            return
        self._live = None
        entry = self.undo.pop()
        self._restore(entry)
        self._undo_key = None
        self.dirty = bool(self.undo)
        self.sel_xref = None
        t = self._sel()
        if t is None:
            self.sel_text = None
        b = self._bsel()
        if b is None:
            self.sel_box = None
        self._render()                   # a díszítés is a lap képének része
        if entry[0] is not None and self.para:
            self._fill_para()
        if entry[0] is None:
            self._say("Visszavonva.")
        if t is not None:
            self._load_tpanel(t)
        self._tpanel_state()
        if b is not None:
            self._select_box(b)
        else:
            self._bpanel_state()
        if self.mode.get() == "form" and entry[0] is not None:
            self._form_build_rows()

    def _bytes(self, dst=None) -> bytes:
        """Mentendő bájtok: az élő rétegek (szövegek, dobozok, díszítés) a lapra írva,
        a használt betűk részhalmaza, tömörítve. A szerkesztett dokumentum NEM
        változik: a rétegek a mentés után is szerkeszthetők maradnak."""
        d = pymupdf.open("pdf", self.doc.tobytes())
        try:
            bake_placed(d, self.texts)
            for b in self.boxes:
                if 0 <= b.page < d.page_count and box_plain(b).strip():
                    write_box(d[b.page], b)
            if self.decor.any_on():
                who = self.app.worker_name() if hasattr(self.app, "worker_name") else ""
                for pno in range(d.page_count):
                    write_decor(d[pno], self.decor, decor_ctx(d, dst or self.path, pno, who), pno)
            try:
                d.subset_fonts()
            except Exception:
                pass                      # a részhalmazolás kényelem, nem feltétel
            return d.tobytes(garbage=3, deflate=True)
        finally:
            d.close()

    def _write(self, dst) -> str:
        data, pages = self._bytes(dst), self.doc.page_count
        backup = backup_existing(dst) if os.path.exists(dst) else ""
        write_pdf_verified(data, dst, pages)
        return backup

    def _save(self):
        if self.doc:
            self._flush_box()
            self._flush_form()
            self._flush_tstyle()
            self._end_live()
            self._save_to(self.path)

    def _save_as(self):
        if not self.doc:
            return
        self._flush_box()
        self._flush_form()
        self._flush_tstyle()
        self._end_live()
        stem = os.path.splitext(os.path.basename(self.path))[0]
        dst = filedialog.asksaveasfilename(title="Mentés másként",
                                           initialdir=os.path.dirname(self.path),
                                           initialfile=f"{stem}_szerkesztett.pdf",
                                           defaultextension=".pdf",
                                           filetypes=[("PDF fájlok", "*.pdf")])
        if dst:
            self._save_to(dst)

    def _save_to(self, dst):
        try:
            backup = self._write(dst)
        except Exception as e:
            traceback.print_exc()
            messagebox.showerror("A mentés nem sikerült", f"{type(e).__name__}: {e}")
            return
        if self.log_parent:
            log_row(self.log_parent, self.path,
                    os.path.relpath(os.path.dirname(dst), self.log_parent),
                    os.path.basename(dst), "",
                    "SZERKESZTVE" + (f" (elozo: {DIR_PREP})" if backup else ""))
        self.path, self.dirty = dst, False
        if not self.files.winfo_ismapped():
            self._files_shown(False)
        note = size_note(dst)
        self.app.status(f"Mentve: {os.path.basename(dst)} {note}")
        self.app.refresh_all()
        self._say("Mentve" + (f", az előző példány a {DIR_PREP} mappában" if backup else "") +
                  (f" · {note}" if note else ""))


# ───────────────────────────── 5. fül: iktató ─────────────────────────────
# ── konfiguráció ────────────────────────────────────────────────────────────
DOC_TYPES_DEFAULT = [
    # Kiírva és ékezettel — ez kerül a fájlnévbe:
    # „John Doe Tartózkodási engedély formanyomtatvány (aláírt, fotóval ellátva).pdf”
    "Tartózkodási engedély formanyomtatvány",
    "Nyilatkozat szálláshely változatlanságáról",
    "Előzetes megállapodás",
    "Elfogadó nyilatkozat",
    "Egyoldalú hozzájárulási nyilatkozat",
    "Belföldi meghatalmazás",
]
# ── egységes fájlnév-metodika ──────────────────────────────────────────────
# A jelölők EGY zárójelben, vesszővel elválasztva, ékezettel és szóközzel:
#   Kiss Anna Tartózkodási engedély formanyomtatvány (aláírt, fotóval ellátva).pdf
# A régi forma („… aláírt.pdf”, „…_kesz.pdf”) ettől még felismerhető marad: a
# norm() minden jelölőt kitöröl az illesztés előtt.
MARK_SIGNED = "aláírt"
MARK_PHOTO = "fotóval ellátva"
# A doktípus áll ELÖL, a dolgozó neve mögötte:
#   NAV jövedelemigazolás — Kiss Anna (aláírt).pdf
# Miért: az iratok amúgy is dolgozónkénti mappában vannak, ott a névvel kezdődő
# fájlnév semmit nem csoportosít (minden fájl ugyanazé a dolgozóé), viszont épp
# azt a helyet foglalja, ahol a szem a típust keresi. A PDF-metaadat (Cím,
# Címkék) nem volt járható út: a Windows Intéző property handler nélkül nem
# olvassa, és egyik gépen sincs telepítve — mérve (kepek-pdf-terv.md 18.).
NAME_SEP = " — "
SUFFIX = MARK_SIGNED                       # az Iktató „Utótag” mezőjének alapértéke
LOG_NAME = "iktato-naplo.csv"
# Külön mentésmappa (korábban .eredeti) NINCS: a felülírt példány a dolgozó
# 01_Elokeszitett mappájába kerül, „(előző példány <időbélyeg>)” jelölővel. Így a
# felhasználó ott látja, ahol dolgozik. A jelölőt az is_noise() ismeri, ezért az
# Áttekintő mátrixába nem számít bele — enélkül minden felülírás hamis
# duplikátumot csinálna ugyanarra a doktípusra.
MARK_BACKUP = "előző példány"
NO_WORKER = "— nincs —"                    # az alapértelmezett-dolgozó választó üres eleme
TYPES_FILE = "iktato-doktipusok.json"      # a szkript mappájában
MEMORY_FILE = "emlekezet.json"             # utoljára használt útvonalak, doktípus

# ── dolgozónkénti két alkönyvtár (kepek-pdf-terv.md 12.) ───────────────────
# Ékezet nélkül és számozva: az Intézőben a folyamat sorrendjében látszanak, és
# csak 15/14 karaktert vesznek el a MAX_FULL_PATH büdzséből.
DIR_PREP = "01_Elokeszitett"    # nyomtatásra/aláírásra váró irat, arckép, docx
DIR_UP   = "02_Feltoltheto"     # szkennelt, aláírt, korlát alatti végleges PDF
WORK_DIRS = (DIR_PREP, DIR_UP)

TILE_W, TILE_H, GAP = 150, 52, 10
CACHE_MAX = 12
BIG_FILE = 20 * 1024 * 1024        # efölött darabolt másolás
MAX_FULL_PATH = 255

ZOOM_MIN, ZOOM_MAX, ZOOM_STEP = 0.25, 6.0, 1.15

COL_TILE_BG = UI["card"]
COL_TILE_BG_HOT = UI["accent_bg"]
COL_TILE_LINE = "#cbd5e8"
COL_TILE_LINE_HOT = UI["accent"]
COL_CANVAS = UI["dark"]
COL_WARN = UI["warn"]
COL_OK = UI["ok"]
COL_CROP = "#ffb300"


# ── doktípus-lista tárolása ─────────────────────────────────────────────────
def types_path() -> str:
    return os.path.join(script_dir(), TYPES_FILE)


def load_types() -> list:
    """Mentett lista, ha van; különben a beépített alapértelmezés."""
    try:
        with open(types_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        items = [str(x).strip() for x in data if str(x).strip()]
        if items:
            return items
    except Exception:
        pass
    return list(DOC_TYPES_DEFAULT)


def save_types(items) -> bool:
    try:
        with open(types_path(), "w", encoding="utf-8") as f:
            json.dump(list(items), f, ensure_ascii=False, indent=2)
        return True
    except OSError:
        return False


# ── emlékezet (utoljára használt útvonalak, doktípus) ───────────────────────
# Külön fájl, nem a szabályfájl mellé: gépenként más, és nem kerül a repóba
# (a .gitignore engedélyező lista épp ezért nem sorolja fel).
def memory_path() -> str:
    return os.path.join(script_dir(), MEMORY_FILE)


def recall(key: str, fallback: str = "") -> str:
    """Az utoljára megjegyzett érték. Útvonalat csak akkor ad vissza, ha még
    létezik — pendrive/hálózati meghajtó közben eltűnhetett."""
    try:
        with open(memory_path(), "r", encoding="utf-8") as f:
            v = json.load(f).get(key, "")
    except Exception:
        return fallback
    if not isinstance(v, str) or not v:
        return fallback
    if os.path.isabs(v) and not os.path.isdir(v):
        return fallback
    return v


def remember(key: str, value: str):
    """Mentés a következő indításra. Fájlútvonalból a mappáját jegyzi meg.
    Csendben elbukik: ez kényelmi funkció, nem akadályozhatja a munkát."""
    if not value:
        return
    if os.path.isabs(value) and not os.path.isdir(value):
        value = os.path.dirname(value)
        if not os.path.isdir(value):
            return
    try:
        try:
            with open(memory_path(), "r", encoding="utf-8") as f:
                d = json.load(f)
            d = d if isinstance(d, dict) else {}
        except Exception:
            d = {}
        if d.get(key) == value:
            return
        d[key] = value
        with open(memory_path(), "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


# ── névképzés és rendezés ───────────────────────────────────────────────────
_HU_MAP = str.maketrans("áéíóöőúüűÁÉÍÓÖŐÚÜŰ", "aeiooouuuAEIOOOUUU")


def strip_accents(s: str) -> str:
    return s.translate(_HU_MAP).lower()


def _fallback_key(s):
    """Ékezet-lebontásos kulcs — mindig helyes magyar sorrendet ad."""
    return (strip_accents(s), s)


def _probe_collation():
    """A locale-t NEM elég beállítani: le is kell mérni, hogy tényleg rendez-e.

    A setlocale sikeresen lefuthat úgy is, hogy a strxfrm közben bájtsorrend
    szerint rendez — ilyenkor az „Áron” a „Zsuk” MÖGÉ kerül, ami a
    felhasználónak hibának látszik. Ezért próbamintán ellenőrizzük.
    """
    probe = ["Zsuk", "Áron", "Bondar", "Ökrös", "Nagy"]
    want = ["Áron", "Bondar", "Nagy", "Ökrös", "Zsuk"]
    for loc in ("Hungarian_Hungary.1250", "hu_HU.UTF-8", "hu_HU"):
        try:
            locale.setlocale(locale.LC_COLLATE, loc)
        except locale.Error:
            continue
        try:
            if sorted(probe, key=locale.strxfrm) == want:
                return locale.strxfrm, loc
        except Exception:
            pass
    try:
        locale.setlocale(locale.LC_COLLATE, "C")
    except locale.Error:
        pass
    return _fallback_key, "beépített"


_sort_key, COLLATION = _probe_collation()


def hu_az(n: int) -> str:
    """Névelő a sorszám elé: „az 1. oldal", de „a 2. oldal” (a kiejtés dönt)."""
    return "az" if n == 1 or n == 5 or 50 <= n <= 59 or 500 <= n <= 599 else "a"


def hu_sorted(names) -> list:
    """Magyar ábécé szerinti rendezés (Zsuk < Áron NEM fordulhat elő)."""
    return sorted(names, key=_sort_key)


def target_name(dir_name: str, doc_type: str, suffix: str = SUFFIX,
                photo: bool = False) -> str:
    """Horváth Dániel + Előzetes megállapodás -> teljes fájlnév.

    A DOKTÍPUS áll elöl, a dolgozó neve mögötte; a jelölők egy zárójelben:
        Útlevél — Kiss Anna (aláírt).pdf
        Tartózkodási engedély formanyomtatvány — Kiss Anna (aláírt, fotóval ellátva).pdf
    """
    marks = [m.strip() for m in (suffix, MARK_PHOTO if photo else "") if m and m.strip()]
    stem = NAME_SEP.join(p for p in (doc_type.strip(), dir_name.strip()) if p)
    if marks:
        stem += " (" + ", ".join(marks) + ")"
    stem = re.sub(r"\s+", " ", stem)
    stem = unicodedata.normalize("NFC", stem)      # Windows NFC-t vár
    return safe_stem(stem) + ".pdf"


def add_mark(stem: str, mark: str) -> str:
    """Jelölő hozzáadása a név végi zárójelhez — ha nincs ilyen, újat nyit.

        „Kiss Anna Útlevél (aláírt)” + „fotóval ellátva”
            -> „Kiss Anna Útlevél (aláírt, fotóval ellátva)”
        „Kiss Anna Útlevél”          -> „Kiss Anna Útlevél (fotóval ellátva)”

    Idempotens: ami már rajta van (ékezettől függetlenül), nem kerül rá kétszer.
    """
    if strip_accents(mark) in strip_accents(stem):
        return stem
    m = re.search(r"\(([^()]*)\)\s*$", stem)
    if m and m.group(1).strip().isdigit():
        m = None                      # „… (2)” ütközés-sorszám: nem jelölőzárójel
    if m:
        belso = m.group(1).strip().rstrip(",")
        return stem[:m.start()].rstrip() + " (" + (belso + ", " if belso else "") + mark + ")"
    return stem.rstrip() + " (" + mark + ")"


def unique_name(folder: str, name: str):
    """Szabad fájlnév keresése: (2), (3) …  -> (név, volt-e ütközés)"""
    if not os.path.exists(os.path.join(folder, name)):
        return name, False
    stem, ext = os.path.splitext(name)
    i = 2
    while True:
        cand = f"{stem} ({i}){ext}"
        if not os.path.exists(os.path.join(folder, cand)):
            return cand, True
        i += 1


def check_path_len(full: str):
    if len(full) > MAX_FULL_PATH:
        raise ValueError(f"Túl hosszú útvonal ({len(full)} karakter):\n{full}")


# ── iktatómag: az Iktató és a kötegelt iktatás közös lépései ────────────────
def worker_root(folder: str) -> str:
    """A dolgozó mappája egy 01/02 alkönyvtárból visszanézve (különben önmaga)."""
    return (os.path.dirname(folder) if os.path.basename(os.path.normpath(folder))
            in WORK_DIRS else folder)


def backup_existing(dst: str) -> str:
    """Felülírás előtt az előző példány másolata a dolgozó 01_Elokeszitett
    mappájába kerül, „(előző példány <időbélyeg>)” jelölővel — külön .eredeti
    mappa nincs. Az időbélyeg miatt több mentés sem ütközik. -> a másolat útja"""
    d = os.path.join(worker_root(os.path.dirname(dst)), DIR_PREP)
    os.makedirs(d, exist_ok=True)
    stem, ext = os.path.splitext(os.path.basename(dst))
    mark = f"{MARK_BACKUP} {datetime.datetime.now():%Y-%m-%d %H-%M-%S}"
    path = os.path.join(d, unique_name(d, add_mark(stem, mark) + ext)[0])
    shutil.copy2(dst, path)
    return path


def undo_copy(dst: str, backup):
    """Egy iktatás visszavonása: felülírásnál az előző példány visszakerül,
    különben a cél törlődik. OSError-t dob, ha nem sikerül."""
    if backup and os.path.exists(backup):
        os.replace(backup, dst)
    elif os.path.exists(dst):
        os.remove(dst)


def log_row(parent: str, src: str, folder: str, name: str, doc_type: str, result: str):
    """Egy sor az iktato-naplo.csv-be (a munkamappában)."""
    path = os.path.join(parent, LOG_NAME)
    new = not os.path.exists(path)
    try:
        with open(path, "a", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, delimiter=";")
            if new:
                w.writerow(["időbélyeg", "forrás", "célmappa", "célfájl",
                            "doktípus", "eredmény"])
            w.writerow([datetime.datetime.now().isoformat(timespec="seconds"),
                        src, folder, name, doc_type, result])
    except OSError:
        pass                        # a napló sosem állítja meg a munkát


def extract_page(path: str, pageno: int) -> bytes:
    """Egy oldal önálló, egyoldalas PDF-ként. Az oldal tartalma változatlanul
    kerül át (insert_pdf: nincs újrarajzolás), tehát a szkennelt kép sem romlik."""
    src = open_checked(path)
    try:
        if not 0 <= pageno < src.page_count:
            # Az insert_pdf tartományon kívül nem hibázik, csak üres iratot adna.
            raise IndexError(f"Nincs {pageno + 1}. oldal ({src.page_count} oldalas).")
        out = pymupdf.open()
        try:
            out.insert_pdf(src, from_page=pageno, to_page=pageno)
            out.set_metadata(dict(CLEAN_META))
            return out.tobytes(garbage=4, deflate=True)
        finally:
            out.close()
    finally:
        src.close()


def worker_dirs(parent: str) -> list:
    """A munkamappa dolgozói mappái (a ponttal kezdődők nélkül), magyar sorrendben.
    OSError-t dob, ha a mappa nem olvasható."""
    return hu_sorted([d for d in os.listdir(parent)
                      if os.path.isdir(os.path.join(parent, d)) and not d.startswith(".")])


# ── csempeelrendezés ────────────────────────────────────────────────────────
def ring_metrics(cw, ch, tw=TILE_W, th=TILE_H, gap=GAP):
    """Hány csempe fér ki, és hol kezdődik a jobb oszlop / az alsó sor.

    JAVÍTÁS: a csempék balra igazított rácsban ülnek, ezért a vászon jobb
    szélén (és alján) marad egy kihasználatlan sáv. Az előnézet keretét NEM a
    vászon széléhez, hanem ezekhez az értékekhez kell igazítani, különben a
    keretezett rész jobbra átlóg és rárajzolódik a mappacsempékre.
    """
    cols = max(1, (cw - gap) // (tw + gap))
    rows = max(1, (ch - gap) // (th + gap))
    ring_left = gap + (cols - 1) * (tw + gap)      # a jobb oszlop BAL éle
    ring_top = gap + (rows - 1) * (th + gap)       # az alsó sor FELSŐ éle
    return cols, rows, ring_left, ring_top


def ring_positions(cw, ch, tw=TILE_W, th=TILE_H, gap=GAP) -> list:
    """A vászon peremén körbefutó csempehelyek, óramutató járása szerint."""
    cols, rows, _, _ = ring_metrics(cw, ch, tw, th, gap)
    pos = []
    for c in range(cols):                          # felső sor →
        pos.append((gap + c * (tw + gap), gap))
    for r in range(1, rows):                       # jobb oszlop ↓
        pos.append((gap + (cols - 1) * (tw + gap), gap + r * (th + gap)))
    if rows > 1:
        for c in range(cols - 2, -1, -1):          # alsó sor ←
            pos.append((gap + c * (tw + gap), gap + (rows - 1) * (th + gap)))
    for r in range(rows - 2, 0, -1):               # bal oszlop ↑
        pos.append((gap, gap + r * (th + gap)))
    return pos


# ── nagyítás és kivágás ─────────────────────────────────────────────────────
def fit_zoom(pw, ph, bw, bh) -> float:
    """Az a nagyítás, amelynél a teljes oldal épp befér a dobozba."""
    return min(bw / pw, bh / ph)


def visible_clip(pw, ph, bw, bh, z, pan_rel=None):
    """Mekkora rész látszik az oldalból, ha z nagyítással a dobozba rajzoljuk.

    A doboz méretét SOSEM lépjük túl: ha a nagyított oldal nagyobb, csak a
    belőle kivágott, dobozméretű részt rendereljük — így a körben álló
    mappacsempék nem takaródnak ki.

    A pan ARÁNYBAN (0..1) érkezik és úgy is tér vissza — így a nézetpozíció
    átvihető másik fájlra, másik oldalra, sőt eltérő lapméretre is.
    Visszatér: (clip | None, vágva?, új pan_rel)
    """
    full_w, full_h = pw * z, ph * z
    if full_w <= bw + 0.5 and full_h <= bh + 0.5:
        return None, False, (pan_rel or (0.5, 0.5))
    vis_w = min(bw, full_w) / z
    vis_h = min(bh, full_h) / z
    fx, fy = pan_rel if pan_rel else (0.5, 0.5)
    cx, cy = fx * pw, fy * ph
    cx = min(max(cx, vis_w / 2.0), pw - vis_w / 2.0)
    cy = min(max(cy, vis_h / 2.0), ph - vis_h / 2.0)
    return ((cx - vis_w / 2.0, cy - vis_h / 2.0,
             cx + vis_w / 2.0, cy + vis_h / 2.0), True, (cx / pw, cy / ph))


# ── doktípus-szerkesztő ─────────────────────────────────────────────────────
class TypeEditor(tk.Toplevel):
    """Dokumentumtípusok hozzáadása, átnevezése, törlése, sorrendezése."""

    def __init__(self, master, items, on_save):
        super().__init__(master)
        self.title("Dokumentumtípusok")
        self.transient(master.winfo_toplevel())
        self.resizable(False, True)
        self.grab_set()
        self.items = list(items)
        self.on_save = on_save

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=12, pady=12)

        ttk.Label(body, text="A legördülő lista elemei:",
                  font=("Segoe UI", 9, "bold")).pack(anchor="w")

        mid = ttk.Frame(body)
        mid.pack(fill="both", expand=True, pady=(6, 8))
        self.lb = tk.Listbox(mid, height=12, width=52, exportselection=False,
                             activestyle="dotbox")
        sb = ttk.Scrollbar(mid, orient="vertical", command=self.lb.yview)
        self.lb.configure(yscrollcommand=sb.set)
        self.lb.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.lb.bind("<Double-Button-1>", lambda e: self._rename())

        add = ttk.Frame(body)
        add.pack(fill="x")
        self.entry = ttk.Entry(add, width=40)
        self.entry.pack(side="left", fill="x", expand=True)
        self.entry.bind("<Return>", lambda e: self._add())
        ttk.Button(add, text="Hozzáad", command=self._add).pack(side="left",
                                                                padx=6)

        row = ttk.Frame(body)
        row.pack(fill="x", pady=(8, 0))
        ttk.Button(row, text="Átnevez", command=self._rename).pack(side="left")
        ttk.Button(row, text="Töröl", command=self._remove).pack(side="left",
                                                                 padx=6)
        ttk.Button(row, text="▲", width=3,
                   command=lambda: self._move(-1)).pack(side="left", padx=(16, 2))
        ttk.Button(row, text="▼", width=3,
                   command=lambda: self._move(1)).pack(side="left")
        ttk.Button(row, text="Alapértelmezett lista",
                   command=self._reset).pack(side="right")

        self.msg = tk.StringVar(value="")
        ttk.Label(body, textvariable=self.msg, foreground=COL_WARN,
                  wraplength=380).pack(anchor="w", pady=(8, 0))

        foot = ttk.Frame(body)
        foot.pack(fill="x", pady=(10, 0))
        ttk.Button(foot, text="Mentés", command=self._save).pack(side="right")
        ttk.Button(foot, text="Mégsem",
                   command=self.destroy).pack(side="right", padx=8)

        self._fill()
        self.entry.focus_set()
        self.bind("<Escape>", lambda e: self.destroy())

    def _fill(self, select=None):
        self.lb.delete(0, tk.END)
        for it in self.items:
            self.lb.insert(tk.END, it)
        if select is not None and 0 <= select < len(self.items):
            self.lb.selection_set(select)
            self.lb.see(select)

    def _sel(self):
        s = self.lb.curselection()
        return s[0] if s else None

    def _add(self):
        txt = self.entry.get().strip()
        if not txt:
            return
        if txt in self.items:
            self.msg.set("Ez az elem már szerepel a listában.")
            return
        bad = set(txt) & set('<>:"/\\|?*')
        if bad:
            self.msg.set("Fájlnévben tiltott karakter: " + " ".join(sorted(bad)))
            return
        self.items.append(txt)
        self.entry.delete(0, tk.END)
        self.msg.set("")
        self._fill(len(self.items) - 1)

    def _rename(self):
        i = self._sel()
        if i is None:
            return
        new = simpledialog.askstring("Átnevezés", "Új megnevezés:",
                                     initialvalue=self.items[i], parent=self)
        if not new:
            return
        new = new.strip()
        if not new or (new in self.items and new != self.items[i]):
            self.msg.set("Üres vagy már létező megnevezés.")
            return
        self.items[i] = new
        self.msg.set("")
        self._fill(i)

    def _remove(self):
        i = self._sel()
        if i is None:
            return
        del self.items[i]
        self._fill(min(i, len(self.items) - 1))

    def _move(self, d):
        i = self._sel()
        if i is None:
            return
        j = i + d
        if not (0 <= j < len(self.items)):
            return
        self.items[i], self.items[j] = self.items[j], self.items[i]
        self._fill(j)

    def _reset(self):
        if messagebox.askyesno("Alapértelmezett lista",
                               "Visszaállítod a beépített hat elemet?\n"
                               "A saját elemek elvesznek.", parent=self):
            self.items = list(DOC_TYPES_DEFAULT)
            self._fill()

    def _save(self):
        if not self.items:
            self.msg.set("A lista nem lehet üres.")
            return
        self.on_save(self.items)
        self.destroy()


# ── a fül ───────────────────────────────────────────────────────────────────
class IktatoTab(ttk.Frame):

    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.parent_dir = script_dir()
        self.dirs = []
        self.queue = []
        self.idx = 0
        self.page = 0
        self.page_no = 0                 # az előnézet oldalszáma
        self.page_count = 1
        self.tile_rects = {}
        self.last_copy = None
        self.preview_tk = None
        self.preview_item = None
        self.prev_box = (0, 0, 100, 100)
        self.types = load_types()

        self.zoom = None                 # None = illesztés; a run alatt megmarad
        self.pan_rel = None              # a látható rész közepe ARÁNYBAN (0..1)
        self.view_locked = False         # igaz, ha nem középre van állítva
        self.cropped = False

        self._cache = {}
        self._drag = None
        self._panning = None
        self._hot = None
        self._job = None
        self._busy = False               # tömörítés fut: új iktatás és visszavonás vár
        self.stamped = False             # sikerült-e a bélyeg az utolsó iktatásnál

        # Oldalankénti szétosztás: egy köteg = TÖBB dolgozó, azonos típus
        # (kepek-pdf-terv.md 13.9). Fájlonként tartjuk, mely oldalak mentek el.
        self.page_mode = tk.BooleanVar(value=False)
        self.done_pages = {}
        self.last_page = None            # (forrás, oldal) a visszavonáshoz
        last = recall("doktipus")
        self.doc_type = tk.StringVar(value=last if last in self.types else "")
        self.suffix = tk.StringVar(value=SUFFIX)
        # Fotóigényes nyomtatványnál: rajta van-e már az arckép. Típusváltáskor
        # szándékosan visszaáll — téves 02 aláírás/fotó nélküli iratot mondana
        # beadhatónak, a téves 01 csak annyit, hogy még nincs kész.
        self.arckep_kesz = tk.BooleanVar(value=False)
        self.filter_text = tk.StringVar(value="")
        self.name_preview = tk.StringVar(value="")
        self.msg = tk.StringVar(value="")
        self.page_lbl = tk.StringVar(value="")
        self.queue_lbl = tk.StringVar(value="nincs betöltött fájl")
        self.pagenav_lbl = tk.StringVar(value="")
        self.zoom_lbl = tk.StringVar(value="illesztve")

        self._build()
        if self.doc_type.get():
            self._type_chosen()      # a megjegyzett típushoz az utótag és a jelölő
        self._info("Rendezés: " + COLLATION +
                   " · Tallózás a középső gombbal · görgő = nagyítás · "
                   "jobb gomb = nézet mozgatása")

    # ---------------- felület ----------------
    def _build(self):
        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=8, pady=(8, 4))
        ttk.Label(bar, text="Dokumentum típusa:").pack(side="left")
        self.cbo = ttk.Combobox(bar, textvariable=self.doc_type,
                                values=self.types, state="readonly", width=42)
        self.cbo.pack(side="left", padx=6)
        self.cbo.bind("<<ComboboxSelected>>", lambda e: self._type_chosen())
        ttk.Button(bar, text="Típusok…", width=10,
                   command=self._edit_types).pack(side="left")
        ttk.Label(bar, text="Utótag:").pack(side="left", padx=(12, 4))
        ttk.Entry(bar, textvariable=self.suffix, width=10).pack(side="left")
        self.suffix.trace_add("write", lambda *a: self._update_name())

        self.arckep_cb = ttk.Checkbutton(bar, text="Az arckép már rajta van",
                                         variable=self.arckep_kesz,
                                         command=self._update_name)
        self.arckep_cb.pack(side="left", padx=(12, 0))
        self._sync_arckep()
        self.page_cb = ttk.Checkbutton(bar, text="Oldalanként (szétosztás)",
                                       variable=self.page_mode,
                                       command=self._page_mode_changed)
        self.page_cb.pack(side="left", padx=(14, 0))

        ttk.Label(bar, text="Szűrő:").pack(side="left", padx=(18, 4))
        ent = ttk.Entry(bar, textvariable=self.filter_text, width=16)
        ent.pack(side="left")
        self.filter_text.trace_add("write", lambda *a: self._relayout())

        # „Mappák frissítése” nincs: a felső sáv Frissítés gombja ugyanezt teszi.

        self.canvas = tk.Canvas(self, bg=COL_CANVAS, highlightthickness=0,
                                height=180)       # kért méret: kis ablakban se
        self.canvas.pack(fill="both", expand=True, padx=8, pady=4)
        self.canvas.bind("<Configure>", lambda e: self._schedule())

        nav = ttk.Frame(self)
        nav.pack(fill="x", padx=8, pady=(0, 4))
        ttk.Button(nav, text="◀", width=3,
                   command=lambda: self._step_file(-1)).pack(side="left")
        ttk.Label(nav, textvariable=self.queue_lbl, width=26,
                  anchor="center").pack(side="left")
        ttk.Button(nav, text="▶", width=3,
                   command=lambda: self._step_file(1)).pack(side="left")
        ttk.Button(nav, text="Sorból kivesz",
                   command=self._drop_current).pack(side="left", padx=(10, 0))

        ttk.Label(nav, text="Oldal:").pack(side="left", padx=(14, 4))
        ttk.Button(nav, text="◀", width=3,
                   command=lambda: self._step_page(-1)).pack(side="left")
        ttk.Label(nav, textvariable=self.pagenav_lbl, width=7,
                  anchor="center").pack(side="left")
        ttk.Button(nav, text="▶", width=3,
                   command=lambda: self._step_page(1)).pack(side="left")

        # Nagyítás: görgővel (a ± gombok elhagyva), a mérték a címke, az Illeszt marad.
        ttk.Label(nav, textvariable=self.zoom_lbl, width=9,
                  anchor="center").pack(side="left", padx=(18, 0))
        ttk.Button(nav, text="Illeszt",
                   command=self._zoom_fit).pack(side="left", padx=4)

        ttk.Button(nav, text="Visszavonás",
                   command=self._undo).pack(side="right")
        ttk.Label(nav, textvariable=self.page_lbl).pack(side="right", padx=10)
        ttk.Button(nav, text="›", width=3,
                   command=lambda: self._step_tilepage(1)).pack(side="right")
        ttk.Button(nav, text="‹", width=3,
                   command=lambda: self._step_tilepage(-1)).pack(side="right")

        foot = ttk.Frame(self)
        foot.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Label(foot, textvariable=self.name_preview,
                  font=("Segoe UI", 9, "bold")).pack(anchor="w")
        self.msg_lbl = ttk.Label(foot, textvariable=self.msg)
        self.msg_lbl.pack(anchor="w")

        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._motion)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.canvas.bind("<ButtonPress-3>", self._pan_start)
        self.canvas.bind("<B3-Motion>", self._pan_move)
        self.canvas.bind("<ButtonRelease-3>",
                         lambda e: setattr(self, "_panning", None))
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.canvas.bind("<Enter>", lambda e: self.canvas.focus_set())

    # ---------------- doktípusok ----------------
    def _edit_types(self):
        TypeEditor(self, self.types, self._apply_types)

    def _apply_types(self, items):
        cur = self.doc_type.get()
        self.types = items
        self.cbo.configure(values=self.types)
        if cur not in self.types:
            self.doc_type.set("")
        ok = save_types(self.types)
        self._update_name()
        self._info(f"{len(self.types)} dokumentumtípus." +
                   ("" if ok else " FIGYELEM: a lista mentése nem sikerült, "
                                  "csak eddig a futásig él."), warn=not ok)

    # ---------------- mappák ----------------
    def set_folder(self, folder):
        self.parent_dir = folder
        self.page = 0
        self._scan_dirs()

    def _scan_dirs(self):
        try:
            self.dirs = worker_dirs(self.parent_dir)
        except OSError as e:
            self.dirs = []
            self._info(f"A mappa nem olvasható: {e}", warn=True)
        self._relayout()

    def _visible_dirs(self):
        f = strip_accents(self.filter_text.get().strip())
        if not f:
            return self.dirs
        return [d for d in self.dirs if f in strip_accents(d)]

    # ---------------- rajzolás ----------------
    def _schedule(self):
        if self._job:
            self.after_cancel(self._job)
        self._job = self.after(60, self._relayout)

    def _relayout(self):
        self._job = None
        c = self.canvas
        c.delete("all")
        self.tile_rects = {}
        self.preview_item = None
        cw, ch = max(200, c.winfo_width()), max(200, c.winfo_height())

        cols, rows, ring_left, ring_top = ring_metrics(cw, ch)
        pos = ring_positions(cw, ch)
        cap = max(1, len(pos))
        vis = self._visible_dirs()
        pages = max(1, (len(vis) + cap - 1) // cap)
        self.page = max(0, min(self.page, pages - 1))
        chunk = vis[self.page * cap:(self.page + 1) * cap]
        self.page_lbl.set(f"{self.page + 1}/{pages} lap · {len(vis)} mappa")

        for name, (x, y) in zip(chunk, pos):
            self._draw_tile(name, x, y)

        # az előnézet doboza: a csempegyűrűN BELÜL — a tényleges csempehelyekhez
        # igazítva, nem a vászon széléhez (különben jobbra átlóg a mappákra)
        left = GAP + TILE_W + GAP
        top = GAP + TILE_H + GAP
        right = (ring_left - GAP) if cols > 1 else cw - GAP
        bottom = (ring_top - GAP) if rows > 1 else ch - GAP
        self.prev_box = (left, top, right, bottom)
        self._render_preview()

    def _draw_tile(self, name, x, y):
        c = self.canvas
        tags = ("tile", f"tile::{name}")
        r = canvas_card(c, x, y, x + TILE_W, y + TILE_H, 9, fill=COL_TILE_BG,
                        outline=COL_TILE_LINE, tags=tags)
        label = name if len(name) <= 20 else name[:19] + "…"
        c.create_text(x + TILE_W / 2, y + TILE_H / 2, text=label,
                      font=FONT_SB, fill=UI["ink"], tags=tags)
        self.tile_rects[name] = (x, y, x + TILE_W, y + TILE_H)
        return r

    def _render_preview(self):
        c = self.canvas
        c.delete("preview")
        self.preview_item = None
        x1, y1, x2, y2 = self.prev_box
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2

        if not self.queue:
            c.create_rectangle(x1, y1, x2, y2, outline="#8d949e", dash=(4, 3),
                               tags=("preview",))
            c.create_text(cx, cy - 26, fill=UI["ink_soft"], justify="center",
                          font=("Segoe UI", 11), text="Nincs betöltött PDF")
            self._btn(cx, cy + 16, "📂  PDF-ek tallózása…", self._browse_files)
            self.queue_lbl.set("nincs betöltött fájl")
            self.pagenav_lbl.set("")
            self.zoom_lbl.set("illesztve")
            self._update_name()
            return

        path = self.queue[self.idx]
        self.queue_lbl.set(f"{self.idx + 1} / {len(self.queue)} · "
                           f"{os.path.basename(path)[:20]}")
        bw, bh = int(x2 - x1) - 16, int(y2 - y1) - 54
        img, note, self.page_count, cropped, zoom = self._page_image(
            path, self.page_no, bw, bh)
        self.cropped = cropped
        self.pagenav_lbl.set(f"{self.page_no + 1}/{self.page_count}")
        self.zoom_lbl.set("illesztve" if self.zoom is None
                          else f"{zoom * 100:.0f}%")

        if img is not None:
            self.preview_tk = img
            self.preview_item = c.create_image(cx, cy - 12, image=img,
                                               tags=("preview",))
            bb = c.bbox(self.preview_item)
            if bb:
                c.create_rectangle(bb, outline=COL_CROP if cropped else UI["line"],
                                   width=2 if cropped else 1, tags=("preview",))
            if cropped:
                pos = ""
                if self.pan_rel:
                    pos = f" · nézet: {self.pan_rel[1] * 100:.0f}% magasságban"
                c.create_text(cx, y1 + 10, fill=COL_CROP,
                              font=("Segoe UI", 8, "bold"), tags=("preview",),
                              text="⤢ kivágott nézet — jobb gombbal mozgatható"
                                   + pos)
        else:
            c.create_rectangle(cx - 120, cy - 80, cx + 120, cy + 40,
                               fill="#ffffff", outline=UI["line"],
                               tags=("preview",))
            c.create_text(cx, cy - 20, text=note, width=220, justify="center",
                          font=("Segoe UI", 10), tags=("preview",))

        size = os.path.getsize(path) if os.path.isfile(path) else 0
        big = size > UPLOAD_LIMIT
        self._chip(cx, y2 - 30,
                   f"{os.path.basename(path)} · {mb(size)}" +
                   ("  ⚠ korlát fölött — iktatáskor tömöríthető" if big else ""),
                   COL_CROP if big else UI["ink_soft"])
        if self.page_count > 1:      # kötegből több irat: az Összeállítóban
            self._btn(cx - 75, y2 - 12, "📂  Tallózás…", self._browse_files)
            self._btn(cx + 85, y2 - 12, "✂  Szétosztás…", self._to_composer)
        else:
            self._btn(cx, y2 - 12, "📂  Tallózás…", self._browse_files)
        self._update_name()

    def _chip(self, cx, cy, text, color):
        """Felirat halvány lapon: az előnézeti oldal fölé csúszva is olvasható."""
        c = self.canvas
        t = c.create_text(cx, cy, text=text, fill=color, font=FONT_SM,
                          tags=("preview",))
        x1, y1, x2, y2 = c.bbox(t)
        r = canvas_card(c, x1 - 8, y1 - 3, x2 + 8, y2 + 3, 7, fill=UI["card"],
                        outline=UI["line_soft"], tags=("preview",))
        c.tag_raise(t, r)

    def _btn(self, cx, cy, text, cmd):
        """Vászonra rajzolt gomb — ugyanaz a nyelv, mint a ttk-gomboké:
        lekerekített fehér lap, halk árnyékkal."""
        c = self.canvas
        t = c.create_text(cx, cy, text=text, fill=UI["ink"],
                          font=FONT_UI, tags=("preview", "cbtn"))
        x1, y1, x2, y2 = c.bbox(t)
        r = canvas_card(c, x1 - 14, y1 - 7, x2 + 14, y2 + 7, 9, fill=UI["card"],
                        outline=UI["line"], shadow=(UI["shade1"], UI["shade2"]),
                        tags=("preview", "cbtn"))
        c.tag_raise(t, r)
        for i in (r, t):
            c.tag_bind(i, "<Button-1>", lambda e, f=cmd: (f(), "break")[1])
            c.tag_bind(i, "<Enter>",
                       lambda e, rr=r: c.itemconfig(rr, fill=UI["accent_bg"]))
            c.tag_bind(i, "<Leave>",
                       lambda e, rr=r: c.itemconfig(rr, fill=UI["card"]))
        return r

    def _page_image(self, path, pageno, max_w, max_h):
        """(PhotoImage|None, üzenet, oldalszám, vágva?, tényleges zoom)"""
        zkey = "fit" if self.zoom is None else round(self.zoom, 4)
        pkey = (round(self.pan_rel[0], 3), round(self.pan_rel[1], 3)) \
            if self.pan_rel else None
        key = (path, pageno, max_w // 8, max_h // 8, zkey, pkey)
        if key in self._cache:
            return self._cache[key]
        try:
            doc = open_checked(path)
        except RuntimeError:
            return None, "🔒 jelszóval védett\n(másolni ettől még lehet)", 1, \
                False, 1.0
        except Exception:
            return None, "⚠ nem olvasható PDF", 1, False, 1.0
        try:
            pageno = max(0, min(pageno, doc.page_count - 1))
            page = doc[pageno]
            r = page.rect
            fz = fit_zoom(r.width, r.height, max_w, max_h)
            z = fz if self.zoom is None else max(ZOOM_MIN * fz,
                                                 min(ZOOM_MAX * fz, self.zoom))
            clip, cropped, pan = visible_clip(r.width, r.height,
                                              max_w, max_h, z, self.pan_rel)
            self.pan_rel = pan
            kw = {"matrix": pymupdf.Matrix(z, z), "annots": True}
            if clip is not None:
                kw["clip"] = pymupdf.Rect(*clip)
            pix = page.get_pixmap(**kw)
            res = (tkimg(pix, "ppm"), "", doc.page_count, cropped, z / fz)
        except Exception:
            res = (None, "⚠ az oldal nem jeleníthető meg", doc.page_count,
                   False, 1.0)
        finally:
            doc.close()
        if len(self._cache) >= CACHE_MAX:
            self._cache.pop(next(iter(self._cache)))
        self._cache[key] = res
        return res

    # ---------------- nagyítás és nézetpozíció ----------------
    def _cur_page_rect(self):
        """Az aktuális oldal mérete pontban — a pan arányosításához."""
        if not self.queue:
            return 595.0, 842.0
        try:
            doc = open_checked(self.queue[self.idx])
        except Exception:
            return 595.0, 842.0
        try:
            r = doc[min(self.page_no, doc.page_count - 1)].rect
            return r.width, r.height
        finally:
            doc.close()

    def _cur_fit(self):
        """Az aktuális fájl illesztési nagyítása (a zoom ehhez arányosít)."""
        if not self.queue:
            return 1.0
        x1, y1, x2, y2 = self.prev_box
        bw, bh = int(x2 - x1) - 16, int(y2 - y1) - 54
        pw, ph = self._cur_page_rect()
        return fit_zoom(pw, ph, bw, bh)

    def _zoom_by(self, k):
        if not self.queue:
            return
        fz = self._cur_fit()
        base = self.zoom if self.zoom is not None else fz
        self.zoom = max(ZOOM_MIN * fz, min(ZOOM_MAX * fz, base * k))
        self._render_preview()

    def _zoom_fit(self):
        """Az EGYETLEN hely, ami a nézetpozíciót is visszaállítja."""
        self.zoom = None
        self.pan_rel = None
        self.view_locked = False
        self._render_preview()

    def _wheel(self, e):
        x1, y1, x2, y2 = self.prev_box
        if not (x1 <= e.x <= x2 and y1 <= e.y <= y2):
            return "break"
        self._zoom_by(ZOOM_STEP if e.delta > 0 else 1 / ZOOM_STEP)
        return "break"

    def _pan_start(self, e):
        if self.cropped:
            self._panning = (e.x, e.y)
        return "break"

    def _pan_move(self, e):
        if not (self._panning and self.pan_rel):
            return "break"
        ox, oy = self._panning
        fz = self._cur_fit()
        z = self.zoom if self.zoom is not None else fz
        pw, ph = self._cur_page_rect()
        self.pan_rel = (self.pan_rel[0] - (e.x - ox) / (z * pw),
                        self.pan_rel[1] - (e.y - oy) / (z * ph))
        self._panning = (e.x, e.y)
        self.view_locked = True
        self._render_preview()
        return "break"

    # ---------------- várólista ----------------
    def _browse_files(self):
        paths = filedialog.askopenfilenames(
            title="PDF fájlok kiválasztása",
            initialdir=recall("mellekletek", self.parent_dir),
            filetypes=[("PDF fájlok", "*.pdf")])
        if paths:
            remember("mellekletek", paths[0])
            self._enqueue(paths)

    def _enqueue(self, paths):
        added, skipped = 0, 0
        for p in paths:
            p = os.path.abspath(p)
            if not p.lower().endswith(".pdf") or not os.path.isfile(p):
                skipped += 1
                continue
            if p not in self.queue:
                self.queue.append(p)
                self.done_pages.pop(p, None)   # újra betöltve: tiszta lappal indul
                added += 1
        if added:
            self.idx = len(self.queue) - added
            self.page_no = 0
            self._render_preview()       # nagyítás és nézet megmarad
        note = f"{added} fájl betöltve."
        if skipped:
            note += f" {skipped} kihagyva (csak .pdf)."
        self._info(note, warn=bool(skipped))

    def _page_mode_changed(self):
        """Be: a vonszolás a LÁTOTT oldalt viszi, nem az egész fájlt."""
        if self.page_mode.get() and self.page_count < 2:
            self._info("Ennek a fájlnak egy oldala van — a mód a többoldalas "
                       "kötegnél hasznos (egy oldal = egy dolgozó).")
        else:
            self._info(self._page_status() if self.page_mode.get()
                       else "Oldalanként mód ki — a teljes fájl megy egy dolgozóhoz.")
        self._update_name()
        self._render_preview()

    def _page_status(self) -> str:
        if not self.queue:
            return ""
        kesz = len(self.done_pages.get(self.queue[self.idx], ()))
        return (f"Oldalanként: ejtsd {hu_az(self.page_no + 1)} {self.page_no + 1}. "
                f"oldalt a dolgozó nevére · {kesz}/{self.page_count} oldal elosztva")

    def _by_page(self) -> bool:
        """Oldalanként iktatunk-e most (egyoldalas fájlnál sosem)."""
        return bool(self.page_mode.get() and self.page_count > 1)

    def _next_page(self) -> bool:
        """A következő, még el nem osztott oldalra lép. -> maradt-e oldal."""
        if not self.queue:
            return False
        done = self.done_pages.get(self.queue[self.idx], set())
        hatra = [i for i in range(self.page_count) if i not in done]
        if not hatra:
            return False
        kov = [i for i in hatra if i > self.page_no]
        self.page_no = kov[0] if kov else hatra[0]
        return True

    def _step_file(self, d):
        if not self.queue:
            return
        self.idx = (self.idx + d) % len(self.queue)
        self.page_no = 0
        self._render_preview()           # nagyítás ÉS nézetpozíció megmarad

    def _step_page(self, d):
        if not self.queue:
            return
        self.page_no = max(0, min(self.page_no + d, self.page_count - 1))
        self._render_preview()

    def _step_tilepage(self, d):
        self.page += d
        self._relayout()

    def _to_composer(self):
        """Többoldalas köteg: az Összeállítóba (oldalanként címkézhető), a sorból ki."""
        path = self.queue[self.idx]
        self._drop_current()
        self.app.goto_composer(path, self.filter_text.get())

    def _drop_current(self):
        if not self.queue:
            return
        self.queue.pop(self.idx)
        self.idx = min(self.idx, max(0, len(self.queue) - 1))
        self.page_no = 0
        self._render_preview()

    # ---------------- vonszolás ----------------
    def _press(self, e):
        if not self.queue:
            return
        cur = self.canvas.find_withtag("current")
        if cur and "cbtn" in self.canvas.gettags(cur[0]):
            return                       # a vászongombot ne vonszoljuk
        if self._busy:
            self._info("Előbb várd meg a folyamatban lévő tömörítést.", warn=True)
            return
        x1, y1, x2, y2 = self.prev_box
        if not (x1 <= e.x <= x2 and y1 <= e.y <= y2):
            return
        if not self.doc_type.get():
            self._flash_combo()
            self._info("Előbb válassz dokumentumtípust.", warn=True)
            return
        self.canvas.create_rectangle(e.x - 90, e.y - 14, e.x + 90, e.y + 14,
                                     fill="#ffffcc", outline=COL_TILE_LINE_HOT,
                                     dash=(3, 2), tags=("ghost",))
        self.canvas.create_text(e.x, e.y, font=("Segoe UI", 8), tags=("ghost",),
                                text=(f"⇢ {self.page_no + 1}. oldal a névre"
                                      if self._by_page() else "⇢ ejtsd a névre"))
        self._drag = (e.x, e.y)

    def _motion(self, e):
        if not self._drag:
            return
        ox, oy = self._drag
        self.canvas.move("ghost", e.x - ox, e.y - oy)
        self._drag = (e.x, e.y)
        self._highlight(self._hover_dir(e.x, e.y))

    def _release(self, e):
        if not self._drag:
            return
        self.canvas.delete("ghost")
        self._drag = None
        name = self._hover_dir(e.x, e.y)
        self._highlight(None)
        if name:
            self._do_copy(name)

    def _hover_dir(self, x, y):
        for name, (x1, y1, x2, y2) in self.tile_rects.items():
            if x1 <= x <= x2 and y1 <= y <= y2:
                return name
        return None

    def _highlight(self, name):
        # (a csempe polygon, nem rectangle — az itemconfig fill/outline ugyanaz)
        if name == self._hot:
            return
        # A csempe lekerekített POLYGON (13.7) — a típusszűrés ezt is engedje,
        # különben a vonszoláskor nem jelez vissza, hova ejtesz.
        for hot, (fill, line, wd) in ((self._hot, (COL_TILE_BG, COL_TILE_LINE, 1)),
                                      (name, (COL_TILE_BG_HOT, COL_TILE_LINE_HOT, 2))):
            if not hot:
                continue
            for i in self.canvas.find_withtag(f"tile::{hot}"):
                if self.canvas.type(i) in ("rectangle", "polygon"):
                    self.canvas.itemconfig(i, fill=fill, outline=line, width=wd)
        self._hot = name
        self._update_name(name)

    def _flash_combo(self):
        try:
            self.cbo.configure(foreground=COL_WARN)
            self.after(700, lambda: self.cbo.configure(foreground=""))
        except Exception:
            pass

    def _type_chosen(self):
        """Az utótag a doktípusból: a DocGen-ből készülő (aláírandó) iratnál
        „aláírt”, a többinél (útlevél, igazolások) üres. Az Áttekintő szabályai
        tudják, melyik melyik; ismeretlen típusnál az utótag marad, ami volt."""
        if self.doc_type.get():
            r, _ = match_rule(target_name("X", self.doc_type.get()), self._rules())
            if r:
                self.suffix.set(SUFFIX if r.generated else "")
        self.arckep_kesz.set(False)          # típusváltáskor nem ragadhat be
        remember("doktipus", self.doc_type.get())
        self._sync_arckep()
        self._update_name()

    def _rules(self) -> list:
        """Az Áttekintő szabályai (a célmappához és az utótaghoz)."""
        att = getattr(self.app, "tabs", {}).get("Áttekintő")
        return att.rules if att else rules_from(default_settings())

    def _sync_arckep(self):
        """A jelölő csak a fotóigényes típusnál él."""
        r = doc_type_rule(self.doc_type.get(), self._rules()) if self.doc_type.get() else None
        self.arckep_cb.configure(state="normal" if (r and r.arckep) else "disabled")

    def _update_name(self, hover=None):
        dt = self.doc_type.get()
        if not dt:
            self.name_preview.set("— válassz dokumentumtípust —")
            return
        who = hover or "<mappanév>"
        sub = target_subdir(dt, self._rules(), self.arckep_kesz.get())
        r = doc_type_rule(dt, self._rules())
        self.name_preview.set(sub + "\\" + target_name(
            who, dt, self.suffix.get(),
            photo=bool(r and r.arckep and self.arckep_kesz.get())) +
                              (f"   ⇠ {self.page_no + 1}. oldal"
                               if self._by_page() else ""))

    # ---------------- másolás ----------------
    def _do_copy(self, dir_name):
        if not self.queue:
            self._info("Nincs betöltött fájl.", warn=True)
            return
        if not self.doc_type.get():
            self._flash_combo()
            self._info("Előbb válassz dokumentumtípust.", warn=True)
            return

        src = self.queue[self.idx]
        if not os.path.isfile(src):                # időközben eltűnhetett
            self._info(f"A forrásfájl eltűnt: {src}", warn=True)
            self.queue.pop(self.idx)
            self.idx = min(self.idx, max(0, len(self.queue) - 1))
            self._render_preview()
            return

        rules = self._rules()
        folder = os.path.join(self.parent_dir, dir_name,
                              target_subdir(self.doc_type.get(), rules,
                                            self.arckep_kesz.get()))
        r = doc_type_rule(self.doc_type.get(), rules)
        stamp = (dir_name, self.doc_type.get(), r.id if r else "",
                 os.path.basename(folder))
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError as e:
            self._info(f"A célmappa nem hozható létre: {e}", warn=True)
            return
        job = dict(src=src, dir_name=dir_name, sub=os.path.basename(folder),
                   doc_type=self.doc_type.get(),
                   name=target_name(dir_name, self.doc_type.get(), self.suffix.get(),
                                    photo=bool(r and r.arckep and self.arckep_kesz.get())),
                   size=os.path.getsize(src), collision=False, overwritten=False,
                   backup=None, shrunk=None, stamp=stamp, data=None, page=None,
                   pages=None)
        if self._by_page():                    # csak a LÁTOTT oldal megy
            try:
                job["data"] = extract_page(src, self.page_no)
            except Exception as e:
                self._info(f"Az oldal nem emelhető ki: {e}", warn=True)
                return
            job["page"] = self.page_no
            job["pages"] = 1
            job["size"] = len(job["data"])
        shrink = False
        if job["size"] > UPLOAD_LIMIT:
            shrink = messagebox.askyesnocancel(
                "5 MB feletti fájl",
                f"{os.path.basename(src)}: {mb(job['size'])}\n"
                f"A feltöltési korlát {mb(UPLOAD_LIMIT)}.\n\n"
                "Tömörítsem iktatás előtt? (A forrásfájl változatlan marad.)\n\n"
                "Igen = tömörítve · Nem = változatlanul · Mégse = megszakítás")
            if shrink is None:
                self._info("Megszakítva — nem történt másolás.")
                return
        try:
            if os.path.exists(os.path.join(folder, job["name"])):
                choice = self._ask_collision(job["name"])
                if choice == "cancel":
                    self._info("Megszakítva — nem történt másolás.")
                    return
                if choice == "new":
                    job["name"], job["collision"] = unique_name(folder, job["name"])
                else:                     # felülírás: előzetes törlés NINCS, az os.replace
                    job["overwritten"] = True   # atomi; az előző példány a .eredeti\-be kerül
            job["dst"] = os.path.join(folder, job["name"])
            check_path_len(job["dst"])
            if job["overwritten"]:
                job["backup"] = backup_existing(job["dst"])
            if shrink:
                data = job["data"]
                if data is None:
                    with open(src, "rb") as f:
                        data = f.read()
                self._busy = True
                shrink_process(self, data,
                               on_step=lambda dpi, q: self._info(
                                   f"Tömörítés… {dpi} DPI, Q{q} "
                                   "(külön folyamatban, a felület él)"),
                               on_done=lambda out, step, err: self._shrink_done(
                                   job, out, step, err))
                return
            if job["data"] is not None:        # kiemelt oldal: bájtok a memóriából
                write_pdf_verified(job["data"], job["dst"], 1, stamp)
                self.stamped = True
            else:
                self._copy_verified(src, job["dst"], stamp)
        except Exception as e:
            self._copy_failed(job, e)
            return
        self._copied(job)

    def _shrink_done(self, job, data, step, err):
        """A lépcsőzetes tömörítés vége: ellenőrzött kiírás, majd a szokásos lezárás."""
        self._busy = False
        try:
            if err:
                raise err
            pages = job.get("pages")
            if pages is None:
                d = pymupdf.open(job["src"])
                pages = d.page_count
                d.close()
            write_pdf_verified(data, job["dst"], pages, job["stamp"])
        except Exception as e:
            self._copy_failed(job, e)
            return
        job["shrunk"] = (len(data), step)
        self._copied(job)

    def _copy_failed(self, job, e):
        traceback.print_exception(e)
        if job["backup"] and os.path.exists(job["backup"]):
            try:
                os.remove(job["backup"])        # a cél érintetlen maradt, a másolat felesleges
            except OSError:
                pass
        self._log(job["src"], os.path.join(job["dir_name"], job["sub"]), job["name"],
                  "HIBA: " + str(e)[:120], job["doc_type"])
        self._info(f"Hiba: {type(e).__name__}: {e}", warn=True)
        messagebox.showerror("A másolás nem sikerült", f"{type(e).__name__}: {e}")

    def _copied(self, job):
        src, name = job["src"], job["name"]
        self.last_copy = (src, job["dst"], job["backup"])
        result = "UTKOZES-UJ NEV" if job["collision"] else \
            ("FELULIRVA" if job["overwritten"] else "OK")
        if job["backup"]:
            result += " (elozo: " + DIR_PREP + ")"
        if job["shrunk"]:
            new_size, step = job["shrunk"]
            result += f" TOMORITVE {mb(job['size'])}->{mb(new_size)}"
            if step is None:
                messagebox.showwarning(
                    "Tömörítés",
                    f"A legerősebb tömörítés után is {mb(new_size)} maradt — "
                    f"a feltöltési korlát ({mb(UPLOAD_LIMIT)}) fölött.\n\n"
                    "Érdemes kevesebb oldalra bontani (Összeállító fül).")
        forras = src if job["page"] is None else src + f" [{job['page'] + 1}]"
        self._log(forras, os.path.join(job["dir_name"], job["sub"]), name,
                  result, job["doc_type"])
        kesz_uzenet = ""
        if job["page"] is not None:
            # Oldalmód: a fájl a sorban MARAD, amíg van el nem osztott oldala.
            done = self.done_pages.setdefault(src, set())
            done.add(job["page"])
            self.last_page = (src, job["page"])
            if self._next_page():
                kesz_uzenet = (f" · {len(done)}/{self.page_count} oldal kész, "
                               f"következő: {self.page_no + 1}.")
            else:
                kesz_uzenet = f" · mind a {self.page_count} oldal elosztva"
                if src in self.queue:
                    self.queue.pop(self.queue.index(src))
                    self.idx = min(self.idx, max(0, len(self.queue) - 1))
                    self.page_no = 0
        elif src in self.queue:              # tömörítés közben a sor mozoghatott
            i = self.queue.index(src)
            self.queue.pop(i)
            if i < self.idx:
                self.idx -= 1
            self.idx = min(self.idx, max(0, len(self.queue) - 1))
            self.page_no = 0
        self._render_preview()           # a nézet marad, ahol volt
        if job["collision"]:
            self._info("⚠ ÜTKÖZÉS: a mappában már volt ilyen nevű fájl — "
                       "az új példány neve: " + name, warn=True)
            messagebox.showwarning(
                "Névütközés",
                "A mappában már volt ilyen nevű fájl.\n\n"
                "Az új példány neve:\n" + name)
        else:
            self._info(f"✔ {job['dir_name']}\\{job['sub']} → {name}" +
                       (f" (felülírva, az előző: {DIR_PREP}\\)" if job["overwritten"] else "") +
                       (f" · tömörítve: {mb(job['size'])} → {mb(job['shrunk'][0])}"
                        if job["shrunk"] else "") +
                       ("" if self.stamped else " · bélyeg nélkül") +
                       kesz_uzenet, ok=True)

    def _ask_collision(self, name):
        """new | overwrite | cancel — alapértelmezés az új név."""
        win = tk.Toplevel(self)
        win.title("A fájl már létezik")
        win.transient(self.winfo_toplevel())
        win.resizable(False, False)
        win.grab_set()
        res = {"v": "cancel"}

        ttk.Label(win, text="Ez a fájl már ott van a mappában:",
                  font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=14,
                                                     pady=(14, 2))
        ttk.Label(win, text=name, foreground=COL_WARN).pack(anchor="w", padx=14)
        ttk.Label(win, wraplength=420, justify="left",
                  text="Az Új néven gomb a meglévőt meghagyja, és (2), (3) … "
                       "sorszámmal menti az újat. Felülírásnál az előző példány a "
                       "mappa .eredeti almappájába kerül, és a Visszavonás visszahozza."
                  ).pack(anchor="w", padx=14, pady=8)

        row = ttk.Frame(win)
        row.pack(fill="x", padx=14, pady=(0, 14))

        def pick(v):
            res["v"] = v
            win.destroy()

        b = ttk.Button(row, text="Új néven (2)", command=lambda: pick("new"))
        b.pack(side="left")
        b.focus_set()
        ttk.Button(row, text="Felülírás",
                   command=lambda: pick("overwrite")).pack(side="left", padx=8)
        ttk.Button(row, text="Mégsem",
                   command=lambda: pick("cancel")).pack(side="right")
        win.bind("<Return>", lambda e: pick("new"))
        win.bind("<Escape>", lambda e: pick("cancel"))
        win.wait_window()
        return res["v"]

    def _copy_verified(self, src, dst, stamp=None):
        """Másolás .part néven, ellenőrzés, bélyegzés, majd atomi átnevezés.
        A másolás továbbra is bájtazonos, a bélyeg NÖVEKMÉNYES függelék — a
        forrás bájtjai a célban is megvannak (13.5). Ha a bélyegzés nem megy,
        tiszta másolat kerül ki: a bélyeg kényelmi adat, nem iktatási feltétel."""
        tmp = dst + ".part"
        total = os.path.getsize(src)
        self.stamped = bool(stamp)
        try:
            if total > BIG_FILE:
                done = 0
                with open(src, "rb") as fi, open(tmp, "wb") as fo:
                    while True:
                        buf = fi.read(1024 * 1024)
                        if not buf:
                            break
                        fo.write(buf)
                        done += len(buf)
                        self._info(f"Másolás… {done * 100 // total}%")
                        self.update_idletasks()
                shutil.copystat(src, tmp)
            else:
                shutil.copy2(src, tmp)

            if os.path.getsize(tmp) != total:
                raise IOError("A másolat mérete eltér a forrásétól.")
            d = pymupdf.open(tmp)                  # olvasható PDF lett?
            n = d.page_count
            d.close()
            if n < 1:
                raise IOError("A másolat nem nyitható meg PDF-ként.")
            if stamp and not stamp_pdf_file(tmp, *stamp):
                shutil.copy2(src, tmp)                 # bélyeg nélkül, de hibátlanul
                self.stamped = False
            os.replace(tmp, dst)
        except Exception:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            raise

    def _undo(self):
        if self._busy:
            self._info("Előbb várd meg a folyamatban lévő tömörítést.", warn=True)
            return
        if not self.last_copy:
            self._info("Nincs mit visszavonni.", warn=True)
            return
        src, dst, backup = self.last_copy
        in_place = os.path.normcase(os.path.abspath(src)) == os.path.normcase(os.path.abspath(dst))
        if in_place and not (backup and os.path.exists(backup)):
            self._info("Helyben felülírt fájl nem vonható vissza (az eredeti nincs meg).",
                       warn=True)
            return
        try:
            undo_copy(dst, backup)
        except OSError as e:
            self._info(f"A visszavonás nem sikerült: {e}", warn=True)
            return
        self.last_copy = None
        if self.last_page:                         # oldalmód: az oldal újra osztható
            psrc, page = self.last_page
            self.done_pages.get(psrc, set()).discard(page)
            self.last_page = None
            if psrc in self.queue:
                self.idx = self.queue.index(psrc)
            elif os.path.isfile(psrc):             # az utolsó oldal után kikerült
                self.queue.insert(self.idx, psrc)
            self.page_no = page
            self._render_preview()
        elif os.path.isfile(src) and src not in self.queue:
            self.queue.insert(self.idx, src)       # vissza a sorba
            self._render_preview()
        self._log(src, os.path.basename(os.path.dirname(dst)),
                  os.path.basename(dst), "VISSZAVONVA" + (" (elozo visszaallitva)" if backup else ""))
        self._info(f"Visszavonva: {os.path.basename(dst)} " +
                   ("— az előző példány visszaállítva." if backup else "törölve."))

    # ---------------- napló és üzenet ----------------
    def _log(self, src, folder, name, result, doc_type=None):
        log_row(self.parent_dir, src, folder, name,
                self.doc_type.get() if doc_type is None else doc_type, result)

    def _info(self, txt, warn=False, ok=False):
        self.msg.set(txt)
        try:
            self.msg_lbl.configure(
                foreground=COL_WARN if warn else (COL_OK if ok else ""))
        except Exception:
            pass
        if hasattr(self.app, "status"):
            self.app.status(txt)



# ──────────────────────────── 6. fül: áttekintő ────────────────────────────
# Mely dolgozónál melyik irat van meg, és ki adható be. CSAK OLVAS: kizárólag
# fájlneveket (és a PDF-ek méretét) vizsgál. A szabályok az attekinto-szabalyok.json-ban.
SETTINGS_FILE = "attekinto-szabalyok.json"


# ── irattípus-szabály ───────────────────────────────────────────────────────
@dataclass
class Rule:
    id: str
    name: str
    short: str
    all_of: list = field(default_factory=list)   # MIND a kulcsszó kell
    any_of: list = field(default_factory=list)   # ELÉG az egyik
    required: bool = False                       # a beadhatóságot ez dönti el
    generated: bool = False                      # készül-e belőle .docx
    width: int = 56                              # oszlopszélesség képpontban
    # Arcképet is kell rá helyezni: aláírva még nem feltölthető, csak előkészített.
    # A width UTÁN van, mert a DEFAULT_RULES egy helyen pozicionálisan adja meg.
    arckep: bool = False


DEFAULT_RULES = [
    # ── KÖTELEZŐ ────────────────────────────────────────────────────────────
    Rule("forma", "Aláírt formanyomtatvány", "Forma",
         [], ["formanyomtatvany"], True, True, arckep=True),
    Rule("elozetes", "Előzetes megállapodás", "Előz",
         [], ["elozetes megallapodas", "elozetes probaido", "elozetes"],
         True, True),
    Rule("elismer", "Nyilatkozat feltöltött dokumentumok elismeréséről", "Elism",
         [], ["elismeres", "elfogado"], True, True),
    Rule("hozzaj", "Egyoldalú hozzájárulási nyilatkozat", "Hozzá",
         [], ["hozzajarulasi", "hozzajarulas"], True, True),
    Rule("meghat", "Meghatalmazás", "Megh",
         [], ["meghatalmazas"], True, True),
    Rule("utlevel", "Útlevél", "Útl",
         [], ["utlevel", "passport"], True, False),
    # ── AJÁNLOTT / ESETI ────────────────────────────────────────────────────
    Rule("szallv", "Nyilatkozat szálláshely változatlanságáról", "SzVált",
         ["szallashely", "valtozatlansag"], [], False, True, 62),
    Rule("szalli", "Szálláshely-igazolás", "SzIg",
         [], ["szallashely igazolas", "szallasado"], False, False),
    Rule("vegzett", "Végzettséget igazoló okirat", "Végz",
         [], ["vegzettseg", "diploma", "bizonyitvany"], False, False),
    Rule("nav", "NAV jövedelemigazolás", "NAV",
         [], ["re:\\bnav\\b", "jovedelemigazolas nav"], False, False),
    Rule("munkalt", "Hat havi munkáltatói jövedelemigazolás", "Munk",
         [], ["munkaltatoi"], False, False),
    # A DocGen tölti ki (NEAK NYT.52), aláírás nélkül kész, egyenesen a 02-be megy
    # (DocGen/TERV-pdf-nyomtatvany.md). .docx-e nincs, mégis „generated”: a jelző
    # itt azt dönti el, hogy szkennelt irat-e (akkor kerül az Összeállító
    # palettájára) — ez soha nem az. Az „aláírt” utótag csak kézi iktatásnál
    # számítana, és ezt az iratot senki nem iktatja kézzel.
    Rule("taj", "TAJ-megrendelő (NEAK NYT.52)", "TAJ",
         [], ["nyt 52", "taj megrendelo"], False, True),
    # A TAJ-igénylés másik két irata (a DocGen pdf-sablonjai): a „taj meghatalmazas”
    # hosszabb kulcsszóként nyer a „meghat” szabály „meghatalmazas”-a ellen.
    Rule("tajigeny", "TAJ-igénylőlap (NEAK NYT.53)", "TAJ-Ig",
         [], ["nyt 53", "taj igenylolap"], False, True),
    Rule("tajmeghat", "TAJ-meghatalmazás", "TAJ-Mh",
         [], ["taj meghatalmazas"], False, True),
]

# A mentett szabályfájl az alapszabályokat EGÉSZBEN felülírja, a frissítő pedig
# soha nem írja felül — így egy később született alapszabály az éles gépen nem
# jelenne meg. Ezért: amit a fájl még nem ismert, az hozzáadódik; amit ismert, de
# a felhasználó törölt, az nem jön vissza. Az „ismert” a fájl `ismert_alapok`
# kulcsa (mentéskor a mostani alapszabályok); régi fájlban ez a lista hiányzik,
# ott a „taj” előtti állapot számít ismertnek.
RULES_BEFORE_TAJ = ("forma", "elozetes", "elismer", "hozzaj", "meghat", "utlevel",
                    "szallv", "szalli", "vegzett", "nav", "munkalt")

# Az arckép-jelölő később született, mint az első szabályfájlok: ha a mentett
# fájlban nincs ez a kulcs, innen jön az alapértelmezés (load_settings).
DEFAULT_ARCKEP = {r.id: r.arckep for r in DEFAULT_RULES}

NOISE_EXACT = {"thumbs.db", "desktop.ini", ".ds_store",
               "iktato-naplo.csv", "iktato-doktipusok.json"}

# ── a mátrix színei (a palettából, hogy a két rajzolás ne csússzon szét) ────
C_BG = UI["card"]
C_GRID = UI["line"]
C_HDR = "#eef2f8"
C_HDR_OPT = "#f7f9fc"
C_TEXT = UI["ink"]
C_MUTED = "#98a2b3"
C_P = "#d4f2de"            # kész (feltölthető)
C_D = "#fdeec8"            # előkészített
C_DP = "#bde9cb"           # mindkettő
C_NONE = "#f7f9fc"
C_AMB = "#ffe2bd"          # kétértelmű
C_BIG = "#ffd9dc"          # 5 MB feletti (nem feltölthető) PDF
C_UNSORTED = "#e6dffb"     # besorolatlan: se 01_Elokeszitett, se 02_Feltoltheto
C_ROW_ALT = "#fbfcfe"
C_SEL = UI["accent_bg"]
C_CUR = UI["accent"]
C_OK = UI["ok"]
C_WARN = UI["warn"]

ROW_H = 24
ROW_BUFFER = 14            # ennyi sort rajzolunk a látható sávon túl (13.10)
HDR_PAD_TOP = 18          # a „KÖTELEZŐ / ajánlott” sávnak
HDR_PAD_BOT = 5
HDR_LINE = 12             # egy fejlécsor magassága
CELL_PAD = 6              # vízszintes belső margó a fejlécben
W_SMALL = 46
W_READY = 66
MIN_COL_W = 30
MAX_COL_W = 260


# ── beállítások ─────────────────────────────────────────────────────────────
def settings_path() -> str:
    return os.path.join(script_dir(), SETTINGS_FILE)


def default_settings() -> dict:
    return {
        "rules": [asdict(r) for r in DEFAULT_RULES],
        "ismert_alapok": [r.id for r in DEFAULT_RULES],
        "name_width": 200,
        "scan_depth": 1,          # 0 = csak a dolgozó mappája; 1..3 = almappák
        "row_height": ROW_H,
        "header_lines": 3,        # hány sorban törhet a teljes név
    }


def load_settings() -> dict:
    s = default_settings()
    try:
        with open(settings_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return s
    if isinstance(data.get("rules"), list) and data["rules"]:
        out = []
        for d in data["rules"]:
            try:
                out.append(Rule(
                    id=str(d["id"]), name=str(d["name"]), short=str(d["short"]),
                    all_of=[str(x) for x in d.get("all_of", []) if str(x).strip()],
                    any_of=[str(x) for x in d.get("any_of", []) if str(x).strip()],
                    required=bool(d.get("required", False)),
                    generated=bool(d.get("generated", False)),
                    width=max(MIN_COL_W, min(MAX_COL_W, int(d.get("width", 56)))),
                    # Kulcs nélküli (régi) szabályfájlnál NEM False: különben a
                    # fotó nélküli formanyomtatvány a feltölthetőbe kerülne.
                    arckep=bool(d.get("arckep",
                                      DEFAULT_ARCKEP.get(str(d["id"]), False))),
                ))
            except Exception:
                continue
        if out:
            ismert = set(data.get("ismert_alapok", RULES_BEFORE_TAJ))
            van = {r.id for r in out}
            out += [r for r in DEFAULT_RULES if r.id not in van and r.id not in ismert]
            s["rules"] = [asdict(r) for r in out]
    for k, lo, hi in (("name_width", 80, 500), ("scan_depth", 0, 3),
                      ("row_height", 16, 48), ("header_lines", 1, 4)):
        try:
            s[k] = max(lo, min(hi, int(data.get(k, s[k]))))
        except Exception:
            pass
    return s


def save_settings(s: dict) -> bool:
    try:
        with open(settings_path(), "w", encoding="utf-8") as f:
            json.dump(s, f, ensure_ascii=False, indent=2)
        return True
    except OSError:
        return False


def rules_from(settings: dict) -> list:
    return [Rule(**d) for d in settings["rules"]]


# ── felismerés ──────────────────────────────────────────────────────────────
# ── fejléctördelés ──────────────────────────────────────────────────────────
def ellipsize(s: str, maxw: int, measure) -> str:
    """Egy sor levágása három ponttal, ha nem fér ki."""
    if measure(s) <= maxw:
        return s
    t = s
    while t and measure(t + "…") > maxw:
        t = t[:-1]
    return (t + "…") if t else ""


def fit_header(name: str, short: str, maxw: int, measure, max_lines=3) -> list:
    """A TELJES nevet tördeli az oszlopszélességhez.

    Szavanként tör; ami így sem fér ki, azt levágja. Egyetlen visszaadott sor
    sem lóghat túl a `maxw` szélességen — ez a garancia.
    """
    words = (name or "").split()
    if not words or maxw < 12:
        return [ellipsize(short or "?", maxw, measure)]
    lines, cur = [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if measure(t) <= maxw:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w                      # a szó önmagában is túllóghat
        if len(lines) >= max_lines:
            break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    if not lines:
        lines = [words[0]]
    truncated = len(" ".join(lines).split()) < len(words)
    out = [ellipsize(l, maxw, measure) for l in lines[:-1]]
    last = lines[-1]
    if truncated and measure(last + "…") <= maxw:
        last = last + "…"
    else:
        last = ellipsize(last + ("…" if truncated else ""), maxw, measure)
    out.append(last)
    out = [l for l in out if l]
    return out or [ellipsize(short, maxw, measure)]


def norm(s: str) -> str:
    """Fájlnév egységesítése az összehasonlításhoz."""
    s = unicodedata.normalize("NFC", s)
    s = strip_accents(s)
    s = re.sub(r"\(\d+\)", " ", s)                  # (2), (3) ütközés-sorszám
    # A jelölők nem részei az azonosításnak. A „kesz” a régi _kesz utótag.
    s = re.sub(r"\b(alairt|signed|fotoval ellatva|kesz)\b", " ", s)
    s = re.sub(r"\(\s*,?\s*\)", " ", s)             # a jelölőktől kiürült zárójel
    s = re.sub(r"[_\-.\u2013\u2014]+", " ", s)      # elválasztók (a gondolatjel is) szóközzé
    return re.sub(r"\s+", " ", s).strip()


def kw_hit(n: str, kw: str) -> bool:
    """Kulcsszó keresése. 're:' előtaggal reguláris kifejezés."""
    kw = kw.strip()
    if not kw:
        return False
    if kw.startswith("re:"):
        try:
            return re.search(kw[3:], n) is not None
        except re.error:
            return False
    return strip_accents(kw) in n


def score(n: str, rule: Rule) -> int:
    """0 = nem illeszkedik. Nagyobb pont = specifikusabb egyezés."""
    if rule.all_of and not all(kw_hit(n, k) for k in rule.all_of):
        return 0
    if rule.any_of and not any(kw_hit(n, k) for k in rule.any_of):
        return 0
    hits = [k for k in list(rule.all_of) + list(rule.any_of) if kw_hit(n, k)]
    if not hits:
        return 0
    return sum(len(strip_accents(k)) for k in hits) + 10 * len(hits)


def match_rule(filename: str, rules: list):
    """(Rule|None, kétes?) — a legtöbb pontot elérő szabály nyer."""
    n = norm(os.path.splitext(os.path.basename(filename))[0])
    scored = [(score(n, r), r) for r in rules]
    scored = [(s, r) for s, r in scored if s > 0]
    if not scored:
        return None, False
    best = max(s for s, _ in scored)
    winners = [r for s, r in scored if s == best]
    return winners[0], len(winners) > 1


def doc_type_rule(doc_type: str, rules: list):
    """Az Iktató doktípusához tartozó Áttekintő-szabály (kétértelműnél None).
    Ugyanaz az illesztés, ami a palettát is sorba rakja (palette_types)."""
    r, amb = match_rule(target_name("X", doc_type), rules)
    return None if amb else r


def target_subdir(doc_type: str, rules: list, arckep_kesz: bool = False) -> str:
    """Hova iktatunk a dolgozó mappáján belül. Alapból 02_Feltoltheto — kivéve a
    fotót igénylő nyomtatványt, amelyen a fotó még nincs rajta: az aláírva sem
    feltölthető, tehát 01_Elokeszitett. Téves 01 csak annyit mond, hogy még nincs
    kész; téves 02 aláírás/fotó nélküli iratot mondana beadhatónak."""
    r = doc_type_rule(doc_type, rules)
    if r is not None and r.arckep and not arckep_kesz:
        return DIR_PREP
    return DIR_UP


def ensure_work_dirs(worker_folder: str) -> list:
    """A 01/02 alkönyvtár létrehozása, ha hiányzik. -> a létrehozottak nevei."""
    made = []
    for d in WORK_DIRS:
        p = os.path.join(worker_folder, d)
        if not os.path.isdir(p):
            os.makedirs(p, exist_ok=True)
            made.append(d)
    return made


def file_loc(rel: str) -> str:
    """Egy relatív út helye a dolgozó mappáján belül: "E" (előkészített),
    "F" (feltölthető) vagy "~" (besorolatlan: gyökér vagy más almappa)."""
    head = rel.split(os.sep)[0] if os.sep in rel else ""
    if head == DIR_PREP:
        return "E"
    if head == DIR_UP:
        return "F"
    return "~"


def is_noise(name: str) -> bool:
    """Amit nem tekintünk iratnak."""
    base = os.path.basename(name)
    low = base.lower()
    if low in NOISE_EXACT:
        return True
    if base.startswith("~$"):                       # Word zárolófájl
        return True
    if low.endswith(".part"):                       # iktató félkész másolata
        return True
    if low.startswith("docgen-") and low.endswith(".json"):
        return True
    if low.startswith("attekinto-"):
        return True
    if strip_accents(MARK_BACKUP) in strip_accents(base):
        return True            # „(előző példány …)”: felülírás mentése, nem irat
    return False


# ── adatmodell ──────────────────────────────────────────────────────────────
@dataclass
class DocState:
    docx: list = field(default_factory=list)
    pdf: list = field(default_factory=list)
    ambiguous: bool = False
    # Hol vannak a fájlok: "E" (01_Elokeszitett), "F" (02_Feltoltheto),
    # "~" (besorolatlan: a dolgozó gyökerében vagy más almappában).
    loc: set = field(default_factory=set)

    @property
    def cell(self) -> str:
        """A hely mondja meg, mi van kész — nem a kiterjesztés. A docx/pdf tény a
        tooltipben van (kepek-pdf-terv.md 12.3)."""
        if self.ambiguous:
            return "?"
        s = ("E" if "E" in self.loc else "") + ("F" if "F" in self.loc else "")
        if s:
            return s
        return "~" if "~" in self.loc else "·"


@dataclass
class PersonRow:
    name: str
    folder: str
    docs: dict
    rules: list
    photos: list = field(default_factory=list)
    extra_pdfs: list = field(default_factory=list)
    other: list = field(default_factory=list)
    big: dict = field(default_factory=dict)      # 5 MB feletti PDF-ek: rel. út -> méret
    # Bélyeg-alapú felismerés (13.5): amit a NÉV nem adott meg, de a bélyeg igen,
    # és amin MÁS dolgozó bélyege van (eltévedt irat).
    by_stamp: list = field(default_factory=list)
    foreign: list = field(default_factory=list)   # [(rel. út, a bélyeg dolgozója)]
    subdirs: int = 0
    error: str = None

    def _req(self):
        return [r for r in self.rules if r.required]

    def _opt(self):
        return [r for r in self.rules if not r.required]

    def _ok(self, r) -> bool:
        """Van-e ehhez a típushoz FELTÖLTHETŐ (korlát alatti) PDF a
        02_Feltoltheto mappában. A gyökérben vagy az előkészítettben lévő PDF nem
        számít: nem tudjuk róla, hogy aláírt-e (kepek-pdf-terv.md 12.3)."""
        return any(p not in self.big and file_loc(p) == "F"
                   for p in self.docs[r.id].pdf)

    @property
    def ready_required(self) -> int:
        return sum(1 for r in self._req() if self._ok(r))

    @property
    def ready_optional(self) -> int:
        return sum(1 for r in self._opt() if self._ok(r))

    @property
    def beadhato(self) -> bool:
        req = self._req()
        return bool(req) and self.ready_required == len(req)

    @property
    def to_print(self) -> list:
        """Nyomtatandó: van előkészített példány, feltölthető még nincs. Pontosabb a
        korábbi „docx van, PDF nincs”-nél, mert a nyomtatandó DocGen-PDF-et is
        elkapja (kepek-pdf-terv.md 12.3)."""
        return [r.name for r in self.rules
                if "E" in self.docs[r.id].loc and "F" not in self.docs[r.id].loc]

    @property
    def missing_required(self) -> list:
        return [r.name for r in self._req()
                if r.generated and not self.docs[r.id].loc]

    @property
    def to_obtain(self) -> list:
        return [r.name for r in self._req()
                if not r.generated and "F" not in self.docs[r.id].loc]

    @property
    def unsorted(self) -> list:
        """Besorolatlan fájlok: se 01_Elokeszitett, se 02_Feltoltheto. -> relatív utak"""
        out = []
        for st in self.docs.values():
            out += [p for p in st.pdf + st.docx if file_loc(p) == "~"]
        out += [p for p in self.extra_pdfs + self.photos + self.other
                if file_loc(p) == "~"]
        return sorted(set(out))

    @property
    def duplicates(self) -> list:
        """Irattípusok, amelyekhez több FELTÖLTHETŐ PDF is van — feltöltéskor melyik
        a jó? -> [(típusnév, [fájlok])]
        Csak a 02_Feltoltheto számít: az előkészített és az aláírt példány együtt a
        normális állapot (EF cella), nem kétely."""
        out = []
        for r in self.rules:
            up = [p for p in self.docs[r.id].pdf if file_loc(p) == "F"]
            if len(up) > 1:
                out.append((r.name, up))
        return out

    @property
    def ambiguous_files(self) -> list:
        out = []
        for r in self.rules:
            d = self.docs[r.id]
            if d.ambiguous:
                out.extend(d.pdf + d.docx)
        return out


def walk_files(root: str, depth: int) -> list:
    """Fájlok relatív úttal, legfeljebb `depth` almappa-szint mélyen."""
    out = []
    base = os.path.abspath(root)
    for dirpath, dirnames, filenames in os.walk(root):
        rel = os.path.relpath(dirpath, base)
        d = 0 if rel == "." else rel.count(os.sep) + 1
        if d > depth:
            dirnames[:] = []
            continue
        dirnames[:] = [x for x in dirnames if not x.startswith(".")]
        for f in filenames:
            out.append(f if rel == "." else os.path.join(rel, f))
    return out


def scan_person(folder: str, name: str, rules: list, depth: int) -> PersonRow:
    docs = {r.id: DocState() for r in rules}
    row = PersonRow(name=name, folder=folder, docs=docs, rules=rules)
    try:
        files = walk_files(folder, depth)
        # A 01/02 a szabványos szerkezet, nem „extra almappa” — csak a többit jelezzük.
        row.subdirs = sum(1 for e in os.scandir(folder)
                          if e.is_dir() and not e.name.startswith(".")
                          and e.name not in WORK_DIRS)
    except OSError as e:
        row.error = str(e)
        return row

    for rel in files:
        if is_noise(rel):
            continue
        ext = os.path.splitext(rel)[1].lower()
        if ext in IMG_EXT:
            row.photos.append(rel)
            continue
        if ext not in (".pdf", ".docx"):
            row.other.append(rel)
            continue
        if ext == ".pdf":
            try:
                n = os.path.getsize(os.path.join(folder, rel))
            except OSError:
                n = 0
            if n > UPLOAD_LIMIT:
                row.big[rel] = n
        rule, amb = match_rule(rel, rules)
        if rule is None and ext == ".pdf":
            # Átnevezett irat: a fájlnév nem ismerhető fel, a bélyeg igen. Csak itt
            # nyitjuk meg a PDF-et — a felismert nevűeknél nincs rá ok (13.5).
            st_info = read_stamp(os.path.join(folder, rel))
            if st_info:
                if strip_accents(st_info.get("dolgozo", "")) != strip_accents(name):
                    row.foreign.append((rel, st_info.get("dolgozo") or "?"))
                rule = next((r for r in rules if r.id == st_info.get("szabaly")), None)
                if rule is None and st_info.get("tipus"):
                    rule, amb = match_rule(target_name(name, st_info["tipus"]), rules)
                if rule is not None:
                    row.by_stamp.append(rel)
        if rule is None:
            if ext == ".pdf":
                row.extra_pdfs.append(rel)
            else:
                row.other.append(rel)
            continue
        st = docs[rule.id]
        if ext == ".docx":
            st.docx.append(rel)
            if not rule.generated:          # ebből sosem lesz docx -> gyanús
                st.ambiguous = True
        else:
            st.pdf.append(rel)
        st.loc.add(file_loc(rel))
        if amb:
            st.ambiguous = True
    return row


def scan(parent: str, rules: list, depth: int = 1) -> list:
    rows = []
    with os.scandir(parent) as it:
        for entry in it:
            if entry.is_dir() and not entry.name.startswith("."):
                rows.append(scan_person(entry.path, entry.name, rules, depth))
    return sorted(rows, key=lambda r: _sort_key(r.name))


# ── egyszeri rendezés a két alkönyvtárba (kepek-pdf-terv.md 12.6) ───────────
def has_docgen_stamp(path: str) -> bool:
    """Van-e a PDF-en DocGen-bélyeg. A bélyeg jelenléte bizonyítja, hogy generált
    (tehát még nem aláírt); a HIÁNYA azt, hogy szkennerből jött."""
    try:
        d = pymupdf.open(path)
    except Exception:
        return False
    try:
        m = d.metadata or {}
    finally:
        d.close()
    return ("docgen" in (m.get("producer") or "").lower()
            or "docgen" in (m.get("keywords") or "").lower())


def is_worker_folder(folder: str, rules: list, depth: int = 3) -> bool:
    """Bizonyíték, hogy ez a mappa EBBEN a folyamatban dolgozói mappa. A Rendezés
    csak ilyenben mozgat — enélkül egy tévesen kiválasztott munkamappában (pl. a
    Letöltések vagy egy képmappa) a Rendezés minden képet elmozgatna, mert a
    képeket szabály-illesztés nélkül sorolja be. A mozgatás nem visszavonható,
    tehát nem elég az előnézet emberi átolvasására bízni.

    Három elfogadott jel:
      * már van benne 01_Elokeszitett vagy 02_Feltoltheto
      * van benne legalább egy irat, ami illeszkedik egy szabályra
      * teljesen üres (frissen létrehozott dolgozói mappa: nincs is mit mozgatni)
    """
    try:
        if any(os.path.isdir(os.path.join(folder, d)) for d in WORK_DIRS):
            return True
        files = walk_files(folder, depth)
    except OSError:
        return False
    if not [f for f in files if not is_noise(f)]:
        return True                                  # üres: ártalmatlan
    return any(match_rule(rel, rules)[0] is not None for rel in files
               if not is_noise(rel)
               and os.path.splitext(rel)[1].lower() in (".pdf", ".docx"))


def name_is_signed(rel: str) -> bool:
    """Látszik-e a néven, hogy aláírt példány. A norm() ezt a szót szándékosan
    kitörli (az illesztéshez), ezért itt strip_accents-szel nézzük."""
    low = strip_accents(os.path.basename(rel))
    return any(k in low for k in (strip_accents(MARK_SIGNED), "signed"))


def name_has_photo(rel: str) -> bool:
    """Rajta van-e már az arckép a név szerint. A régi „_kesz” utótag ugyanezt
    jelentette — a visszamenőleges átnevezéshez azt is el kell fogadni."""
    low = strip_accents(os.path.basename(rel))
    return strip_accents(MARK_PHOTO) in low or "_kesz" in low


def rule_type(rule, ikt_types, rules):
    """A szabályhoz tartozó Iktató-doktípus (a fájlnévbe ez kerül), vagy None.
    Ugyanaz az illesztés, ami a típuspalettát is sorba rakja (palette_types)."""
    return next((t for t in ikt_types
                 if match_rule(target_name("X", t), rules) == (rule, False)), None)


def rename_plan(parent: str, rules: list, ikt_types=None, depth: int = 2) -> list:
    """A meglévő iratok átnevezése az egységes metodikára (kepek-pdf-terv.md 14.1).

    -> [(dolgozó, rel, új név, indok, biztos-e)]
    Csak azokat adja vissza, ahol az új név TÉR EL a mostanitól.

    A forrás sorrendje: a **bélyeg** a bizonyíték (oda iktattuk, az a típus), a
    név csak tartalék. Ahol egyik sem dönt — nincs bélyeg és a név sem illeszkedik
    egyértelműen —, ott nem tippelünk: `biztos=False`, és a párbeszéd külön jelzi.
    """
    out = []
    ikt_types = load_types() if ikt_types is None else ikt_types
    for who in worker_dirs(parent):
        folder = os.path.join(parent, who)
        for rel in walk_files(folder, depth):
            if is_noise(rel) or not rel.lower().endswith(".pdf"):
                continue
            path = os.path.join(folder, rel)
            st = read_stamp(path)
            rule, amb = match_rule(rel, rules)
            if st.get("tipus"):
                tipus, indok, biztos = st["tipus"], "bélyeg", True
            elif rule is not None and not amb:
                # A szabály NEVE oszlopcímke („Aláírt formanyomtatvány”), nem
                # dokumentumnév — a fájlnévbe az Iktató doktípusa való. Enélkül
                # „Kiss Anna Aláírt formanyomtatvány (aláírt)…” lenne (mérve).
                tipus = rule_type(rule, ikt_types, rules) or rule.name
                indok, biztos = "felismert név", True
            else:
                out.append((who, rel, None,
                            "se bélyeg, se egyértelmű név — kézzel", False))
                continue
            # Aláírt-e: a bélyeg helye a bizonyíték, a név a tartalék. A nem
            # generált iratra (útlevél, diploma) nem kerül „aláírt” jelölő.
            r = rule if rule is not None else doc_type_rule(tipus, rules)
            generalt = r is None or r.generated
            alairt = (st.get("hely") == DIR_UP) or name_is_signed(rel)
            uj = target_name(who, tipus, MARK_SIGNED if (generalt and alairt) else "",
                             photo=bool(r and r.arckep and name_has_photo(rel)))
            if uj != os.path.basename(rel):
                out.append((who, rel, uj, indok, biztos))
    return out


def rename_apply(parent: str, items) -> tuple:
    """A kiválasztott átnevezések végrehajtása. -> (kész, [(dolgozó\\rel, hiba)])
    Ütközésnél (2), (3) … — soha nem írunk felül meglévő iratot."""
    done, errs = 0, []
    for who, rel, uj, _indok, _biztos in items:
        if not uj:
            continue
        folder = os.path.join(parent, who)
        src = os.path.join(folder, rel)
        dstdir = os.path.dirname(src)
        try:
            cel = os.path.join(dstdir, unique_name(dstdir, uj)[0])
            check_path_len(cel)
            os.rename(src, cel)
            done += 1
        except OSError as e:
            errs.append((os.path.join(who, rel), str(e)))
    return done, errs


def migracio_terv(folder: str, rules: list, depth: int = 3) -> list:
    """Mit hova mozgatnánk egy dolgozó mappájában.
    -> [(relatív út, cél | None, indok, biztos-e)]
    A besorolás ugyanaz a match_rule, ami a mátrixot hajtja — nincs új logika.
    A bizonytalan eset szándékosan 01 felé téved: téves 02 aláírás nélküli iratot
    mondana beadhatónak, a téves 01 csak annyit, hogy még nincs kész."""
    out = []
    for rel in walk_files(folder, depth):
        if is_noise(rel) or file_loc(rel) != "~":
            continue                       # zaj, vagy már a helyén van
        ext = os.path.splitext(rel)[1].lower()
        if ext in IMG_EXT:
            out.append((rel, DIR_PREP, "kép: nyersanyag", True))
            continue
        if ext not in (".pdf", ".docx"):
            out.append((rel, None, "nem irat", True))
            continue
        if ext == ".pdf":
            # A bélyeg bizonyíték, nem tipp: ide iktattuk, tehát ide tartozik —
            # akkor is, ha közben átnevezték (13.5).
            st_info = read_stamp(os.path.join(folder, rel))
            if st_info.get("hely") in WORK_DIRS:
                out.append((rel, st_info["hely"],
                            f"bélyeg: {st_info.get('tipus') or '?'}", True))
                continue
        rule, _amb = match_rule(rel, rules)
        if rule is None:
            out.append((rel, None, "nem ismeri fel egyik szabály sem", True))
            continue
        if ext == ".docx":
            out.append((rel, DIR_PREP, "docx: nyomtatásra vár", True))
            continue
        if has_docgen_stamp(os.path.join(folder, rel)):
            out.append((rel, DIR_PREP, "DocGen-bélyeg: generált, még nem aláírt", True))
        # strip_accents, NEM norm: a norm() szándékosan kitörli az „alairt” szót
        # (a szabályillesztéshez), tehát azzal soha nem találnánk meg.
        elif SUFFIX and strip_accents(SUFFIX) in strip_accents(rel):
            out.append((rel, DIR_UP, f"„{SUFFIX}” utótag: az Iktatón át jött", True))
        else:
            out.append((rel, DIR_PREP,
                        "nincs bélyeg és nincs utótag — tipp", False))
    return out


def migracio_vegrehajt(folder: str, terv: list) -> tuple:
    """A terv mozgatható sorainak végrehajtása. -> (kész, [(rel, hiba)])
    ponytail: nincs visszavonás — egyszeri eszköz, a védelem az előnézet. Ha kell,
    a bővítés útja: naplósor minden mozgatásról + fordított mozgatás belőle."""
    done, errs = 0, []
    for rel, dst, _reason, _sure in terv:
        if dst is None:
            continue
        src = os.path.join(folder, rel)
        target = os.path.join(folder, dst, os.path.basename(rel))
        try:
            check_path_len(target)          # ELŐBB mérünk, nem mozgatás közben
            os.makedirs(os.path.dirname(target), exist_ok=True)
            if os.path.exists(target):
                target = os.path.join(os.path.dirname(target),
                                      unique_name(os.path.dirname(target),
                                                  os.path.basename(target))[0])
            os.replace(src, target)
            done += 1
        except (OSError, ValueError) as e:
            errs.append((rel, str(e)))
    return done, errs


def file_sha1(path: str) -> str:
    """Tartalom-ujjlenyomat: ugyanaz a szkennelt PDF két néven is lehet."""
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def audit_folder(parent: str, rules: list, depth: int = 2, on_step=None) -> dict:
    """A munkamappa minden dolgozói PDF-jének EGYSZERI átnézése: bélyeg és
    tartalom (13.6). Ez az egyetlen hely, ahol minden PDF-et megnyitunk — a
    mátrix szándékosan csak a név szerint fel nem ismerteket nézi meg.
    -> {"stampable": [(dolgozó, rel, út, szabály, alkönyvtár)],
        "misplaced": [(dolgozó, rel, út, szabály)],  # felismert név, rossz hely
        "unknown": [(dolgozó, rel)],            # se bélyeg, se felismert név
        "foreign": [(dolgozó, rel, bélyeg dolgozója)],
        "mismatch": [(dolgozó, rel, bélyeg típusa, név szerinti típus)],
        "dupes": [[(dolgozó, rel), …]], "seen": n}"""
    res = {"stampable": [], "misplaced": [], "unknown": [], "foreign": [],
           "mismatch": [], "dupes": [], "seen": 0}
    by_hash = {}
    for who in worker_dirs(parent):
        folder = os.path.join(parent, who)
        for rel in walk_files(folder, depth):
            if is_noise(rel) or not rel.lower().endswith(".pdf"):
                continue
            path = os.path.join(folder, rel)
            res["seen"] += 1
            if on_step and res["seen"] % 20 == 0:
                on_step(res["seen"])
            st = read_stamp(path)
            rule, amb = match_rule(rel, rules)
            sub = rel.split(os.sep)[0] if os.sep in rel else ""
            if not st:
                # Utólag csak ott bélyegezhetünk, ahol a NÉV és a HELY együtt
                # megadja, mit írjunk — találgatva nem bélyegzünk (13.6).
                if rule is not None and not amb and sub in WORK_DIRS:
                    res["stampable"].append((who, rel, path, rule, sub))
                elif rule is not None and not amb:
                    # A NEVÉT felismerjük, csak nem a 01/02 valamelyikében fekszik
                    # (jellemzően a dolgozói mappa gyökerében). Ez eddig az
                    # „unknown” kosárba esett, és a párbeszéd azt írta rá, hogy a
                    # nevét sem ismerjük fel — ez volt az Áttekintő „hibás adat”
                    # panasz valódi oka. Mérve: 6 teszt-iratból 3 esett ide.
                    res["misplaced"].append((who, rel, path, rule))
                else:
                    res["unknown"].append((who, rel))
            else:
                if strip_accents(st.get("dolgozo", "")) != strip_accents(who):
                    res["foreign"].append((who, rel, st.get("dolgozo") or "?"))
                if rule is not None and st.get("szabaly") and st["szabaly"] != rule.id:
                    res["mismatch"].append((who, rel, st.get("tipus") or "?", rule.name))
            try:
                by_hash.setdefault(file_sha1(path), []).append((who, rel))
            except OSError:
                pass
    res["dupes"] = sorted((v for v in by_hash.values() if len(v) > 1),
                          key=lambda g: g[0])
    return res


def stamp_missing(items) -> tuple:
    """A bélyegezhető iratok utólagos bélyegzése. -> (sikeres, [(út, hiba)])"""
    ok, errs = 0, []
    for who, rel, path, rule, sub in items:
        if stamp_pdf_file(path, who, rule.name, rule.id, sub):
            ok += 1
        else:
            errs.append((os.path.join(who, rel), "a bélyegzés nem sikerült"))
    return ok, errs


def text_rule(path: str, page: int, rules: list):
    """Egy oldal szövegrétegéből a szabály (None, ha nincs szöveg vagy nem
    egyértelmű). Ugyanaz a score(), ami a fájlneveket illeszti — csak az oldal
    ELEJÉT nézzük (ott van a cím), különben egy hosszú irat minden szabályra
    rálicitál. Szkennelt, OCR nélküli lapon nincs szövegréteg: ott None."""
    if not path.lower().endswith(".pdf"):
        return None
    try:
        d = pymupdf.open(path)
        try:
            txt = d[page].get_text() if 0 <= page < d.page_count else ""
        finally:
            d.close()
    except Exception:
        return None
    if len(txt.strip()) < 40:
        return None
    nn = norm(txt[:1500])
    rows = sorted(((score(nn, r), r) for r in rules), key=lambda x: -x[0])
    if not rows or rows[0][0] <= 0:
        return None
    if len(rows) > 1 and rows[1][0] == rows[0][0]:
        return None                       # holtverseny: ne tippeljünk
    return rows[0][1]


def open_path(path: str):
    try:
        if sys.platform == "win32":
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception as e:
        messagebox.showerror("Nem nyitható meg", f"{path}\n\n{e}")


# ── beállítások ablak ───────────────────────────────────────────────────────
class SettingsDialog(tk.Toplevel):
    """Irattípusok és kulcsszavak szerkesztése — élő próbával."""

    def __init__(self, master, settings, on_save):
        super().__init__(master)
        self.title("Áttekintő — beállítások")
        self.transient(master.winfo_toplevel())
        self.grab_set()
        self.geometry("980x680")
        self.minsize(860, 580)
        self.on_save = on_save
        self.base = settings        # a dialógusban nem szereplő kulcsok (header_lines) innen jönnek
        self.rules = rules_from(settings)
        self.gen = {k: settings[k] for k in
                    ("name_width", "scan_depth", "row_height", "header_lines")}
        self.cur = None

        self.v_name = tk.StringVar()
        self.v_short = tk.StringVar()
        self.v_all = tk.StringVar()
        self.v_any = tk.StringVar()
        self.v_req = tk.BooleanVar()
        self.v_gen = tk.BooleanVar()
        self.v_arckep = tk.BooleanVar()
        self.v_width = tk.IntVar(value=56)
        self.v_depth = tk.IntVar(value=self.gen["scan_depth"])
        self.v_namew = tk.IntVar(value=self.gen["name_width"])
        self.v_rowh = tk.IntVar(value=self.gen["row_height"])
        self.v_hdrl = tk.IntVar(value=self.gen["header_lines"])
        self.v_probe = tk.StringVar(
            value="X Y Előzetes próbaidő nélkül_ukran_alairt.pdf")
        self.probe_out = tk.StringVar(value="")
        self.msg = tk.StringVar(value="")

        self._build()
        self._fill()
        if self.rules:
            self.lb.selection_set(0)
            self._select()
        self.bind("<Escape>", lambda e: self.destroy())

    def _build(self):
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=10, pady=10)
        p1 = ttk.Frame(nb)
        p2 = ttk.Frame(nb)
        nb.add(p1, text="Irattípusok és kulcsszavak")
        nb.add(p2, text="Megjelenés és beolvasás")

        left = ttk.Frame(p1)
        left.pack(side="left", fill="y", padx=(8, 4), pady=8)
        ttk.Label(left, text="Irattípusok (sorrend = oszlopsorrend)",
                  font=("Segoe UI", 9, "bold")).pack(anchor="w")
        box = ttk.Frame(left)
        box.pack(fill="both", expand=True, pady=4)
        self.lb = tk.Listbox(box, width=34, height=20, exportselection=False,
                             activestyle="dotbox")
        sb = ttk.Scrollbar(box, orient="vertical", command=self.lb.yview)
        self.lb.configure(yscrollcommand=sb.set)
        self.lb.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.lb.bind("<<ListboxSelect>>", lambda e: self._select())

        r = ttk.Frame(left)
        r.pack(fill="x")
        ttk.Button(r, text="Új", width=5, command=self._new).pack(side="left")
        ttk.Button(r, text="Töröl", width=6,
                   command=self._del).pack(side="left", padx=3)
        ttk.Button(r, text="▲", width=3,
                   command=lambda: self._move(-1)).pack(side="left", padx=(10, 2))
        ttk.Button(r, text="▼", width=3,
                   command=lambda: self._move(1)).pack(side="left")

        right = ttk.Frame(p1)
        right.pack(side="left", fill="both", expand=True, padx=4, pady=8)

        f = ttk.LabelFrame(right, text="A kiválasztott irattípus")
        f.pack(fill="x")
        self._row(f, 0, "Megnevezés:", self.v_name, 52)
        self._row(f, 1, "Oszlopfejléc (rövid):", self.v_short, 14)
        ttk.Label(f, text="Oszlopszélesség:").grid(row=2, column=0, sticky="w",
                                                   padx=8, pady=3)
        ttk.Spinbox(f, from_=MIN_COL_W, to=MAX_COL_W, textvariable=self.v_width,
                    width=6, command=self._apply_cur).grid(row=2, column=1,
                                                           sticky="w", padx=6)
        ttk.Checkbutton(f, text="Kötelező (ez dönti el a beadhatóságot)",
                        variable=self.v_req,
                        command=self._apply_cur).grid(row=3, column=0,
                                                      columnspan=2, sticky="w",
                                                      padx=8)
        ttk.Checkbutton(f, text="Generált (készül belőle .docx a DocGen-ből)",
                        variable=self.v_gen,
                        command=self._apply_cur).grid(row=4, column=0,
                                                      columnspan=2, sticky="w",
                                                      padx=8)
        ttk.Checkbutton(f, text="Arcképet is kell rá helyezni (aláírva sem "
                               "feltölthető, míg nincs rajta fotó)",
                        variable=self.v_arckep,
                        command=self._apply_cur).grid(row=5, column=0,
                                                      columnspan=2, sticky="w",
                                                      padx=8, pady=(0, 6))
        f.columnconfigure(1, weight=1)

        k = ttk.LabelFrame(right, text="Kulcsszavak — vesszővel elválasztva")
        k.pack(fill="x", pady=8)
        ttk.Label(k, text="ELÉG az egyik (any):").grid(row=0, column=0,
                                                       sticky="w", padx=8, pady=3)
        ttk.Entry(k, textvariable=self.v_any, width=64).grid(row=0, column=1,
                                                             sticky="ew", padx=6)
        ttk.Label(k, text="MIND kell (all):").grid(row=1, column=0, sticky="w",
                                                   padx=8, pady=3)
        ttk.Entry(k, textvariable=self.v_all, width=64).grid(row=1, column=1,
                                                             sticky="ew", padx=6)
        k.columnconfigure(1, weight=1)
        ttk.Label(k, justify="left", foreground=C_MUTED, wraplength=560,
                  text="Az összehasonlítás ékezet- és kisbetű-érzéketlen, az "
                       "aláhúzás/kötőjel/pont szóköznek számít, az „aláírt” szó "
                       "és a „(2)” sorszám figyelmen kívül marad.\n"
                       "Több szóból álló kulcsszó is adható: „elozetes probaido”.\n"
                       "Reguláris kifejezés: „re:” előtaggal, pl. re:\\bnav\\b — "
                       "így a Navratil név nem lesz NAV-igazolás."
                  ).grid(row=2, column=0, columnspan=2, sticky="w", padx=8,
                         pady=(4, 8))
        for v in (self.v_any, self.v_all, self.v_name, self.v_short):
            v.trace_add("write", lambda *a: self._apply_cur())

        t = ttk.LabelFrame(right, text="Próba — írj be egy valódi fájlnevet")
        t.pack(fill="both", expand=True)
        ttk.Entry(t, textvariable=self.v_probe).pack(fill="x", padx=8, pady=6)
        self.v_probe.trace_add("write", lambda *a: self._probe())
        ttk.Label(t, textvariable=self.probe_out, justify="left",
                  font=("Consolas", 9), wraplength=580).pack(anchor="w",
                                                             padx=8, pady=(0, 8))

        g = ttk.LabelFrame(p2, text="Beolvasás")
        g.pack(fill="x", padx=10, pady=10)
        ttk.Label(g, text="Almappák vizsgálata a dolgozó mappáján belül:"
                  ).grid(row=0, column=0, sticky="w", padx=8, pady=6)
        ttk.Spinbox(g, from_=0, to=3, textvariable=self.v_depth,
                    width=5).grid(row=0, column=1, sticky="w")
        ttk.Label(g, foreground=C_MUTED, justify="left", wraplength=700,
                  text="0 = csak a dolgozó mappája · 1 = egy almappa-szint "
                       "(pl. „Mellékletek\\”) · 2–3 = mélyebb fák.\n"
                       "A mélyebb beolvasás lassabb hálózati meghajtón, és a "
                       "régi/archív almappákból is behúzhat iratot."
                  ).grid(row=1, column=0, columnspan=2, sticky="w", padx=8,
                         pady=(0, 8))

        d = ttk.LabelFrame(p2, text="Megjelenés")
        d.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Label(d, text="Névoszlop szélessége:").grid(row=0, column=0,
                                                        sticky="w", padx=8, pady=6)
        ttk.Spinbox(d, from_=80, to=500, textvariable=self.v_namew,
                    width=6).grid(row=0, column=1, sticky="w")
        ttk.Label(d, text="Sormagasság:").grid(row=1, column=0, sticky="w",
                                               padx=8, pady=6)
        ttk.Spinbox(d, from_=16, to=48, textvariable=self.v_rowh,
                    width=6).grid(row=1, column=1, sticky="w")
        ttk.Label(d, text="Fejléc sorai:").grid(row=2, column=0, sticky="w",
                                                padx=8, pady=6)
        ttk.Spinbox(d, from_=1, to=4, textvariable=self.v_hdrl,
                    width=6).grid(row=2, column=1, sticky="w")
        ttk.Label(d, foreground=C_MUTED, justify="left", wraplength=700,
                  text="Fejléc sorai: ennyi sorba törhet az irattípus teljes neve. "
                       "Több sorral az oszlopok keskenyebbre húzhatók, így kevesebbet "
                       "kell vízszintesen görgetni.\n"
                       "Az oszlopszélesség a táblázatban is állítható: húzd az "
                       "oszlophatárt a fejlécben, vagy Ctrl+← / Ctrl+→ a "
                       "kijelölt oszlopon. Vízszintes görgetés: Shift+görgő, "
                       "touchpad-söprés vagy görgő a vízszintes sávon."
                  ).grid(row=3, column=0, columnspan=2, sticky="w", padx=8,
                         pady=(0, 8))

        foot = ttk.Frame(self)
        foot.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Label(foot, textvariable=self.msg,
                  foreground=C_WARN).pack(side="left")
        ttk.Button(foot, text="Mentés", command=self._save).pack(side="right")
        ttk.Button(foot, text="Mégsem",
                   command=self.destroy).pack(side="right", padx=8)
        ttk.Button(foot, text="Alapértelmezett szabályok",
                   command=self._reset).pack(side="left", padx=16)

    def _row(self, parent, r, label, var, width):
        ttk.Label(parent, text=label).grid(row=r, column=0, sticky="w",
                                           padx=8, pady=3)
        ttk.Entry(parent, textvariable=var, width=width).grid(
            row=r, column=1, sticky="ew", padx=6)

    def _fill(self, select=None):
        self.lb.delete(0, tk.END)
        for r in self.rules:
            mark = "●" if r.required else "○"
            self.lb.insert(tk.END, f"{mark} {r.short:8} {r.name[:30]}")
        if select is not None and 0 <= select < len(self.rules):
            self.lb.selection_set(select)
            self.lb.see(select)
            self._select()

    def _idx(self):
        s = self.lb.curselection()
        return s[0] if s else None

    def _select(self):
        i = self._idx()
        if i is None:
            return
        self.cur = None                       # ne írjon vissza töltés közben
        r = self.rules[i]
        self.v_name.set(r.name)
        self.v_short.set(r.short)
        self.v_all.set(", ".join(r.all_of))
        self.v_any.set(", ".join(r.any_of))
        self.v_req.set(r.required)
        self.v_gen.set(r.generated)
        self.v_arckep.set(r.arckep)
        self.v_width.set(r.width)
        self.cur = i
        self._probe()

    def _apply_cur(self):
        if self.cur is None:
            return
        r = self.rules[self.cur]
        r.name = self.v_name.get().strip() or r.name
        r.short = (self.v_short.get().strip() or r.short)[:10]
        r.all_of = [x.strip() for x in self.v_all.get().split(",") if x.strip()]
        r.any_of = [x.strip() for x in self.v_any.get().split(",") if x.strip()]
        r.required = bool(self.v_req.get())
        r.generated = bool(self.v_gen.get())
        r.arckep = bool(self.v_arckep.get())
        try:
            r.width = max(MIN_COL_W, min(MAX_COL_W, int(self.v_width.get())))
        except Exception:
            pass
        i = self.cur
        self.lb.delete(i)
        self.lb.insert(i, f"{'●' if r.required else '○'} {r.short:8} "
                          f"{r.name[:30]}")
        self.lb.selection_set(i)
        self.cur = i
        self._probe()

    def _probe(self):
        fn = self.v_probe.get().strip()
        if not fn:
            self.probe_out.set("")
            return
        n = norm(os.path.splitext(os.path.basename(fn))[0])
        rows = [(score(n, r), r) for r in self.rules]
        rows = sorted([x for x in rows if x[0] > 0], key=lambda x: -x[0])
        lines = [f"normalizált:  {n}"]
        if not rows:
            lines.append("NINCS TALÁLAT → melléklet (fel nem ismert PDF)")
        else:
            best = rows[0][0]
            tie = sum(1 for s, _ in rows if s == best) > 1
            for s, r in rows[:5]:
                mark = "►" if s == best else " "
                lines.append(f"{mark} {s:4d} pont   {r.name}")
            if tie:
                lines.append("!! HOLTVERSENY → a cella „?” jelet kap")
        self.probe_out.set("\n".join(lines))

    def _new(self):
        base = "uj"
        ids = {r.id for r in self.rules}
        i = 1
        while f"{base}{i}" in ids:
            i += 1
        self.rules.append(Rule(f"{base}{i}", "Új irattípus", f"Új{i}",
                               [], ["kulcsszo"], False, False))
        self._fill(len(self.rules) - 1)

    def _del(self):
        i = self._idx()
        if i is None:
            return
        if not messagebox.askyesno("Törlés",
                                   f"Törlöd: {self.rules[i].name}?",
                                   parent=self):
            return
        del self.rules[i]
        self.cur = None
        self._fill(min(i, len(self.rules) - 1))

    def _move(self, d):
        i = self._idx()
        if i is None:
            return
        j = i + d
        if not (0 <= j < len(self.rules)):
            return
        self.rules[i], self.rules[j] = self.rules[j], self.rules[i]
        self.cur = None
        self._fill(j)

    def _reset(self):
        if messagebox.askyesno("Alapértelmezett szabályok",
                               "Visszaállítod a beépített 11 irattípust?\n"
                               "A saját szabályok elvesznek.", parent=self):
            self.rules = rules_from(default_settings())
            self.cur = None
            self._fill(0)

    def _save(self):
        if not self.rules:
            self.msg.set("Legalább egy irattípus kell.")
            return
        ids = [r.id for r in self.rules]
        if len(set(ids)) != len(ids):
            self.msg.set("Két irattípusnak azonos az azonosítója.")
            return
        empty = [r.name for r in self.rules if not r.all_of and not r.any_of]
        if empty:
            self.msg.set("Kulcsszó nélküli típus: " + ", ".join(empty[:3]))
            return
        if not any(r.required for r in self.rules):
            if not messagebox.askyesno(
                    "Nincs kötelező típus",
                    "Egyetlen típus sincs kötelezőnek jelölve — így mindenki "
                    "azonnal „beadható” lesz.\n\nMentsem így?", parent=self):
                return
        s = dict(self.base,
                 rules=[asdict(r) for r in self.rules],
                 name_width=int(self.v_namew.get()),
                 scan_depth=int(self.v_depth.get()),
                 row_height=int(self.v_rowh.get()),
                 header_lines=max(1, min(4, int(self.v_hdrl.get()))))
        self.on_save(s)
        self.destroy()


# ── a fül ───────────────────────────────────────────────────────────────────
class AttekintoTab(ttk.Frame):
    """Mátrix-nézet vásznon — a Treeview nem tud cellánként színezni."""

    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.parent_dir = script_dir()
        self.settings = load_settings()
        self.rules = rules_from(self.settings)
        self.rows = []
        self.view_rows = []
        self._drawn = (-1, -1)          # a legutóbb kirajzolt sortartomány
        self.sort_col = "name"
        self.sort_desc = False
        self.sel = None
        self.cur_r = 0                 # kurzor sor a billentyűs navigációhoz
        self.cur_c = 0                 # kurzor oszlop
        self._resize = None            # (oszlopazonosító, kezdő x, kezdő szél.)
        self._tip = None
        self._tip_key = None
        self.hdr_h = 46                # dinamikus fejlécmagasság
        self._hdr_top = {}             # vászon -> a rögzített fejléc mostani y-ja

        self.filter_text = tk.StringVar(value="")
        self.mode = tk.StringVar(value="mind")
        self.show_opt = tk.BooleanVar(value=True)
        self.summary = tk.StringVar(value="")
        self.msg = tk.StringVar(value="")

        self._build()
        self.filter_text.trace_add("write", lambda *a: self._apply())
        self.mode.trace_add("write", lambda *a: self._apply())
        self.show_opt.trace_add("write", lambda *a: self._redraw())

    # ---------------- felület ----------------
    def _build(self):
        self.f_hdr = tkfont.Font(family="Segoe UI", size=8)
        self.f_hdr_b = tkfont.Font(family="Segoe UI", size=8,
                                   weight="bold")

        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=8, pady=(8, 4))
        ttk.Label(bar, text="Szűrő:").pack(side="left")
        e = ttk.Entry(bar, textvariable=self.filter_text, width=18)
        e.pack(side="left", padx=(4, 16))
        e.bind("<Down>", lambda ev: (self.c_data.focus_set(), "break")[1])
        ttk.Label(bar, text="Nézet:").pack(side="left")
        for txt, val in (("Mind", "mind"), ("Nem adható be", "hianyos"),
                         ("Beadható", "kesz")):
            ttk.Radiobutton(bar, text=txt, value=val,
                            variable=self.mode).pack(side="left", padx=2)
        ttk.Checkbutton(bar, text="Ajánlott oszlopok",
                        variable=self.show_opt).pack(side="left", padx=(16, 0))
        ttk.Label(bar, textvariable=self.summary, style="Dim.TLabel").pack(
            side="left", padx=20)
        ttk.Button(bar, text="Frissítés", command=self.refresh).pack(side="right")
        ttk.Button(bar, text="Beállítások…",
                   command=self._open_settings).pack(side="right", padx=6)

        grid = ttk.Frame(self)
        grid.pack(fill="both", expand=True, padx=8, pady=4)
        self.c_name = tk.Canvas(grid, width=self.settings["name_width"],
                                bg=C_BG, highlightthickness=1,
                                highlightbackground=C_GRID, takefocus=0)
        self.c_data = tk.Canvas(grid, bg=C_BG, highlightthickness=1,
                                highlightbackground=C_GRID, takefocus=1)
        vsb = ttk.Scrollbar(grid, orient="vertical", command=self._yview)
        hsb = ttk.Scrollbar(grid, orient="horizontal", command=self.c_data.xview)
        self.c_name.configure(yscrollcommand=vsb.set)
        self.c_data.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.c_name.grid(row=0, column=0, sticky="ns")
        self.c_data.grid(row=0, column=1, sticky="nsew")
        vsb.grid(row=0, column=2, sticky="ns")
        hsb.grid(row=1, column=1, sticky="ew")
        grid.rowconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)
        # Windowson a touchpad oldalirányú söprése is Shift+görgőként érkezik
        for w, seq in ((hsb, "<MouseWheel>"), (hsb, "<Shift-MouseWheel>"),
                       (self.c_name, "<Shift-MouseWheel>"), (self.c_data, "<Shift-MouseWheel>")):
            w.bind(seq, self._hwheel)

        for c in (self.c_name, self.c_data):
            c.bind("<MouseWheel>", self._wheel)
            c.bind("<Button-1>", lambda e, cv=c: self._click(e, cv))
            c.bind("<Double-Button-1>", lambda e, cv=c: self._dclick(e, cv))
            c.bind("<Button-3>", lambda e, cv=c: self._rclick(e, cv))
            c.bind("<Configure>", lambda e: debounce(self, "_cfg_job", self._redraw))
        self.c_data.bind("<Motion>", self._hover)
        self.c_data.bind("<ButtonPress-1>", self._maybe_resize, add="+")
        self.c_data.bind("<B1-Motion>", self._do_resize, add="+")
        self.c_data.bind("<ButtonRelease-1>", self._end_resize, add="+")

        for key, fn in (("<Up>", lambda e: self._move_cur(-1, 0)),
                        ("<Down>", lambda e: self._move_cur(1, 0)),
                        ("<Left>", lambda e: self._move_cur(0, -1)),
                        ("<Right>", lambda e: self._move_cur(0, 1)),
                        ("<Prior>", lambda e: self._move_cur(-10, 0)),
                        ("<Next>", lambda e: self._move_cur(10, 0)),
                        ("<Home>", lambda e: self._goto(0, 0)),
                        ("<End>", lambda e: self._goto(len(self.view_rows) - 1,
                                                       len(self._cols()) + 2)),
                        ("<Return>", lambda e: self._activate()),
                        ("<space>", lambda e: self._activate()),
                        ("<Control-Left>", lambda e: self._resize_cur(-10)),
                        ("<Control-Right>", lambda e: self._resize_cur(10)),
                        ("<F5>", lambda e: self.refresh())):
            self.c_data.bind(key, fn)
        self.c_data.bind("<FocusIn>", lambda e: self._redraw())
        self.c_data.bind("<FocusOut>", lambda e: self._redraw())

        foot = ttk.Frame(self)
        foot.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(foot, text="Hiánylista…",
                   command=self._show_todo).pack(side="left")
        ttk.Button(foot, text="CSV export…",
                   command=self._export_csv).pack(side="left", padx=6)
        ttk.Button(foot, text="Mappa megnyitása",
                   command=lambda: open_path(self.parent_dir)).pack(side="left")
        ttk.Button(foot, text="Rendezés…",
                   command=self._open_tidy).pack(side="left", padx=6)
        ttk.Button(foot, text="Ellenőrzés…",
                   command=self._open_audit).pack(side="left")
        ttk.Button(foot, text="Tömörítés…",
                   command=self._open_shrink).pack(side="left", padx=6)
        self.msg_lbl = ttk.Label(foot, textvariable=self.msg)
        self.msg_lbl.pack(side="right")

    def _yview(self, *a):
        self.c_name.yview(*a)
        self.c_data.yview(*a)
        self._after_scroll()

    def _wheel(self, e):
        d = -1 if e.delta > 0 else 1
        self.c_name.yview_scroll(d, "units")
        self.c_data.yview_scroll(d, "units")
        self._after_scroll()
        return "break"

    def _after_scroll(self):
        """Görgetés után csak akkor rajzolunk újra, ha a látható sáv kicsúszott
        a kirajzolt (pufferelt) tartományból — így a görgetés sima marad."""
        self._pin_all()
        kezd, veg = self._rows_view(self.c_data)
        if not (self._drawn[0] <= kezd and veg <= self._drawn[1]):
            self._redraw()

    def _hwheel(self, e):
        """Vízszintes görgetés; a Dolgozó oszlop fix, csak az adatok gördülnek."""
        self.c_data.xview_scroll(-1 if e.delta > 0 else 1, "units")
        return "break"

    # ---------------- rögzített fejléc ----------------
    def _pin(self, c, fresh=False):
        """A „hdr” címkéjű fejléc a látható rész tetejére kerül, a sorok fölé —
        görgetéskor sem tűnik el. `fresh`: most rajzoltuk, még y = 0-n áll."""
        top = c.canvasy(0)
        c.move("hdr", 0, top - (0 if fresh else self._hdr_top.get(c, 0)))
        c.tag_raise("hdr")
        self._hdr_top[c] = top

    def _pin_all(self):
        for c in (self.c_name, self.c_data):
            self._pin(c)

    def _in_hdr(self, c, e) -> bool:
        """Az egér a (rögzített) fejlécen áll-e."""
        return c.canvasy(e.y) < self._hdr_top.get(c, 0) + self.hdr_h

    # ---------------- beállítások ----------------
    def _open_settings(self):
        SettingsDialog(self, self.settings, self._apply_settings)

    def _apply_settings(self, s):
        self.settings = s
        self.rules = rules_from(s)
        self.c_name.configure(width=s["name_width"])
        ok = save_settings(s)
        self.refresh()
        self._info(f"{len(self.rules)} irattípus · almappa-mélység: "
                   f"{s['scan_depth']}" +
                   ("" if ok else "  FIGYELEM: a beállítás mentése nem sikerült!"),
                   warn=not ok)

    # ---------------- beolvasás ----------------
    def set_folder(self, folder):
        self.parent_dir = folder
        self.refresh()

    def refresh(self):
        try:
            self.rows = scan(self.parent_dir, self.rules,
                             self.settings["scan_depth"])
            self._info(f"{len(self.rows)} mappa beolvasva "
                       f"({datetime.datetime.now():%H:%M:%S}) · "
                       "dupla kattintás / Enter = megnyitás")
        except OSError as e:
            self.rows = []
            self._info(f"A gyűjtőmappa nem olvasható: {e}", warn=True)
        self._apply()

    def _cols(self):
        return self.rules if self.show_opt.get() else \
            [r for r in self.rules if r.required]

    def _by_id(self):
        return {r.id: r for r in self.rules}

    def _apply(self):
        f = strip_accents(self.filter_text.get().strip())
        mode = self.mode.get()
        out = []
        for r in self.rows:
            if f and f not in strip_accents(r.name):
                continue
            if mode == "kesz" and not r.beadhato:
                continue
            if mode == "hianyos" and r.beadhato:
                continue
            out.append(r)

        key = self.sort_col
        byid = self._by_id()
        if key == "name":
            out.sort(key=lambda r: _sort_key(r.name), reverse=self.sort_desc)
        elif key == "ready":
            out.sort(key=lambda r: (r.ready_required, r.ready_optional),
                     reverse=self.sort_desc)
        elif key in byid:
            order = {"F": 0, "EF": 0, "E": 1, "~": 2, "?": 3, "·": 4}
            out.sort(key=lambda r: (order.get(r.docs[key].cell, 9),
                                    _sort_key(r.name)), reverse=self.sort_desc)
        self.view_rows = out
        self.cur_r = min(self.cur_r, max(0, len(out) - 1))

        n = len(self.rows)
        ok = sum(1 for r in self.rows if r.beadhato)
        pr = sum(len(r.to_print) for r in self.rows)
        amb = sum(1 for r in self.rows if r.ambiguous_files)
        nof = sum(1 for r in self.rows if not r.photos)
        big = sum(1 for r in self.rows if r.big)
        morep = sum(1 for r in self.rows if len(r.photos) > 1)
        dup = sum(1 for r in self.rows if r.duplicates)
        sub = sum(r.subdirs for r in self.rows)
        uns = sum(1 for r in self.rows if r.unsorted)
        extra = f" · {uns} mappában besorolatlan fájl (~)" if uns else ""
        extra += f" · {sub} egyéb almappa" if sub else ""
        extra += f" · {big} mappában 5 MB feletti PDF" if big else ""
        extra += f" · {dup} mappában több PDF ugyanahhoz" if dup else ""
        extra += f" · {morep} mappában az arcképen kívül más kép is" if morep else ""
        self.summary.set(f"{n} dolgozó · {ok} beadható · {n - ok} hiányos · "
                         f"{pr} nyomtatandó · {amb} kétes · "
                         f"{nof} arckép hiányzik{extra}")
        self._redraw()

    # ---------------- geometria ----------------
    def _xs(self, cols):
        xs, x = [], 0
        for r in cols:
            xs.append(x)
            x += r.width
        return xs, x

    def _rh(self):
        return self.settings["row_height"]

    def _rows_view(self, c, puffer=0):
        """A sorok tartománya: ami LÁTSZIK (+ puffer). 150 dolgozónál a mátrix
        4700 vászonelem volt, pedig egyszerre ~25 sor fér ki — a Tk minden
        újrafestéskor mindet átrajzolta (13.10). A puffer azért kell, hogy
        görgetéskor ne kelljen minden lépésnél újrarajzolni."""
        rh = max(1, self._rh())
        try:
            top = max(0.0, c.canvasy(0) - self.hdr_h)
            magas = max(1, c.winfo_height())
        except Exception:
            return 0, len(self.view_rows)
        start = max(0, int(top // rh) - puffer)
        end = min(len(self.view_rows), int((top + magas) // rh) + 1 + puffer)
        return start, end

    # ---------------- rajzolás ----------------
    def _measure(self, s):
        return self.f_hdr.measure(s)

    def _wrap_headers(self, cols):
        """Oszloponként a tördelt TELJES név + a fejléc magassága."""
        maxl = int(self.settings.get("header_lines", 3))
        wrapped = {}
        for r in cols:
            wrapped[r.id] = fit_header(r.name, r.short, r.width - CELL_PAD,
                                       self._measure, maxl)
        for lbl, w in (("Kép", W_SMALL), ("Melléklet", W_SMALL),
                       ("Kötelező", W_READY)):
            wrapped["__" + lbl] = fit_header(lbl, lbl[:4], w - CELL_PAD,
                                             self._measure, maxl)
        lines = max([len(v) for v in wrapped.values()] or [1])
        self.hdr_h = HDR_PAD_TOP + lines * HDR_LINE + HDR_PAD_BOT
        return wrapped

    def _draw_header_text(self, c, cx, lines, bold, fill):
        """Középre igazított, több soros fejlécszöveg — alulról építve."""
        n = len(lines)
        y0 = self.hdr_h - HDR_PAD_BOT - n * HDR_LINE + HDR_LINE / 2
        for i, ln in enumerate(lines):
            c.create_text(cx, y0 + i * HDR_LINE, text=ln, tags=("hdr",),
                          font=self.f_hdr_b if bold else self.f_hdr, fill=fill)

    def _show_tip(self, x, y, text, key):
        if self._tip_key == key:
            return
        self._hide_tip()
        self._tip_key = key
        tw = tk.Toplevel(self)
        tw.wm_overrideredirect(True)
        tw.wm_geometry("+%d+%d" % (x + 14, y + 18))
        tk.Label(tw, text=text, justify="left", background="#ffffe0",
                 relief="solid", borderwidth=1, font=("Segoe UI", 9),
                 padx=6, pady=3).pack()
        self._tip = tw

    def _hide_tip(self):
        if self._tip is not None:
            try:
                self._tip.destroy()
            except Exception:
                pass
        self._tip = None
        self._tip_key = None

    def _redraw(self):
        cols = self._cols()
        self.cur_c = min(self.cur_c, len(cols) + 3)
        wrapped = self._wrap_headers(cols)
        self._draw_names()
        self._draw_data(cols, wrapped)
        self._drawn = self._rows_view(self.c_data, ROW_BUFFER)

    def _draw_names(self):
        c = self.c_name
        c.delete("all")
        W = self.settings["name_width"]
        rh = self._rh()
        H = self.hdr_h
        c.create_rectangle(0, 0, W, H, fill=C_HDR, outline=C_GRID, tags=("hdr",))
        arrow = (" ▼" if self.sort_desc else " ▲") \
            if self.sort_col == "name" else ""
        c.create_text(8, H - HDR_PAD_BOT - HDR_LINE / 2, anchor="w",
                      text="Dolgozó" + arrow, font=("Segoe UI", 9, "bold"),
                      tags=("hdr::name", "hdr"))
        kezd, veg = self._rows_view(c, ROW_BUFFER)
        for i in range(kezd, veg):
            r = self.view_rows[i]
            y = H + i * rh
            bg = C_SEL if r is self.sel else (C_ROW_ALT if i % 2 else C_BG)
            c.create_rectangle(0, y, W, y + rh, fill=bg, outline=C_GRID)
            c.create_text(8, y + rh / 2, anchor="w",
                          text=ellipsize(r.name, W - 14, self._measure),
                          fill=C_WARN if r.error else C_TEXT,
                          font=("Segoe UI", 9))
            if i == self.cur_r and self.cur_c == 0:
                c.create_rectangle(1, y + 1, W - 1, y + rh - 1,
                                   outline=C_CUR, width=2)
        c.configure(scrollregion=(0, 0, W,
                                  H + max(1, len(self.view_rows)) * rh))
        self._pin(c, fresh=True)

    def _draw_data(self, cols, wrapped=None):
        c = self.c_data
        c.delete("all")
        if wrapped is None:
            wrapped = self._wrap_headers(cols)
        rh = self._rh()
        H = self.hdr_h
        xs, x = self._xs(cols)
        x_photo, x_extra, x_ready = x, x + W_SMALL, x + 2 * W_SMALL
        total = x_ready + W_READY
        nreq = sum(1 for r in cols if r.required)

        c.create_rectangle(0, 0, total, self.hdr_h, fill=C_HDR, outline=C_GRID,
                           tags=("hdr",))
        if nreq and nreq < len(cols):
            c.create_rectangle(xs[nreq], 0, x_photo, self.hdr_h,
                               fill=C_HDR_OPT, outline=C_GRID, tags=("hdr",))
            c.create_text((xs[nreq] + x_photo) / 2, 10, text="ajánlott",
                          fill=C_MUTED, font=("Segoe UI", 7), tags=("hdr",))
            c.create_text(xs[nreq] / 2, 10, text="KÖTELEZŐ",
                          fill=C_TEXT, font=("Segoe UI", 7, "bold"), tags=("hdr",))

        for i, r in enumerate(cols):
            arrow = ("  ▼" if self.sort_desc else "  ▲") \
                if self.sort_col == r.id else ""
            lines = list(wrapped[r.id])
            if arrow:
                lines[-1] = ellipsize(lines[-1] + arrow, r.width - CELL_PAD,
                                      self._measure)
            self._draw_header_text(c, xs[i] + r.width / 2, lines, r.required,
                                   C_TEXT if r.required else C_MUTED)
        self._draw_header_text(c, x_photo + W_SMALL / 2,
                               wrapped["__Kép"], False, C_MUTED)
        self._draw_header_text(c, x_extra + W_SMALL / 2,
                               wrapped["__Melléklet"], False, C_MUTED)
        rl = list(wrapped["__Kötelező"])
        if self.sort_col == "ready":
            rl[-1] = ellipsize(rl[-1] + ("  ▼" if self.sort_desc else "  ▲"),
                               W_READY - CELL_PAD, self._measure)
        self._draw_header_text(c, x_ready + W_READY / 2, rl, True, C_TEXT)

        nreq_all = sum(1 for r in self.rules if r.required)
        kezd, veg = self._rows_view(c, ROW_BUFFER)
        for i in range(kezd, veg):
            row = self.view_rows[i]
            y = self.hdr_h + i * rh
            base = C_SEL if row is self.sel else (C_ROW_ALT if i % 2 else C_BG)
            c.create_rectangle(0, y, total, y + rh, fill=base, outline="")

            if row.error:
                c.create_text(6, y + rh / 2, anchor="w", fill=C_WARN,
                              text="a mappa nem olvasható: " + row.error[:60],
                              font=("Segoe UI", 8))
                c.create_line(0, y + rh, total, y + rh, fill=C_GRID)
                continue

            for j, rule in enumerate(cols):
                st = row.docs.get(rule.id)
                txt = st.cell if st else "·"
                # F = kész (02), EF = mindkettőben, E = még csak előkészített (01),
                # ~ = besorolatlan (gyökér vagy más almappa) — nem beadható.
                fill = {"F": C_P, "EF": C_DP, "E": C_D,
                        "~": C_UNSORTED, "?": C_AMB}.get(txt, C_NONE)
                if txt == "·":
                    fill = base
                if st and len(st.pdf) > 1:
                    txt, fill = f"{txt}×{len(st.pdf)}", C_AMB    # melyik a jó?
                if st and any(p in row.big for p in st.pdf):
                    txt, fill = txt + "!", C_BIG      # 5 MB fölött: nem feltölthető
                if fill != base:          # üres cellánál a sor háttere látszik:
                    # a vele azonos színű téglalap láthatatlan, de a Tk minden
                    # újrafestéskor átrajzolná — 150 dolgozónál ez a cellák
                    # harmada volt feleslegesen (13.10).
                    c.create_rectangle(xs[j] + 1, y + 1, xs[j] + rule.width - 1,
                                       y + rh - 1, fill=fill, outline="")
                c.create_text(xs[j] + rule.width / 2, y + rh / 2, text=txt,
                              font=("Segoe UI", 9,
                                    "bold" if txt in ("P", "DP") else "normal"),
                              fill=C_MUTED if txt == "·" else C_TEXT)

            np_ = len(row.photos)
            ptxt = "·" if np_ == 0 else ("✓" if np_ == 1 else f"{np_} ⚠")
            c.create_text(x_photo + W_SMALL / 2, y + rh / 2, text=ptxt,
                          fill=C_MUTED if np_ == 0 else
                          (C_TEXT if np_ == 1 else C_WARN),
                          font=("Segoe UI", 9))
            ne = len(row.extra_pdfs)
            nbig = sum(1 for p in row.extra_pdfs if p in row.big)
            c.create_text(x_extra + W_SMALL / 2, y + rh / 2,
                          text="·" if ne == 0 else str(ne) + ("!" if nbig else ""),
                          fill=C_MUTED if ne == 0 else (C_WARN if nbig else C_TEXT),
                          font=("Segoe UI", 9))

            if row.beadhato:
                c.create_rectangle(x_ready + 3, y + 3, x_ready + W_READY - 3,
                                   y + rh - 3, fill=C_P, outline=C_OK)
                c.create_text(x_ready + W_READY / 2, y + rh / 2,
                              text="BEADHATÓ", fill=C_OK,
                              font=("Segoe UI", 7, "bold"))
            else:
                k = row.ready_required
                bw = (W_READY - 34) * k / max(1, nreq_all)
                c.create_rectangle(x_ready + 4, y + 8,
                                   x_ready + 4 + W_READY - 34, y + rh - 8,
                                   fill="#e6e9ec", outline="")
                if bw > 0:
                    c.create_rectangle(x_ready + 4, y + 8, x_ready + 4 + bw,
                                       y + rh - 8, fill="#7fb77f", outline="")
                c.create_text(x_ready + W_READY - 4, y + rh / 2, anchor="e",
                              text=f"{k}/{nreq_all}", font=("Segoe UI", 8))
            c.create_line(0, y + rh, total, y + rh, fill=C_GRID)

        body_h = H + len(self.view_rows) * rh
        for xx in xs + [x_photo, x_extra, x_ready]:
            c.create_line(xx, 0, xx, body_h, fill=C_GRID)
            c.create_line(xx, 0, xx, H, fill=C_GRID, tags=("hdr",))   # a rögzített fejlécben is
        if nreq and nreq < len(cols):
            for y1, tags in ((body_h, ()), (H, ("hdr",))):
                c.create_line(xs[nreq], 0, xs[nreq], y1, fill="#9aa7b4", width=2, tags=tags)

        # kurzorkeret
        if self.view_rows and self.cur_c > 0 and \
                self.c_data.focus_get() is self.c_data:
            i = min(self.cur_r, len(self.view_rows) - 1)
            y = self.hdr_h + i * rh
            (cx, cw), _ = self._col_span(self.cur_c - 1)
            c.create_rectangle(cx + 1, y + 1, cx + cw - 1, y + rh - 1,
                               outline=C_CUR, width=2)

        c.configure(scrollregion=(0, 0, total,
                                  self.hdr_h + max(1, len(self.view_rows)) * rh))
        if not self.view_rows:
            cw = max(200, c.winfo_width())
            c.create_text(cw / 2, self.hdr_h + 40, fill=C_MUTED, justify="center",
                          font=("Segoe UI", 10),
                          text="Nincs megjeleníthető sor.\n"
                               "Válassz gyűjtőmappát, vagy oldd fel a szűrőt.")
        self._pin(c, fresh=True)

    # ---------------- oszlopszélesség húzással ----------------
    def _edge_at(self, x):
        """Melyik oszlop jobb szélén állunk? -> Rule vagy None."""
        cols = self._cols()
        xs, _ = self._xs(cols)
        for i, r in enumerate(cols):
            if abs(x - (xs[i] + r.width)) <= 3:
                return r
        return None

    def _hover(self, e):
        if self._resize:
            return
        x = self.c_data.canvasx(e.x)
        in_hdr = self._in_hdr(self.c_data, e)
        on_edge = in_hdr and self._edge_at(x)
        try:
            self.c_data.configure(cursor="sb_h_double_arrow" if on_edge else "")
        except Exception:
            pass
        if in_hdr and not on_edge:
            cols = self._cols()
            xs, xend = self._xs(cols)
            for i, r in enumerate(cols):
                if xs[i] <= x < xs[i] + r.width:
                    tip = r.name
                    tip += "\nkötelező" if r.required else "\najánlott"
                    if r.any_of:
                        tip += "\nbármelyik: " + ", ".join(r.any_of[:4])
                    if r.all_of:
                        tip += "\nmind: " + ", ".join(r.all_of[:4])
                    self._show_tip(e.x_root, e.y_root, tip, ("h", r.id))
                    return
            rest = x - xend
            if 0 <= rest < W_SMALL:
                self._show_tip(e.x_root, e.y_root,
                               "Képek száma a mappában — csak EGY, az arckép\n"
                               "maradhat; minden más fotó PDF-be (Összeállító)",
                               ("h", "photo"))
                return
            if W_SMALL <= rest < 2 * W_SMALL:
                self._show_tip(e.x_root, e.y_root,
                               "Fel nem ismert PDF-ek (mellékletek) száma",
                               ("h", "extra"))
                return
            if rest >= 2 * W_SMALL:
                self._show_tip(e.x_root, e.y_root,
                               "Megvan-e mind a kötelező irat", ("h", "ready"))
                return
        self._hide_tip()

    def _maybe_resize(self, e):
        x = self.c_data.canvasx(e.x)
        if not self._in_hdr(self.c_data, e):
            return
        r = self._edge_at(x)
        if r:
            self._resize = (r.id, x, r.width)
            return "break"

    def _do_resize(self, e):
        if not self._resize:
            return
        rid, x0, w0 = self._resize
        x = self.c_data.canvasx(e.x)
        for r in self.rules:
            if r.id == rid:
                r.width = max(MIN_COL_W, min(MAX_COL_W, int(w0 + x - x0)))
        self._redraw()
        return "break"

    def _end_resize(self, e):
        if not self._resize:
            return
        self._resize = None
        self._persist_widths()
        return "break"

    def _persist_widths(self):
        self.settings["rules"] = [asdict(r) for r in self.rules]
        save_settings(self.settings)

    def _resize_cur(self, d):
        cols = self._cols()
        j = self.cur_c - 1
        if 0 <= j < len(cols):
            rid = cols[j].id
            for r in self.rules:
                if r.id == rid:
                    r.width = max(MIN_COL_W, min(MAX_COL_W, r.width + d))
            self._redraw()
            self._persist_widths()
        return "break"

    # ---------------- billentyűs navigáció ----------------
    def _goto(self, r, c):
        if not self.view_rows:
            return "break"
        self.cur_r = max(0, min(r, len(self.view_rows) - 1))
        self.cur_c = max(0, min(c, len(self._cols()) + 3))
        self.sel = self.view_rows[self.cur_r]
        self._scroll_to_cursor()
        self._redraw()
        return "break"

    def _move_cur(self, dr, dc):
        return self._goto(self.cur_r + dr, self.cur_c + dc)

    def _scroll_to_cursor(self):
        rh = self._rh()
        h = self.hdr_h + max(1, len(self.view_rows)) * rh
        y = self.hdr_h + self.cur_r * rh
        vis = self.c_data.winfo_height()
        top = self.c_data.canvasy(0)
        if y < top + self.hdr_h:
            frac = max(0.0, (y - self.hdr_h) / max(1, h))
            self.c_data.yview_moveto(frac)
            self.c_name.yview_moveto(frac)
        elif y + rh > top + vis:
            frac = max(0.0, (y + rh - vis) / max(1, h))
            self.c_data.yview_moveto(frac)
            self.c_name.yview_moveto(frac)
        if self.cur_c > 0:                 # vízszintesen is kövesse (a névoszlop fix)
            (cx, cw), total = self._col_span(self.cur_c - 1)
            left, visw = self.c_data.canvasx(0), self.c_data.winfo_width()
            if cx < left:
                self.c_data.xview_moveto(cx / total)
            elif cx + cw > left + visw:
                self.c_data.xview_moveto((cx + cw - visw) / total)

    def _col_span(self, j):
        """A j. adatoszlop (0 = első irattípus; utána Kép, Melléklet, Kötelező)
        -> ((bal szél, szélesség), a tábla teljes szélessége)."""
        cols = self._cols()
        xs, x = self._xs(cols)
        spans = [(xs[k], r.width) for k, r in enumerate(cols)] + \
                [(x, W_SMALL), (x + W_SMALL, W_SMALL), (x + 2 * W_SMALL, W_READY)]
        return spans[min(j, len(spans) - 1)], x + 2 * W_SMALL + W_READY

    def _activate(self):
        """Enter/Space/dupla kattintás: a kurzor alatti cella megnyitása."""
        if not self.view_rows:
            return "break"
        row = self.view_rows[self.cur_r]
        cols = self._cols()
        j = self.cur_c - 1
        if self.cur_c == 0:
            open_path(row.folder)
        elif 0 <= j < len(cols):
            st = row.docs.get(cols[j].id)
            files = (st.pdf + st.docx) if st else []
            if files:
                open_path(os.path.join(row.folder, files[0]))
            else:
                self._info(f"{row.name} — {cols[j].name}: nincs ilyen fájl.")
        elif j == len(cols) and row.photos:
            open_path(os.path.join(row.folder, row.photos[0]))
        elif j == len(cols) + 1 and row.extra_pdfs:
            open_path(os.path.join(row.folder, row.extra_pdfs[0]))
        return "break"

    # ---------------- egér ----------------
    def _hit(self, e, canvas):
        y = canvas.canvasy(e.y)
        x = canvas.canvasx(e.x)
        rh = self._rh()
        cols = self._cols()
        if self._in_hdr(canvas, e):
            if canvas is self.c_name:
                return None, "name", True
            xs, _ = self._xs(cols)
            for i, r in enumerate(cols):
                if xs[i] <= x < xs[i] + r.width:
                    return None, r.id, True
            rest = x - (xs[-1] + cols[-1].width if cols else 0)
            if rest >= 2 * W_SMALL:
                return None, "ready", True
            return None, None, True
        i = int((y - self.hdr_h) // rh)
        if not (0 <= i < len(self.view_rows)):
            return None, None, False
        if canvas is self.c_name:
            return i, "name", False
        xs, xend = self._xs(cols)
        for k, r in enumerate(cols):
            if xs[k] <= x < xs[k] + r.width:
                return i, r.id, False
        rest = x - xend
        if rest < W_SMALL:
            return i, "photo", False
        if rest < 2 * W_SMALL:
            return i, "extra", False
        return i, "ready", False

    def _click(self, e, canvas):
        # a <Button-1> a _maybe_resize ELŐTT fut: az oszlophatár megfogása ne rendezzen
        if self._resize or (canvas is self.c_data and self._in_hdr(canvas, e)
                            and self._edge_at(canvas.canvasx(e.x))):
            return
        i, col, is_hdr = self._hit(e, canvas)
        if is_hdr:
            if col:
                self.sort_desc = (col == self.sort_col) and not self.sort_desc
                self.sort_col = col
                self._apply()
            return
        if i is None:
            return
        self.c_data.focus_set()
        cols = self._cols()
        self.cur_r = i
        if col == "name":
            self.cur_c = 0
        elif col == "photo":
            self.cur_c = len(cols) + 1
        elif col == "extra":
            self.cur_c = len(cols) + 2
        elif col == "ready":
            self.cur_c = len(cols) + 3
        else:
            self.cur_c = next((k + 1 for k, r in enumerate(cols)
                               if r.id == col), 0)
        self.sel = self.view_rows[i]
        self._redraw()                  # egy kattintás csak kijelöl; megnyitás: dupla

    def _dclick(self, e, canvas):
        """Dupla kattintás: a cella fájlja (a névoszlopban a mappa) megnyílik.
        A kurzort az első kattintás (_click) már a cellára tette."""
        i, _col, is_hdr = self._hit(e, canvas)
        if not is_hdr and i is not None:
            self._activate()
        return "break"

    def _rclick(self, e, canvas):
        i, col, is_hdr = self._hit(e, canvas)
        if is_hdr or i is None:
            return
        row = self.view_rows[i]
        self.sel = row
        self.cur_r = i
        self._redraw()
        byid = self._by_id()
        m = tk.Menu(self, tearoff=0)
        m.add_command(label=f"📂  {row.name} mappája",
                      command=lambda: open_path(row.folder))
        st = row.docs.get(col)
        if st:
            for fn in (st.pdf + st.docx)[:6]:
                m.add_command(label="   " + fn[:60],
                              command=lambda f=fn: open_path(
                                  os.path.join(row.folder, f)))
        if st and st.pdf and hasattr(self.app, "goto_szerkeszto"):
            for fn in st.pdf[:6]:
                m.add_command(label="✎ Szerkesztés: " + fn[:50],
                              command=lambda f=fn: self.app.goto_szerkeszto(
                                  os.path.join(row.folder, f), self.parent_dir))
        if row.extra_pdfs:
            m.add_separator()
            for fn in row.extra_pdfs[:6]:
                m.add_command(label="melléklet: " + fn[:52],
                              command=lambda f=fn: open_path(
                                  os.path.join(row.folder, f)))
        if row.big and hasattr(self.app, "goto_iktato"):
            m.add_separator()
            for fn, n in list(row.big.items())[:6]:
                r0, _ = match_rule(fn, self.rules)
                m.add_command(label=f"⚠ tömörítés az Iktatóban: {fn[:44]} ({mb(n)})",
                              command=lambda f=fn, r0=r0: self.app.goto_iktato(
                                  row.name, r0.name if r0 else None,
                                  os.path.join(row.folder, f)))
        m.add_separator()
        rule = byid.get(col)
        if hasattr(self.app, "goto_iktato"):
            m.add_command(label="→ Iktatás ehhez a dolgozóhoz",
                          command=lambda: self.app.goto_iktato(
                              row.name, rule.name if rule else None))
        else:
            m.add_command(label="→ Iktatás ehhez a dolgozóhoz", state="disabled")
        if hasattr(self.app, "goto_arckep"):
            m.add_command(label="→ Arckép elhelyezése",
                          command=lambda: self.app.goto_arckep(row.folder))
        else:
            m.add_command(label="→ Arckép elhelyezése", state="disabled")
        try:
            m.tk_popup(e.x_root, e.y_root)
        finally:
            m.grab_release()

    # ---------------- hiánylista ----------------
    def _todo_text(self) -> str:
        stamp = datetime.date.today().isoformat()
        base = os.path.basename(os.path.normpath(self.parent_dir))
        nreq = sum(1 for r in self.rules if r.required)
        nopt = len(self.rules) - nreq
        L = [f"{base} — hiánylista ({stamp})", ""]
        bad = [r for r in self.rows if not r.beadhato]
        good = [r for r in self.rows if r.beadhato]

        L.append(f"╔═ NEM ADHATÓ BE ({len(bad)}) " + "═" * 40)
        L.append("")
        for r in bad:
            L.append(f"{r.name} …… {r.ready_required}/{nreq} kötelező")
            if r.error:
                L.append(f"    HIBA: a mappa nem olvasható — {r.error}")
                L.append("")
                continue
            if r.to_print:
                L.append("    nyomtatni:   " + ", ".join(r.to_print))
            if r.missing_required:
                L.append("    generálni:   " + ", ".join(r.missing_required))
            if r.to_obtain:
                L.append("    bekérni:     " + ", ".join(r.to_obtain))
            if r.ambiguous_files:
                L.append("    ellenőrizni: " +
                         ", ".join(f'„{f}"' for f in r.ambiguous_files[:3]))
            if r.big:
                L.append("    tömöríteni:  " +
                         ", ".join(f'„{f}" ({mb(n)})' for f, n in r.big.items()))
            if r.unsorted:
                L.append("    besorolni:   " +
                         ", ".join(f'„{f}"' for f in r.unsorted[:4]) +
                         (f" … ({len(r.unsorted)} db)" if len(r.unsorted) > 4 else ""))
            for name, files in r.duplicates:
                L.append(f"    több PDF:    {name} — " + ", ".join(f'„{f}"' for f in files))
            if r.by_stamp:
                L.append("    átnevezve:   " +
                         ", ".join(f'„{f}"' for f in r.by_stamp[:3]) +
                         " (a bélyeg alapján felismerve)")
            for f, w in r.foreign:
                L.append(f'    IDEGEN:      „{f}" bélyege: {w}')
            if not r.photos:
                L.append("    arckép hiányzik")
            elif len(r.photos) > 1:
                L.append(f"    {len(r.photos)} kép — csak az arckép maradhat, "
                         "a többi PDF-be (Összeállító)")
            L.append("")

        L.append(f"╔═ BEADHATÓ ({len(good)}) " + "═" * 44)
        L.append("")
        for r in good:
            extra = "   ⚠ arckép hiányzik" if not r.photos else ""
            if len(r.photos) > 1:
                extra += f"   ⚠ {len(r.photos)} kép (csak az arckép maradhat)"
            if r.big:
                extra += f"   ⚠ {len(r.big)} db 5 MB feletti PDF"
            if r.unsorted:
                extra += f"   ⚠ {len(r.unsorted)} besorolatlan fájl"
            if r.duplicates:
                extra += "   ⚠ több PDF: " + ", ".join(n for n, _ in r.duplicates)
            if r.foreign:
                extra += "   ⚠ idegen bélyeg: " + ", ".join(w for _, w in r.foreign)
            L.append(f"{r.name} …… {r.ready_required}/{nreq} kötelező · "
                     f"{r.ready_optional}/{nopt} ajánlott{extra}")
        return "\n".join(L)

    def _show_todo(self):
        if not self.rows:
            self._info("Nincs beolvasott mappa.", warn=True)
            return
        txt = self._todo_text()
        win = tk.Toplevel(self)
        win.title("Hiánylista")
        win.geometry("780x640")
        t = tk.Text(win, wrap="none", font=("Consolas", 9))
        sb = ttk.Scrollbar(win, orient="vertical", command=t.yview)
        t.configure(yscrollcommand=sb.set)
        t.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        t.insert("1.0", txt)
        t.configure(state="disabled")
        row = ttk.Frame(win)
        row.pack(side="bottom", fill="x", padx=8, pady=6)

        def copy():
            self.clipboard_clear()
            self.clipboard_append(txt)
            self._info("A hiánylista a vágólapra másolva.", ok=True)

        def save():
            p = filedialog.asksaveasfilename(
                parent=win, title="Hiánylista mentése",
                initialdir=self.parent_dir,
                initialfile=f"hianylista-{datetime.date.today().isoformat()}.txt",
                defaultextension=".txt", filetypes=[("Szövegfájl", "*.txt")])
            if not p:
                return
            try:
                with open(p, "w", encoding="utf-8-sig") as f:
                    f.write(txt)
                self._info(f"Mentve: {os.path.basename(p)}", ok=True)
            except OSError as e:
                messagebox.showerror("Mentés", str(e), parent=win)

        ttk.Button(row, text="Vágólapra", command=copy).pack(side="left")
        ttk.Button(row, text="Mentés…", command=save).pack(side="left", padx=6)
        ttk.Button(row, text="Bezár", command=win.destroy).pack(side="right")

    # ---------------- rendezés a két alkönyvtárba ----------------
    def _open_tidy(self):
        """Hiányzó 01/02 mappák létrehozása + a gyökérben hagyott fájlok besorolása,
        előnézettel. A mozgatás nem visszavonható, ezért itt minden sor látszik."""
        if not self.rows:
            self._info("Nincs beolvasott mappa.", warn=True)
            return
        # Mappánkénti kapu: csak bizonyítottan dolgozói mappában mozgatunk.
        ok_rows, skipped = [], []
        for r in self.rows:
            if r.error:
                continue
            (ok_rows if is_worker_folder(r.folder, self.rules) else skipped).append(r)
        missing = [r for r in ok_rows
                   if any(not os.path.isdir(os.path.join(r.folder, d))
                          for d in WORK_DIRS)]
        plans = {}
        for r in ok_rows:
            t = migracio_terv(r.folder, self.rules)
            if t:
                plans[r.name] = (r.folder, t)

        win = tk.Toplevel(self)
        win.title("Rendezés a két alkönyvtárba")
        win.transient(self.winfo_toplevel())
        win.grab_set()
        head = (f"{len(missing)} dolgozónál hiányzik a {DIR_PREP} vagy a {DIR_UP}. "
                if missing else "A mappaszerkezet mindenhol megvan. ")
        movable = sum(1 for _f, t in plans.values() for row in t if row[1])
        guesses = sum(1 for _f, t in plans.values() for row in t if row[1] and not row[3])
        stay = sum(1 for _f, t in plans.values() for row in t if not row[1])
        ttk.Label(win, text=head + f"{movable} fájl kerülne a helyére "
                                   f"({guesses} ebből tipp), {stay} marad a gyökérben.",
                  wraplength=620, justify="left").pack(anchor="w", padx=14, pady=(14, 6))

        if not ok_rows:
            # Ez a leggyakoribb tévedés: nem munkamappa van kiválasztva. A mozgatás
            # nem visszavonható, ezért itt nincs továbblépés, csak Mégsem.
            ttk.Label(win, foreground=C_WARN, wraplength=620, justify="left",
                      text=f"⚠ Ez nem úgy néz ki, mint egy munkamappa: a "
                           f"{len(skipped)} almappa egyikében sincs 01/02 mappa és "
                           f"felismert irat sem.\n\nEllenőrizd a fenti Munkamappa "
                           f"sávot:\n{self.parent_dir}").pack(anchor="w", padx=14,
                                                              pady=(4, 8))
            ttk.Button(win, text="Mégsem", command=win.destroy).pack(pady=(0, 14))
            win.bind("<Escape>", lambda e: win.destroy())
            return
        if skipped:
            ttk.Label(win, foreground=C_WARN, wraplength=620, justify="left",
                      text=f"⚠ {len(skipped)} almappát kihagyok (nem dolgozói mappa: "
                           f"nincs benne 01/02 és felismert irat sem): " +
                           ", ".join(r.name for r in skipped[:6]) +
                           (" …" if len(skipped) > 6 else "")).pack(anchor="w",
                                                                    padx=14, pady=(0, 6))

        # Iratonkénti jelölőnégyzet: a mozgatás nem visszavonható, ezért a
        # felhasználó döntsön soronként — ne „mindent vagy semmit” legyen. A
        # mozgatható sorok alapból bejelölve; a tippek is, de halványan jelölve.
        cl = checklist_box(
            win, ("Dolgozó", "Fájl", "Hova", "Miért"), (150, 330, 120, 220), 18,
            on_change=lambda n: go.configure(
                text=f"Áthelyezés ({n} fájl)",
                state=("normal" if n else "disabled")))
        self.tidy_cl = cl

        row = ttk.Frame(win)
        row.pack(fill="x", padx=14, pady=12)
        go = ttk.Button(row, text="Áthelyezés")
        sorok = []
        for name in hu_sorted(list(plans)):
            folder, t = plans[name]
            for rel, dst, reason, sure in t:
                if not dst:
                    continue                   # marad a gyökérben: nincs mit mozgatni
                sorok.append(((folder, rel, dst, reason, sure),
                              (name, rel, dst, ("" if sure else "TIPP: ") + reason),
                              not sure))
        cl.fill(sorok)

        def only_dirs():
            made = 0
            for r in ok_rows:                  # a kihagyott almappákba nem nyúlunk
                try:
                    made += len(ensure_work_dirs(r.folder))
                except OSError as e:
                    messagebox.showerror("Mappa létrehozása", str(e), parent=win)
                    break
            win.destroy()
            self._info(f"{made} mappa létrehozva.", ok=True)
            self.refresh()

        def move_all():
            pick = cl.selected()
            if not pick:                   # a gomb tiltva van; ez csak öv + nadrágtartó
                return
            if not messagebox.askyesno(
                    "Rendezés",
                    f"{len(pick)} fájl mozgatása a helyére.\n\n"
                    "Ez NEM visszavonható (a fájlok a mappán belül mozognak).\n"
                    "Folytatjuk?", parent=win):
                return
            # Mappánként csoportosítva: a migracio_vegrehajt egy dolgozóra dolgozik.
            per_folder = {}
            for folder, rel, dst, reason, sure in pick:
                per_folder.setdefault(folder, []).append((rel, dst, reason, sure))
            done, errs = 0, []
            for folder, t in per_folder.items():
                try:
                    ensure_work_dirs(folder)
                except OSError as e:
                    errs.append((folder, str(e)))
                    continue
                d, e = migracio_vegrehajt(folder, t)
                done += d
                errs += e
            win.destroy()
            self.refresh()
            if errs:
                messagebox.showwarning(
                    "Rendezés — részben",
                    f"{done} fájl a helyére került, {len(errs)} nem:\n\n" +
                    "\n".join(f"{r}: {m}" for r, m in errs[:8]))
            self._info(f"{done} fájl a helyére került." +
                       (f" {len(errs)} hiba." if errs else ""),
                       ok=not errs, warn=bool(errs))

        b = ttk.Button(row, text="Csak a mappák létrehozása", command=only_dirs)
        b.pack(side="left")
        # Az Áthelyezés gomb a lista fölött jött létre (a visszahívása állítja a
        # feliratát); itt kerül a helyére. Üres kijelölésnél tiltott: legalább egy
        # iratot ki kell választani.
        go.configure(command=move_all)
        go.pack(side="left", padx=8)
        ttk.Button(row, text="Mégsem", command=win.destroy).pack(side="right")
        b.focus_set()
        win.bind("<Escape>", lambda e: win.destroy())

    # ---------------- ellenőrzés és utólagos bélyegzés ----------------
    def _open_audit(self):
        """Minden PDF egyszeri átnézése: hol nincs bélyeg, hol idegen, hol tér el
        a névtől, és mi a tartalom szerint duplikátum (13.6)."""
        if not self.rows:
            self._info("Nincs beolvasott mappa.", warn=True)
            return
        self._info("Ellenőrzés…")
        self.update_idletasks()
        try:
            res = audit_folder(self.parent_dir, self.rules,
                               on_step=lambda k: (self._info(f"Ellenőrzés… {k} PDF"),
                                                  self.update_idletasks()))
        except OSError as e:
            self._info(f"Az ellenőrzés nem futott le: {e}", warn=True)
            return
        self._info(f"{res['seen']} PDF átnézve.", ok=True)

        win = tk.Toplevel(self)
        win.title("Ellenőrzés és utólagos bélyegzés")
        win.transient(self.winfo_toplevel())
        win.grab_set()
        ttk.Label(win, wraplength=640, justify="left",
                  text=f"{res['seen']} PDF átnézve. "
                       f"{len(res['stampable'])} bélyegezhető utólag, "
                       f"{len(res['misplaced'])} rossz helyen, "
                       f"{len(res['foreign'])} idegen bélyeg, "
                       f"{len(res['mismatch'])} eltérő típus, "
                       f"{len(res['dupes'])} tartalom-azonos csoport.").pack(
            anchor="w", padx=14, pady=(14, 6))

        txt = tk.Text(win, width=88, height=22, wrap="none")
        txt.pack(fill="both", expand=True, padx=14)

        def section(title, lines):
            if not lines:
                return
            txt.insert(tk.END, title + "\n")
            for ln in lines:
                txt.insert(tk.END, "   " + ln + "\n")
            txt.insert(tk.END, "\n")

        section(f"BÉLYEGEZHETŐ UTÓLAG ({len(res['stampable'])}) — a névből és a helyből",
                [f"{w}\\{rel}  →  {rule.name} / {sub}"
                 for w, rel, _p, rule, sub in res["stampable"][:200]])
        section(f"ROSSZ HELYEN ({len(res['misplaced'])}) — a nevét felismerjük, de nem "
                f"a {DIR_PREP}/{DIR_UP} mappában fekszik",
                [f"{w}\\{rel}  →  {rule.name}"
                 for w, rel, _p, rule in res["misplaced"][:200]])
        section(f"IDEGEN BÉLYEG ({len(res['foreign'])}) — más dolgozó irata?",
                [f"{w}\\{rel}  →  a bélyeg szerint: {other}"
                 for w, rel, other in res["foreign"]])
        section(f"A BÉLYEG ÉS A NÉV ELTÉR ({len(res['mismatch'])}) — a név az igazság",
                [f"{w}\\{rel}  →  bélyeg: {bt} · név: {nt}"
                 for w, rel, bt, nt in res["mismatch"]])
        section(f"TARTALOM-AZONOS ({len(res['dupes'])} csoport)",
                [" = ".join(f"{w}\\{rel}" for w, rel in g) for g in res["dupes"]])
        section(f"BÉLYEG ÉS FELISMERT NÉV SINCS ({len(res['unknown'])}) — kézzel",
                [f"{w}\\{rel}" for w, rel in res["unknown"][:60]])
        if txt.index("end-1c") == "1.0":
            txt.insert(tk.END, "Minden irat bélyegzett, és nincs ütközés.\n")
        txt.configure(state="disabled")

        row = ttk.Frame(win)
        row.pack(fill="x", padx=14, pady=12)

        def do_stamp():
            ok, errs = stamp_missing(res["stampable"])
            win.destroy()
            self.refresh()
            if errs:
                messagebox.showwarning(
                    "Bélyegzés — részben",
                    f"{ok} irat bélyegezve, {len(errs)} nem:\n\n" +
                    "\n".join(f"{a}: {b}" for a, b in errs[:8]))
            self._info(f"{ok} irat utólag bélyegezve." +
                       (f" {len(errs)} hiba." if errs else ""),
                       ok=not errs, warn=bool(errs))

        if res["stampable"]:
            ttk.Button(row, text=f"Bélyegzés ({len(res['stampable'])} irat)",
                       command=do_stamp).pack(side="left")
        if res["misplaced"]:
            # Az áthelyezés a Rendezés párbeszédében történik (iratonkénti
            # jelölőnégyzettel) — nem építünk belőle másodikat.
            ttk.Button(row, text=f"Áthelyezés… ({len(res['misplaced'])})",
                       command=lambda: (win.destroy(), self._open_tidy())).pack(
                side="left", padx=6)
        ttk.Button(row, text="Átnevezés…",
                   command=lambda: (win.destroy(), self._open_rename())).pack(side="left")
        ttk.Button(row, text="Bezárás", command=win.destroy).pack(side="right")
        win.bind("<Escape>", lambda e: win.destroy())

    # ---------------- visszamenőleges átnevezés az egységes metodikára ----------------
    def _open_rename(self):
        """A meglévő iratok átnevezése a „(aláírt, fotóval ellátva)” metodikára
        (kepek-pdf-terv.md 14.1). A bélyeg a bizonyíték, a név a tartalék; ahol
        egyik sem dönt, a sor TIPP-ként, kijelöletlenül jön — ott nem tippelünk."""
        if not self.rows:
            self._info("Nincs beolvasott mappa.", warn=True)
            return
        self._info("Nevek vizsgálata…")
        self.update_idletasks()
        ikt = self.app.tabs.get("Iktató")
        try:
            terv = rename_plan(self.parent_dir, self.rules,
                               ikt.types if ikt else None)
        except OSError as e:
            self._info(f"A vizsgálat nem futott le: {e}", warn=True)
            return
        jo = [t for t in terv if t[2]]
        elakadt = [t for t in terv if not t[2]]
        if not jo:
            self._info(f"Minden irat neve megfelel a metodikának."
                       + (f" {len(elakadt)} iratnál nem lehet eldönteni." if elakadt else ""),
                       ok=not elakadt, warn=bool(elakadt))
            return

        win = tk.Toplevel(self)
        win.title("Átnevezés az egységes metodikára")
        win.transient(self.winfo_toplevel())
        win.grab_set()
        ttk.Label(win, wraplength=760, justify="left",
                  text=f"{len(jo)} irat neve tér el a metodikától "
                       f"(„Név Doktípus (aláírt, fotóval ellátva).pdf”). "
                       f"A bélyeggel ellátottaknál a típus bizonyított, a többinél a "
                       f"felismert névből jön. Az átnevezés nem ír felül meglévő "
                       f"iratot: ütközésnél (2), (3) … lesz belőle."
                       + (f"\n\n⚠ {len(elakadt)} iratnál se bélyeg, se egyértelmű név — "
                          f"azokhoz nem nyúlunk." if elakadt else "")).pack(
            anchor="w", padx=14, pady=(14, 8))

        self.rename_cl = cl = checklist_box(
            win, ("Dolgozó", "Mostani név", "Új név", "Miből"),
            (140, 300, 300, 100), 18,
            on_change=lambda n: go.configure(
                text=f"Átnevezés ({n} irat)",
                state=("normal" if n else "disabled")))
        row = ttk.Frame(win)
        row.pack(fill="x", padx=14, pady=12)
        go = ttk.Button(row, text="Átnevezés")
        cl.fill([(t, (t[0], os.path.basename(t[1]), t[2], t[3]), not t[4]) for t in jo])

        def do_rename():
            pick = cl.selected()
            if not pick:
                return
            if not messagebox.askyesno(
                    "Átnevezés",
                    f"{len(pick)} irat átnevezése.\n\n"
                    "A fájlok a helyükön maradnak, csak a nevük változik.\n"
                    "Folytatjuk?", parent=win):
                return
            done, errs = rename_apply(self.parent_dir, pick)
            win.destroy()
            self.refresh()
            if errs:
                messagebox.showwarning(
                    "Átnevezés — részben",
                    f"{done} irat átnevezve, {len(errs)} nem:\n\n" +
                    "\n".join(f"{a}: {b}" for a, b in errs[:8]))
            self._info(f"{done} irat átnevezve." + (f" {len(errs)} hiba." if errs else ""),
                       ok=not errs, warn=bool(errs))

        go.configure(command=do_rename)
        go.pack(side="left")
        ttk.Button(row, text="Mégsem", command=win.destroy).pack(side="right")
        win.bind("<Escape>", lambda e: win.destroy())

    # ---------------- kötegelt tömörítés ----------------
    def _open_shrink(self):
        """Minden 5 MB feletti PDF tömörítése egy körben. Az előző példány a
        dolgozó .eredeti mappájába kerül, és naplósort is kap."""
        jobs = [(r.name, r.folder, rel, sz)
                for r in self.rows for rel, sz in sorted(r.big.items())]
        if not jobs:
            self._info("Nincs 5 MB feletti PDF.", ok=True)
            return
        win = tk.Toplevel(self)
        win.title("Kötegelt tömörítés")
        win.transient(self.winfo_toplevel())
        win.grab_set()
        ttk.Label(win, wraplength=620, justify="left",
                  text=f"{len(jobs)} PDF van a feltöltési korlát ({mb(UPLOAD_LIMIT)}) "
                       f"fölött. A tömörítés csak a beágyazott képeket kódolja újra, "
                       f"lépcsőnként; az előző példány a dolgozó {DIR_PREP} "
                       f"mappájába kerül.").pack(anchor="w", padx=14, pady=(14, 6))
        txt = tk.Text(win, width=80, height=14, wrap="none")
        txt.pack(fill="both", expand=True, padx=14)
        for who, _f, rel, sz in jobs:
            txt.insert(tk.END, f"   {who}\\{rel} — {mb(sz)}\n")
        txt.configure(state="disabled")
        lbl = tk.StringVar(value="")
        ttk.Label(win, textvariable=lbl).pack(anchor="w", padx=14, pady=(6, 0))
        pb = ttk.Progressbar(win, maximum=len(jobs))
        pb.pack(fill="x", padx=14, pady=4)
        row = ttk.Frame(win)
        row.pack(fill="x", padx=14, pady=12)
        self._shrink_stop = False
        go = ttk.Button(row, text=f"Tömörítés ({len(jobs)} PDF)")
        go.pack(side="left")
        ttk.Button(row, text="Mégsem",
                   command=lambda: (setattr(self, "_shrink_stop", True),
                                    win.destroy())).pack(side="right")
        go.configure(command=lambda: (go.state(["disabled"]),
                                      self._shrink_jobs(jobs, win, pb, lbl)))
        win.bind("<Escape>", lambda e: (setattr(self, "_shrink_stop", True),
                                        win.destroy()))

    def _shrink_jobs(self, jobs, win, pb, lbl, i=0, acc=None):
        """Fájlonként egy shrink_later-lánc: a felület a lépcsők között él."""
        acc = acc if acc is not None else {"ok": 0, "fail": [], "big": []}
        if self._shrink_stop or i >= len(jobs):
            if win.winfo_exists():
                win.destroy()
            self.refresh()
            if acc["fail"]:
                messagebox.showwarning(
                    "Tömörítés — részben",
                    f"{acc['ok']} PDF tömörítve, {len(acc['fail'])} nem:\n\n" +
                    "\n".join(f"{a}: {b}" for a, b in acc["fail"][:8]))
            if acc["big"]:
                messagebox.showwarning(
                    "A korlát fölött maradt",
                    "A legerősebb lépcső után is a korlát fölött maradt:\n\n" +
                    "\n".join(acc["big"][:8]) +
                    "\n\nÉrdemes kevesebb oldalra bontani (Összeállító).")
            self._info(f"{acc['ok']} PDF tömörítve." +
                       (f" {len(acc['fail'])} hiba." if acc["fail"] else ""),
                       ok=not acc["fail"], warn=bool(acc["fail"]))
            return
        who, folder, rel, sz = jobs[i]
        path = os.path.join(folder, rel)
        pb.configure(value=i)
        lbl.set(f"{i + 1}/{len(jobs)}  {who}: {os.path.basename(rel)}")

        def nxt():
            self.after(1, lambda: self._shrink_jobs(jobs, win, pb, lbl, i + 1, acc))

        try:
            with open(path, "rb") as f:
                data = f.read()
            d = pymupdf.open(path)
            pages = d.page_count
            d.close()
        except Exception as e:
            acc["fail"].append((f"{who}\\{rel}", str(e)[:80]))
            nxt()
            return

        def done(out, step, err):
            try:
                if err:
                    raise err
                backup_existing(path)                  # a Visszavonás helye marad
                write_pdf_verified(out, path, pages)
                acc["ok"] += 1
                if len(out) > UPLOAD_LIMIT:
                    acc["big"].append(f"{who}\\{rel} — {mb(len(out))}")
                r0, _ = match_rule(rel, self.rules)
                log_row(self.parent_dir, path,
                        os.path.join(who, os.path.dirname(rel)),
                        os.path.basename(rel), r0.name if r0 else "",
                        f"TOMORITVE {mb(sz)}->{mb(len(out))}")
            except Exception as e:
                acc["fail"].append((f"{who}\\{rel}", str(e)[:80]))
            nxt()

        shrink_process(self, data, on_done=done,
                       on_step=lambda dpi, q: lbl.set(
                           f"{i + 1}/{len(jobs)}  {who}: {os.path.basename(rel)} "
                           f"— {dpi} DPI, Q{q}"))

    # ---------------- CSV ----------------
    def _export_csv(self):
        if not self.rows:
            self._info("Nincs beolvasott mappa.", warn=True)
            return
        p = filedialog.asksaveasfilename(
            title="CSV export", initialdir=self.parent_dir,
            initialfile=f"attekinto-{datetime.date.today().isoformat()}.csv",
            defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not p:
            return
        nreq = sum(1 for r in self.rules if r.required)
        nopt = len(self.rules) - nreq
        try:
            with open(p, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f, delimiter=";")
                w.writerow(["Dolgozó"] + [r.name for r in self.rules] +
                           ["Arckép", "Melléklet", "Kötelező", "Ajánlott",
                            "Beadható", "5 MB feletti PDF", "Besorolatlan"])
                for row in self.rows:
                    w.writerow([row.name] +
                               [row.docs[r.id].cell for r in self.rules] +
                               [len(row.photos), len(row.extra_pdfs),
                                f"{row.ready_required}/{nreq}",
                                f"{row.ready_optional}/{nopt}",
                                "igen" if row.beadhato else "nem", len(row.big),
                                len(row.unsorted)])
            self._info(f"Exportálva: {os.path.basename(p)}", ok=True)
        except OSError as e:
            messagebox.showerror("CSV export", str(e))

    def _info(self, txt, warn=False, ok=False):
        self.msg.set(txt)
        try:
            self.msg_lbl.configure(
                foreground=C_WARN if warn else (C_OK if ok else ""))
        except Exception:
            pass
        if hasattr(self.app, "status"):
            self.app.status(txt)



# ──────────────────────────── 7. fül: összeállító ────────────────────────────
# Képekből és PDF-kötegekből iratok egy lépésben. Az oldalak doktípus-címkét
# kapnak; egy irat = az azonos címkéjű oldalak a rács sorrendjében. Az Iktatás a
# dolgozó mappájába írja őket az Iktató közös magjával (név, ütközés, .eredeti,
# napló, 5 MB). A döntések: szetvago-terv.md, 14. fejezet.
THUMB = 160                                   # bélyegkép befoglaló mérete (px)
CELL_W, CELL_H = THUMB + 16, THUMB + 34       # csempe: kép + fájlnév
PRESETS = (("Irodai · 200 DPI", 200, 75),     # (felirat, DPI, JPEG-minőség)
           ("Archív · 300 DPI", 300, 85),
           ("E-mail · 150 DPI", 150, 65))
A4_LONG_IN = 842 / 72                         # az A4 hosszabb oldala hüvelykben
SRC_EXT = IMG_EXT + (".pdf",)
PANEL_W = 318                                 # a jobb oldali panel szélessége
# A típuspaletta legfeljebb ennyi sort mutat, a többi görgethető. Korlát nélkül a
# lista a típusok számával nőtt, és 650 px magas ablakban 15 típustól az Iktatás
# gomb kicsúszott a látható részből (mérve; szerkeszto-terv.md 17.).
PAL_ROWS = 11
# Azonos tónusú, egymástól jól megkülönböztethető készlet — fehér szöveggel
# mindegyik olvasható marad (a régi, teljesen telített színek harsányak voltak).
LABEL_COLORS = ("#2f6fe4", "#0f8f8f", "#7c4dd6", "#c07c0a", "#d6456b",
                "#2f8f4e", "#4455c7", "#cd6329", "#1a7fa8", "#9a3fb5", "#5b6678")
COL_NOLABEL = "#8b94a6"                       # a palettán már nem szereplő típus


def image_page_jpeg(path, rot, dpi, quality, gray, page=0):
    """Egy képoldal -> (JPEG-bájtok, szélesség px, magasság px).
    A hosszabb oldal legfeljebb dpi × A4 hosszabb oldala; nagyítás soha.
    Az EXIF-forgatást a MuPDF magától alkalmazza, a `rot` a felhasználói ráadás."""
    src = pymupdf.open(path)
    try:
        pg = src[page]
        info = pg.get_image_info()
        native = max(info[0]["width"], info[0]["height"]) if info else \
            max(pg.rect.width, pg.rect.height)
        z = min(native, dpi * A4_LONG_IN) / max(pg.rect.width, pg.rect.height)
        pix = pg.get_pixmap(matrix=pymupdf.Matrix(z, z).prerotate(rot))
        if gray:
            pix = pymupdf.Pixmap(pymupdf.csGRAY, pix)
        return pix.tobytes("jpeg", jpg_quality=quality), pix.width, pix.height
    finally:
        src.close()


def add_image_page(out, jpeg, w, h, dpi, fit_a4):
    """Új lap a képpel — a JPEG újrakódolás nélkül (DCTDecode) kerül be."""
    if fit_a4:
        r = pymupdf.paper_rect("a4")
        if w > h:                                  # fekvő kép -> fekvő lap
            r = pymupdf.Rect(0, 0, r.height, r.width)
    else:
        r = pymupdf.Rect(0, 0, w * 72 / dpi, h * 72 / dpi)
    page = out.new_page(width=r.width, height=r.height)
    page.insert_image(page.rect, stream=jpeg)      # arányt tart, középre tesz


def add_item_page(out, it, dpi, quality, gray, fit_a4, srcs):
    """Az elem oldala az `out` végére. A PDF-oldal veszteségmentesen megy át (a
    képei bájtra azonosak, a forgatás csak /Rotate); a kép újrakódolva.
    `srcs`: a már megnyitott forrás-PDF-ek (útvonal -> dokumentum)."""
    if not it.path.lower().endswith(".pdf"):
        jpeg, w, h = image_page_jpeg(it.path, it.rot, dpi, quality, gray, it.page)
        add_image_page(out, jpeg, w, h, dpi, fit_a4)
        return
    if it.path not in srcs:
        srcs[it.path] = open_checked(it.path)
    out.insert_pdf(srcs[it.path], from_page=it.page, to_page=it.page)
    if it.rot:                      # a bélyegképpel azonos irány: óramutató szerint
        pg = out[-1]
        pg.set_rotation((pg.rotation + it.rot) % 360)


def page_ranges(nums) -> str:
    """Oldalindexek (0-tól) -> „1-3,5” (1-től), a megadott sorrendben."""
    out, start = [], None
    for i, n in enumerate(nums):
        start = n if start is None else start
        if i + 1 == len(nums) or nums[i + 1] != n + 1:
            out.append(str(start + 1) if start == n else f"{start + 1}-{n + 1}")
            start = None
    return ",".join(out)


def source_desc(items) -> str:
    """A napló „forrás” mezője: fájlonként, PDF-nél az oldalakkal."""
    by = {}
    for it in items:
        by.setdefault(it.path, []).append(it.page)
    return "; ".join(p + (f" [{page_ranges(n)}]" if p.lower().endswith(".pdf") else "")
                     for p, n in by.items())


def tint(color: str, k: float = 0.86) -> str:
    """A szín világos árnyalata (fehérrel keverve) — listához, ahol sok sor van
    egymás alatt: a telített szín ott harsány, a csempe sávján viszont marad."""
    c = color.lstrip("#")
    r, g, b = (int(c[i:i + 2], 16) for i in (0, 2, 4))
    return "#%02x%02x%02x" % tuple(int(v + (255 - v) * k) for v in (r, g, b))


def palette_types(ikt_types, rules) -> list:
    """A típuspaletta: az Iktató típusai és az Áttekintő nem DocGen-szabályai, az
    Áttekintő oszlopsorrendjében (a kötelezők elöl); a szabályra nem illeszkedő
    saját típusok a végén. -> [(típusnév, szabály | None)]"""
    out, used = [], set()
    for r in rules:
        t = next((t for t in ikt_types
                  if match_rule(target_name("X", t), rules) == (r, False)), None)
        if t:
            out.append((t, r))
            used.add(t)
        elif not r.generated:
            out.append((r.name, r))
    return out + [(t, None) for t in ikt_types if t not in used]


def resolve_worker(text: str, dirs: list):
    """A Dolgozó mező szövegéből a mappa: pontos (ékezet- és kisbetű-független)
    egyezés, vagy az egyetlen részegyezés. -> (mappa | None, találatok)"""
    f = strip_accents(text.strip())
    if not f:
        return None, list(dirs)
    hits = [d for d in dirs if f in strip_accents(d)]
    exact = [d for d in hits if strip_accents(d) == f]
    one = exact if len(exact) == 1 else hits if len(hits) == 1 else []
    return (one[0] if one else None), hits


@dataclass(eq=False)             # azonosság szerint hashel: a kijelölés halmaz
class PageItem:
    path: str                    # kép vagy PDF
    page: int = 0                # oldalszám a fájlban (képnél 0)
    rot: int = 0                 # felhasználói forgatás: 0 / 90 / 180 / 270
    thumb: object = None         # tk.PhotoImage, ha már elkészült
    bad: str = ""                # hibaüzenet, ha az oldal nem olvasható
    doc: object = None           # OutDoc — a címke; None: kimarad

    def paged(self) -> bool:
        """PDF-oldal vagy többoldalas kép egy oldala: a névhez az oldalszám is kell."""
        return bool(self.page) or self.path.lower().endswith(".pdf")

    def label(self) -> str:
        n = os.path.basename(self.path)
        return f"{self.page + 1}. o. · {n}" if self.paged() else n


@dataclass(eq=False)
class OutDoc:
    """Egy kimeneti irat címkéje. Az oldalait nem tároljuk: a rács azon elemei,
    amelyeken ez a címke van, a rács sorrendjében — így nem csúszhat el."""
    doc_type: str
    suffix: str
    # Fotóigényes nyomtatványnál: rajta van-e már az arckép. Iratonkénti, mert egy
    # köteg formanyomtatványt és mást is tartalmaz (szetvago-terv.md 15.).
    arckep_kesz: bool = False


class PageViewer(tk.Toplevel):
    """Nagyított előnézet — nem modális, közben a rácsban lehet vonszolni, és a
    Backspace itt is leveszi a címkét. A nagyítás az illesztéshez képest értendő,
    lapozáskor a nézettel együtt megmarad; képnél a felső határa a natív felbontás."""

    HINT = ("Backspace: címke le · görgő: nagyítás · húzás: mozgatás · "
            "←/→: előző/következő · dupla kattintás: illesztés · Esc: bezárás")

    def __init__(self, tab):
        super().__init__(tab)
        self.tab = tab
        self.transient(tab.winfo_toplevel())
        h = int(self.winfo_screenheight() * 0.8)
        self.geometry(f"{int(h * 0.85)}x{h}")
        self.c = tk.Canvas(self, bg=COL_CANVAS, highlightthickness=0)
        self.c.pack(fill="both", expand=True)
        ttk.Label(self, text=self.HINT, anchor="center").pack(fill="x", pady=2)
        self.item = self.doc = self.photo = None
        self.zk = None               # nagyítás az illesztéshez képest; None = illesztve
        self.W = self.H = 1          # a görgethető terület mérete
        self._want = self._at = self._job = None
        c = self.c
        c.bind("<Configure>", lambda e: self._later(self._render))
        c.bind("<MouseWheel>", self._wheel)
        c.bind("<ButtonPress-1>", lambda e: c.scan_mark(e.x, e.y))
        c.bind("<B1-Motion>", lambda e: c.scan_dragto(e.x, e.y, gain=1))
        c.bind("<Double-Button-1>", lambda e: self._fit())
        self.bind("<Left>", lambda e: self._step(-1))
        self.bind("<Right>", lambda e: self._step(1))
        self.bind("<Escape>", lambda e: self.close())
        self.bind("<Key>", lambda e: self.tab._key(e, self.item))
        self.protocol("WM_DELETE_WINDOW", self.close)

    def _later(self, fn, ms=40):
        if self._job:
            self.after_cancel(self._job)
        self._job = self.after(ms, lambda: (setattr(self, "_job", None), fn()))

    def show(self, item, keep_view=False):
        view = (self.c.xview()[0], self.c.yview()[0]) if keep_view else None
        if self.doc:
            self.doc.close()
        self.item = item
        try:
            self.doc = pymupdf.open(item.path)
        except Exception:
            self.doc = None
        self._render()
        if view:
            self.c.xview_moveto(view[0])
            self.c.yview_moveto(view[1])
        self.tab.sel, self.tab.anchor = {item}, item      # a rácsban is ez legyen kijelölve
        self.tab._redraw()
        self.lift()
        self.focus_set()

    def _render(self):
        c = self.c
        cw, ch = max(100, c.winfo_width()), max(100, c.winfo_height())
        c.delete("all")
        items = self.tab.items
        pos = f"{items.index(self.item) + 1}/{len(items)}" if self.item in items else "–"
        name = self.item.label()
        if self.item.doc:
            name += f" · {self.item.doc.doc_type}"
        if not self.doc:
            self.W, self.H = cw, ch
            c.configure(scrollregion=(0, 0, cw, ch))
            c.create_text(cw / 2, ch / 2, text="⚠ nem olvasható", fill=UI["warn"],
                          font=("Segoe UI", 12))
            self.title(f"{pos} · {name}")
            return
        page, rot = self.doc[self.item.page], self.item.rot
        r = page.rect
        pw, ph = (r.height, r.width) if rot in (90, 270) else (r.width, r.height)
        fz = fit_zoom(pw, ph, cw, ch)
        info = page.get_image_info()
        if info and not self.item.path.lower().endswith(".pdf"):
            native = max(info[0]["width"], info[0]["height"]) / max(r.width, r.height)
        else:
            native = ZOOM_MAX        # PDF-oldal: a vektoros tartalom tetszőlegesen nagyítható
        k = 1.0 if self.zk is None else max(1.0, min(max(1.0, native / fz), self.zk))
        self.zk = None if k <= 1.0 else k
        z = fz * k
        pix = page.get_pixmap(matrix=pymupdf.Matrix(z, z).prerotate(rot))
        self.photo = tkimg(pix, "ppm")
        self.W, self.H = max(cw, pix.width), max(ch, pix.height)
        c.create_image(self.W / 2, self.H / 2, image=self.photo)
        c.configure(scrollregion=(0, 0, self.W, self.H))
        self.title(f"{pos} · {name} · " + ("illesztve" if self.zk is None else f"{k:.1f}×"))

    def _wheel(self, e):
        """A görgetés összegyűlik, és egyszerre renderelődik (nagy képnél lassú)."""
        self._want = (self._want or self.zk or 1.0) * (ZOOM_STEP if e.delta > 0 else 1 / ZOOM_STEP)
        self._at = (e.x, e.y)
        self._later(self._apply_zoom)
        return "break"

    def _apply_zoom(self):
        c, (ex, ey) = self.c, self._at
        fx, fy = c.canvasx(ex) / self.W, c.canvasy(ey) / self.H    # ez marad a kurzor alatt
        self.zk, self._want = self._want, None
        self._render()
        c.xview_moveto((fx * self.W - ex) / self.W)
        c.yview_moveto((fy * self.H - ey) / self.H)

    def _fit(self):
        self.zk = None
        self._render()

    def _step(self, d):
        items = self.tab.items
        if self.item in items and 0 <= items.index(self.item) + d < len(items):
            self.show(items[items.index(self.item) + d], keep_view=True)

    def close(self):
        if self.doc:
            self.doc.close()
        self.tab.viewer = None
        self.destroy()


class ComposerTab(ttk.Frame):
    """Összeállító: képek és PDF-oldalak bélyegképrácsa doktípus-címkékkel, és
    kötegelt iktatás. Szálak nincsenek: a bélyegképek és az iktatás is
    after()-láncban, oldalanként futnak, így a felület élő marad (és a PyMuPDF
    szálbiztonsága sem kérdés)."""

    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.folder = script_dir()   # munkamappa: a dolgozói mappák szülője
        self.last_dir = None         # ahonnan legutóbb forrást adtunk hozzá
        self.items = []
        self.sel = set()             # kijelölt PageItem-ek (a sorrendezés nem érinti)
        self.anchor = None           # a Shift+kattintásos tartomány kiinduló eleme
        self.dirs = []               # dolgozói mappák
        self.who = None              # a Dolgozó mezőből feloldott mappanév
        self.palette = []            # [(típus, szabály | None)] — sorszám = billentyű
        self.docs = {}               # típus -> OutDoc
        self.cur_doc = None          # a Kimenet listában kijelölt irat
        self.last_batch = None       # az utolsó iktatás, a visszavonáshoz
        self.preset = tk.IntVar(value=0)
        self.gray = tk.BooleanVar(value=False)
        self.fit_a4 = tk.BooleanVar(value=True)
        self.who_text = tk.StringVar(value="")
        self.who_msg = tk.StringVar(value="")
        self.suffix = tk.StringVar(value="")
        self.arckep_kesz = tk.BooleanVar(value=False)   # a kijelölt iraté
        self.out_info = tk.StringVar(value="")
        self.info = tk.StringVar(value="")
        self._quiet = False          # az Utótag mező programból íródik
        self._drag = None            # (index, kezdő x, kezdő y)
        self._thumb_job = None
        self._b = None               # a futó iktatás állapota
        self.viewer = None           # a nyitott nagyító ablak (PageViewer), ha van
        self._build()
        self._redraw()

    def _build(self):
        # A jobb panel görgethető: 940x620-as (minimális) ablakban 647 px kellett és
        # 466 jutott — az Utótag mező és az „arckép rajta” jelölő levágódott (mérve).
        _shell, right = scroll_panel(self, PANEL_W, side="right", padx=(0, 8))
        left = ttk.Frame(self)
        left.pack(side="left", fill="both", expand=True)

        bar = ttk.Frame(left)
        bar.pack(fill="x", padx=8, pady=(8, 4))
        ttk.Button(bar, text="PDF / kép hozzáadása…", command=self._add_files).pack(side="left")
        ttk.Button(bar, text="Mappa hozzáadása…", command=self._add_dir).pack(side="left", padx=4)
        ttk.Button(bar, text="↺", width=3, command=lambda: self._rotate(-90)).pack(side="left", padx=(16, 2))
        ttk.Button(bar, text="↻", width=3, command=lambda: self._rotate(90)).pack(side="left")
        ttk.Button(bar, text="Kijelölt törlése", command=self._remove).pack(side="left", padx=(16, 4))
        ttk.Button(bar, text="Mind törlése", command=self._clear).pack(side="left")

        grid = ttk.Frame(left)
        grid.pack(fill="both", expand=True, padx=8, pady=4)
        self.canvas = tk.Canvas(grid, bg=COL_CANVAS, highlightthickness=0,
                                takefocus=1, height=180)
        sb = ttk.Scrollbar(grid, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=sb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.canvas.bind("<Configure>",
                         lambda e: debounce(self, "_cfg_job", self._redraw))
        self.canvas.bind("<ButtonPress-1>", self._press)
        # külön binding modifikátoronként (mint az Arckép fülön), nem a state-bit
        self.canvas.bind("<Control-ButtonPress-1>", self._press_ctrl)
        self.canvas.bind("<Shift-ButtonPress-1>", self._press_shift)
        self.canvas.bind("<B1-Motion>", self._motion)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.canvas.bind("<Double-Button-1>", self._open_viewer)
        self.canvas.bind("<Delete>", lambda e: self._remove())
        self.canvas.bind("<Key>", self._key)
        self.canvas.bind("<MouseWheel>", lambda e: (
            self.canvas.yview_scroll(-1 if e.delta > 0 else 1, "units"), "break")[1])
        ttk.Label(left, textvariable=self.info).pack(fill="x", padx=8)

        opt = ttk.Frame(left)
        opt.pack(fill="x", padx=8, pady=4)
        ttk.Label(opt, text="Képoldalak:").pack(side="left")
        pc = ttk.Combobox(opt, state="readonly", width=17, values=[p[0] for p in PRESETS])
        pc.current(self.preset.get())
        pc.bind("<<ComboboxSelected>>", lambda e: self.preset.set(pc.current()))
        pc.pack(side="left", padx=4)
        ttk.Checkbutton(opt, text="Szürkeárnyalatos",
                        variable=self.gray).pack(side="left", padx=(16, 0))
        ttk.Checkbutton(opt, text="A4-re illesztve (különben lap = kép)",
                        variable=self.fit_a4).pack(side="left", padx=16)

        run = ttk.Frame(left)
        run.pack(fill="x", padx=8, pady=4)
        self.pb = ttk.Progressbar(run, mode="determinate")
        self.pb.pack(side="left", fill="x", expand=True)
        ttk.Button(run, text="Mégsem", command=self._cancel).pack(side="left", padx=8)

        self.log = tk.Text(left, height=5, wrap="none", state="disabled", bg="#f7f7f7")
        self.log.pack(fill="x", padx=8, pady=(0, 8))

        # ── jobb oldali panel: dolgozó, típuspaletta, kimenet ──
        w = ttk.LabelFrame(right, text="Dolgozó (kötegenként egy)")
        w.pack(fill="x")
        self.picker = WorkerPicker(w, on_change=self._who_changed,
                                   on_select=lambda: self.canvas.focus_set(),
                                   wraplength=PANEL_W - 24)
        self.picker.pack(fill="x", padx=6, pady=(6, 6))
        self.who_text, self.who_msg = self.picker.var, self.picker.msg
        self.who_lbl, self.who_cb = self.picker.lbl, self.picker.cb

        p = ttk.LabelFrame(right, text="Doktípus — kattintással")
        p.pack(fill="x", pady=8)
        lf = ttk.Frame(p)
        lf.pack(fill="x", padx=6, pady=(6, 2))
        self.pal = tk.Listbox(lf, height=PAL_ROWS, activestyle="none", exportselection=False,
                              font=("Segoe UI", 9), highlightthickness=0, borderwidth=0)
        self.pal_sb = ttk.Scrollbar(lf, orient="vertical", command=self.pal.yview)
        self.pal.configure(yscrollcommand=self.pal_sb.set)
        self.pal.pack(side="left", fill="x", expand=True)
        self.pal.bind("<ButtonRelease-1>", self._pal_click)
        row = ttk.Frame(p)
        row.pack(fill="x", padx=6, pady=(2, 6))
        ttk.Button(row, text="Címke le", command=lambda: self._label(None)).pack(side="left")
        ttk.Button(row, text="Típusok…", command=self._edit_types).pack(side="right")
        ttk.Button(p, text="Címke a szövegből (ahol van)",
                   command=self._label_from_text).pack(fill="x", padx=6, pady=(0, 6))

        o = ttk.LabelFrame(right, text="Kimenet")
        o.pack(fill="both", expand=True)
        # Az Iktatás a görgethető panelen KÍVÜL, fix alsó sávban: kis ablakban eddig
        # a panel aljával együtt levágódott, most görgetés nélkül is ott van.
        go = ttk.Frame(_shell)
        go.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        self.btn_go = ttk.Button(go, text="Iktatás", command=self._iktat)
        self.btn_go.pack(side="left", fill="x", expand=True)
        ttk.Button(go, text="Visszavonás", command=self._undo).pack(side="left", padx=(6, 0))
        ttk.Label(o, textvariable=self.out_info, foreground=COL_WARN,
                  wraplength=PANEL_W - 24).pack(side="bottom", anchor="w", padx=6)
        sf = ttk.Frame(o)
        sf.pack(side="bottom", fill="x", padx=6, pady=(0, 2))
        self.arckep_cb = ttk.Checkbutton(sf, text="arckép rajta", state="disabled",
                                         variable=self.arckep_kesz,
                                         command=self._arckep_changed)
        self.arckep_cb.pack(side="left")
        ttk.Label(sf, text="(a kijelölt iraté)",
                  foreground=UI["ink_soft"]).pack(side="left", padx=6)
        sf2 = ttk.Frame(o)                      # két sor: a panel fix szélességű
        sf2.pack(side="bottom", fill="x", padx=6, pady=(2, 0))
        ttk.Label(sf2, text="Utótag:").pack(side="left")
        self.suffix_ent = ttk.Entry(sf2, textvariable=self.suffix, state="disabled")
        self.suffix_ent.pack(side="left", fill="x", expand=True, padx=4)
        self.suffix.trace_add("write", lambda *a: self._suffix_changed())
        # height=2 a KÉRT magasság; ha van hely, az expand=True kifeszíti. Négy sort
        # kérve a panel a szokásos ablakban is görgetni kezdett (mérve).
        self.tree = ttk.Treeview(o, columns=("name", "n", "note"), show="", height=2,
                                 selectmode="browse")
        self.tree.column("name", width=170, stretch=True)
        self.tree.column("n", width=40, anchor="e", stretch=False)
        self.tree.column("note", width=64, stretch=False)
        self.tree.pack(fill="both", expand=True, padx=6, pady=(6, 2))
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._doc_selected())

    def _write_log(self, txt):
        self.log.configure(state="normal")
        self.log.insert(tk.END, txt + "\n")
        self.log.see(tk.END)
        self.log.configure(state="disabled")

    # ---------------- munkamappa, dolgozó, paletta ----------------
    def set_folder(self, folder):
        self.folder = folder         # a források külön mappából jönnek — a lista marad
        self.refresh()

    def set_worker(self, name, force=False):
        """Az alapértelmezett dolgozó (a fülsor választója): váltáskor átvesszük,
        frissítéskor csak az üres mezőbe — a fülön kézzel választott megmarad."""
        if name and (force or not self.who_text.get().strip()):
            self.who_text.set(name)

    def refresh(self):
        """Dolgozói mappák és típuspaletta újra — mappaváltáskor és fülváltáskor
        (közben új dolgozói mappa vagy doktípus jöhetett)."""
        try:
            self.dirs = worker_dirs(self.folder)
        except OSError:
            self.dirs = []
        self.picker.set_dirs(self.dirs)
        ikt, att = self.app.tabs["Iktató"], self.app.tabs["Áttekintő"]
        self.palette = palette_types(ikt.types, att.rules)
        self.pal.delete(0, tk.END)
        for i, (t, _r) in enumerate(self.palette):
            self.pal.insert(tk.END, f"  {t}")
            c = LABEL_COLORS[i % len(LABEL_COLORS)]
            self.pal.itemconfig(i, background=tint(c), foreground=UI["ink"],
                                selectbackground=tint(c, 0.72),
                                selectforeground=UI["ink"])
        n = len(self.palette)
        self.pal.configure(height=max(1, min(PAL_ROWS, n)))
        if n > PAL_ROWS:                              # a többi sor görgetéssel érhető el
            self.pal_sb.pack(side="right", fill="y")
        else:
            self.pal_sb.pack_forget()
        self._who_changed()
        self._redraw()

    def _edit_types(self):
        ikt = self.app.tabs["Iktató"]
        TypeEditor(self, ikt.types, lambda items: (ikt._apply_types(items), self.refresh()))

    def _look(self, doc_type):
        """A címke sávja: (rövid név, szín) a palettából."""
        for i, (t, r) in enumerate(self.palette):
            if t == doc_type:
                return (r.short if r else t[:6]), LABEL_COLORS[i % len(LABEL_COLORS)]
        return doc_type[:6], COL_NOLABEL

    def _default_suffix(self, doc_type):
        """Mint az Iktatóban: DocGen-irat „aláírt”, útlevél, igazolás üres."""
        r = next((r for t, r in self.palette if t == doc_type), None)
        return "" if r and not r.generated else SUFFIX

    def _who_changed(self):
        self.who = self.picker.who
        self._refresh_out()

    # ---------------- címkézés ----------------
    def _pal_click(self, e):
        i = self.pal.nearest(e.y)
        self.pal.selection_clear(0, tk.END)
        if 0 <= i < len(self.palette):
            self._label(self.palette[i][0])
        self.canvas.focus_set()

    def _key(self, e, item=None):
        """Backspace: címke le a kijelöltekről (a nagyítóban a látott oldalról).

        A számbillentyűs címkézés megszűnt: 16-nál több egyedi doktípusnál az 1–9
        csak az első kilencet érte el, a többi típus néma maradt — a felhasználó
        joggal hitte hibásnak. Egy fél megoldás rosszabb, mint a kattintás."""
        if e.keysym != "BackSpace":
            return None
        if item is not None:
            self.sel = {item}
        self._label(None)
        return "break"

    def _label(self, doc_type):
        """A kijelölt oldalak címkéje (None: le). Utána a kijelölés az utolsó
        kijelölt utáni oldalra lép — így billentyűvel végig lehet menni a kötegen."""
        todo = [it for it in self.items if it in self.sel and not it.bad]
        if self._b or not todo:
            if not todo:
                self.app.status("Jelöld ki az oldalakat (kattintás, Ctrl/Shift+kattintás), "
                                "aztán kattints a Doktípus listában.")
            return
        doc = None
        if doc_type is not None:
            if doc_type not in self.docs:
                self.docs[doc_type] = OutDoc(doc_type, self._default_suffix(doc_type))
            doc = self.docs[doc_type]
        for it in todo:
            it.doc = doc
        nxt = self.items.index(todo[-1]) + 1
        if nxt < len(self.items):
            self.sel, self.anchor = {self.items[nxt]}, self.items[nxt]
            self._see(nxt)
        self._redraw()
        self._refresh_out()
        if self.viewer and len(self.sel) == 1:
            self.viewer.show(next(iter(self.sel)), keep_view=True)

    def _label_from_text(self):
        """A címke nélküli oldalakra a doktípus a SZÖVEGRÉTEGBŐL (DocGen-PDF vagy
        OCR-es szkenner). Szkennelt, szöveg nélküli lapon nem tud dönteni — azok
        maradnak kézi címkézésre."""
        rules = self._rules()
        hit, miss = 0, 0
        for it in self.items:
            if it.doc is not None or it.bad:
                continue
            r = text_rule(it.path, it.page, rules)
            t = next((t for t, rr in self.palette if rr and r and rr.id == r.id), None)
            if t is None:
                miss += 1
                continue
            if t not in self.docs:
                self.docs[t] = OutDoc(t, self._default_suffix(t))
            it.doc = self.docs[t]
            hit += 1
        self._redraw()
        self._refresh_out()
        self.app.status(f"Szövegréteg: {hit} oldal megcímkézve" +
                        (f", {miss} oldalon nincs mire támaszkodni (kézzel)."
                         if miss else "."))

    # ---------------- kimenet ----------------
    def _out_docs(self):
        """[(OutDoc, oldalai)] — az iratok az első oldaluk rácsbeli helye szerint."""
        docs = {}
        for it in self.items:
            if it.doc is not None and not it.bad:
                docs.setdefault(it.doc, []).append(it)
        return list(docs.items())

    def _doc_name(self, d):
        r = doc_type_rule(d.doc_type, self._rules())
        return target_name(self.who or "Dolgozó", d.doc_type, d.suffix,
                           photo=bool(r and r.arckep and d.arckep_kesz))

    def _doc_sub(self, d) -> str:
        """Ennek az iratnak az alkönyvtára a dolgozó mappáján belül."""
        return target_subdir(d.doc_type, self._rules(), d.arckep_kesz)

    def _rules(self) -> list:
        att = getattr(self.app, "tabs", {}).get("Áttekintő")
        return att.rules if att else rules_from(default_settings())

    def _doc_dir(self, d) -> str:
        return os.path.join(self.folder, self.who or "", self._doc_sub(d))

    def _refresh_out(self):
        t = self.tree
        docs = self._out_docs()
        t.delete(*t.get_children())
        for n, (d, its) in enumerate(docs):
            color = self._look(d.doc_type)[1]
            exists = self.who and os.path.exists(os.path.join(self._doc_dir(d), self._doc_name(d)))
            note = "⚠ létezik" if exists else ""
            if self._doc_sub(d) == DIR_PREP:
                note = (note + " · " if note else "") + "→ előkészített"
            t.insert("", "end", iid=str(n),
                     values=(f"{d.doc_type} {d.suffix}".strip(), f"{len(its)} o.", note),
                     tags=("c" + color[1:],))
            t.tag_configure("c" + color[1:], background=color, foreground="white")
        keep = [d for d, _ in docs]
        if self.cur_doc in keep:
            t.selection_set(str(keep.index(self.cur_doc)))
        else:
            self.cur_doc = None
            self._quiet = True
            self.suffix.set("")
            self.arckep_kesz.set(False)
            self._quiet = False
            self.suffix_ent.state(["disabled"])
            self.arckep_cb.state(["disabled"])
        free = sum(1 for it in self.items if it.doc is None and not it.bad)
        self.out_info.set(f"{free} oldal címke nélkül — kimarad" if free and docs else "")
        self.btn_go.configure(text=f"Iktatás ({len(docs)} irat)" if docs else "Iktatás")

    def _doc_selected(self):
        """Egy irat a Kimenet listában: az oldalai kijelölődnek, az utótagja szerkeszthető."""
        s, docs = self.tree.selection(), self._out_docs()
        if not s or int(s[0]) >= len(docs) or docs[int(s[0])][0] is self.cur_doc:
            return                   # a lista újrarajzolása is ide fut — az nem kattintás
        self.cur_doc, its = docs[int(s[0])]
        self._quiet = True
        self.suffix.set(self.cur_doc.suffix)
        self.arckep_kesz.set(self.cur_doc.arckep_kesz)
        self._quiet = False
        self.suffix_ent.state(["!disabled"])
        r = doc_type_rule(self.cur_doc.doc_type, self._rules())
        self.arckep_cb.state(["!disabled" if (r and r.arckep) else "disabled"])
        self.sel, self.anchor = set(its), its[0]
        self._see(self.items.index(its[0]))
        self._redraw()

    def _suffix_changed(self):
        if not self._quiet and self.cur_doc:
            self.cur_doc.suffix = self.suffix.get()
            self._refresh_out()

    def _arckep_changed(self):
        if not self._quiet and self.cur_doc:
            self.cur_doc.arckep_kesz = self.arckep_kesz.get()
            self._refresh_out()          # a célmappa jelzése frissül

    # ---------------- lista ----------------
    def _add_files(self):
        pat = " ".join("*" + e for e in SRC_EXT)
        self._add(filedialog.askopenfilenames(
            title="PDF-ek és képek kiválasztása",
            initialdir=self.last_dir or recall("mellekletek", self.folder),
            filetypes=[("PDF és kép", pat)]))

    def _add_dir(self):
        d = filedialog.askdirectory(title="A források mappája",
                                    initialdir=self.last_dir or recall("mellekletek", self.folder))
        if d:
            self._add([os.path.join(d, f) for f in list_files(d, SRC_EXT)])

    def _add(self, paths):
        """PDF-ek és képek a rács végére, oldalanként (többoldalas TIFF is)."""
        known = {(it.path, it.page) for it in self.items}
        files = sorted({os.path.abspath(p) for p in paths if p.lower().endswith(SRC_EXT)},
                       key=lambda p: natural_key(os.path.basename(p)))
        new = []
        for p in files:
            try:
                d = open_checked(p)
                n = d.page_count
                d.close()
            except Exception as e:
                self._write_log(f"  ⚠ {os.path.basename(p)}: {e}")
                if (p, 0) not in known:
                    new.append(PageItem(p, bad="⚠ nem olvasható"))
                continue
            new += [PageItem(p, i) for i in range(n) if (p, i) not in known]
        if not new:
            return
        self.last_dir = os.path.dirname(new[0].path)
        remember("mellekletek", self.last_dir)
        self.items += new
        self._redraw()
        self._thumbs()
        self._refresh_out()

    def _rotate(self, d):
        for it in self.sel:
            it.rot = (it.rot + d) % 360
            it.thumb = None
        self._redraw()
        self._thumbs()
        if self.viewer and self.viewer.item in self.sel:
            self.viewer._render()

    def _remove(self):
        if not self.sel or self._b:
            return
        self.items = [it for it in self.items if it not in self.sel]
        self.sel, self.anchor = set(), None
        self._redraw()
        self._refresh_out()
        self._close_viewer_if_gone()

    def _clear(self):
        if not self._b:
            self.items, self.sel, self.anchor = [], set(), None
            self._redraw()
            self._refresh_out()
            self._close_viewer_if_gone()

    def _close_viewer_if_gone(self):
        if self.viewer and self.viewer.item not in self.items:
            self.viewer.close()

    def _open_viewer(self, e):
        """Dupla kattintás egy bélyegképen: nagyított előnézet."""
        i, _, _ = self._hit_item(e)
        if i is not None:
            if not self.viewer:
                self.viewer = PageViewer(self)
            self.viewer.show(self.items[i])
        return "break"

    # ---------------- bélyegképek ----------------
    def _thumbs(self):
        if not self._thumb_job:
            self._thumb_job = self.after(1, self._thumb_next)

    def _thumb_next(self):
        it = next((it for it in self.items if it.thumb is None and not it.bad), None)
        if it is None:
            self._thumb_job = None
            return
        try:
            d = pymupdf.open(it.path)
            try:
                p = d[it.page]
                z = THUMB / max(p.rect.width, p.rect.height)
                it.thumb = tkimg(p.get_pixmap(matrix=pymupdf.Matrix(z, z).prerotate(it.rot)), "ppm")
            finally:
                d.close()
        except Exception:
            it.bad = "⚠ nem olvasható"
        self._redraw()
        self._thumb_job = self.after(1, self._thumb_next)

    # ---------------- rács ----------------
    def _cols(self):
        return max(1, (self.canvas.winfo_width() - GAP) // (CELL_W + GAP))

    def _xy(self, i):
        c = self._cols()
        return GAP + (i % c) * (CELL_W + GAP), GAP + (i // c) * (CELL_H + GAP)

    def _see(self, i):
        """Görgetés, hogy az i-edik csempe látsszon."""
        c, (_, y) = self.canvas, self._xy(i)
        top, h = c.canvasy(0), c.winfo_height()
        total = GAP + -(-len(self.items) // self._cols()) * (CELL_H + GAP)
        if y < top or y + CELL_H > top + h:
            c.yview_moveto(max(0, y - GAP) / max(1, total))

    def _redraw(self):
        c = self.canvas
        c.delete("all")
        for i, it in enumerate(self.items):
            x, y = self._xy(i)
            hot = it in self.sel
            short, color = self._look(it.doc.doc_type) if it.doc else (None, None)
            canvas_card(c, x, y, x + CELL_W, y + CELL_H, 10,
                        fill=COL_TILE_BG_HOT if hot else COL_TILE_BG,
                        outline=color or (COL_TILE_LINE_HOT if hot else COL_TILE_LINE),
                        width=3 if color else (2 if hot else 1))
            cx, cy = x + CELL_W / 2, y + 8 + THUMB / 2
            if it.thumb:
                c.create_image(cx, cy, image=it.thumb)
            else:
                c.create_text(cx, cy, text=it.bad or "…", font=("Segoe UI", 9),
                              fill=COL_WARN if it.bad else "#8a929b")
            if color:                                  # a címke sávja
                c.create_polygon(round_pts(x + 1, y + 1, x + CELL_W - 1, y + 19, 9),
                                 fill=color, outline=color)
                c.create_rectangle(x + 1, y + 11, x + CELL_W - 1, y + 19,
                                   fill=color, outline=color)
                c.create_text(cx, y + 10, text=short, fill="white", font=FONT_SB)
            name = it.label() if it.paged() else f"{i + 1}. {it.label()}"
            name = name if len(name) <= 26 else name[:25] + "…"
            c.create_text(cx, y + CELL_H - 12, text=name, font=FONT_SM,
                          fill=UI["ink_soft"])
        n = len(self.items)
        rows = (n + self._cols() - 1) // self._cols()
        c.configure(scrollregion=(0, 0, c.winfo_width(), GAP + rows * (CELL_H + GAP)))
        if not n:
            c.create_text(max(200, c.winfo_width()) / 2, 90, fill=UI["ink_soft"],
                          justify="center", font=("Segoe UI", 11),
                          text="Nincs oldal.\nAdj hozzá PDF-et vagy képeket — a sorrend "
                               "vonszolással állítható.\nJelöld ki az oldalakat, és nyomj "
                               "a Doktípus listában a típusra.\nCtrl+kattintás: több oldal · "
                               "Shift+kattintás: tartomány · dupla kattintás: nagyítás")
        bad = sum(1 for it in self.items if it.bad)
        self.info.set(f"{n} oldal · {len(self.sel)} kijelölve · címke: a Doktípus listából · "
                      "dupla kattintás: nagyítás" +
                      (f" · {bad} nem olvasható (kimarad)" if bad else ""))

    # ---------------- vonszolás ----------------
    def _index_at(self, x, y):
        for i in range(len(self.items)):
            x0, y0 = self._xy(i)
            if x0 <= x <= x0 + CELL_W and y0 <= y <= y0 + CELL_H:
                return i
        return None

    def _slot_at(self, x, y):
        """Beszúrási hely (0..n) a kurzor alatt: a csempe bal fele elé, jobb fele mögé."""
        c = self._cols()
        row = max(0, int((y - GAP) // (CELL_H + GAP)))
        col = max(0, min(c, round((x - GAP) / (CELL_W + GAP))))
        return max(0, min(len(self.items), row * c + col))

    def _hit_item(self, e):
        """(index | None, x, y) a kattintás helyén, vászonkoordinátában."""
        self.canvas.focus_set()
        x, y = self.canvas.canvasx(e.x), self.canvas.canvasy(e.y)
        return self._index_at(x, y), x, y

    def _press(self, e):
        """Sima kattintás: csak ez az egy oldal lesz kijelölve (és vonszolható)."""
        i, x, y = self._hit_item(e)
        self.sel = {self.items[i]} if i is not None else set()
        self.anchor = self.items[i] if i is not None else None
        self._drag = (i, x, y) if i is not None and not self._b else None
        self._redraw()

    def _press_ctrl(self, e):
        """Ctrl+kattintás: az oldal ki-/bekapcsolása a kijelölésben."""
        i, _, _ = self._hit_item(e)
        if i is not None:
            self.sel ^= {self.items[i]}
            self.anchor = self.items[i]
            self._redraw()
        return "break"

    def _press_shift(self, e):
        """Shift+kattintás: a kiinduló elemtől eddig minden oldal."""
        i, _, _ = self._hit_item(e)
        if i is None:
            return "break"
        a = self.items.index(self.anchor) if self.anchor in self.items else i
        self.sel = set(self.items[min(a, i):max(a, i) + 1])
        self._redraw()
        return "break"

    def _motion(self, e):
        if not self._drag:
            return
        i, x0, y0 = self._drag
        h = self.canvas.winfo_height()
        if e.y < 20:                                   # automatikus görgetés a szélén
            self.canvas.yview_scroll(-1, "units")
        elif e.y > h - 20:
            self.canvas.yview_scroll(1, "units")
        x, y = self.canvas.canvasx(e.x), self.canvas.canvasy(e.y)
        if abs(x - x0) + abs(y - y0) < 6 and not self.canvas.find_withtag("ghost"):
            return                                     # még csak kattintás
        c = self.canvas
        c.delete("ghost")
        s = self._slot_at(x, y)
        if s < len(self.items):
            lx, ly = self._xy(s)
            lx -= GAP / 2
        else:
            lx, ly = self._xy(s - 1)
            lx += CELL_W + GAP / 2
        c.create_line(lx, ly, lx, ly + CELL_H, fill=COL_CROP, width=3, tags=("ghost",))
        c.create_rectangle(x - 70, y - 12, x + 70, y + 12, fill="#ffffcc",
                           outline=COL_TILE_LINE_HOT, dash=(3, 2), tags=("ghost",))
        c.create_text(x, y, text=self.items[i].label()[:22],
                      font=("Segoe UI", 8), tags=("ghost",))

    def _release(self, e):
        if not self._drag:
            return
        i = self._drag[0]
        self._drag = None
        moved = bool(self.canvas.find_withtag("ghost"))
        self.canvas.delete("ghost")
        if not moved:
            return
        s = self._slot_at(self.canvas.canvasx(e.x), self.canvas.canvasy(e.y))
        if s in (i, i + 1):
            return
        j = s - 1 if s > i else s
        self.items.insert(j, self.items.pop(i))
        self._redraw()
        self._refresh_out()

    # ---------------- iktatás ----------------
    def _iktat(self):
        """Minden címkézett irat a dolgozó mappájába, egyetlen összegzés után."""
        if self._b:
            return
        if not self.who:
            self.who_msg.set("Előbb válaszd ki a dolgozót.")
            self.who_lbl.configure(foreground=COL_WARN)
            self.who_cb.focus_set()
            return
        docs = self._out_docs()
        if not docs:
            messagebox.showwarning("Nincs irat", "Címkézz fel legalább egy oldalt: jelöld ki, "
                                                 "majd kattints a Doktípus listában.")
            return
        folder = os.path.join(self.folder, self.who)
        jobs = []
        for d, its in docs:
            name = self._doc_name(d)
            sub = self._doc_sub(d)                 # iratonként: 01 vagy 02
            dfolder = os.path.join(folder, sub)
            try:
                check_path_len(os.path.join(dfolder, name))
            except ValueError as e:
                messagebox.showerror("Túl hosszú útvonal", str(e))
                return
            jobs.append(dict(doc=d, items=its, name=name, sub=sub, folder=dfolder,
                             exists=os.path.exists(os.path.join(dfolder, name))))
        try:
            ensure_work_dirs(folder)
        except OSError as e:
            messagebox.showerror("A mappaszerkezet nem hozható létre", str(e))
            return
        free = sum(1 for it in self.items if it.doc is None and not it.bad)
        mode = self._ask_batch(jobs, free)
        if mode == "cancel":
            return
        _, dpi, q = PRESETS[self.preset.get()]
        self._b = dict(jobs=jobs, j=0, i=0, out=None, srcs={}, who=self.who, folder=folder,
                       mode=mode, dpi=dpi, q=q, gray=self.gray.get(), a4=self.fit_a4.get(),
                       cancel=False, done=[], errors=[], big=[])
        self.log.configure(state="normal")
        self.log.delete("1.0", tk.END)
        self.log.configure(state="disabled")
        self.pb.configure(maximum=sum(len(j["items"]) for j in jobs), value=0)
        self.btn_go.state(["disabled"])
        self.after(1, self._step)

    def _ask_batch(self, jobs, free):
        """Egyetlen összegzés az iktatás előtt. -> new | overwrite | cancel"""
        win = tk.Toplevel(self)
        win.title("Iktatás")
        win.transient(self.winfo_toplevel())
        win.resizable(False, False)
        win.grab_set()
        res = {"v": "cancel"}
        coll = [j for j in jobs if j["exists"]]
        ttk.Label(win, text=f"{len(jobs)} irat → {self.who}\\",
                  font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=14, pady=(14, 4))
        for j in jobs:
            ttk.Label(win, text=("⚠ " if j["exists"] else "    ") +
                      f"{j['sub']}\\{j['name']} · {len(j['items'])} oldal",
                      foreground=COL_WARN if j["exists"] else "").pack(anchor="w", padx=14)
        notes = [f"{free} oldal címke nélkül — kimarad."] if free else []
        if any(j["sub"] == DIR_PREP for j in jobs):
            notes.append(f"Az {DIR_PREP}-be menő irat még NEM feltölthető (nincs rajta "
                         "az arckép) — az Áttekintőben „E” jellel látszik.")
        if coll:
            notes.append(f"{len(coll)} irat már létezik (⚠). Az Új néven gomb (2), (3) … "
                         "sorszámmal menti; Felülírásnál az előző példány a mappa .eredeti "
                         "almappájába kerül. A Visszavonás mindkettőt visszacsinálja.")
        if notes:
            ttk.Label(win, text="\n".join(notes), wraplength=460,
                      justify="left").pack(anchor="w", padx=14, pady=(8, 0))
        row = ttk.Frame(win)
        row.pack(fill="x", padx=14, pady=14)

        def pick(v):
            res["v"] = v
            win.destroy()

        b = ttk.Button(row, text="Új néven (2)" if coll else "Iktatás", command=lambda: pick("new"))
        b.pack(side="left")
        b.focus_set()
        if coll:
            ttk.Button(row, text="Felülírás", command=lambda: pick("overwrite")).pack(side="left", padx=8)
        ttk.Button(row, text="Mégsem", command=lambda: pick("cancel")).pack(side="right")
        win.bind("<Return>", lambda e: pick("new"))
        win.bind("<Escape>", lambda e: pick("cancel"))
        win.wait_window()
        return res["v"]

    def _cancel(self):
        if self._b:
            self._b["cancel"] = True

    def _step(self):
        """Egy oldal az éppen készülő iratba."""
        b = self._b
        if b["cancel"]:
            self._end_batch()
            return
        job = b["jobs"][b["j"]]
        if b["out"] is None:
            b["out"] = pymupdf.open()
        try:
            add_item_page(b["out"], job["items"][b["i"]], b["dpi"], b["q"], b["gray"], b["a4"],
                          b["srcs"])
        except Exception as e:
            self._doc_failed(job, e)
            return
        b["i"] += 1
        self.pb.configure(value=float(self.pb["value"]) + 1)
        self.app.status(f"{job['name']}: {b['i']}/{len(job['items'])} oldal")
        if b["i"] < len(job["items"]):
            self.after(1, self._step)
        else:
            self._doc_built(job)

    def _doc_built(self, job):
        """Az irat kész a memóriában: kiírás, 5 MB fölött előbb lépcsőzetes tömörítés."""
        b = self._b
        out, b["out"] = b["out"], None
        try:
            out.set_metadata(dict(CLEAN_META, title=os.path.splitext(job["name"])[0]))
            r = doc_type_rule(job["doc"].doc_type, self._rules())
            set_stamp(out, b["who"], job["doc"].doc_type, r.id if r else "", job["sub"])
            pages = out.page_count
            data = out.tobytes(garbage=4, deflate=True)
        except Exception as e:
            self._doc_failed(job, e)
            return
        finally:
            out.close()
        job["size"] = len(data)
        if len(data) <= UPLOAD_LIMIT:
            self._doc_save(job, data, pages)
            return
        self._write_log(f"  {job['name']}: {mb(len(data))} — a korlát ({mb(UPLOAD_LIMIT)}) "
                        "fölött, tömörítés…")
        shrink_process(self, data,
                       on_step=lambda dpi, q: self._write_log(
                           f"    lépcső: {dpi} DPI, Q{q}"),
                       on_done=lambda d, step, err: self._doc_save(
                           job, d, pages, step, err, True))

    def _doc_save(self, job, data, pages, step=None, err=None, shrunk=False):
        """Ellenőrzött kiírás a dolgozó mappájába — az Iktató szabályai szerint."""
        b = self._b
        name, backup, result = job["name"], None, "OK"
        dst = os.path.join(job["folder"], name)      # iratonként 01 vagy 02
        try:
            if err:
                raise err
            if os.path.exists(dst):
                if b["mode"] == "overwrite":
                    backup = backup_existing(dst)
                    result = f"FELULIRVA (elozo: {DIR_PREP})"
                else:
                    name = unique_name(job["folder"], name)[0]
                    dst = os.path.join(job["folder"], name)
                    result = "UTKOZES-UJ NEV"
            write_pdf_verified(data, dst, pages)
        except Exception as e:
            if backup and os.path.exists(backup):
                try:
                    os.remove(backup)       # a cél érintetlen maradt, a másolat felesleges
                except OSError:
                    pass
            self._doc_failed(job, e)
            return
        note = ""
        if shrunk:
            result += f" TOMORITVE {mb(job['size'])}->{mb(len(data))}"
            note = f" · tömörítve: {mb(job['size'])} → {mb(len(data))}"
            if step is None:
                b["big"].append(name)
        log_row(self.folder, source_desc(job["items"]),
                os.path.join(b["who"], job["sub"]), name, job["doc"].doc_type, result)
        b["done"].append(dict(dst=dst, backup=backup, name=name, doc_type=job["doc"].doc_type,
                              items=job["items"]))
        self._write_log(f"  ✔ {name} — {pages} oldal, {mb(len(data))}{note}" +
                        (" · új néven (már volt ilyen)" if result == "UTKOZES-UJ NEV" else "") +
                        (f" · felülírva, az előző: {DIR_PREP}\\" if backup else ""))
        self._next_doc()

    def _doc_failed(self, job, e):
        b = self._b
        if b["out"] is not None:
            b["out"].close()
            b["out"] = None
        traceback.print_exception(e)
        log_row(self.folder, source_desc(job["items"]), b["who"], job["name"],
                job["doc"].doc_type, "HIBA: " + str(e)[:120])
        b["errors"].append(f"{job['name']}: {type(e).__name__}: {e}")
        self._write_log(f"  ⚠ {job['name']}: {type(e).__name__}: {e}")
        self._next_doc()

    def _next_doc(self):
        b = self._b
        b["j"], b["i"] = b["j"] + 1, 0
        self.pb.configure(value=sum(len(j["items"]) for j in b["jobs"][:b["j"]]))
        if b["j"] < len(b["jobs"]):
            self.after(1, self._step)
        else:
            self._end_batch()

    def _end_batch(self):
        """Az iktatott oldalak kikerülnek a rácsból (mint az Iktató várólistájáról);
        a visszavonás az eredeti helyükre teszi vissza őket."""
        b, self._b = self._b, None
        if b["out"] is not None:
            b["out"].close()
        for d in b["srcs"].values():
            d.close()
        done = b["done"]
        if done:
            gone = [it for rec in done for it in rec["items"]]
            pos = sorted(((self.items.index(it), it) for it in gone if it in self.items),
                         key=lambda p: p[0])
            self.last_batch = dict(files=done, pos=pos, who=b["who"])
            gone = set(gone)
            self.items = [it for it in self.items if it not in gone]
            self.sel -= gone
            if self.anchor in gone:
                self.anchor = None
        self.btn_go.state(["!disabled"])
        msg = (f"✔ {len(done)} irat iktatva → {b['who']}" +
               (f" · {len(b['errors'])} hiba" if b["errors"] else "") +
               (" · megszakítva" if b["cancel"] else ""))
        self._write_log(msg)
        self.app.status(msg)
        self._redraw()
        self._refresh_out()
        self._close_viewer_if_gone()
        if b["errors"]:
            messagebox.showerror("Iktatás", "Nem sikerült:\n\n" + "\n".join(b["errors"]))
        if b["big"]:
            messagebox.showwarning(
                "Tömörítés", "A legerősebb tömörítés után is a feltöltési korlát "
                f"({mb(UPLOAD_LIMIT)}) fölött maradt:\n\n" + "\n".join(b["big"]) +
                "\n\nÉrdemes kevesebb oldalra bontani: vond vissza, és címkézd két iratba.")

    def _undo(self):
        """Az utolsó iktatás egészét vonja vissza: a fájlok törlődnek (felülírásnál
        az előző példány visszakerül), az oldalak visszakerülnek a rácsba."""
        if self._b:
            self.app.status("Előbb várd meg az iktatás végét.")
            return
        lb = self.last_batch
        if not lb:
            self.app.status("Nincs mit visszavonni.")
            return
        undone, kept = [], []
        for rec in reversed(lb["files"]):
            try:
                undo_copy(rec["dst"], rec["backup"])
            except OSError as e:
                kept.insert(0, rec)
                self._write_log(f"  ⚠ nem vonható vissza: {rec['name']} ({e})")
                continue
            undone.append(rec)
            log_row(self.folder, source_desc(rec["items"]), lb["who"], rec["name"], rec["doc_type"],
                    "VISSZAVONVA" + (" (elozo visszaallitva)" if rec["backup"] else ""))
        back = {it for rec in undone for it in rec["items"]}
        for i, it in lb["pos"]:              # növekvő sorrendben: mind az eredeti helyére
            if it in back:
                self.items.insert(min(i, len(self.items)), it)
        self.last_batch = dict(lb, files=kept) if kept else None
        msg = f"Visszavonva: {len(undone)} irat" + (f", {len(kept)} nem sikerült" if kept else "")
        self._write_log(msg)
        self.app.status(msg)
        self._redraw()
        self._refresh_out()


# ───────────────────────────────── főablak ─────────────────────────────────
# ── kódból rajzolt felületi grafika ─────────────────────────────────────────
# A gombok, mezők és fülek háttere nem beépített ttk-grafika, hanem itt rajzolt,
# élsimított kép (pymupdf → PNG → PhotoImage), 9-slice képelemként a témába
# kötve. Így a widget MARAD igazi ttk.Button — minden meglévő hívás, állapot
# (active/pressed/disabled) és teszt változatlanul működik —, a megjelenés
# viszont a miénk. A képeket referenciában kell tartani, különben a Tk eldobja.
_UI_KEEP = []
_UI_READY = []


def _page(w, h):
    doc = pymupdf.open()
    return doc, doc.new_page(width=w, height=h)


def _png(doc, page, alpha=True):
    """PNG a lapról. `alpha=False`: ÁTLÁTSZATLAN kép — a Tk minden egyes
    újrarajzolásnál szoftveresen kompozitálja az alfát, és ez mérhetően (≈20×)
    lassítja az egész felületet (13.8). Ezért a felületi elemek a saját
    hátterükre ELŐRE ráégetve készülnek; alfa csak az ikonokon marad."""
    pix = page.get_pixmap(alpha=alpha)
    doc.close()
    return pix.tobytes("png")


def _round(shape, r, radius, fill=None, border=None, width=1.0, opacity=1.0,
           grad=None):
    """Lekerekített téglalap a formára. `grad`: (felső szín, alsó szín) —
    vízszintes sávokból rakjuk ki, mert a PDF-rajzolónak nincs színátmenete."""
    if grad:
        c1, c2 = _rgb(grad[0]), _rgb(grad[1])
        steps = max(4, int(r.height))
        rad = min(radius, r.height / 2, r.width / 2)
        for i in range(steps):
            t = i / (steps - 1)
            y0 = r.y0 + r.height * i / steps
            y1 = min(y0 + r.height / steps + 0.5, r.y1)
            d = min(y0 - r.y0, r.y1 - y1)            # távolság a lap szélétől
            dx = (rad - math.sqrt(max(0.0, rad * rad - (rad - d) ** 2))
                  if d < rad else 0.0)               # a sarok köríve
            sh = shape.page.new_shape()
            sh.draw_rect(pymupdf.Rect(r.x0 + dx, y0, r.x1 - dx, y1))
            sh.finish(fill=tuple(c1[k] + (c2[k] - c1[k]) * t for k in range(3)),
                      color=None, width=0)
            sh.commit()
        if border:
            sh = shape.page.new_shape()
            sh.draw_rect(r, radius=min(0.5, radius / min(r.width, r.height)))
            sh.finish(fill=None, color=_rgb(border), width=width)
            sh.commit()
        return
    if radius > 0:
        shape.draw_rect(r, radius=min(0.5, radius / min(r.width, r.height)))
    else:
        shape.draw_rect(r)                 # szögletes (pl. gördítősáv sínje)
    shape.finish(fill=_rgb(fill) if fill else None,
                 color=_rgb(border) if border else None,
                 width=width if border else 0,
                 fill_opacity=opacity, stroke_opacity=opacity)
    shape.commit()


def round_png(size, radius: float, fill, border=None, width=1.0,
              accent_bar=None, shadow=0.0, grad=None, pad=0.0, bg=None) -> bytes:
    """Lekerekített téglalap PNG-ben. `size`: élhossz vagy (szélesség, magasság);
    `radius` képpontban; `accent_bar`: (szín, magasság) alsó jelzősáv.

    A képméret nem mindegy: a Tk a 9-slice nyújtható sávját CSEMPÉZI, nem
    skálázza — kis képből sok csempe lesz, és a rajzolás belassul. A felületi
    elemek ezért szélesek (13.8)."""
    w, h = (size, size) if isinstance(size, (int, float)) else size
    doc, page = _page(w, h)
    if bg:                                   # a környező felület a kép hátterébe
        page.draw_rect(page.rect, color=None, fill=_rgb(bg))
    m = width / 2 + 0.25 + pad
    r = pymupdf.Rect(m, m, w - m, h - m)
    if shadow:
        # Lágy árnyék elmosás nélkül: néhány egyre nagyobb, egyre halványabb
        # lekerekített téglalap a forma alatt. Három réteg már simának látszik.
        for k, op in ((2.6, 0.07), (1.7, 0.09), (0.9, 0.11)):
            sh = page.new_shape()
            _round(sh, pymupdf.Rect(r.x0 - k * 0.5, r.y0 - k * 0.2 + shadow * 0.5,
                                    r.x1 + k * 0.5, r.y1 + k + shadow * 0.5),
                   radius + k, fill=UI["shadow"], opacity=op)
    shape = page.new_shape()
    if fill is None and not grad:
        shape.commit()                      # átlátszó (pl. nem aktív fül)
    else:
        _round(shape, r, radius, fill=fill, border=border, width=width, grad=grad)
    if accent_bar:
        col, hh = accent_bar
        shape = page.new_shape()
        shape.draw_rect(pymupdf.Rect(radius * 0.6, h - hh, w - radius * 0.6, h))
        shape.finish(fill=_rgb(col), color=None, width=0)
        shape.commit()
    return _png(doc, page, alpha=bg is None)


def _rgb(c):
    """„#rrggbb” -> (r, g, b) 0..1 — a pymupdf így kéri."""
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) / 255 for i in (0, 2, 4))


def round_pts(x0, y0, x1, y1, r):
    """Lekerekített téglalap pontsora a tk.Canvas create_polygon-hoz (a vászon
    nem tud rádiuszt). Sarkonként öt pont elég simának látszik."""
    r = max(1.0, min(r, (x1 - x0) / 2, (y1 - y0) / 2))
    k = r * 0.45                                 # köríves sarok közelítése
    # Sarkonként három pont: a vászon MINDEN újrarajzoláskor végigmegy rajtuk,
    # és egy köteg bélyegképnél ez mérhető (13.8). 1–2 képpont a pontatlanság.
    return [x0 + r, y0, x1 - r, y0, x1 - k, y0 + k, x1, y0 + r,
            x1, y1 - r, x1 - k, y1 - k, x1 - r, y1,
            x0 + r, y1, x0 + k, y1 - k, x0, y1 - r,
            x0, y0 + r, x0 + k, y0 + k]


def canvas_card(c, x0, y0, x1, y1, r=8, fill=None, outline=None, width=1,
                shadow=None, tags=()):
    """Lekerekített „kártya” a vásznon, opcionális lágy árnyékkal. -> az alakzat."""
    if shadow:
        # Egyetlen árnyékréteg: a vásznon elemenként rajzolunk, és egy köteg
        # bélyegképnél a rétegenkénti polygon már mérhető (13.8).
        c.create_polygon(round_pts(x0 + 1, y0 + 1.6, x1 - 1, y1 + 2.4, r + 2),
                         fill=shadow[0], outline="", smooth=False, tags=tags)
    return c.create_polygon(round_pts(x0, y0, x1, y1, r), fill=fill or "",
                            outline=outline or "", width=width, smooth=False,
                            tags=tags)


def _arc(cx, cy, r, a0, a1, steps=12):
    """Körív pontsora fokban (az óra járásával egyezően, y lefelé)."""
    return [(cx + r * math.cos(math.radians(a0 + (a1 - a0) * i / steps)),
             cy + r * math.sin(math.radians(a0 + (a1 - a0) * i / steps)))
            for i in range(steps + 1)]


def draw_app_mark(c, size: int = 32):
    """Az alkalmazás jele a fejlécben: lekerekített jelvényen egy irat behajtott
    sarokkal, mögötte egy második lap.

    Miért ez: a program a nyomtatás–aláírás–szkennelés UTÁNI lépéseket végzi —
    iratokat rak össze, iktat és néz át. A két egymásra csúsztatott lap pont ezt
    mondja („köteg”), a behajtott sarok pedig az „irat” bevett jele (ugyanaz a
    forma, mint az ICON_PATHS „doc” ikonja — egy nyelvet beszél a felület).
    A korábbi „PM” monogram betűfüggő volt és 32 képpontban mosódott.
    """
    k = size / 32.0                       # a rajz 32×32-es rácson készült

    def P(*pts):
        return [(x * k, y * k) for x, y in pts]

    # Egyetlen, egyszínű jelvény, SIMÍTOTT sarokkal. Két dolgot kellett javítani:
    # a korábbi „felső derengés” külön lekerekített kártya volt, és az ALSÓ sarkai
    # is lekerekedtek — félmagasságban benyomták a jelvény oldalát; a round_pts
    # pedig sarkonként három pontot ad (bélyegképekhez gyors), amitől 32 képpontban
    # nyolcszögnek látszik. Itt egyetlen alakzatot rajzolunk egyszer: a smooth=True
    # ingyen van, és valódi körívet ad (mérve a 10× nagyításon).
    c.create_polygon(round_pts(1 * k, 1 * k, 31 * k, 31 * k, 6.5 * k),
                     fill=UI["accent"], outline="", smooth=True)
    # Hátsó lap: jobbra-fel csúsztatva kilátszik — ettől lesz köteg, nem egy lap.
    c.create_polygon(P((13, 7), (20, 7), (23.5, 10.5), (23.5, 21.5), (13, 21.5)),
                     fill="#a9c4fa", outline="", smooth=False)
    # Elülső lap, behajtott sarokkal (ugyanaz a forma, mint a „doc” ikon).
    c.create_polygon(P((8, 10.5), (15.5, 10.5), (19, 14), (19, 25), (8, 25)),
                     fill="#ffffff", outline="", smooth=False)
    c.create_polygon(P((15.5, 10.5), (15.5, 14), (19, 14)),
                     fill="#8fb0f2", outline="", smooth=False)
    # Sorok az iraton: a tartalom jele. Vastagságuk a mérettel nő.
    lw = max(1, round(1.4 * k))
    for y, x1 in ((16.8, 16.5), (19.6, 16.5), (22.4, 13.5)):
        c.create_line(*P((10.5, y), (x1, y)), fill=UI["accent"],
                      width=lw, capstyle="round")


ICON_PATHS = {
    # (pontsorok, zárt-e) — 24×24-es rácson, stroke stílusban
    "folder": ([[(3, 7), (9, 7), (11, 9.5), (21, 9.5), (21, 19), (3, 19)]], True),
    # Frissítés: majdnem teljes kör, a végén nyílheggyel — egy mozdulat, nem négy.
    "refresh": ([_arc(12, 12, 8, -55, 250),
                 [(12.5, 6.3), (16.6, 6.9), (16.2, 2.6)]], False),
    # Visszavonás: balra forduló nyíl (vissza az előző állapotba).
    "undo": ([_arc(12, 13, 7.5, 180, 345),
              [(9.5, 10.5), (4.5, 13), (9.5, 16)]], False),
    "search": ([_arc(10.5, 10.5, 6.2, 0, 360), [(15, 15), (20.5, 20.5)]], False),
    "sort": ([[(4, 7), (20, 7)], [(4, 12), (15, 12)], [(4, 17), (10, 17)]], False),
    # Tömörítés: két nyíl egymás felé, köztük a cél vonala — a nyilak NEM érnek
    # a vonalig, különben csillaggá olvadnak össze.
    "compress": ([[(3.5, 12), (20.5, 12)],
                  [(12, 2.5), (12, 8.5)], [(8.5, 5.5), (12, 9), (15.5, 5.5)],
                  [(12, 21.5), (12, 15.5)], [(8.5, 18.5), (12, 15), (15.5, 18.5)]],
                 False),
    "stamp": ([[(6, 20), (18, 20)], [(7, 17), (17, 17)],
               [(9, 17), (9, 11), (15, 11), (15, 17)],
               [(10, 11), (10, 6), (14, 6), (14, 11)]], False),
    "crop": ([[(7, 3), (7, 17), (21, 17)], [(3, 7), (17, 7), (17, 21)]], False),
    # Irat: lap behajtott sarokkal (zárt kontúr + a sarok vonala).
    "doc": ([[(6, 3), (13.5, 3), (18, 7.5), (18, 21), (6, 21), (6, 3)],
             [(13.5, 3), (13.5, 7.5), (18, 7.5)]], False),
    "sliders": ([[(4, 8), (20, 8)], [(4, 16), (20, 16)],
                 [(9, 5.5), (9, 10.5)], [(16, 13.5), (16, 18.5)]], False),
    "archive": ([[(12, 3), (12, 14)], [(8, 10), (12, 14), (16, 10)],
                 [(4, 17), (4, 21), (20, 21), (20, 17)]], False),
    "plus": ([[(12, 4), (12, 20)], [(4, 12), (20, 12)]], False),
    "trash": ([[(4, 7), (20, 7)], [(10, 4), (14, 4)],
               [(6, 7), (7, 21), (17, 21), (18, 7)]], False),
    # Mentés: lemez (a letöltő nyíl az „archive”, ne legyen két egyforma ikon).
    "save": ([[(4, 4), (16, 4), (20, 8), (20, 20), (4, 20), (4, 4)],
              [(8, 4), (8, 9), (15, 9), (15, 4)],
              [(7, 20), (7, 14), (17, 14), (17, 20)]], False),
    "tag": ([[(4, 10), (10, 4), (20, 4), (20, 14), (14, 20), (4, 10)],
             _arc(16.2, 7.8, 1.5, 0, 360)], False),
    # Szétosztás: olló — két penge és két fogógyűrű.
    "split": ([[(7, 4), (16.5, 15.5)], [(17, 4), (7.5, 15.5)],
               _arc(6.5, 18.5, 2.6, 0, 360), _arc(17.5, 18.5, 2.6, 0, 360)], False),
    "check": ([[(5, 13), (10, 18), (19, 6)]], False),
    "close": ([[(6, 6), (18, 18)], [(18, 6), (6, 18)]], False),
    # Lapozás: chevron, a szélső lapra vonallal (Szerkesztés eszköztára).
    "first": ([[(6, 5), (6, 19)], [(17, 5), (10, 12), (17, 19)]], False),
    "prev": ([[(15, 5), (8, 12), (15, 19)]], False),
    "next": ([[(9, 5), (16, 12), (9, 19)]], False),
    "last": ([[(18, 5), (18, 19)], [(7, 5), (14, 12), (7, 19)]], False),
    # A Szerkesztés eszközcsempéi (szerkeszto-terv.md 23.1).
    "text": ([[(5, 5), (19, 5)], [(12, 5), (12, 19)], [(9, 19), (15, 19)]], False),
    "textbox": ([[(3, 5), (21, 5), (21, 19), (3, 19), (3, 5)],
                 [(7, 9.5), (17, 9.5)], [(7, 14.5), (14, 14.5)]], False),
    "para": ([[(4, 6), (20, 6)], [(4, 10), (20, 10)], [(4, 14), (20, 14)],
              [(4, 18), (13, 18)]], False),
    "field": ([[(3, 8), (21, 8), (21, 16), (3, 16), (3, 8)], [(7, 10.5), (7, 13.5)]], False),
    "eraser": ([[(3, 14), (11, 6), (19, 14), (13, 20), (9, 20), (3, 14)],
                [(7, 10), (15, 18)], [(13, 20), (21, 20)]], False),
    "shield": ([[(12, 3), (20, 6), (20, 12), (12, 21), (4, 12), (4, 6), (12, 3)],
                [(8.5, 12), (11, 14.5), (15.5, 9.5)]], False),
    "header": ([[(6, 3), (18, 3), (18, 21), (6, 21), (6, 3)], [(9, 7), (15, 7)],
                [(9, 17), (15, 17)]], False),
    "form": ([[(4, 5), (9, 5), (9, 10), (4, 10), (4, 5)], [(12, 7.5), (20, 7.5)],
              [(4, 14), (9, 14), (9, 19), (4, 19), (4, 14)], [(12, 16.5), (20, 16.5)],
              [(5, 7.5), (6.5, 9), (8.5, 6)]], False),
    "ocr": ([[(3, 8), (3, 3), (8, 3)], [(16, 3), (21, 3), (21, 8)],
             [(21, 16), (21, 21), (16, 21)], [(8, 21), (3, 21), (3, 16)],
             [(8, 17), (12, 7), (16, 17)], [(9.6, 13), (14.4, 13)]], False),
    "al_left": ([[(4, 6), (20, 6)], [(4, 10), (15, 10)], [(4, 14), (20, 14)],
                 [(4, 18), (13, 18)]], False),
    "al_center": ([[(4, 6), (20, 6)], [(7, 10), (17, 10)], [(4, 14), (20, 14)],
                   [(8, 18), (16, 18)]], False),
    "al_right": ([[(4, 6), (20, 6)], [(9, 10), (20, 10)], [(4, 14), (20, 14)],
                  [(11, 18), (20, 18)]], False),
    "al_justify": ([[(4, 6), (20, 6)], [(4, 10), (20, 10)], [(4, 14), (20, 14)],
                    [(4, 18), (20, 18)]], False),
    "up": ([[(5, 15), (12, 8), (19, 15)]], False),
    "down": ([[(5, 9), (12, 16), (19, 9)]], False),
}


def icon_png(name: str, px: int = 15, color=None, width=1.8) -> bytes:
    """Ikon kódból: vonalrajz a 24-es rácson, a kért képpontméretre rajzolva."""
    paths, closed = ICON_PATHS[name]
    k = px / 24.0
    doc, page = _page(px, px)
    shape = page.new_shape()
    for pts in paths:
        p0 = pymupdf.Point(pts[0][0] * k, pts[0][1] * k)
        for x, y in pts[1:]:
            p1 = pymupdf.Point(x * k, y * k)
            shape.draw_line(p0, p1)
            p0 = p1
    shape.finish(color=_rgb(color or UI["ink_soft"]), width=width * k * 1.4,
                 closePath=False, lineJoin=1, lineCap=1)
    shape.commit()
    return _png(doc, page)


def ui_icon(name: str, color=None, px: int = 15):
    """PhotoImage-gyorsítótár az ikonokhoz (kulcs: név + szín + méret)."""
    key = (name, color, px)
    for k, img in _UI_KEEP:
        if k == key:
            return img
    img = tk.PhotoImage(data=icon_png(name, px, color))
    _UI_KEEP.append((key, img))
    return img


# Melyik gombra melyik ikon és melyik stílus kerül. Egy helyen, felirat szerint:
# ponytail: így a ~60 gombhívás egyike sem változik. Új gomb ikon nélkül is jó.
BTN_LOOK = {
    "Mappa megnyitása": ("folder", 0), "Módosítás": ("folder", 0),
    "Mappa hozzáadása": ("folder", 0), "Frissítés": ("refresh", 0),
    "Mappák frissítése": ("refresh", 0), "Rendezés": ("sort", 0),
    "Ellenőrzés": ("search", 0), "Tömörítés": ("compress", 1),
    "Bélyegzés": ("stamp", 1), "Körülvágás": ("crop", 0),
    "Hiánylista": ("doc", 0), "CSV export": ("doc", 0),
    "Beállítások": ("sliders", 0), "Típusok": ("sliders", 0),
    "Iktatás": ("archive", 1), "Visszavonás": ("undo", 0),
    "PDF / kép hozzáadása": ("plus", 0), "Kijelölt törlése": ("trash", 0),
    "Mind törlése": ("trash", 0), "Sorból kivesz": ("trash", 0),
    "Mentés": ("save", 1), "Mentés másként": ("save", 1),
    "Címke a szövegből": ("tag", 0), "Szétosztás": ("split", 0),
    "Mentés szövegfájlba": ("save", 0), "Körülvág": ("crop", 1),
    "Alkalmaz": ("check", 1), "Mégsem": ("close", 0), "Bezárás": ("close", 0),
}


def decorate(widget):
    """Ikon és elsődleges stílus a gombokra a feliratuk szerint, rekurzívan.
    Minden ablakra (fülek, dialógusok) ugyanez fut — egy szabály, egy hely."""
    for w in widget.winfo_children():
        if w.winfo_class() == "TButton":
            try:
                txt = str(w.cget("text"))
            except tk.TclError:
                txt = ""
            hit = next((v for k, v in BTN_LOOK.items() if txt.startswith(k)), None)
            if hit and not w.cget("image"):
                name, primary = hit
                saját = str(w.cget("style")) not in ("", "TButton")
                w.configure(image=ui_icon(name, "#ffffff" if primary else None),
                            compound="left")
                if not saját:            # a kézzel megadott stílus marad (fejléc)
                    w.configure(style="Accent.TButton" if primary else "TButton")
        decorate(w)


def debounce(widget, attr: str, fn, ms: int = 60):
    """Átméretezéskor a <Configure> másodpercenként tucatszor jön; a munkát
    elhalasztjuk, és csak az utolsó esemény után futtatjuk le egyszer (13.8)."""
    job = getattr(widget, attr, None)
    if job:
        try:
            widget.after_cancel(job)
        except Exception:
            pass
    setattr(widget, attr, widget.after(ms, lambda: (setattr(widget, attr, None),
                                                    fn())[1]))


def round_window(owner, widget, radius: int = 10):
    """A felugró ablak (legördülő lista) sarkának lekerekítése. A Tk ablaka
    szögletes, ezért a Windows ablakrégióját vágjuk körbe — különben a
    lekerekített mező alatt éles sarkú lista nyílik (13.8).
    `widget` a felugrónál csak egy ÚTVONAL-sztring (a Tkinter nem ismeri),
    ezért kell az `owner` az értelmezőhöz."""
    try:
        tk_ = owner.tk
        path = str(widget)
        hwnd = int(tk_.call("winfo", "id", path), 0)
        w = int(tk_.call("winfo", "width", path))
        h = int(tk_.call("winfo", "height", path))
        if w < 4 or h < 4:
            return
        rgn = ctypes.windll.gdi32.CreateRoundRectRgn(0, 0, w + 1, h + 1,
                                                     radius, radius)
        ctypes.windll.user32.SetWindowRgn(hwnd, rgn, True)
    except Exception:
        pass                                  # nem Windows vagy nincs ablak: marad


def paint_accent_line(c):
    """Vízszintes színátmenetes csík a vásznon (a fejléc zárása). Fix számú
    sávból áll, nem képpontonként — így széles ablaknál sem lassít."""
    c.delete("all")
    w = max(1, c.winfo_width())
    a, b = _rgb(UI["accent"]), _rgb("#53c0f0")
    bands = 28
    step = w / bands
    for i in range(bands):
        t = i / (bands - 1)
        col = "#%02x%02x%02x" % tuple(
            int(255 * (a[k] + (b[k] - a[k]) * t)) for k in range(3))
        c.create_rectangle(i * step, 0, (i + 1) * step + 1, 4, fill=col,
                           outline=col)


def build_theme(root):
    """A ttk-téma felépítése: a gombok, mezők, fülek és jelölők grafikája a fenti
    rajzolókból. A clam az alap, mert annak minden elemét át lehet írni."""
    st = ttk.Style(root)
    st.theme_use("clam")
    root.configure(background=UI["bg"])
    root.option_add("*Font", FONT_UI)
    root.option_add("*TCombobox*Listbox.font", FONT_UI)
    root.option_add("*TCombobox*Listbox.background", UI["card"])
    root.option_add("*TCombobox*Listbox.foreground", UI["ink"])
    root.option_add("*TCombobox*Listbox.selectBackground", UI["accent"])
    root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")
    root.option_add("*Text.font", FONT_SM)
    root.option_add("*Toplevel.background", UI["bg"])
    # A legördülő lista külön ablak (ComboboxPopdown): a kerete a clam sötét,
    # szögletes stílusa, a háttere rendszerszürke — mindkettő kilóg a felületből.
    root.option_add("*ComboboxPopdown.background", UI["card"])
    root.option_add("*Canvas.highlightThickness", 0)
    root.option_add("*Text.relief", "flat")
    root.option_add("*Text.borderWidth", 0)
    root.option_add("*Text.highlightThickness", 1)
    root.option_add("*Text.highlightBackground", UI["line"])
    root.option_add("*Text.highlightColor", UI["line"])
    root.option_add("*Text.padX", 10)
    root.option_add("*Text.padY", 8)
    root.option_add("*Text.background", UI["card"])
    root.option_add("*Text.foreground", UI["ink"])
    root.option_add("*Listbox.relief", "flat")
    root.option_add("*Listbox.borderWidth", 0)
    root.option_add("*Listbox.highlightThickness", 0)
    root.option_add("*Listbox.background", UI["card"])
    root.option_add("*Listbox.foreground", UI["ink"])
    root.option_add("*Listbox.selectBackground", UI["accent_bg"])
    root.option_add("*Listbox.selectForeground", UI["ink"])
    root.option_add("*Listbox.activeStyle", "none")

    def img(data):
        i = tk.PhotoImage(data=data)
        _UI_KEEP.append((None, i))
        return i

    def nine(name, specs, border, padding, sticky="nsew", width=1, height=1):
        """9-slice képelem: az első kép az alap, a többi állapotonként.
        `width/height=1`: a kép SZÉLES (a csempézés miatt, 13.8), de a widget
        mérete a tartalmához igazodjon, ne a képhez. Kivétel a görgetősáv: annak
        nincs tartalma, a vastagságát nekünk kell kérnünk (lásd SB_THICK)."""
        base, rest = specs[0], specs[1:]
        spec = [(*states, img(data)) for states, data in rest]
        st.element_create(name, "image", img(base), *spec, border=border,
                          sticky=sticky, padding=padding, width=width, height=height)

    if not _UI_READY:                       # elemet csak egyszer lehet létrehozni
        # Minden kép a SAJÁT felületére égetve (B: lap, W: fehér kártya) —
        # átlátszatlanul a Tk nagyságrenddel gyorsabban rajzol (13.8).
        R, P = 9, 4                         # sarokrádiusz, árnyékhely
        S = (420, 48)                       # SZÉLES kép: kevés csemperajzolás
        B, W = UI["bg"], UI["card"]

        def btnset(name, surf, pad_xy=(10, 5)):
            nine(name, [
                round_png(S, R, W, UI["line"], 1.1, shadow=1.0, pad=P, bg=surf),
                (("disabled",), round_png(S, R, "#f2f4f8", UI["line_soft"], 1.0,
                                          pad=P, bg=surf)),
                (("pressed",), round_png(S, R, "#e7ecf5", "#c9d3e4", 1.1, pad=P,
                                         bg=surf)),
                (("active",), round_png(S, R, "#ffffff", "#bccbe6", 1.2,
                                        shadow=1.8, pad=P, bg=surf)),
                (("focus",), round_png(S, R, W, UI["accent"], 1.6, shadow=1.0,
                                       pad=P, bg=surf)),
            ], R + P, pad_xy)

        btnset("Modern.button", B)
        btnset("Head.button", W)                  # a fejléc fehér lapján ülő gombok
        nine("Accent.button", [
            round_png(S, R, None, None, 0, shadow=0.9, pad=P, bg=B,
                      grad=("#3b74f0", UI["accent"])),
            (("disabled",), round_png(S, R, "#c2cfea", None, 0, pad=P, bg=B)),
            (("pressed",), round_png(S, R, UI["accent_lo"], None, 0, pad=P, bg=B)),
            (("active",), round_png(S, R, None, None, 0, shadow=1.5, pad=P, bg=B,
                                    grad=("#4a80f5", UI["accent_hi"]))),
        ], R + P, (11, 5))
        for nm, surf in (("Modern.field", B), ("Head.field", W)):
            nine(nm, [
                round_png(S, 8, W, UI["line"], 1.2, pad=P, bg=surf),
                (("disabled",), round_png(S, 8, "#f4f6fb", UI["line"], 1.0, pad=P,
                                          bg=surf)),
                (("focus",), round_png(S, 8, W, UI["accent"], 1.6, pad=P, bg=surf)),
            ], 8 + P, (9, 5))
        nine("Modern.tab", [
            round_png(S, R, B, None, 0, pad=P, bg=B),
            (("selected",), round_png(S, R, UI["accent"], None, 0, shadow=1.6,
                                      pad=P, bg=B)),
            (("active",), round_png(S, R, UI["hover"], None, 0, pad=P, bg=B)),
        ], R + P, (17, 7))
        nine("Light.tab", [
            round_png(S, R, B, None, 0, pad=P, bg=B),
            (("selected",), round_png(S, R, UI["accent"], None, 0, shadow=1.4,
                                      pad=P, bg=B)),
            (("active",), round_png(S, R, UI["hover"], None, 0, pad=P, bg=B)),
        ], R + P, (16, 8))
        nine("Modern.card", [round_png((420, 320), R, B, UI["line"], 1.1,
                                       pad=P, bg=B)], R + P, (3, 3))
        for o in ("Horizontal", "Vertical"):
            vert = o == "Vertical"
            nine(f"{o}.Scale.trough",
                 [_bar_png((18, 240) if vert else (240, 18), 6, "#dde3ee",
                           vertical=vert, bg=B)], 8, (0, 0),
                 "ns" if vert else "ew")
            st.element_create(f"{o}.Scale.slider", "image",
                              img(_dot_png(17, bg=B)),
                              ("pressed", img(_dot_png(17, UI["accent_lo"], bg=B))),
                              ("active", img(_dot_png(17, UI["accent_hi"], bg=B))))
            SB = (16, 240) if vert else (240, 16)
            # A sáv a VASTAGSÁGÁT kérje: width/height=1-gyel minden görgetősáv 1×1
            # képpontot kért, és ahol a geometriakezelő nem feszítette ki (grid
            # sticky="ns", pack fill="y"), ott láthatatlan maradt — a Szerkesztés
            # és az Arckép vásznán nagyítva sem volt csúszka (mérve: 1×1 px; 19.1).
            nine(f"{o}.Scrollbar.trough", [round_png(SB, 0, B, None, 0, bg=B)],
                 2, (0, 0), width=SB_THICK if vert else 1,
                 height=1 if vert else SB_THICK)
            nine(f"{o}.Scrollbar.thumb", [
                round_png(SB, 5, "#c6cfdf", None, 0, pad=2.5, bg=B),
                (("pressed",), round_png(SB, 5, UI["accent"], None, 0, pad=2.5,
                                         bg=B)),
                (("active",), round_png(SB, 5, "#9fabc2", None, 0, pad=2.5, bg=B)),
            ], 7, (0, 0))
        # Eszközcsempe és formázógomb (F / D / A): kijelölve halvány akcentus-
        # háttér akcentus-kerettel — tíz csempén a telt kék túl hangos volna.
        nine("Tile.button", [
            round_png(S, 7, W, UI["line"], 1.0, pad=2, bg=B),
            (("disabled",), round_png(S, 7, "#f4f6fb", UI["line_soft"], 1.0, pad=2, bg=B)),
            (("selected",), round_png(S, 7, UI["accent_bg"], UI["accent"], 1.4, pad=2, bg=B)),
            (("pressed",), round_png(S, 7, "#e7ecf5", "#c9d3e4", 1.1, pad=2, bg=B)),
            (("active",), round_png(S, 7, UI["hover"], "#bccbe6", 1.1, pad=2, bg=B)),
        ], 9, (8, 5))
        # Ugyanez kis belső margóval a függőleges (ikon fölül) csempéhez: 64 px-es
        # csempén a 8 px-es margó a felirat végét levágta („Bekezdé”).
        nine("VTile.button", [
            round_png(S, 7, W, UI["line"], 1.0, pad=2, bg=B),
            (("disabled",), round_png(S, 7, "#f4f6fb", UI["line_soft"], 1.0, pad=2, bg=B)),
            (("selected",), round_png(S, 7, UI["accent_bg"], UI["accent"], 1.4, pad=2, bg=B)),
            (("pressed",), round_png(S, 7, "#e7ecf5", "#c9d3e4", 1.1, pad=2, bg=B)),
            (("active",), round_png(S, 7, UI["hover"], "#bccbe6", 1.1, pad=2, bg=B)),
        ], 9, (2, 2))
        st.element_create("Modern.radio", "image", img(_radio_png(16, bg=B)),
                          ("disabled", img(_radio_png(16, border=UI["line_soft"],
                                                      bg=B))),
                          ("selected", img(_radio_png(16, True, bg=B))),
                          ("active", img(_radio_png(16, border=UI["accent"], bg=B))))
        st.element_create("Modern.chev", "image", img(_chev_png(16, bg=W)),
                          ("disabled", img(_chev_png(16, "#c3cad6", bg=W))))
        box = 17
        st.element_create("Modern.check", "image", img(_box_png(box, bg=B)),
                          ("disabled", img(_box_png(box, border=UI["line_soft"],
                                                    fill="#f2f4f8", bg=B))),
                          ("selected", img(_box_png(box, checked=True, bg=B))),
                          ("active", img(_box_png(box, border=UI["accent"], bg=B))))
        _UI_READY.append(True)

    st.layout("TButton", [("Modern.button", {"sticky": "nsew", "children": [
        ("Button.padding", {"sticky": "nsew", "children": [
            ("Button.label", {"sticky": "nsew"})]})]})])
    st.layout("Accent.TButton", [("Accent.button", {"sticky": "nsew", "children": [
        ("Button.padding", {"sticky": "nsew", "children": [
            ("Button.label", {"sticky": "nsew"})]})]})])
    st.layout("TNotebook.Tab", [("Modern.tab", {"sticky": "nsew", "children": [
        ("Notebook.padding", {"side": "top", "sticky": "nsew", "children": [
            ("Notebook.label", {"side": "top", "sticky": ""})]})]})])
    st.layout("TEntry", [("Modern.field", {"sticky": "nsew", "children": [
        ("Entry.padding", {"sticky": "nsew", "children": [
            ("Entry.textarea", {"sticky": "nsew"})]})]})])
    st.layout("Head.TEntry", [("Head.field", {"sticky": "nsew", "children": [
        ("Entry.padding", {"sticky": "nsew", "children": [
            ("Entry.textarea", {"sticky": "nsew"})]})]})])
    st.layout("Head.TButton", [("Head.button", {"sticky": "nsew", "children": [
        ("Button.padding", {"sticky": "nsew", "children": [
            ("Button.label", {"sticky": "nsew"})]})]})])
    st.layout("Light.TNotebook.Tab", [("Light.tab", {"sticky": "nsew", "children": [
        ("Notebook.padding", {"side": "top", "sticky": "nsew", "children": [
            ("Notebook.label", {"side": "top", "sticky": ""})]})]})])
    st.layout("TCombobox", [("Modern.field", {"sticky": "nsew", "children": [
        ("Combobox.padding", {"sticky": "nsew", "children": [
            ("Modern.chev", {"side": "right", "sticky": ""}),
            ("Combobox.textarea", {"sticky": "nsew"})]})]})])
    st.layout("TLabelframe", [("Modern.card", {"sticky": "nsew"})])

    st.configure(".", background=UI["bg"], foreground=UI["ink"], font=FONT_UI,
                 borderwidth=0, focuscolor=UI["accent"])
    st.configure("TButton", font=FONT_UI, foreground=UI["ink"], anchor="center")
    st.map("TButton", foreground=[("disabled", "#a7b0bf")])
    st.configure("Accent.TButton", font=FONT_SB, foreground="#ffffff")
    st.map("Accent.TButton", foreground=[("disabled", "#eef2fb")])
    st.configure("TLabel", background=UI["bg"], foreground=UI["ink"])
    st.configure("TFrame", background=UI["bg"])
    st.configure("Card.TFrame", background=UI["card"])
    st.configure("Title.TLabel", background=UI["card"], foreground=UI["ink"],
                 font=FONT_SB)
    st.configure("Muted.TLabel", background=UI["card"], foreground=UI["ink_soft"],
                 font=FONT_SM)
    st.configure("Dim.TLabel", background=UI["bg"], foreground=UI["ink_soft"],
                 font=FONT_SM)
    st.configure("Status.TLabel", background=UI["card"], foreground=UI["ink_soft"],
                 font=FONT_SM, padding=(4, 6))
    st.configure("Foot.TFrame", background=UI["card"])
    st.configure("TLabelframe", background=UI["bg"])
    st.configure("TLabelframe.Label", background=UI["bg"], foreground=UI["ink_soft"],
                 font=FONT_SB)
    st.configure("TNotebook", background=UI["bg"], borderwidth=0,
                 bordercolor=UI["bg"], lightcolor=UI["bg"], darkcolor=UI["bg"],
                 tabmargins=(12, 8, 12, 2))
    st.configure("TNotebook.Tab", font=FONT_SB, foreground=UI["ink_soft"],
                 padding=0)
    st.map("TNotebook.Tab", foreground=[("selected", "#ffffff"),
                                        ("active", UI["ink"])])
    st.configure("Light.TNotebook", background=UI["bg"], borderwidth=0,
                 tabmargins=(2, 6, 2, 0))
    st.configure("Light.TNotebook.Tab", font=FONT_SB, foreground=UI["ink_soft"],
                 padding=0)
    st.map("Light.TNotebook.Tab", foreground=[("selected", "#ffffff"),
                                              ("active", UI["ink"])])
    st.configure("Head.TFrame", background=UI["head"])
    st.configure("Head.TLabel", background=UI["head"], foreground=UI["head_ink"])
    st.configure("HeadTitle.TLabel", background=UI["head"], foreground=UI["ink"],
                 font=("Segoe UI Semibold", 12))
    st.configure("HeadMuted.TLabel", background=UI["head"],
                 foreground=UI["head_mute"], font=FONT_SM)
    st.configure("Head.TButton", font=FONT_UI, foreground=UI["ink"],
                 background=UI["card"], anchor="center")
    st.map("Head.TButton", foreground=[("disabled", "#a7b0bf")])
    st.configure("TEntry", foreground=UI["ink"], fieldbackground=UI["card"],
                 insertcolor=UI["accent"], padding=(2, 3))
    st.configure("TCombobox", foreground=UI["ink"], fieldbackground=UI["card"],
                 background=UI["bg"], bordercolor=UI["line"],
                 arrowcolor=UI["ink_soft"], arrowsize=14, padding=(4, 2))
    st.map("TCombobox", fieldbackground=[("readonly", UI["card"])],
           bordercolor=[("focus", UI["accent"])],
           arrowcolor=[("disabled", "#c3cad6")])
    st.configure("TSpinbox", fieldbackground=UI["card"], background=UI["bg"],
                 bordercolor=UI["line"], arrowcolor=UI["ink_soft"], padding=(4, 3))
    st.configure("TEntry", background=UI["bg"])
    # A fejléc fehér lapon ül: ott a mező körüli szín is fehér legyen.
    st.configure("Head.TEntry", background=UI["card"], foreground=UI["ink"],
                 fieldbackground=UI["card"], insertcolor=UI["accent"])
    st.layout("TCheckbutton", [("Checkbutton.padding", {"sticky": "nsew", "children": [
        ("Modern.check", {"side": "left", "sticky": ""}),
        ("Checkbutton.focus", {"side": "left", "sticky": "w", "children": [
            ("Checkbutton.label", {"sticky": "nsew"})]})]})])
    st.configure("TCheckbutton", background=UI["bg"], foreground=UI["ink"],
                 padding=(2, 3), focusthickness=0)
    st.map("TCheckbutton", foreground=[("disabled", "#a7b0bf")],
           background=[("disabled", UI["bg"]), ("active", UI["bg"])])
    st.layout("TRadiobutton", [("Radiobutton.padding", {"sticky": "nsew", "children": [
        ("Modern.radio", {"side": "left", "sticky": ""}),
        ("Radiobutton.focus", {"side": "left", "sticky": "w", "children": [
            ("Radiobutton.label", {"sticky": "nsew"})]})]})])
    st.configure("TRadiobutton", background=UI["bg"], foreground=UI["ink"],
                 padding=(2, 3), focusthickness=0)
    for kind in ("Radiobutton", "Checkbutton"):
        st.layout(f"Tile.T{kind}", [("Tile.button", {"sticky": "nsew", "children": [
            (f"{kind}.padding", {"sticky": "nsew", "children": [
                (f"{kind}.label", {"sticky": "w"})]})]})])
        st.configure(f"Tile.T{kind}", background=UI["bg"], foreground=UI["ink"],
                     padding=(6, 3), focusthickness=0, font=FONT_UI)
        st.map(f"Tile.T{kind}", foreground=[("disabled", "#a7b0bf"),
                                            ("selected", UI["accent_lo"])],
               background=[("active", UI["bg"])])
    st.layout("VTile.TRadiobutton", [("VTile.button", {"sticky": "nsew", "children": [
        ("Radiobutton.padding", {"sticky": "nsew", "children": [
            ("Radiobutton.label", {"sticky": ""})]})]})])
    st.configure("VTile.TRadiobutton", background=UI["bg"], foreground=UI["ink"],
                 padding=(0, 5, 0, 4), focusthickness=0, font=FONT_SM, anchor="center")
    st.map("VTile.TRadiobutton", foreground=[("disabled", "#a7b0bf"),
                                             ("selected", UI["accent_lo"])],
           background=[("active", UI["bg"])])
    # A formázógombok betűje maga a jel: F félkövér, D dőlt, A aláhúzott.
    st.configure("B.Tile.TCheckbutton", font=("Segoe UI", 10, "bold"), padding=(9, 3))
    st.configure("I.Tile.TCheckbutton", font=("Segoe UI", 10, "italic"), padding=(10, 3))
    st.configure("U.Tile.TCheckbutton", font=("Segoe UI", 10, "underline"), padding=(9, 3))
    st.configure("Icon.Tile.TRadiobutton", padding=(4, 3))
    st.configure("Warn.TLabel", foreground=UI["warn"])
    st.configure("Ok.TLabel", foreground=UI["ok"])
    st.map("TRadiobutton", foreground=[("disabled", "#a7b0bf")],
           background=[("disabled", UI["bg"]), ("active", UI["bg"])])
    for o in ("Horizontal", "Vertical"):      # nyilak nélküli, karcsú gördítősáv
        st.layout(f"{o}.TScrollbar", [(f"{o}.Scrollbar.trough", {
            "sticky": "nswe", "children": [
                (f"{o}.Scrollbar.thumb", {"sticky": "nswe", "unit": 1})]})])
    st.configure("TScale", background=UI["bg"])
    st.configure("TProgressbar", background=UI["accent"], troughcolor="#e3e9f3",
                 bordercolor=UI["line"], lightcolor=UI["accent"],
                 darkcolor=UI["accent"], thickness=8)
    st.configure("TScrollbar", background="#cfd7e4", troughcolor=UI["bg"],
                 bordercolor=UI["bg"], arrowcolor=UI["ink_soft"], width=12)
    st.map("TScrollbar", background=[("active", UI["ink_soft"])])
    st.configure("Treeview", background=UI["card"], fieldbackground=UI["card"],
                 foreground=UI["ink"], borderwidth=0, rowheight=22)
    st.map("Treeview", background=[("selected", UI["accent_bg"])],
           foreground=[("selected", UI["ink"])])
    st.configure("TSeparator", background=UI["line"])
    st.configure("ComboboxPopdownFrame", relief="solid", borderwidth=1,
                 bordercolor=UI["line"], background=UI["card"], padding=2)
    # Minden később nyíló ablak (dialógus) ugyanazt a kezelést kapja: a gombok
    # ikont és elsődleges stílust a feliratukból — egy kötés, nincs hívási hely.
    root.bind_class("Toplevel", "<Map>", lambda e: decorate(e.widget), add="+")
    for ev in ("<Map>", "<Configure>"):   # a lista mérete nyitáskor még változhat
        root.bind_class("ComboboxPopdown", ev,
                        lambda e, r=root: round_window(r, e.widget), add="+")
    return st


def _chev_png(px: int = 16, color=None, bg=None) -> bytes:
    """Lefelé mutató chevron a legördülőkhöz."""
    doc, page = _page(px + 6, px)
    if bg:
        page.draw_rect(page.rect, color=None, fill=_rgb(bg))
    sh = page.new_shape()
    k = px / 16.0
    sh.draw_line(pymupdf.Point(4 * k, 6.5 * k), pymupdf.Point(8 * k, 10.5 * k))
    sh.draw_line(pymupdf.Point(8 * k, 10.5 * k), pymupdf.Point(12 * k, 6.5 * k))
    sh.finish(color=_rgb(color or UI["ink_soft"]), width=1.6 * k, closePath=False,
              lineCap=1, lineJoin=1)
    sh.commit()
    return _png(doc, page, alpha=bg is None)


def _bar_png(size, thick: int, color, vertical: bool = False, bg=None) -> bytes:
    """A csúszka sínje: a közepén futó vékony, lekerekített sáv."""
    w, h = (size, size) if isinstance(size, (int, float)) else size
    doc, page = _page(w, h)
    if bg:
        page.draw_rect(page.rect, color=None, fill=_rgb(bg))
    r = (pymupdf.Rect((w - thick) / 2, 0.5, (w + thick) / 2, h - 0.5) if vertical
         else pymupdf.Rect(0.5, (h - thick) / 2, w - 0.5, (h + thick) / 2))
    _round(page.new_shape(), r, thick / 2, fill=color)
    return _png(doc, page, alpha=bg is None)


def _dot_png(size: int, color=None, bg=None) -> bytes:
    """Csúszkagomb: fehér korong akcentus gyűrűvel."""
    doc, page = _page(size, size)
    if bg:
        page.draw_rect(page.rect, color=None, fill=_rgb(bg))
    sh = page.new_shape()
    sh.draw_circle(pymupdf.Point(size / 2, size / 2), size / 2 - 1.6)
    sh.finish(fill=(1, 1, 1), color=_rgb(color or UI["accent"]), width=2.4)
    sh.commit()
    return _png(doc, page, alpha=bg is None)


def _radio_png(size: int, checked: bool = False, border=None, bg=None) -> bytes:
    """Rádiógomb-jelölő: kör, bejelölve akcentus gyűrű + pötty."""
    doc, page = _page(size + 7, size)
    if bg:
        page.draw_rect(page.rect, color=None, fill=_rgb(bg))
    c, rr = size / 2.0, size / 2.0 - 1.0
    sh = page.new_shape()
    sh.draw_circle(pymupdf.Point(c, c), rr)
    sh.finish(fill=_rgb(UI["card"]),
              color=_rgb(UI["accent"] if checked else (border or "#b6c0d2")),
              width=1.6 if checked else 1.3)
    sh.commit()
    if checked:
        sh = page.new_shape()
        sh.draw_circle(pymupdf.Point(c, c), rr * 0.45)
        sh.finish(fill=_rgb(UI["accent"]), color=None, width=0)
        sh.commit()
    return _png(doc, page, alpha=bg is None)


def _box_png(size: int, checked: bool = False, fill=None, border=None,
             bg=None) -> bytes:
    """Jelölőnégyzet jobb oldali térközzel — a felirat ne tapadjon rá."""
    doc, page = _page(size + 7, size)
    if bg:
        page.draw_rect(page.rect, color=None, fill=_rgb(bg))
    r = pymupdf.Rect(0.8, 0.8, size - 0.8, size - 0.8)
    sh = page.new_shape()
    _round(sh, r, 5, fill=UI["accent"] if checked else (fill or UI["card"]),
           border=UI["accent_hi"] if checked else (border or "#b6c0d2"), width=1.3)
    if checked:
        sh = page.new_shape()
        k = size / 24.0
        pts = [(6, 12.5), (10.5, 17), (18, 7.5)]
        p0 = pymupdf.Point(pts[0][0] * k, pts[0][1] * k)
        for x, y in pts[1:]:
            p1 = pymupdf.Point(x * k, y * k)
            sh.draw_line(p0, p1)
            p0 = p1
        sh.finish(color=(1, 1, 1), width=2.2 * k, closePath=False, lineJoin=1,
                  lineCap=1)
        sh.commit()
    return _png(doc, page, alpha=bg is None)


def _check_png(size: int) -> bytes:
    """Bepipált jelölő: akcentus háttér + fehér pipa — kódból, hogy a jelölő is
    a többi elemmel egy nyelvet beszéljen."""
    doc, page = _page(size, size)
    shape = page.new_shape()
    shape.draw_rect(pymupdf.Rect(0.6, 0.6, size - 0.6, size - 0.6),
                    radius=5 / size)
    shape.finish(fill=_rgb(UI["accent"]), color=_rgb(UI["accent_hi"]), width=1.0)
    shape.commit()
    shape = page.new_shape()
    k = size / 24.0
    pts = [(6, 12.5), (10, 17), (18, 7)]
    p0 = pymupdf.Point(pts[0][0] * k, pts[0][1] * k)
    for x, y in pts[1:]:
        p1 = pymupdf.Point(x * k, y * k)
        shape.draw_line(p0, p1)
        p0 = p1
    shape.finish(color=(1, 1, 1), width=2.1 * k, closePath=False, lineJoin=1,
                 lineCap=1)
    shape.commit()
    return _png(doc, page)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"PDF Műhely – offline · {app_version()}")
        # Az ablak a KÉPERNYŐHÖZ igazodik: a korábbi fix 1200×840 egy 864 képpont
        # magas munkaállomáson a tálca alá lógott (13.7).
        w = max(960, min(1320, self.winfo_screenwidth() - 120))
        h = max(650, min(900, self.winfo_screenheight() - 110))
        self.geometry(f"{w}x{h}+{(self.winfo_screenwidth() - w) // 2}+24")
        self.minsize(940, 620)
        build_theme(self)
        # Nagyított kijelzőn a feliratok vége ne vágódjon le (TextSlack).
        self.scale_factor = _SCALE[0] = screen_scale()
        self.slack = TextSlack(self, self.scale_factor)
        self.folder = tk.StringVar(value=recall("munkamappa", script_dir()))
        self._status = tk.StringVar(value="Kész.")

        # Fejléc: sötét sáv a névvel, a verzióval és a munkamappával; a fülsáv
        # ugyanebben a sávban folytatódik, így egy összefüggő „parancsfejléc”
        # lesz belőle (13.7).
        head = ttk.Frame(self, style="Head.TFrame")
        head.pack(fill="x")
        inner = ttk.Frame(head, style="Head.TFrame")
        inner.pack(fill="x", padx=18, pady=(9, 7))
        mark = tk.Canvas(inner, width=32, height=32, highlightthickness=0,
                         bg=UI["head"])
        mark.pack(side="left")
        draw_app_mark(mark, 32)
        tit = ttk.Frame(inner, style="Head.TFrame")
        tit.pack(side="left", padx=(12, 28))
        # A jobb oldali ráhagyás NEM dísz. Az app DPI-UNAWARE, GDI-skálázással fut
        # (lásd a __main__ SetProcessDpiAwarenessContext(-5) hívását): 125–150%-os
        # Windows-nagyításnál a GDI szélesebben rajzolja a szöveget, mint ahogy a Tk
        # a logikai pixeleken kimérte — a sor VÉGE csúszik le, vagyis épp a
        # verzió utáni dátum. A ráhagyás ezt a különbséget nyeli el.
        ttk.Label(tit, text="PDF Műhely", style="HeadTitle.TLabel",
                  padding=(0, 0, DPI_SLACK, 0)).pack(anchor="w", fill="x")
        ttk.Label(tit, text=f"offline eszköztár · {app_version()}",
                  style="HeadMuted.TLabel",
                  padding=(0, 0, DPI_SLACK, 0)).pack(anchor="w", fill="x")
        ttk.Button(inner, text="Frissítés", style="Head.TButton",
                   command=self.refresh_all).pack(side="right")
        ttk.Button(inner, text="Módosítás…", style="Head.TButton",
                   command=self._pick_folder).pack(side="right", padx=8)
        fe = ttk.Entry(inner, textvariable=self.folder, style="Head.TEntry", font=FONT_SM)
        fe.pack(side="right", fill="x", expand=True, padx=(0, 6))
        # Szűk ablakban az útnak csak a VÉGE fér ki: az látsszon (a munkamappa
        # neve), ne a mindig egyforma „C:\Users\…” eleje.
        for ev in ("<Configure>", "<FocusOut>"):
            fe.bind(ev, lambda e: e.widget.xview_moveto(1.0), add="+")
        self.folder.trace_add("write", lambda *a: self.after_idle(
            lambda: fe.xview_moveto(1.0)))
        self.folder_entry = fe
        ttk.Label(inner, text="MUNKAMAPPA", style="HeadMuted.TLabel").pack(
            side="right", padx=(0, 10))
        line = tk.Canvas(head, height=3, highlightthickness=0, bg=UI["card"])
        line.pack(fill="x")                 # vékony akcentuscsík zárja a fejlécet
        line.bind("<Configure>",
                  lambda e, c=line: debounce(c, "_job", lambda: paint_accent_line(c)))

        # A felső sáv a munka sorrendje (ezért a sorszám), az eseti PDF-műveletek
        # és az arcképre helyezés egy „Eszközök” alfülcsoportba kerültek: a napi
        # munkához három fül kell, nem hat.
        # Az állapotsor a fülek ELŐTT kerül a helyére: a pack a korábban
        # becsomagoltnak ad helyet először, különben kis ablakban kiszorulna.
        foot = ttk.Frame(self, style="Foot.TFrame")
        foot.pack(fill="x", side="bottom")
        ttk.Separator(foot, orient="horizontal").pack(fill="x")
        self._dot = tk.Canvas(foot, width=16, height=24, highlightthickness=0,
                              bg=UI["card"])
        self._dot.pack(side="left", padx=(12, 0))
        self._dot.create_oval(5, 10, 12, 17, fill=UI["ok"], outline="")
        ttk.Label(foot, textvariable=self._status, style="Status.TLabel",
                  anchor="w").pack(side="left", fill="x", expand=True)

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True)
        self.tools = ttk.Notebook(self.nb, style="Light.TNotebook")
        self.tabs = {
            "Összeállító": ComposerTab(self.nb, self),
            "Iktató": IktatoTab(self.nb, self),
            "Áttekintő": AttekintoTab(self.nb, self),
            "Arckép elhelyezés": PlacerTab(self.tools, self),
            "Szerkesztés": EditorTab(self.tools, self),
            "Összefűzés": MergeTab(self.tools, self),
            "Raszterizálás": RasterTab(self.tools, self),
            "MD → DOCX": MdDocxTab(self.tools, self),
        }
        for i, name in enumerate(("Összeállító", "Iktató", "Áttekintő"), 1):
            self.nb.add(self.tabs[name], text=f"{i} · {name}")
        self.nb.add(self.tools, text="Eszközök")
        for name in ("Arckép elhelyezés", "Szerkesztés", "Összefűzés", "Raszterizálás",
                     "MD → DOCX"):
            self.tools.add(self.tabs[name], text=name)
        self.nb.bind("<<NotebookTabChanged>>", self._tab_changed)
        self.tools.bind("<<NotebookTabChanged>>", self._tab_changed)

        # Alapértelmezett dolgozó, közvetlenül a munkamappa alatt, a fülsor jobb
        # végén: az Összeállító és az Arckép dolgozóválasztója, valamint a
        # Szerkesztés, Összefűzés és Raszterizálás fájllistája ezt veszi át — nem kell
        # fülenként újra kiválasztani. Az Iktató NEM: annak épp az a dolga, hogy a
        # köteget több dolgozó között ossza szét. A fejlécbe nem fért: 960 px-es
        # ablakban a munkamappa mezője kiszorult volna (kepek-pdf-terv.md 19.3).
        self._worker = ""                  # az érvényes (feloldott) dolgozói mappa neve
        self.worker = tk.StringVar(value="")
        wk = ttk.Frame(self)
        ttk.Label(wk, text="ALAPÉRTELMEZETT DOLGOZÓ", style="Dim.TLabel").pack(
            side="left", padx=(0, 8))
        self.worker_cb = ttk.Combobox(wk, textvariable=self.worker, width=20,
                                      postcommand=self._worker_values)
        self.worker_cb.pack(side="left")
        for ev in ("<<ComboboxSelected>>", "<Return>", "<FocusOut>"):
            self.worker_cb.bind(ev, self._worker_commit)
        wk.place(in_=self.nb, relx=1.0, x=-14, y=7, anchor="ne")
        wk.lift()
        self.worker_bar = wk

        decorate(self)                   # ikonok és elsődleges stílus a gombokra
        w = recall("dolgozo", "")
        self._worker = "" if w == NO_WORKER else w   # a refresh_all ellenőrzi
        self.refresh_all()
        self.after(300, self._check_deps)

    def _check_deps(self):
        """Régi PyMuPDF-nél indításkor szól, nem munka közben dob hibát."""
        miss = missing_features()
        if miss:
            messagebox.showwarning(
                "Régi PyMuPDF",
                f"A telepített PyMuPDF ({pymupdf.VersionBind}) túl régi, ezek nem működnek:\n"
                "  • " + "\n  • ".join(miss) +
                "\n\nA többi funkció használható. Frissítés parancssorból:\n"
                "  pip install -U pymupdf")

    def _pick_folder(self):
        d = filedialog.askdirectory(title="Munkamappa", initialdir=self.folder.get())
        if d:
            remember("munkamappa", d)
            self.folder.set(d)
            self.refresh_all()

    def refresh_all(self):
        folder = self.folder.get()
        try:
            dirs = worker_dirs(folder)
        except OSError:
            dirs = []
        if self._worker not in dirs:          # másik munkamappa: a dolgozó nem él tovább
            self._worker = ""
        if self.worker.get() != self._worker:
            self.worker.set(self._worker)
        for tab in self.tabs.values():
            tab.set_folder(folder)
        for tab in self.tabs.values():        # frissítéskor csak az üres választóba
            if hasattr(tab, "set_worker"):
                tab.set_worker(self._worker, force=False)

    # -- alapértelmezett dolgozó --
    def worker_name(self) -> str:
        return self._worker

    def list_target(self):
        """Hol keressenek a fájllisták: a kiválasztott dolgozó mappájában (a két
        alkönyvtárával együtt), vagy ha nincs, a munkamappában. -> (mappa, almappák)"""
        f = self.folder.get()
        if self._worker:
            d = os.path.join(f, self._worker)
            if os.path.isdir(d):
                return d, WORK_DIRS
        return f, ()

    def _worker_values(self):
        """A legördülő: a beírt részletre szűkítve (mint a fülek WorkerPickere)."""
        try:
            dirs = worker_dirs(self.folder.get())
        except OSError:
            dirs = []
        txt = self.worker.get().strip()
        who, hits = resolve_worker("" if txt == NO_WORKER else txt, dirs)
        self.worker_cb.configure(values=[NO_WORKER] + (dirs if who else hits))

    def _worker_commit(self, _e=None):
        txt = self.worker.get().strip()
        if txt in ("", NO_WORKER):
            name = ""
        else:
            try:
                dirs = worker_dirs(self.folder.get())
            except OSError:
                dirs = []
            name, hits = resolve_worker(txt, dirs)
            if not name:
                self.status(f"Dolgozó: {len(hits)} találat — pontosíts" if hits
                            else f"Nincs ilyen dolgozói mappa: „{txt}”")
                self.worker.set(self._worker)
                return
        self.worker.set(name)
        if name == self._worker:
            return
        self._worker = name
        remember("dolgozo", name or NO_WORKER)
        for tab in self.tabs.values():        # váltáskor minden fülön átveszik
            if hasattr(tab, "set_worker"):
                tab.set_worker(name, force=True)
        self.status(f"Alapértelmezett dolgozó: {name} — az Összeállító, az Arckép és a "
                    "fájllisták ezt használják (az Iktató nem)." if name else
                    "Nincs alapértelmezett dolgozó: a fájllisták a munkamappát mutatják.")

    def active_tab(self):
        """A látható fül — az Eszközök alfüléig lemegy (gyorsbillentyűk!)."""
        try:
            w = self.nametowidget(self.nb.select())
            return self.nametowidget(w.select()) if w is self.tools else w
        except Exception:
            return None

    def show(self, tab):
        """Váltás erre a fülre, az Eszközök alfülére is."""
        if tab.master is self.tools:
            self.tools.select(tab)
            self.nb.select(self.tools)
        else:
            self.nb.select(tab)

    def status(self, txt):
        self._status.set(txt)

    def _tab_changed(self, _e=None):
        tab = self.active_tab()
        if tab is self.tabs["Áttekintő"]:
            tab.refresh()        # iktatás után is friss állapot
        elif tab is self.tabs["Összeállító"]:
            tab.refresh()        # közben új dolgozói mappa vagy doktípus jöhetett

    def goto_iktato(self, who, rule_name=None, path=None):
        """Az Áttekintő jobb klikkes menüjéből: Iktató a dolgozóra szűrve,
        a doktípus előválasztva, opcionálisan egy fájllal a várólistán."""
        ikt, att = self.tabs["Iktató"], self.tabs["Áttekintő"]
        rule = next((r for r in att.rules if r.name == rule_name), None)
        if rule:    # az az Iktató-típus, amelyből ennek a szabálynak megfelelő fájlnév lesz
            t = next((t for t in ikt.types if match_rule(
                target_name(who, t, ikt.suffix.get()), att.rules)[0] is rule), None)
            if t:
                ikt.doc_type.set(t)
        ikt.filter_text.set(who)
        if path:
            ikt._enqueue([path])
        ikt._type_chosen()
        self.show(ikt)

    def goto_composer(self, path, who=""):
        """Az Iktatóból: egy többoldalas köteg az Összeállítóba, a dolgozóval."""
        tab = self.tabs["Összeállító"]
        tab._add([path])
        if who.strip() and not tab.who_text.get().strip():
            tab.who_text.set(who)
        self.show(tab)

    def goto_arckep(self, folder):
        self.tabs["Arckép elhelyezés"].set_folder(folder)
        self.show(self.tabs["Arckép elhelyezés"])

    def goto_szerkeszto(self, path, parent=None):
        """Az Áttekintő jobb klikkes menüjéből: a fájl a Szerkesztés fülön; a
        mentés a munkamappa naplójába kerül."""
        tab = self.tabs["Szerkesztés"]
        self.show(tab)
        self.update_idletasks()          # a vászon mérete kell az illesztéshez
        tab.open_file(path, parent)


# ── önteszt ─────────────────────────────────────────────────────────────────
def _tolerant(fn) -> bool:
    """Lefutott-e kivétel nélkül (öntesztekhez)."""
    try:
        fn()
        return True
    except Exception:
        return False


def _selftest() -> int:
    res = []
    RULES = rules_from(default_settings())

    def ck(label, cond, actual=""):
        res.append(bool(cond))
        print(("  PASS  " if cond else "  FAIL  ") + label +
              (f"   -> {actual}" if actual != "" else ""))

    def mid(fn):
        r, _ = match_rule(fn, RULES)
        return r.id if r else None

    print("FELISMERÉS")
    ck("formanyomtatvány (docgen név)",
       mid("Horvath Daniel Tart_eng_formanyomtatvany.docx") == "forma")
    ck("előzetes megállapodás", mid("Kiss Anna Előzetes megállapodás (2).pdf")
       == "elozetes")
    ck("ELŐZETES PRÓBAIDŐ NÉLKÜL (a bejelentett eset)",
       mid("X Y Előzetes próbaidő nélkül_ukran_alairt.pdf") == "elozetes",
       mid("X Y Előzetes próbaidő nélkül_ukran_alairt.pdf"))
    ck("aláhúzásos docx", mid("Nagy_Bela_Elozetes_megallapodas.docx") == "elozetes")
    ck("elfogadó -> elismerés", mid("X Elfogadó nyilatkozat aláírt.pdf") == "elismer")
    ck("belföldi meghatalmazás", mid("X Belföldi meghatalmazás aláírt.pdf") == "meghat")
    ck("útlevélmásolat", mid("utlevelmasolat.pdf") == "utlevel")
    ck("szálláshely VÁLTOZATLANSÁG",
       mid("X Nyilatkozat szálláshely változatlanságáról.pdf") == "szallv")
    ck("szálláshely-IGAZOLÁS", mid("Szálláshely-igazolás.pdf") == "szalli")
    ck("diploma -> végzettség", mid("diploma.pdf") == "vegzett")
    ck("NAV igazolás", mid("nav_igazolas.pdf") == "nav")
    ck("NÉV nem NAV (Navratil)",
       mid("Navratil Ivan Előzetes megállapodás.pdf") == "elozetes")
    ck("Navratil + próbaidő sem NAV",
       mid("Navratil Ivan előzetes próbaidő nélkül.pdf") == "elozetes")
    ck("ismeretlen -> melléklet", mid("valami_mas_irat.pdf") is None)
    ck("rövidített név -> nem tippel", mid("Kiss Anna Nyilatkozat.pdf") is None)

    print("KULCSSZÓ-SZERKESZTÉS")
    r = Rule("teszt", "Teszt", "T", [], ["sajat kulcsszo"])
    ck("saját kulcsszó illeszkedik",
       score(norm("X Y sajat_kulcsszo alairt"), r) > 0)
    r2 = Rule("t2", "T2", "T2", ["alfa", "beta"], [])
    ck("all_of: csak az egyik -> 0", score(norm("csak alfa"), r2) == 0)
    ck("all_of: mindkettő -> >0", score(norm("alfa es beta"), r2) > 0)
    r3 = Rule("t3", "T3", "T3", [], ["re:\\bxy\\b"])
    ck("regex szóhatár", score(norm("abc xy def"), r3) > 0 and
       score(norm("abcxydef"), r3) == 0)

    print("ZAJSZŰRÉS")
    ck("Word zárolófájl", is_noise("~$Elfogadó nyilatkozat.docx"))
    ck("iktató .part", is_noise("valami.pdf.part"))
    ck("almappában lévő zaj", is_noise(os.path.join("Regi", "Thumbs.db")))
    ck("valódi fájl nem zaj", not is_noise("Horváth Dániel Útlevél.pdf"))

    print("BEÁLLÍTÁSOK")
    s = default_settings()
    ck("alapból 14 szabály", len(s["rules"]) == 14, len(s["rules"]))
    ck("6 kötelező", sum(1 for d in s["rules"] if d["required"]) == 6)
    ck("azonosítók egyediek",
       len({d["id"] for d in s["rules"]}) == len(s["rules"]))
    ck("alap mélység 1", s["scan_depth"] == 1)
    ck("kör: Rule -> dict -> Rule",
       rules_from({"rules": [asdict(x) for x in RULES]})[1].any_of ==
       RULES[1].any_of)

    print("RÉGI SZABÁLYFÁJL ÉS EMLÉKEZET")
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        g = globals()
        old_sd = g["script_dir"]
        g["script_dir"] = lambda: td
        try:
            # A mezőt nem ismerő (régi) szabályfájl: az arckép-jelölő NEM veszhet
            # el, különben a fotó nélküli formanyomtatvány a feltölthetőbe kerül.
            legacy = [{k: v for k, v in asdict(r).items() if k != "arckep"}
                      for r in DEFAULT_RULES]
            with open(settings_path(), "w", encoding="utf-8") as f:
                json.dump({"rules": legacy}, f)
            R = rules_from(load_settings())
            ck("régi szabályfájl: az arckép-jelölő az alapértelmezésből pótlódik",
               next(r for r in R if r.id == "forma").arckep)
            ck("célmappa régi szabályfájllal is 01, amíg nincs fotó",
               target_subdir("Tartózkodási engedély formanyomtatvány", R, False) == DIR_PREP)
            # A „taj” később született: a régi fájlhoz hozzáadódik…
            regi = [asdict(r) for r in DEFAULT_RULES if r.id != "taj"]
            with open(settings_path(), "w", encoding="utf-8") as f:
                json.dump({"rules": regi}, f)
            R = rules_from(load_settings())
            ck("régi szabályfájl: az új alapszabály (taj) hozzáadódik",
               [r.id for r in R].count("taj") == 1, [r.id for r in R])
            ck("…és felismeri a DocGen kimenetét",
               match_rule("Kovacevic Milan NYT.52.K.pdf", R)[0].id == "taj")
            ck("a TAJ-igénylés másik két irata is, egyértelműen",
               match_rule("Kovacevic Milan TAJ-igénylőlap (NYT.53).pdf", R) == (
                   next(r for r in R if r.id == "tajigeny"), False) and
               match_rule("Kovacevic Milan TAJ-meghatalmazás.pdf", R) == (
                   next(r for r in R if r.id == "tajmeghat"), False))
            ck("a sima meghatalmazás marad „meghat”",
               match_rule("Kiss Anna Belföldi meghatalmazás aláírt.pdf", R)[0].id == "meghat")
            # …de amit a felhasználó kézzel törölt (és mentett), az nem jön vissza.
            s2 = load_settings()
            s2["rules"] = [d for d in s2["rules"] if d["id"] != "taj"]
            save_settings(s2)
            ck("kézzel törölt alapszabály nem tér vissza",
               all(r.id != "taj" for r in rules_from(load_settings())))
            # A felhasználó saját szabálya nem tűnik el az összefésüléstől.
            with open(settings_path(), "w", encoding="utf-8") as f:
                json.dump({"rules": regi + [asdict(Rule("sajat", "Saját", "S", [], ["sajat"]))]}, f)
            ids = [r.id for r in rules_from(load_settings())]
            ck("saját szabály megmarad, az új alapszabály mellé", "sajat" in ids and "taj" in ids, ids)
            remember("mellekletek", td)
            ck("emlékezet: útvonal visszaolvasható", recall("mellekletek") == td)
            remember("doktipus", "Útlevél")
            ck("emlékezet: a doktípus is megmarad", recall("doktipus") == "Útlevél")
            remember("mellekletek", os.path.join(td, "x.pdf"))
            ck("emlékezet: fájlútvonalból a mappa", recall("mellekletek") == td)
            with open(memory_path(), "w", encoding="utf-8") as f:
                json.dump({"munkamappa": os.path.join(td, "nincs-ilyen")}, f)
            ck("emlékezet: eltűnt mappa helyett a tartalék",
               recall("munkamappa", "tartalék") == "tartalék")
        finally:
            g["script_dir"] = old_sd

    print("BEOLVASÁS A KÉT ALKÖNYVTÁRRAL")
    with tempfile.TemporaryDirectory() as td:
        who = os.path.join(td, "Teszt Elek")
        up = os.path.join(who, DIR_UP)
        prep = os.path.join(who, DIR_PREP)
        os.makedirs(os.path.join(up, "Regi"))
        os.makedirs(prep)
        for p, fn in [
                (up, "Teszt Elek Aláírt formanyomtatvány aláírt.pdf"),
                (up, "Teszt Elek Előzetes próbaidő nélkül_ukran_alairt.pdf"),
                (up, "Teszt Elek Elfogadó nyilatkozat aláírt.pdf"),
                (up, "Teszt Elek Egyoldalú hozzájárulási nyilatkozat.pdf"),
                (up, "Teszt Elek Belföldi meghatalmazás aláírt.pdf"),
                (up, "Teszt Elek Útlevél.pdf"),
                (prep, "Teszt Elek.jpg"),
                (prep, "~$zar.docx"),
                (os.path.join(up, "Regi"), "nav_igazolas.pdf")]:
            open(os.path.join(p, fn), "w").close()

        r1 = scan(td, RULES, 1)[0]
        ck("mind a 6 kötelező a feltölthetőben -> BEADHATÓ",
           r1.beadhato and r1.ready_required == 6, r1.ready_required)
        ck("cella: F, ahol csak feltölthető van",
           r1.docs["utlevel"].cell == "F", r1.docs["utlevel"].cell)
        ck("a 01/02 nem „egyéb almappa”", r1.subdirs == 0, r1.subdirs)
        ck("mélység 1: a 02 alatti Regi még nem látszik", not r1.docs["nav"].pdf)
        r2 = scan(td, RULES, 2)[0]
        ck("mélység 2: a 02/Regi is megvan, és F-nek számít",
           r2.docs["nav"].cell == "F", r2.docs["nav"].cell)
        ck("zaj kimaradt", not r1.other, r1.other)
        ck("nincs besorolatlan fájl", not r1.unsorted, r1.unsorted)

        # csak előkészített példány: E, és NEM beadható
        open(os.path.join(prep, "Teszt Elek Szálláshely-igazolás.pdf"), "w").close()
        re1 = scan(td, RULES, 1)[0]
        ck("cella: E, ahol csak előkészített van",
           re1.docs["szalli"].cell == "E", re1.docs["szalli"].cell)
        ck("az előkészített benne van a nyomtatandóban",
           "Szálláshely-igazolás" in re1.to_print, re1.to_print)

        # mindkettőben: EF
        open(os.path.join(up, "Teszt Elek Szálláshely-igazolás.pdf"), "w").close()
        ref = scan(td, RULES, 1)[0]
        ck("cella: EF, ha mindkettőben van",
           ref.docs["szalli"].cell == "EF", ref.docs["szalli"].cell)
        ck("EF -> már nem nyomtatandó",
           "Szálláshely-igazolás" not in ref.to_print, ref.to_print)
        ck("EF nem „több PDF”: az előkészített + aláírt példány a normális állapot",
           [n for n, _ in ref.duplicates] == [], ref.duplicates)

        # a gyökérben hagyott irat: besorolatlan, NEM beadható
        root_pdf = os.path.join(who, "Teszt Elek Végzettséget igazoló okirat.pdf")
        open(root_pdf, "w").close()
        ru = scan(td, RULES, 1)[0]
        ck("cella: ~ a gyökérben hagyott iratra",
           ru.docs["vegzett"].cell == "~", ru.docs["vegzett"].cell)
        ck("a besorolatlan megjelenik a listában",
           os.path.basename(root_pdf) in ru.unsorted, ru.unsorted)
        os.remove(root_pdf)

        big = os.path.join(up, "Teszt Elek Útlevél.pdf")
        with open(big, "wb") as f:
            f.truncate(UPLOAD_LIMIT + 1)
        rb = scan(td, RULES, 1)[0]
        ck("5 MB feletti útlevél -> nem feltölthető, NEM beadható",
           not rb.beadhato and rb.ready_required == 5,
           (rb.ready_required, list(rb.big)))
        open(os.path.join(up, "Teszt Elek Útlevél 2.pdf"), "w").close()
        rd = scan(td, RULES, 1)[0]
        ck("mellette egy korlát alatti útlevél -> beadható", rd.beadhato)
        ck("két útlevél-PDF -> „több PDF” jelzés",
           [n for n, _ in rd.duplicates] == ["Útlevél"], rd.duplicates)

        # A felülírás mentése a 01_Elokeszitett-be kerül, jelölt névvel. A mátrix
        # NEM számolhatja iratnak: különben minden felülírás hamis duplikátum lenne.
        open(os.path.join(prep, "Teszt Elek Előzetes megállapodás "
                                "(aláírt, előző példány 2026-10-07 11-30-00).pdf"),
             "w").close()
        re_ = scan(td, RULES, 1)[0]
        ck("a felülírás-mentést nem számolja iratnak",
           len(re_.docs["elozetes"].pdf) == 1 and re_.subdirs == 0,
           (re_.docs["elozetes"].pdf, re_.subdirs))

    # A régi, lapos szerkezet szándékosan NEM beadható: egy gyökérben hagyott
    # PDF-ről nem tudjuk, hogy aláírt-e (kepek-pdf-terv.md 12.3).
    with tempfile.TemporaryDirectory() as td2:
        w2 = os.path.join(td2, "Lapos Lajos")
        os.makedirs(w2)
        for fn in ("Lapos Lajos Aláírt formanyomtatvány aláírt.pdf",
                   "Lapos Lajos Előzetes megállapodás aláírt.pdf",
                   "Lapos Lajos Elfogadó nyilatkozat aláírt.pdf",
                   "Lapos Lajos Egyoldalú hozzájárulási nyilatkozat aláírt.pdf",
                   "Lapos Lajos Belföldi meghatalmazás aláírt.pdf",
                   "Lapos Lajos Útlevél.pdf"):
            open(os.path.join(w2, fn), "w").close()
        rl = scan(td2, RULES, 1)[0]
        ck("a régi lapos szerkezet NEM beadható (mind besorolatlan)",
           not rl.beadhato and rl.ready_required == 0 and len(rl.unsorted) == 6,
           (rl.ready_required, len(rl.unsorted)))

    print("CÉLMAPPA ÉS HELY")
    ck("file_loc: 02 -> F", file_loc(os.path.join(DIR_UP, "a.pdf")) == "F")
    ck("file_loc: 01 -> E", file_loc(os.path.join(DIR_PREP, "a.pdf")) == "E")
    ck("file_loc: gyökér -> ~", file_loc("a.pdf") == "~")
    ck("file_loc: más almappa -> ~", file_loc(os.path.join("Regi", "a.pdf")) == "~")
    ck("file_loc: 02 mélyebben is F",
       file_loc(os.path.join(DIR_UP, "Regi", "a.pdf")) == "F")
    ck("célmappa: útlevél -> 02", target_subdir("Útlevél", RULES) == DIR_UP)
    ck("célmappa: formanyomtatvány fotó nélkül -> 01",
       target_subdir("Tartózkodási engedély formanyomtatvány", RULES, False) == DIR_PREP)
    ck("célmappa: formanyomtatvány fotóval -> 02",
       target_subdir("Tartózkodási engedély formanyomtatvány", RULES, True) == DIR_UP)
    ck("célmappa: ismeretlen típus -> 02", target_subdir("Saját irat", RULES) == DIR_UP)
    ck("worker_root: a 02-ből egyet vissza",
       worker_root(os.path.join("X", "Kiss Anna", DIR_UP)) ==
       os.path.join("X", "Kiss Anna"))
    ck("worker_root: a dolgozó mappája önmaga",
       worker_root(os.path.join("X", "Kiss Anna")) == os.path.join("X", "Kiss Anna"))

    print("RENDEZÉS (MIGRÁCIÓ)")
    with tempfile.TemporaryDirectory() as td:
        who = os.path.join(td, "Rendez Rita")
        os.makedirs(who)
        for fn in ("Rendez Rita Útlevél aláírt.pdf",
                   "Rendez Rita Előzetes megállapodás.pdf",
                   "Rendez Rita.jpg",
                   "Rendez Rita Meghatalmazás.docx",
                   "jegyzet.txt",
                   "valami-ismeretlen.pdf"):
            open(os.path.join(who, fn), "w").close()
        terv = {t[0]: t for t in migracio_terv(who, RULES)}
        ck("aláírt utótag -> 02",
           terv["Rendez Rita Útlevél aláírt.pdf"][1] == DIR_UP)
        ck("utótag és bélyeg nélkül -> 01, tippként",
           terv["Rendez Rita Előzetes megállapodás.pdf"][1] == DIR_PREP and
           terv["Rendez Rita Előzetes megállapodás.pdf"][3] is False)
        ck("kép -> 01", terv["Rendez Rita.jpg"][1] == DIR_PREP)
        ck("docx -> 01", terv["Rendez Rita Meghatalmazás.docx"][1] == DIR_PREP)
        ck("nem irat -> marad", terv["jegyzet.txt"][1] is None)
        ck("nem ismeri fel -> marad", terv["valami-ismeretlen.pdf"][1] is None)
        done, errs = migracio_vegrehajt(who, list(terv.values()))
        ck("4 fájl mozgott, hiba nélkül", (done, errs) == (4, []), (done, errs))
        ck("az útlevél a 02-ben van",
           os.path.isfile(os.path.join(who, DIR_UP, "Rendez Rita Útlevél aláírt.pdf")))
        ck("a kép a 01-ben van",
           os.path.isfile(os.path.join(who, DIR_PREP, "Rendez Rita.jpg")))
        ck("a nem felismert a gyökérben maradt",
           os.path.isfile(os.path.join(who, "valami-ismeretlen.pdf")))
        ck("második futás már nem mozgat semmit",
           not [t for t in migracio_terv(who, RULES) if t[1]],
           migracio_terv(who, RULES))
        ck("ensure_work_dirs idempotens", ensure_work_dirs(who) == [])

    print("MUNKAMAPPA-KAPU")
    # A Rendezés csak bizonyítottan dolgozói mappában mozgat: egy tévesen
    # kiválasztott munkamappában a képeket egyébként vaktában elmozgatná.
    with tempfile.TemporaryDirectory() as td:
        ures = os.path.join(td, "Uj Ur")
        os.makedirs(ures)
        ck("üres mappa átmegy a kapun (nincs is mit mozgatni)",
           is_worker_folder(ures, RULES))

        van02 = os.path.join(td, "Van Vera")
        os.makedirs(os.path.join(van02, DIR_UP))
        ck("már van benne 02 -> átmegy", is_worker_folder(van02, RULES))

        irat = os.path.join(td, "Irat Imre")
        os.makedirs(irat)
        open(os.path.join(irat, "Irat Imre Útlevél aláírt.pdf"), "w").close()
        ck("felismert irat -> átmegy", is_worker_folder(irat, RULES))

        kepek = os.path.join(td, "nyaralas 2026")
        os.makedirs(kepek)
        for n in ("IMG_0001.jpg", "IMG_0002.jpg"):
            open(os.path.join(kepek, n), "w").close()
        ck("csak képek, se 01/02, se irat -> KIHAGYVA",
           not is_worker_folder(kepek, RULES))
        ck("a kapu nélkül a képeket elmozgatná",
           [t[1] for t in migracio_terv(kepek, RULES)] == [DIR_PREP, DIR_PREP],
           migracio_terv(kepek, RULES))

        egyeb = os.path.join(td, "projekt")
        os.makedirs(egyeb)
        open(os.path.join(egyeb, "jegyzet.txt"), "w").close()
        ck("nem felismert tartalom -> KIHAGYVA", not is_worker_folder(egyeb, RULES))

        zaj = os.path.join(td, "Zaj Zoli")
        os.makedirs(zaj)
        open(os.path.join(zaj, "Thumbs.db"), "w").close()
        ck("csak zaj -> üresnek számít, átmegy", is_worker_folder(zaj, RULES))

    # A DocGen-bélyeg bizonyíték: bélyeges PDF -> 01, akkor is, ha „aláírt” a nevében.
    with tempfile.TemporaryDirectory() as td:
        who = os.path.join(td, "Belyeg Bela")
        os.makedirs(who)
        stamped = os.path.join(who, "Belyeg Bela Meghatalmazás aláírt.pdf")
        d = pymupdf.open()
        d.new_page()
        d.set_metadata({"producer": "DocGen 10.62", "keywords": "docgen;meghat"})
        d.save(stamped)
        d.close()
        plain = os.path.join(who, "Belyeg Bela Útlevél aláírt.pdf")
        d = pymupdf.open()
        d.new_page()
        d.set_metadata(dict(CLEAN_META))
        d.save(plain)
        d.close()
        ck("has_docgen_stamp: bélyeges PDF", has_docgen_stamp(stamped))
        ck("has_docgen_stamp: bélyeg nélküli PDF", not has_docgen_stamp(plain))
        t = {x[0]: x for x in migracio_terv(who, RULES)}
        ck("a bélyeg felülírja az „aláírt” utótagot -> 01",
           t[os.path.basename(stamped)][1] == DIR_PREP,
           t[os.path.basename(stamped)])
        ck("bélyeg nélkül + utótaggal -> 02",
           t[os.path.basename(plain)][1] == DIR_UP, t[os.path.basename(plain)])

    print("OLDAL KIEMELÉSE (ISKTATÓ: OLDALANKÉNTI SZÉTOSZTÁS)")
    ck("magyar névelő a sorszám előtt (az 1., a 2., az 5., a 12.)",
       [hu_az(i) for i in (1, 2, 5, 12, 50, 100)] ==
       ["az", "a", "az", "a", "az", "a"], [hu_az(i) for i in (1, 2, 5, 12, 50, 100)])
    with tempfile.TemporaryDirectory() as td:
        koteg = os.path.join(td, "koteg.pdf")
        d = pymupdf.open()
        for i in range(4):
            d.new_page(width=595, height=842).insert_text((72, 100), f"oldal {i + 1}",
                                                          fontsize=20)
        d.save(koteg)
        d.close()
        one = extract_page(koteg, 2)
        chk = pymupdf.open("pdf", one)
        try:
            ck("a kiemelt oldal egyoldalas PDF, a KÉRT oldallal",
               chk.page_count == 1 and chk[0].get_text().strip() == "oldal 3",
               (chk.page_count, chk[0].get_text().strip()))
            ck("a lapméret megmarad", abs(chk[0].rect.width - 595) < 1, chk[0].rect)
        finally:
            chk.close()
        src = pymupdf.open(koteg)
        try:
            ck("a forrás érintetlen marad", src.page_count == 4, src.page_count)
        finally:
            src.close()
        ck("rossz oldalszám -> hiba, nem csendes üres fájl",
           not _tolerant(lambda: extract_page(koteg, 9)))

    print("BÉLYEG: DOLGOZÓ ÉS DOKTÍPUS A METAADATBAN")
    kw = stamp_keywords("Kiss Anna", "Útlevél", "utlevel", DIR_UP)
    st0 = parse_stamp(kw)
    ck("a bélyeg mind a négy adatot hordozza",
       (st0["dolgozo"], st0["tipus"], st0["szabaly"], st0["hely"]) ==
       ("Kiss Anna", "Útlevél", "utlevel", DIR_UP), st0)
    ck("idegen kulcsszó megmarad (a DocGen-jel is)",
       "docgen" in stamp_keywords("X", "Y", old="docgen;meghat"))
    ck("újrabélyegzés nem duplázza a kulcsokat",
       stamp_keywords("Nagy Béla", "Útlevél", old=kw).count("dolgozo=") == 1)
    ck("a pontosvessző és az egyenlőségjel kiesik a névből",
       parse_stamp(stamp_keywords("A;B=C", "T"))["dolgozo"] == "A B C")
    ck("bélyeg nélküli kulcsszó -> üres", parse_stamp("docgen;meghat") == {})
    with tempfile.TemporaryDirectory() as td:
        f = os.path.join(td, "a.pdf")
        d = pymupdf.open()
        d.new_page()
        d.new_page()
        d.set_metadata({"producer": "DocGen 10.62", "keywords": "docgen;meghat"})
        d.save(f)
        d.close()
        before = open(f, "rb").read()
        ok = stamp_pdf_file(f, "Kiss Anna", "Meghatalmazás", "meghat", DIR_UP)
        after = open(f, "rb").read()
        ck("bélyegzés növekményes: az eddigi bájtok érintetlenek",
           ok and after.startswith(before) and len(after) > len(before),
           (ok, len(before), len(after)))
        chk = pymupdf.open(f)
        pages = chk.page_count
        chk.close()
        ck("a DocGen-bélyeg és az oldalszám megmarad",
           has_docgen_stamp(f) and pages == 2, (has_docgen_stamp(f), pages))
        ck("a fájlból visszaolvasva ugyanaz",
           read_stamp(f)["tipus"] == "Meghatalmazás", read_stamp(f))
        ck("bélyeg nélküli és nem létező fájl -> üres",
           read_stamp(os.path.join(td, "nincs.pdf")) == {})

    # Átnevezés: a NÉV az elsődleges igazság, a bélyeg a tartalék (13.5)
    with tempfile.TemporaryDirectory() as td:
        who = os.path.join(td, "Kiss Anna")
        up = os.path.join(who, DIR_UP)
        os.makedirs(up)
        ren = os.path.join(up, "scan0042.pdf")        # értelmetlen szkennernév
        d = pymupdf.open()
        d.new_page()
        d.save(ren)
        d.close()
        r0 = scan(td, RULES, 1)[0]
        ck("bélyeg nélkül az átnevezett irat csak melléklet",
           r0.docs["utlevel"].cell == "·" and not r0.by_stamp,
           (r0.docs["utlevel"].cell, r0.extra_pdfs))
        stamp_pdf_file(ren, "Kiss Anna", "Útlevél", "utlevel", DIR_UP)
        r1 = scan(td, RULES, 1)[0]
        rel = os.path.join(DIR_UP, "scan0042.pdf")
        ck("bélyeggel az átnevezett irat a típusához számít, és jelezve van",
           r1.docs["utlevel"].cell == "F" and r1.by_stamp == [rel] and not r1.foreign,
           (r1.docs["utlevel"].cell, r1.by_stamp))
        ck("a felismert nevű iratot nem írja felül a bélyeg (a név az igazság)",
           match_rule("Kiss Anna Útlevél.pdf", RULES)[0].id == "utlevel")
        stamp_pdf_file(ren, "Nagy Béla", "Útlevél", "utlevel", DIR_UP)
        r2 = scan(td, RULES, 1)[0]
        ck("más dolgozó bélyege -> IDEGEN jelzés",
           r2.foreign == [(rel, "Nagy Béla")], r2.foreign)
        stamp_pdf_file(ren, "Kiss Anna", "Útlevél", "utlevel", DIR_UP)
        moved = os.path.join(who, "akarmi.pdf")       # kiesett a gyökérbe, átnevezve
        os.replace(ren, moved)
        terv = {t[0]: t for t in migracio_terv(who, RULES)}
        ck("Rendezés: a bélyeg bizonyíték, visszaviszi a 02-be",
           terv["akarmi.pdf"][1] == DIR_UP and terv["akarmi.pdf"][3] is True,
           terv["akarmi.pdf"])

    print("IKTATÓ-TÍPUS ↔ ÁTTEKINTŐ-SZABÁLY")
    for t in DOC_TYPES_DEFAULT:
        r, amb = match_rule(target_name("Kiss Anna", t), RULES)
        ck(f"{t} -> egyértelmű szabály", r is not None and not amb, r.id if r else None)
    ck("minden szabálynév önmagára illeszkedik",
       all(match_rule(f"Kiss Anna {r.name}.pdf", RULES) == (r, False) for r in RULES))

    print("5 MB ÉS TÖMÖRÍTÉS")
    w, h = 1800, 2500                              # zajos „szkennelt” lap
    noisy = pymupdf.Pixmap(pymupdf.csRGB, w, h, os.urandom(w * h * 3), False)
    doc = pymupdf.open()
    for _ in range(2):
        pg = doc.new_page(width=595, height=842)
        pg.insert_image(pg.rect, stream=noisy.tobytes("jpeg", jpg_quality=95))
    raw = doc.tobytes(garbage=4, deflate=True)
    doc.close()
    ck("a PyMuPDF minden szükséges képessége megvan", not missing_features(),
       (pymupdf.VersionBind, missing_features()))
    seen = []
    g = shrink_steps(raw)
    try:
        while True:
            seen.append(next(g))
    except StopIteration as s:
        small, step = s.value
    chk = pymupdf.open("pdf", small)
    ck("tömörítés a korlát alá, oldalszám marad",
       len(raw) > UPLOAD_LIMIT >= len(small) and chk.page_count == 2 and step,
       f"{mb(len(raw))} -> {mb(len(small))}, {step}")
    chk.close()
    ck("lépcsőnként halad, és megáll, amint befért", seen[-1] == step and len(seen) <= 4, seen)
    ck("ha már az első lépcső elég, ott megáll",
       shrink_pdf(small, limit=len(small))[1] == SHRINK_STEPS[0])
    with tempfile.TemporaryDirectory() as td:
        be, ki = os.path.join(td, "be.pdf"), os.path.join(td, "ki.pdf")
        with open(be, "wb") as f:
            f.write(raw)
        kod = shrink_cli([be, ki, str(UPLOAD_LIMIT)])
        ck("külön folyamat ága (--tomorit): kiírja a tömörített PDF-et",
           kod == 0 and os.path.getsize(ki) <= UPLOAD_LIMIT < os.path.getsize(be),
           (kod, mb(os.path.getsize(ki))))
        d2 = pymupdf.open(ki)
        ck("és az oldalszám megmarad", d2.page_count == 2, d2.page_count)
        d2.close()
        ck("hiányzó bemenetnél hibakóddal áll le, nem némán",
           shrink_cli([os.path.join(td, "nincs.pdf"), ki]) == 1)
    with tempfile.TemporaryDirectory() as td:
        dst = os.path.join(td, "x.pdf")
        try:
            write_pdf_verified(small, dst, 3)
            ok = False
        except IOError:
            ok = not os.listdir(td)
        ck("oldalszám-eltérés -> hiba, nem marad .part", ok)

    print("KÉPEK → PDF")
    half = bytes((255, 255, 255) * 200 + (0, 0, 0) * 200) * 200    # 400×200, bal fele fehér
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "fekvo.jpg")
        with open(p, "wb") as f:
            f.write(pymupdf.Pixmap(pymupdf.csRGB, 400, 200, half, False).tobytes("jpeg"))
        jpeg, w, h = image_page_jpeg(p, 0, 200, 75, False)
        ck("kis kép nem nagyítódik", (w, h) == (400, 200), (w, h))
        jpeg, w, h = image_page_jpeg(p, 90, 200, 75, True)
        px = pymupdf.Pixmap(jpeg)
        ck("↻ 90° = óramutató szerint (a bal fehér fél felülre kerül)",
           (w, h) == (200, 400) and px.pixel(100, 40)[0] > 200 and px.pixel(100, 360)[0] < 60,
           (w, h, px.pixel(100, 40), px.pixel(100, 360)))
        ck("szürkeárnyalat -> 1 csatorna", px.n == 1, px.n)
        big = os.path.join(td, "nagy.jpg")
        with open(big, "wb") as f:
            f.write(pymupdf.Pixmap(pymupdf.csRGB, 4000, 3000, bytes(4000 * 3000 * 3), False)
                    .tobytes("jpeg"))
        _, w, h = image_page_jpeg(big, 0, 150, 65, False)
        ck("nagy kép -> hosszabb oldal 150 DPI × A4", abs(max(w, h) - 150 * A4_LONG_IN) <= 1, (w, h))
        full = open_image_pdf(p)                      # 400×200 px -> 300×150 pt
        fr = full[0].rect
        cr = open_image_pdf(p, pymupdf.Rect(0, 0, fr.width / 2, fr.height))
        cpix = cr[0].get_pixmap()
        ck("körülvágás: a lap feleződik, és csak a fehér fél marad",
           abs(cr[0].rect.width - fr.width / 2) < 1 and
           cpix.pixel(cpix.width - 2, cpix.height // 2)[0] > 200,
           (cr[0].rect, cpix.pixel(cpix.width - 2, cpix.height // 2)))
        wide = open_image_pdf(p, pymupdf.Rect(-50, -50, 5000, 5000))
        ck("lapon kívüli vágás: nem hiba, a lap marad",
           wide[0].rect.width == fr.width, wide[0].rect)
        for d in (full, cr, wide):
            d.close()
        out = pymupdf.open()
        jpeg, w, h = image_page_jpeg(p, 0, 200, 75, False)
        add_image_page(out, jpeg, w, h, 200, True)
        pg = out[0]
        ck("fekvő kép -> fekvő A4, a JPEG bájtra azonos",
           pg.rect.width > pg.rect.height and
           out.xref_stream_raw(pg.get_images()[0][0]) == jpeg)
        out.close()

    print("FELÜLET: KÓDBÓL RAJZOLT GRAFIKA")
    data = round_png(26, 9, UI["card"], UI["line"], 1.1, shadow=1.0, pad=2)
    pix = pymupdf.Pixmap(data)

    def alpha(px, x, y):                     # a pix.n már tartalmazza az alfát
        return px.samples[(y * px.width + x) * px.n + px.n - 1]

    ck("gombkép: PNG, alfacsatornával, a kért méretben",
       data[:8] == b"\x89PNG\r\n\x1a\n" and (pix.width, pix.height) == (26, 26)
       and pix.alpha, (data[:4], pix.width, pix.height, pix.alpha))
    ck("a sarok átlátszó, a közép tömör — ettől lekerekített a gomb",
       alpha(pix, 1, 1) < 40 and alpha(pix, 13, 13) == 255,
       (alpha(pix, 1, 1), alpha(pix, 13, 13)))
    ck("a kitöltés a paletta kártyaszíne",
       pix.pixel(13, 13)[:3] == tuple(int(UI["card"].lstrip("#")[i:i + 2], 16)
                                      for i in (0, 2, 4)), pix.pixel(13, 13))
    grad = pymupdf.Pixmap(round_png(40, 9, None, None, 0, grad=("#3b74f0", "#2563eb")))
    ck("az elsődleges gomb színátmenetes (fent világosabb)",
       grad.pixel(20, 4)[0] > grad.pixel(20, 35)[0] + 8,
       (grad.pixel(20, 4), grad.pixel(20, 35)))
    ic = pymupdf.Pixmap(icon_png("folder", 17))
    ink = sum(1 for i in range(ic.width * ic.height)
              if ic.samples[i * ic.n + ic.n - 1] > 60)
    ck("az ikon tényleg rajzol valamit, és a kért méretű",
       (ic.width, ic.height) == (17, 17) and 15 < ink < 17 * 17, (ic.width, ink))
    ck("minden ikon rajzol valamit (egyik sem üres)",
       all(sum(1 for i in range(ic2.width * ic2.height)
               if ic2.samples[i * ic2.n + ic2.n - 1] > 60) > 15
           for ic2 in (pymupdf.Pixmap(icon_png(nm, 17)) for nm in ICON_PATHS)),
       [nm for nm in ICON_PATHS
        if sum(1 for i in range(17 * 17)
               if pymupdf.Pixmap(icon_png(nm, 17)).samples[i * 4 + 3] > 60) <= 15])
    ck("minden gombfelirathoz LÉTEZŐ ikon tartozik",
       all(name in ICON_PATHS for name, _p in BTN_LOOK.values()),
       [v for v in BTN_LOOK.values() if v[0] not in ICON_PATHS])
    pts = round_pts(0, 0, 100, 40, 8)
    ck("vászon-kártya pontsora: 12 pont, a dobozon belül",
       len(pts) == 24 and max(pts[0::2]) <= 100 and max(pts[1::2]) <= 40, len(pts))
    ck("a rádió- és jelölőnégyzet-kép jobbra tart térközt (ne tapadjon a felirat)",
       pymupdf.Pixmap(_box_png(17)).width == 24 and
       pymupdf.Pixmap(_radio_png(16)).width == 23)
    ck("a lista halvány árnyalata világos (sötét szöveg olvasható rajta)",
       all(sum(int(tint(c).lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)) > 650
           for c in LABEL_COLORS),
       [tint(c) for c in LABEL_COLORS[:3]])
    ck("a paletta minden színe sötét (fehér szöveg olvasható marad rajta)",
       all(sum(int(c.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)) < 560
           for c in LABEL_COLORS),
       [c for c in LABEL_COLORS
        if sum(int(c.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)) >= 560])

    print("FÉNYERŐ ÉS KONTRASZT")
    ck("fényerő +40: a középszürke világosodik", level_lut(40, 0)[128] == 179,
       level_lut(40, 0)[128])
    ck("fényerő -40: sötétedik", level_lut(-40, 0)[128] == 77, level_lut(-40, 0)[128])
    ck("a tábla nem fut ki 0..255-ből",
       level_lut(100, 100)[255] == 255 and level_lut(-100, 100)[0] == 0)
    ck("kontraszt: a 128 a tengely, a szélek szétnyílnak",
       level_lut(0, 100)[128] == 128 and level_lut(0, 100)[160] > level_lut(0, 0)[160])
    ck("kontraszt -100: minden a közép felé", level_lut(0, -100)[0] == 64,
       level_lut(0, -100)[0])
    ck("szintezés nélkül a tábla azonosság", level_lut(0, 0) == bytes(range(256)))
    with tempfile.TemporaryDirectory() as td:
        ip = os.path.join(td, "arc.jpg")                 # 200×400 px, középszürke
        with open(ip, "wb") as f:
            f.write(pymupdf.Pixmap(pymupdf.csRGB, 200, 400, bytes([128]) * 240000,
                                   False).tobytes("jpeg"))
        base = open_image_pdf(ip)
        up = open_image_pdf(ip, None, (40, 0))
        pb, pu = base[0].get_pixmap(), up[0].get_pixmap()
        ck("a szintezett kép világosabb, a lap mérete marad",
           pu.pixel(100, 200)[0] > pb.pixel(100, 200)[0] + 30 and
           abs(up[0].rect.width - base[0].rect.width) < 1,
           (pb.pixel(100, 200), pu.pixel(100, 200), up[0].rect))
        ck("a natív felbontás megmarad (nem a 72 DPI-s alap)",
           abs(image_px_scale(base) - 200 / base[0].rect.width) < 0.01,
           image_px_scale(base))
        vagott = open_image_pdf(ip, pymupdf.Rect(0, 0, 75, 150), (30, 10))
        ck("vágás és szintezés együtt",
           abs(vagott[0].rect.width - 75) < 2 and
           vagott[0].get_pixmap().pixel(10, 10)[0] > 150, vagott[0].rect)
        for d in (base, up, vagott):
            d.close()

    print("CÍMKE A SZÖVEGRÉTEGBŐL")
    with tempfile.TemporaryDirectory() as td:
        tp = os.path.join(td, "generalt.pdf")
        d = pymupdf.open()
        for title in ("Belföldi meghatalmazás", "Szálláshely-igazolás"):
            pg = d.new_page()                            # cím + törzs, mint egy valódi irat
            pg.insert_text((72, 100), title, fontsize=20)
            pg.insert_text((72, 140), "Alulírott az alábbi nyilatkozatot teszem, "
                                      "a jogkövetkezmények ismeretében.", fontsize=11)
        d.new_page()                                     # üres: nincs mire támaszkodni
        d.save(tp)
        d.close()
        ck("szövegréteg -> a cím szerinti szabály",
           (text_rule(tp, 0, RULES).id, text_rule(tp, 1, RULES).id) ==
           ("meghat", "szalli"),
           (text_rule(tp, 0, RULES), text_rule(tp, 1, RULES)))
        ck("szöveg nélküli oldal -> nincs találgatás", text_rule(tp, 2, RULES) is None)
        ck("rossz oldalszám és nem PDF -> None",
           text_rule(tp, 9, RULES) is None and text_rule("x.jpg", 0, RULES) is None)
        sp = os.path.join(td, "szkennelt.pdf")           # kép, szövegréteg nélkül
        d = pymupdf.open()
        pg = d.new_page(width=595, height=842)
        pg.insert_image(pg.rect, stream=pymupdf.Pixmap(
            pymupdf.csRGB, 60, 80, bytes([200]) * 14400, False).tobytes("jpeg"))
        d.save(sp)
        d.close()
        ck("szkennelt lap (OCR nélkül) -> None", text_rule(sp, 0, RULES) is None)

    print("ELLENŐRZÉS ÉS UTÓLAGOS BÉLYEGZÉS")
    with tempfile.TemporaryDirectory() as td:
        anna = os.path.join(td, "Kiss Anna")
        bela = os.path.join(td, "Nagy Béla")
        aup, bup = os.path.join(anna, DIR_UP), os.path.join(bela, DIR_UP)
        os.makedirs(aup)
        os.makedirs(bup)

        def pdf(path, pages=1, text=""):
            d = pymupdf.open()
            for _ in range(pages):
                pg = d.new_page()
                if text:
                    pg.insert_text((72, 100), text, fontsize=12)
            d.save(path)
            d.close()
            return path

        jo = pdf(os.path.join(aup, "Kiss Anna Útlevél.pdf"))          # bélyegezhető
        ismeretlen = pdf(os.path.join(aup, "scan0001.pdf"))           # se név, se bélyeg
        idegen = pdf(os.path.join(aup, "Kiss Anna Meghatalmazás.pdf"))
        stamp_pdf_file(idegen, "Nagy Béla", "Meghatalmazás", "meghat", DIR_UP)
        elter = pdf(os.path.join(bup, "Nagy Béla Útlevél.pdf"))
        stamp_pdf_file(elter, "Nagy Béla", "Szálláshely-igazolás", "szalli", DIR_UP)
        dup1 = pdf(os.path.join(bup, "Nagy Béla Elfogadó nyilatkozat.pdf"), 2)
        shutil.copy2(dup1, os.path.join(bup, "Nagy Béla Előzetes megállapodás.pdf"))

        a = audit_folder(td, RULES)
        ck("minden PDF egyszer át van nézve", a["seen"] == 6, a["seen"])
        ck("bélyegezhető: amit a név ÉS a hely megad",
           sorted(os.path.basename(x[1]) for x in a["stampable"]) ==
           ["Kiss Anna Útlevél.pdf", "Nagy Béla Elfogadó nyilatkozat.pdf",
            "Nagy Béla Előzetes megállapodás.pdf"],
           [x[1] for x in a["stampable"]])
        ck("felismerhetetlen név, bélyeg nélkül -> kézi",
           [os.path.basename(r) for _w, r in a["unknown"]] == ["scan0001.pdf"],
           a["unknown"])
        ck("idegen bélyeg a másik dolgozó nevével",
           a["foreign"] and a["foreign"][0][2] == "Nagy Béla", a["foreign"])
        ck("a bélyeg és a név eltérése jelezve",
           a["mismatch"] and a["mismatch"][0][2] == "Szálláshely-igazolás",
           a["mismatch"])
        ck("tartalom-azonos csoport (két néven ugyanaz)",
           len(a["dupes"]) == 1 and len(a["dupes"][0]) == 2, a["dupes"])
        ck("egyező tartalom = egyező ujjlenyomat",
           file_sha1(dup1) == file_sha1(os.path.join(
               bup, "Nagy Béla Előzetes megállapodás.pdf")) != file_sha1(jo))

        ok, errs = stamp_missing(a["stampable"])
        a2 = audit_folder(td, RULES)
        ck("utólagos bélyegzés: a bélyegezhetők elfogytak",
           (ok, errs) == (3, []) and not a2["stampable"], (ok, errs, a2["stampable"]))
        st = read_stamp(jo)
        ck("az utólagos bélyeg a névből és a helyből áll össze",
           (st["dolgozo"], st["szabaly"], st["hely"]) ==
           ("Kiss Anna", "utlevel", DIR_UP), st)
        ck("a felismerhetetlen nevű továbbra is kézi",
           len(a2["unknown"]) == 1 and not read_stamp(ismeretlen))

    print("NÉVSORREND: A DOKTÍPUS ELÖL")
    # A dolgozó neve a MAPPÁBÓL úgyis látszik; a fájlnév elején a típus álljon,
    # hogy az Intézőben arra essen a szem, és a rendezés típusonként csoportosítson.
    # A PDF-metaadat nem volt járható út (kepek-pdf-terv.md 18.).
    ck("a típus áll elöl, a dolgozó mögötte",
       target_name("Kiss Anna", "NAV jövedelemigazolás") ==
       "NAV jövedelemigazolás — Kiss Anna (aláírt).pdf",
       target_name("Kiss Anna", "NAV jövedelemigazolás"))
    ck("fotójelölővel is",
       target_name("John Doe", "Tartózkodási engedély formanyomtatvány", SUFFIX, True) ==
       "Tartózkodási engedély formanyomtatvány — John Doe (aláírt, fotóval ellátva).pdf",
       target_name("John Doe", "Tartózkodási engedély formanyomtatvány", SUFFIX, True))
    ck("jelölő nélkül nincs üres zárójel",
       target_name("Kiss Anna", "Útlevél", "") == "Útlevél — Kiss Anna.pdf")
    ck("az új sorrendet is a helyes szabályra illeszti (a gondolatjel nem zavar)",
       all(match_rule(target_name("Kiss Anna", t), RULES)[0] is not None and
           match_rule(target_name("Kiss Anna", t), RULES)[0].id == rid
           for t, rid in (("Útlevél", "utlevel"), ("Meghatalmazás", "meghat"),
                          ("NAV jövedelemigazolás", "nav"),
                          ("Előzetes megállapodás", "elozetes"))))
    ck("egy mappa listája típus szerint csoportosul",
       sorted(target_name("Kiss Anna", t, "") for t in
              ("Útlevél", "NAV jövedelemigazolás", "Előzetes megállapodás"))[0]
       .startswith("Előzetes megállapodás"))

    print("ÖSSZEÁLLÍTÓ")
    ck("oldaltartomány: 1-3,5", page_ranges([0, 1, 2, 4]) == "1-3,5", page_ranges([0, 1, 2, 4]))
    ck("oldaltartomány a rács sorrendjében: 3,1-2", page_ranges([2, 0, 1]) == "3,1-2")
    ck("napló-forrás: PDF oldalakkal, kép anélkül",
       source_desc([PageItem("k.pdf", 0), PageItem("k.pdf", 1), PageItem("f.jpg")]) ==
       "k.pdf [1-2]; f.jpg")
    pal = palette_types(DOC_TYPES_DEFAULT + ["Saját irat"], RULES)
    shorts = [r.short if r else t for t, r in pal]
    ck("paletta: az Áttekintő sorrendje, a kötelezők elöl, a saját típus a végén",
       shorts == ["Forma", "Előz", "Elism", "Hozzá", "Megh", "Útl", "SzVált", "SzIg",
                  "Végz", "NAV", "Munk", "Saját irat"], shorts)
    ck("paletta: az Iktató-típus neve marad, az Áttekintőből a szabály neve jön",
       pal[0][0] == "Tartózkodási engedély formanyomtatvány" and pal[5][0] == "Útlevél")
    ck("paletta-név -> az Áttekintő felismeri",
       all(match_rule(target_name("Kiss Anna", t), RULES)[0] is r for t, r in pal if r))
    dirs = ["Kiss Anna", "Kiss Anna Mária", "Nagy Béla", "Ökrös Zsófia"]
    ck("dolgozó: részlet -> egyetlen találat", resolve_worker("bela", dirs)[0] == "Nagy Béla")
    ck("dolgozó: ékezet és kisbetű nélkül is", resolve_worker("okros", dirs)[0] == "Ökrös Zsófia")
    ck("dolgozó: pontos egyezés nyer a hosszabb név ellen",
       resolve_worker("kiss anna", dirs)[0] == "Kiss Anna")
    ck("dolgozó: kétes részlet -> nincs választás, két találat",
       resolve_worker("kiss", dirs) == (None, ["Kiss Anna", "Kiss Anna Mária"]))
    with tempfile.TemporaryDirectory() as td:
        kp = os.path.join(td, "koteg.pdf")                 # 2 oldal, felső negyedük piros
        src = pymupdf.open()
        for k in range(2):
            px = pymupdf.Pixmap(pymupdf.csRGB, 100, 200,
                                bytes((255, 0, 0) * 5000 + (0, 0, 40 * k) * 15000), False)
            pg = src.new_page(width=300, height=600)
            pg.insert_image(pg.rect, stream=px.tobytes("jpeg"))
        src.save(kp)
        ip = os.path.join(td, "foto.jpg")
        with open(ip, "wb") as f:
            f.write(pymupdf.Pixmap(pymupdf.csRGB, 400, 200, half, False).tobytes("jpeg"))
        out, srcs = pymupdf.open(), {}
        add_item_page(out, PageItem(kp, 1, rot=90), 200, 75, False, True, srcs)
        add_item_page(out, PageItem(ip), 200, 75, False, True, srcs)
        ck("PDF-oldal veszteségmentesen: a kép bájtra azonos",
           out.xref_stream_raw(out[0].get_images()[0][0]) ==
           src.xref_stream_raw(src[1].get_images()[0][0]))
        def red_at(pix):             # melyik szélén piros: 0 fent, 1 jobb, 2 lent, 3 bal
            probes = ((0.5, 0.1), (0.9, 0.5), (0.5, 0.9), (0.1, 0.5))
            rgb = [pix.pixel(int(x * (pix.width - 1)), int(y * (pix.height - 1))) for x, y in probes]
            return [i for i, c in enumerate(rgb) if c[0] > 200 and c[2] < 80]
        thumb = src[1].get_pixmap(matrix=pymupdf.Matrix(0.3, 0.3).prerotate(90))
        ck("forgatás: a kimenet ugyanarra fordul, mint a bélyegkép (/Rotate 90)",
           out[0].rotation == 90 and red_at(out[0].get_pixmap()) == red_at(thumb) == [1],
           (out[0].rotation, red_at(out[0].get_pixmap()), red_at(thumb)))
        ck("vegyes irat: PDF-oldal + kép", out.page_count == 2 and out[1].get_images())
        out.close()
        for d in srcs.values():
            d.close()
        src.close()

    print("IKTATÓMAG")
    with tempfile.TemporaryDirectory() as td:
        who = os.path.join(td, "Kiss Anna")
        os.makedirs(who)
        dst = os.path.join(who, "Kiss Anna Útlevél.pdf")
        with open(dst, "w") as f:
            f.write("régi")
        bak = backup_existing(dst)
        ck("felülírás előtt: jelölt másolat a 01_Elokeszitett-ben",
           os.path.dirname(bak) == os.path.join(who, DIR_PREP) and
           MARK_BACKUP in os.path.basename(bak) and
           open(bak).read() == "régi", bak)
        ck("a mentést az is_noise kiszűri (nem kerül a mátrixba)",
           is_noise(os.path.basename(bak)), os.path.basename(bak))
        with open(dst, "w") as f:
            f.write("új")
        undo_copy(dst, bak)
        ck("visszavonás felülírás után: a régi visszaállt, a másolat eltűnt",
           open(dst).read() == "régi" and not os.path.exists(bak))
        undo_copy(dst, None)
        ck("visszavonás új fájlnál: a cél törlődik", not os.path.exists(dst))
        for r in ("OK", "VISSZAVONVA"):
            log_row(td, "forras.pdf", "Kiss Anna", "Kiss Anna Útlevél.pdf", "Útlevél", r)
        with open(os.path.join(td, LOG_NAME), encoding="utf-8-sig") as f:
            rows = list(csv.reader(f, delimiter=";"))
        ck("napló: egy fejléc, soronként egy iktatás",
           len(rows) == 3 and rows[0][0] == "időbélyeg" and
           [r[5] for r in rows[1:]] == ["OK", "VISSZAVONVA"], rows)
        log_row(os.path.join(td, "nincs"), "x", "y", "z", "t", "OK")
        ck("hibás naplóhely nem dob kivételt", True)

    print("SZERKESZTŐ")
    # Word-szerű lap: táblázat vékony kitöltött téglalapokból, egy sorban négy
    # egyenetlen betűnkénti cella, egy keretes jelölőnégyzet, egy aláhúzás, szöveg.
    d = pymupdf.open()
    pg = d.new_page(width=595, height=842)
    sh = pg.new_shape()
    for y in (100, 120, 140):
        sh.draw_rect(pymupdf.Rect(50, y - 0.25, 400, y + 0.25))
    for x in (50, 150, 400):
        sh.draw_rect(pymupdf.Rect(x - 0.25, 100, x + 0.25, 120))
    for x in (50, 150, 175, 190, 215, 400):
        sh.draw_rect(pymupdf.Rect(x - 0.25, 120, x + 0.25, 140))
    sh.draw_rect(pymupdf.Rect(300, 103, 400, 120.5))      # (nem vonal: 17 pt magas)
    sh.finish(color=None, fill=(0, 0, 0))
    sh.draw_rect(pymupdf.Rect(60, 200, 71, 211))
    sh.draw_line((60, 260), (260, 260))
    sh.finish(color=(0, 0, 0), fill=None, width=0.6)
    sh.commit()
    add_text(pg, (55, 114), "Régi szöveg", pymupdf.Font("helv"), 10)
    dr = pg.get_drawings()
    L = page_lines(dr)
    rr = lambda r: r and [round(v) for v in r]
    ck("cella a vonalakból", rr(snap_cell(L, 100, 110)) == [50, 100, 150, 120], rr(snap_cell(L, 100, 110)))
    ck("aláhúzásos rovat: a vonal fölötti sáv", rr(snap_cell(L, 150, 255)) == [60, 246, 260, 260],
       rr(snap_cell(L, 150, 255)))
    ck("vonal nélkül nincs illesztés", snap_cell(L, 500, 500) is None)
    cells = snap_cells(L, pymupdf.Rect(160, 125, 200, 135))
    ck("húzás a cellákon: a két szélső cella is teljes",
       [rr(c)[0] for c in cells] == [150, 175, 190], [rr(c) for c in cells])
    ck("jelölőnégyzet a keretes négyzetből", rr(snap_box(dr, 65, 205)) == [60, 200, 71, 211])
    ck("a nagy téglalap nem jelölőnégyzet", snap_box(dr, 350, 110) is None)
    n0 = len(dr)
    sp = span_at(pg, 70, 110)
    ck("a kattintott szöveg", sp is not None and sp["text"] == "Régi szöveg")
    rewrite_span(d, pg, sp, "Árvíztűrő Őrs", pymupdf.Font("helv"))
    t = pg.get_text()
    ck("átírás: a régi szöveg TÉNYLEGESEN eltűnt, az új (ő/ű) bent van",
       "Régi" not in t and "Árvíztűrő Őrs" in t, t)
    ck("átírás: a vonalak megmaradtak", len(pg.get_drawings()) == n0)
    box = snap_box(dr, 65, 205)
    ck("X be", toggle_x(pg, box, pymupdf.Font("helv")) and "X" in pg.get_text("text", clip=box))
    ck("X ki", not toggle_x(pg, box, pymupdf.Font("helv")) and
       "X" not in pg.get_text("text", clip=box) and len(pg.get_drawings()) == n0)
    add_field(pg, snap_cell(L, 100, 130), "date_of_birth_year#1")
    add_field(pg, box, "Neme=male", check=True)
    names = sorted(w.field_name for w in pg.widgets())
    ck("mezők a DocGen-jelölő nevével", names == ["Neme=male", "date_of_birth_year#1"], names)
    ck("mező a pontnál", field_at(pg, 100, 130).field_name == "date_of_birth_year#1")
    rename_field(d, field_at(pg, 100, 130), "employment_start_year#1")
    ck("átnevezés", field_at(pg, 100, 130).field_name == "employment_start_year#1")
    add_text(pg, (60, 400), "Új sor itt", edit_font("Calibri"), 10.5)
    ck("a szövegrétegben rendes szóköz (nem U+00A0), Calibrivel is",
       "Új sor itt" in pg.get_text(), repr(pg.get_text()[-20:]))
    ck("mezőnév: pont nem lehet benne", field_name_error("a.b") and not field_name_error("{a}, {b}#2"))
    d.set_metadata({"keywords": "pdf-muhely=1;dolgozo=Kiss Anna"})
    set_upper(d, True)
    ck("nagybetűs jelölő be, a bélyeg megmarad",
       get_upper(d) and "dolgozo=Kiss Anna" in d.metadata["keywords"], d.metadata["keywords"])
    set_upper(d, False)
    ck("nagybetűs jelölő ki", not get_upper(d) and d.metadata["keywords"] == "pdf-muhely=1;dolgozo=Kiss Anna")
    erase_area(pg, pymupdf.Rect(52, 102, 148, 118))
    ck("kitakarás: a terület szövege eltűnt", "Árvíztűrő" not in pg.get_text())
    d2 = pymupdf.open("pdf", d.tobytes())
    ck("mentés után is olvasható mezők", sum(1 for _ in d2[0].widgets()) == 2)
    d2.close()
    d.close()

    print("BEKEZDÉS")
    # Próbalap: cím + két balra zárt bekezdés ragged jobb széllel, a hasáb 60..520.
    d = pymupdf.open()
    pg = d.new_page(width=595, height=842)
    FB, FN = edit_font("Calibri", True), edit_font("Calibri")
    COL, GAP, SZ = 460.0, 14.0, 10.5

    def fill(page, words, base, font, size, x0=60.0, gap=GAP, col=COL):
        """Balra zárt bekezdés: a hasáb szélessége tördeli, a szavak a tördelés
        szerinti helyükre kerülnek — ugyanazokkal a magfüggvényekkel, mint a fülön."""
        wd = [font.text_length(w, size) for w in words]
        sp = font.text_length(" ", size)
        rows = wrap_words(wd, sp, col)
        for r, row in enumerate(rows):
            xs = line_positions([wd[i] for i in row], x0, x0 + col, sp, "left")
            for i, x in zip(row, xs):
                add_text(page, (x, base + r * gap), words[i], font, size)
        return len(rows)

    P1 = ("Alulírott munkavállaló kijelentem, hogy a bejelentett magyarországi "
          "szálláshelyem a kérelem benyújtása óta változatlan maradt, és az ott "
          "megadott adataim a valóságnak minden tekintetben megfelelnek. A "
          "szálláshely címe, a befogadó nyilatkozata és a bérleti jogviszony "
          "időtartama a benyújtott iratokkal egyezik, azokat nem módosítottuk.").split()
    P2 = ("A nyilatkozatot a hatóság előtt felhasználni kívánom, és tudomásul veszem, "
          "hogy a valótlan tartalmú nyilatkozat jogkövetkezményekkel járhat.").split()
    add_text(pg, (60, 100), "A NYILATKOZAT TÁRGYA", FB, 12)
    n1 = fill(pg, P1, 140, FN, SZ)
    n2 = fill(pg, P2, 140 + n1 * GAP + 20, FN, SZ)
    base_pdf, nd = d.tobytes(), len(pg.get_drawings())
    ck("a próbalap felépült: cím + két bekezdés", n1 >= 4 and n2 >= 2, (n1, n2))

    # -- felismerés --
    p = paragraph_at(pg, 200, 139)
    ck("a bekezdés sorai a kattintásból (a cím és a másik bekezdés nélkül)",
       p is not None and len(p["lines"]) == n1, None if p is None else len(p["lines"]))
    ck("bal szél, alapvonal-távolság, méret",
       abs(p["left"] - 60) < 0.5 and abs(p["gap"] - GAP) < 0.5 and abs(p["size"] - SZ) < 0.1,
       (p["left"], p["gap"], p["size"]))
    ck("egységes formázású bekezdés: nem vegyes", not p["mixed"])
    ck("a mai igazítás: balra zárt", guess_align(p) == "left", guess_align(p))
    ck("a második bekezdés külön bekezdés",
       len(paragraph_at(pg, 200, 140 + n1 * GAP + 20 - 1)["lines"]) == n2)
    ck("a cím egysoros bekezdés", len(paragraph_at(pg, 100, 98)["lines"]) == 1)
    ck("szövegen kívül nincs bekezdés", paragraph_at(pg, 560, 700) is None)
    ck("a bekezdés szövege visszaolvasható", para_text(p).split() == P1, para_text(p)[:60])

    # -- line_positions és wrap_words: tiszta függvények --
    xs = line_positions([30, 20, 25], 100, 200, 4, "justify")
    ck("sorkizárt hézag: az utolsó szó pontosan a jobb szélen ér véget",
       xs == [100, 142.5, 175.0] and abs(xs[-1] + 25 - 200) < 1e-9, xs)
    ck("az utolsó sort nem nyújtjuk",
       line_positions([30, 20], 100, 200, 4, "justify", last=True) == [100, 134])
    ck("egyszavas sort nem nyújtunk", line_positions([30], 100, 200, 4, "justify") == [100])
    ck("rövid sort nem teszünk sorkizárttá (félreismert bekezdésvég)",
       line_positions([10, 10], 100, 200, 4, "justify") == [])
    ck("jobbra zárt: az utolsó szó a jobb szélen",
       line_positions([30, 20], 100, 200, 4, "right") == [146, 180])
    ck("középre: a sor a hasáb közepén",
       line_positions([30, 20], 100, 200, 4, "center") == [123, 157])
    ck("üres sorhoz nincs pozíció", line_positions([], 100, 200, 4, "left") == [])
    ck("tördelés: a sorok a szélesség alá esnek",
       wrap_words([30, 30, 30, 30], 4, 70) == [[0, 1], [2, 3]],
       wrap_words([30, 30, 30, 30], 4, 70))
    ck("tördelés: az első sor szélessége külön adható meg (behúzás)",
       wrap_words([30, 30, 30], 4, 70, 30) == [[0], [1, 2]])

    # -- sorkizárás: az eltolásos úton a sortörések NEM változnak --
    before = pg.get_text(sort=True).split()
    ck("formázás előtt nincs betűhiba", para_font_error(p, {}) == "")
    ck("sorkizárás figyelmeztetés nélkül", para_format(d, pg, p, {"align": "justify"}) == "")
    jd = pymupdf.open("pdf", d.tobytes())
    jg = jd[0]
    q = paragraph_at(jg, 200, 139)
    ck("sorkizárás után ugyanannyi sor (a sortörések nem változtak)",
       len(q["lines"]) == n1, len(q["lines"]))
    R1 = p["right"]            # a bekezdés jobb széle: a leghosszabb soráé (19.5)
    ck("minden sor a jobb szélen ér véget, az utolsó kivételével",
       all(abs(ln["bbox"][2] - R1) < 0.6 for ln in q["lines"][:-1])
       and q["lines"][-1]["bbox"][2] < R1 - 1,
       [round(ln["bbox"][2], 1) for ln in q["lines"]])
    ck("a szöveg karakterre azonos maradt (olvasási sorrendben)",
       jg.get_text(sort=True).split() == before)
    ck("a bekezdés most sorkizártnak látszik", guess_align(q) == "justify", guess_align(q))
    ck("a lap rajzai érintetlenek", len(jg.get_drawings()) == nd)
    ck("a formázott bekezdés újra felismerhető, ugyanannyi sorral",
       len(paragraph_at(jg, 200, 139)["lines"]) == n1)
    jd.close()

    # -- a többi művelet, mindig a próbalap friss példányán --
    def once(fmt, probe=(200, 139)):
        """Egy formázás a friss próbalapon -> (üzenet, az új bekezdés, az új lap)."""
        dd = pymupdf.open("pdf", base_pdf)
        m = para_format(dd, dd[0], paragraph_at(dd[0], 200, 139), fmt)
        g = pymupdf.open("pdf", dd.tobytes())[0]
        dd.close()
        return m, paragraph_at(g, *probe), g

    _m, r, _g = once({"align": "center"})
    ck("középre: minden sor a bekezdés közepén",
       all(abs((ln["bbox"][0] + ln["bbox"][2]) / 2 - (60 + R1) / 2) < 1.5
           for ln in r["lines"]),
       [round((ln["bbox"][0] + ln["bbox"][2]) / 2, 1) for ln in r["lines"]])
    _m, r, _g = once({"align": "right"})
    ck("jobbra: minden sor a jobb szélen",
       all(abs(ln["bbox"][2] - R1) < 0.6 for ln in r["lines"]),
       [round(ln["bbox"][2], 1) for ln in r["lines"]])
    _m, r, _g = once({"gap": 21.0})
    ck("sortávolság 1,5×: az első alapvonal marad, a többi 21 pt-tal lép",
       r is not None and len(r["lines"]) == n1 and abs(r["gap"] - 21) < 0.5
       and abs(_baseline(r["lines"][0]) - 140) < 0.5,
       None if r is None else (len(r["lines"]), round(r["gap"], 1)))
    _m, r, _g = once({"dy": 30.0}, (200, 169))
    ck("térköz előtte 30 pt: a bekezdés lejjebb került, a sorok száma marad",
       r is not None and len(r["lines"]) == n1 and abs(_baseline(r["lines"][0]) - 170) < 0.5,
       None if r is None else _baseline(r["lines"][0]))
    _m, r, _g = once({"size": 8.0})
    ck("méret 8 pt: kevesebb sor, a szöveg megmarad",
       r is not None and len(r["lines"]) < n1 and abs(r["size"] - 8) < 0.1
       and para_text(r).split() == P1,
       None if r is None else (len(r["lines"]), r["size"]))
    _m, r, _g = once({"family": "Calibri", "bold": True})
    ck("félkövér: a szövegréteg félkövérnek jelzi, a szöveg megmarad",
       r is not None and all(s["flags"] & 16 for ln in r["lines"] for s in ln["spans"])
       and para_text(r).split() == P1)
    _m, r, _g = once({"indent_left": 20.0, "indent_first": 15.0})
    ck("behúzás: az első sor beljebb, a többi a bal behúzásnál",
       r is not None and abs(r["lines"][0]["bbox"][0] - 95) < 0.6
       and abs(r["lines"][1]["bbox"][0] - 80) < 0.6,
       None if r is None else [round(ln["bbox"][0], 1) for ln in r["lines"][:2]])
    _m, _r, g = once({"underline": True})
    ck("aláhúzás: soronként egy vonal került a lapra",
       len(g.get_drawings()) == nd + n1, (len(g.get_drawings()), nd + n1))
    _m, r, _g = once({"color": (1, 0, 0)})
    ck("szín: a szövegréteg pirosat jelez",
       r is not None and all(s["color"] == 0xFF0000 for ln in r["lines"] for s in ln["spans"]),
       None if r is None else [hex(s["color"]) for ln in r["lines"] for s in ln["spans"]][:3])
    NEW = "Ez a bekezdés új szöveget kapott, amit a program a hasáb szélességére tördel."
    # Egysoros bekezdésnél a PARA_MAX_GAP kapu tartja távol a következő bekezdést.
    _m, r, g = once({"text": NEW})
    ck("szövegátírás: az új szöveg bent, a régi eltűnt",
       r is not None and para_text(r).split() == NEW.split()
       and "szálláshelyem" not in g.get_text(), para_text(r) if r else None)
    m, r, _g = once({"align": "justify", "reflow": True})
    ck("újratördelés + sorkizárás: a sorok a jobb szélen, a szöveg megmarad",
       r is not None and all(abs(ln["bbox"][2] - R1) < 0.6 for ln in r["lines"][:-1])
       and para_text(r).split() == P1, m)
    d.close()

    # -- vegyes formázás: az eltolásos út megtartja, az újratördelő szól --
    d2 = pymupdf.open()
    g2 = d2.new_page(width=595, height=842)
    add_text(g2, (60, 140), "Fontos:", FB, SZ)
    add_text(g2, (60 + FB.text_length("Fontos: ", SZ), 140),
             "a nyilatkozatot a hatóság előtt felhasználni kívánom, és", FN, SZ)
    add_text(g2, (60, 140 + GAP), "tudomásul veszem a jogkövetkezményeket is.", FN, SZ)
    pv = paragraph_at(g2, 200, 141)
    ck("vegyes formázású bekezdés: a program vegyesnek látja", pv["mixed"])
    ck("az eltolásos út nem tördel újra, és nem figyelmeztet",
       not para_reflows({"align": "justify"})
       and para_format(d2, g2, pv, {"align": "justify"}) == "")
    g3d = pymupdf.open("pdf", d2.tobytes())
    g3 = g3d[0]
    fonts3 = {s["font"] for b in g3.get_text("dict")["blocks"]
              for ln in b.get("lines", []) for s in ln["spans"]}
    ck("sorkizárás után megvan a félkövér ÉS a sima betű is",
       any("Bold" in f for f in fonts3) and any("Bold" not in f for f in fonts3), fonts3)
    ck("újratördelő művelet vegyes bekezdésen figyelmeztet",
       "egységes" in para_format(g3d, g3, paragraph_at(g3, 200, 141), {"size": 9.0}))
    g3d.close()
    d2.close()

    # -- a két kapu: ismeretlen betűcsalád és hiányzó karakter --
    d4 = pymupdf.open()
    g4 = d4.new_page(width=595, height=842)
    # A PyMuPDF beépített Helveticája NimbusSans-ként ágyazódik be; ugyanazzal a
    # metrikával mérhető vissza, ezért formázható (FONT_ALIAS).
    add_text(g4, (60, 140), "Helvetica betűvel írt sor, amit vissza tudunk mérni",
             pymupdf.Font("helv"), 10)
    ck("a beépített Helvetica felismerése (NimbusSans)",
       span_style(paragraph_at(g4, 200, 139)["lines"][0]["spans"][0])[0] == "Helvetica",
       span_style(paragraph_at(g4, 200, 139)["lines"][0]["spans"][0]))
    ck("a Helvetica bekezdés formázható", para_font_error(paragraph_at(g4, 200, 139), {}) == "")
    # A Courier (NimbusMonoPS) szándékosan nincs a listán: nem tudjuk pontosan mérni.
    add_text(g4, (60, 300), "Courier betuvel irt sor amit nem tudunk megmerni",
             pymupdf.Font("cour"), 10)
    pc = paragraph_at(g4, 200, 299)
    ec = para_font_error(pc, {})
    ck("ismeretlen betűcsalád: megtagadja magát, és megnevezi a betűt",
       "NimbusMonoPS" in ec, ec)
    txt4 = g4.get_text()
    ck("a megtagadott bekezdés nem módosul",
       para_format(d4, g4, pc, {"align": "justify"}) == ec and g4.get_text() == txt4)
    ck("de a felületről választott betűvel már átformázható",
       para_font_error(pc, {"family": "Calibri"}) == "")
    # Az Arial Bold nem ismeri a nem-törő kötőjelet: a karakter csendben eltűnne.
    add_text(g4, (60, 400), "Cegjegyzekszam: 19‐09‐503741 es meg egy kis szoveg",
             FN, SZ)
    p5 = paragraph_at(g4, 200, 399)
    e5 = para_font_error(p5, {"family": "Arial", "bold": True})
    ck("hiányzó karakter: az Arial Bold nem ismeri az U+2010-et, ezért megtagadja",
       "U+2010" in e5, e5)
    ck("ugyanaz a bekezdés Calibrivel átmegy",
       para_font_error(p5, {"family": "Calibri", "bold": True}) == "")
    d4.close()

    print("ÉLŐ SZÖVEG (szerkeszto-terv.md 21.)")
    # A mentés (subset_fonts) a betűt „Calibri Regular” néven teszi vissza: a saját
    # mentett iratunk bekezdését is fel kell ismerni.
    ck("mentés utáni betűnév: „X+Calibri Bold Italic” → Calibri",
       span_style({"font": "ABCDEF+Calibri Bold Italic", "flags": 18})
       == ("Calibri", True, True))
    ck("…de a családnév része marad: Times New Roman",
       span_style({"font": "Times New Roman Bold", "flags": 16})[0] == "Times New Roman")
    ck("ugyanaz a betűobjektum jön vissza (gyorsítótár: élő formázás)",
       edit_font("Helvetica", True) is edit_font("Helvetica", True))
    d5 = pymupdf.open()
    g5 = d5.new_page(width=595, height=842)
    t5 = PlacedText(0, 100, 200, "Kőműves Győző", "Helvetica", 12)
    b5 = placed_bbox(t5)
    ck("befoglaló: az alapvonal köré, a szöveg szélességével",
       b5.y0 < 200 < b5.y1 and abs(b5.width - edit_font("Helvetica").text_length(
           "Kőműves Győző", 12)) < 0.01, b5)
    ck("üres szövegnek is van kijelölhető szélessége",
       placed_bbox(PlacedText(0, 0, 50, "")).width > 0)
    t5u = copy.copy(t5)
    t5u.underline = True
    ck("aláhúzással lejjebb ér", placed_bbox(t5u).y1 > b5.y1 - 0.01)
    pix5, org5 = placed_pixmap(t5, 2.0)
    ck("előnézet: átlátszó kép, a befoglaló méretén",
       pix5.alpha and abs(pix5.width - (b5.width + 2) * 2) <= 2
       and abs(org5[0] - (b5.x0 - 1)) < 1e-6, (pix5.width, pix5.alpha, org5))
    ck("az előnézet a lapot nem érinti", g5.get_text() == "")
    t6 = PlacedText(0, 300, 400, "második", "Helvetica", 10, bold=True,
                    color=(1.0, 0.0, 0.0))
    bake_placed(d5, [t5u, t6, PlacedText(5, 1, 1, "nem létező lap")])
    sp5 = {s["text"]: s for b in g5.get_text("dict")["blocks"] for ln in b.get("lines", [])
           for s in ln["spans"]}
    k5 = sp5.get("Kőműves Győző")
    ck("mentéskor a lapra kerül, a helyén", k5 is not None and
       abs(k5["origin"][0] - 100) < 0.01 and abs(k5["origin"][1] - 200) < 0.01, list(sp5))
    ck("félkövér és piros", "második" in sp5 and sp5["második"]["flags"] & 16
       and sp5["második"]["color"] == 0xFF0000, sp5.get("második"))
    ck("az aláhúzás vonalként", any(it[0] == "l" for g in g5.get_drawings() for it in g["items"]))
    ck("hiányzó karakter jelzése", placed_missing(
        PlacedText(0, 0, 0, "a中", "Helvetica")) == "中")
    d5.close()
    ck("lista a dolgozó két alkönyvtárával (relatív úttal)",
       list_files_in(script_dir(), (".py",), ("nincs-ilyen",)) == list_files(script_dir(), (".py",)))

    print("SZÖVEGDOBOZ (szerkeszto-terv.md 23.2)")
    paras = [[("Alulírott ", 0, 0, 0), ("Kőműves Győző", 1, 0, 0), (" kijelentem, hogy a ", 0, 0, 0),
              ("bejelentett", 0, 1, 0), (" szálláshelyem ", 0, 0, 1), ("változatlan", 0, 0, 1),
              (" maradt, és az adataim a valóságnak megfelelnek.", 0, 0, 0)], [],
             [("Budapest, 2026. október 14.", 0, 0, 0)]]
    bx = PlacedBox(0, (60, 60, 300, 160), paras, size=11, align="justify")
    pl, un, bot = box_layout(bx)
    rows = sorted({round(y, 2) for _x, y, *_ in pl})
    ck("tördelés: több sor, a doboz szélességén belül",
       len(rows) >= 4 and all(x >= 60 and x + f.text_length(t, sz) <= 300.01
                              for x, _y, t, f, sz in pl), (len(rows), bot))
    first = [p for p in pl if abs(p[1] - rows[0]) < 0.01]
    ck("sorkizárt: az első sor a jobb szélig ér",
       abs(max(x + f.text_length(t, sz) for x, _y, t, f, sz in first) - (300 - BOX_PAD)) < 0.05)
    ck("a félkövér szó félkövér betűvel, a dőlt dőlttel",
       any(t == "Kőműves" and f is edit_font("Helvetica", True) for _x, _y, t, f, _s in pl)
       and any(t == "bejelentett" and f is edit_font("Helvetica", False, True)
               for _x, _y, t, f, _s in pl))
    ck("aláhúzás: a két aláhúzott szó és a köztük lévő szóköz is", len(un) >= 2 and any(
        u[1] - u[0] > edit_font("Helvetica").text_length("szálláshelyem", 11) for u in un), un)
    ck("az üres bekezdés egy üres sor",
       rows[-1] - rows[-2] > (rows[1] - rows[0]) * 1.9, rows)
    _p, _u, sz, ok = box_fit(PlacedBox(0, (60, 60, 300, 100), paras, size=11))
    ck("illesztés: kicsinyít, hogy kiférjen", ok and BOX_FIT_MIN * 11 <= sz < 11, sz)
    _p, _u, sz, ok = box_fit(PlacedBox(0, (60, 60, 300, 100), paras, size=11, fit=False))
    ck("illesztés nélkül: jelzi, hogy nem fér ki", not ok and sz == 11)
    d6 = pymupdf.open()
    g6 = d6.new_page()
    write_box(g6, bx)
    t6 = " ".join(g6.get_text().split())
    ck("kiírás: a szöveg a lapon, ligatúra nélkül (a TextWriter nem formál)",
       "Kőműves Győző" in t6 and "\x82" not in t6, t6[:80])
    ck("a futamok összevonása: azonos stílus egy futam",
       norm_paras([[("a", 1, 0, 0), ("b", 1, 0, 0), ("", 0, 0, 0), ("c", 0, 0, 0)]])
       == [[("ab", True, False, False), ("c", False, False, False)]])
    d6.close()

    print("KERESÉS ÉS CSERE (23.3)")
    d7 = pymupdf.open()
    g7 = d7.new_page()
    FC = edit_font("Helvetica")
    add_text(g7, (60, 100), "Alulírott Kiss Anna (TAJ: 123 456 788) kijelentem, hogy Kiss Anna vagyok.", FC, 10)
    add_text(g7, (60, 114), "Második sor: Kiss Anna a vége.", FC, 10)
    add_text(g7, (60, 128), "Telefon: +36 30", FC, 10)
    add_text(g7, (60, 142), "123 4567, köszönöm.", FC, 10)
    hits7 = find_hits(d7, search_regex("kiss anna"))
    ck("keresés: három találat, kis-/nagybetűtől függetlenül", len(hits7) == 3, len(hits7))
    ck("…kis-/nagybetűre érzékenyen nincs", find_hits(d7, search_regex("kiss anna", case=True)) == [])
    ck("egész szó: a „Kiss” nem találja a „Kisskert”-et", len(find_hits(
        d7, search_regex("Kis", whole=True))) == 0)
    ck("hibás mintánál None, nem kivétel", search_regex("(", regex=True) is None)
    tel = find_hits(d7, re.compile(r"\+36 30 123 4567"))
    ck("sortörésen átnyúló találat: két téglalap", len(tel) == 1 and tel[0]["multi"]
       and len(tel[0]["rects"]) == 2, tel and len(tel[0]["rects"]))
    cache = {}
    find_hits(d7, search_regex("Anna"), cache=cache)
    ck("a szövegsor-gyorsítótár megtelik, és újra használható",
       0 in cache and len(find_hits(d7, search_regex("Anna"), cache=cache)) == 3)
    plan = replace_plan(d7, hits7, "Kis Ági", FC)
    ck("rövidebb csere: a sor vége a helyére csúszik", all(it["ok"] and it["shift"] for it in plan),
       [(it["note"], it["shift"]) for it in plan])
    plan2 = replace_plan(d7, tel, "x", FC)
    ck("a sortörésen átnyúló találat nem cserélhető (jelzi)", not plan2[0]["ok"]
       and "sortörés" in plan2[0]["note"])
    x_vagyok = next(c[1].x0 for ln in page_text_lines(g7) for i, c in enumerate(ln["chars"])
                    if ln["text"][i:i + 6] == "vagyok")
    apply_replace(d7, plan, "Kis Ági")
    t7 = " ".join(g7.get_text("text", sort=True).split())
    ck("csere után: az új szöveg bent, a régi nincs", "Kiss Anna" not in t7 and t7.count("Kis Ági") == 3, t7)
    x2 = next(c[1].x0 for ln in page_text_lines(g7) for i, c in enumerate(ln["chars"])
              if ln["text"][i:i + 6] == "vagyok")
    ck("a sor vége ténylegesen balra csúszott (nincs lyuk)", x2 < x_vagyok - 5, (x_vagyok, x2))
    ck("a többi sor érintetlen", "Telefon: +36 30" in t7 and "123 4567, köszönöm." in t7)
    d8 = pymupdf.open()
    g8 = d8.new_page()
    add_text(g8, (60, 100), "Név: Kiss Anna, születési hely: Győr, állampolgárság: magyar", FC, 10)
    p8 = replace_plan(d8, find_hits(d8, search_regex("Kiss Anna")), "Kovács-Nagy Erzsébet", FC)
    ck("hosszabb csere, van hely: a sor vége jobbra csúszik",
       p8[0]["ok"] and p8[0]["shift"] and "jobbra" in p8[0]["note"], p8[0]["note"])
    apply_replace(d8, p8, "Kovács-Nagy Erzsébet")
    ck("…és a lapon is", "Kovács-Nagy Erzsébet, születési hely" in " ".join(
        g8.get_text("text", sort=True).split()))
    d7.close()
    d8.close()

    ck("a lista rövid megjegyzése", plan_short("a sor vége jobbra csúszik · más betűvel "
                                               "(az eredeti nincs meg)") == "jobbra csúszik · más betű"
       and plan_short("kicsinyítve 85%") == "betű 85%" and plan_short("nem fér el") == "nem fér el")
    print("SZEMÉLYES ADATOK (23.4)")
    ck("TAJ-ellenőrzőszám: jó és rossz", taj_ok("123 456 788") and not taj_ok("123 456 789"))
    ck("adóazonosító: jó és rossz", adoaz_ok("8123456786") and not adoaz_ok("8123456785")
       and not adoaz_ok("7123456786"))
    ck("IBAN (mod 97): jó és rossz", iban_ok("HU42 1177 3016 1111 1018 0000 0000")
       and not iban_ok("HU42 1177 3016 1111 1018 0000 0001"))
    ck("belföldi számlaszám (9-7-3-1)", bankszamla_ok("11773016-11111018")
       and not bankszamla_ok("11773016-11111019"))
    d9 = pymupdf.open()
    g9 = d9.new_page()
    add_text(g9, (60, 100), "TAJ: 123 456 788, adóazonosító: 8123456786, útlevél: BA1234567,", FC, 10)
    add_text(g9, (60, 114), "számla: 11773016-11111018, e-mail: kiss.anna@example.com,", FC, 10)
    add_text(g9, (60, 128), "iktatószám: 123 456 789, kelt: 2026. 10. 14.", FC, 10)
    allk = {k for k, *_ in PII_PATTERNS}
    found = {(h["kind"], h["text"]) for h in find_pii(d9, allk - {"datum"})}
    ck("minden mintatípus megtalálva", {"TAJ-szám", "Adóazonosító", "Útlevélszám",
                                        "Bankszámla, IBAN", "E-mail"} <= {k for k, _t in found},
       found)
    ck("az ellenőrzőszám kiszűri az iktatószámot", ("TAJ-szám", "123 456 789") not in found)
    ck("a dátum csak külön kérésre", not any(k == "Dátum" for k, _t in found)
       and any(h["kind"] == "Dátum" for h in find_pii(d9, {"datum"})))
    ck("saját szöveg is", [h["text"] for h in find_pii(d9, set(), "kiss.anna")] == ["kiss.anna"])
    d9.set_metadata({"title": "Kiss Anna adatai", "author": "Kiss Anna",
                     "keywords": "pdf-muhely=1;dolgozo=Kiss Anna;tipus=Útlevél"})
    redact_hits(d9, find_pii(d9, {"taj", "adoaz"}))
    clean_metadata(d9)
    ck("kitakarás után a szöveg végleg eltűnt", "123 456 788" not in g9.get_text()
       and "8123456786" not in g9.get_text() and find_pii(d9, {"taj", "adoaz"}) == [])
    ck("…a helye fekete sáv", any(dr.get("fill") == (0.0, 0.0, 0.0) for dr in g9.get_drawings())
       or g9.get_pixmap(clip=pymupdf.Rect(80, 92, 120, 100)).pixel(5, 3)[0] < 40)
    ck("metaadat: a cím és a szerző törölve, a Műhely bélyege megmaradt",
       not d9.metadata.get("title") and not d9.metadata.get("author")
       and "dolgozo=Kiss Anna" in d9.metadata.get("keywords", ""))
    d9.close()

    print("FEJLÉC, LÁBLÉC, OLDALSZÁM, BÉLYEG, VÍZJEL (23.5)")
    d10 = pymupdf.open()
    for _ in range(3):
        add_text(d10.new_page(width=595, height=842), (60, 400), "Lap szövege", FC, 10)
    d10.set_metadata({"keywords": "pdf-muhely=1;dolgozo=Kiss Anna;tipus=Útlevél"})
    dec = Decor(header_on=True, footer_on=True, pageno_on=True, stamp_on=True, wm_on=True,
                pageno_skip_first=True)
    ctx = decor_ctx(d10, "/x/Útlevél — Kiss Anna.pdf", 0)
    ck("változók: dolgozó és típus a bélyegből, fájlnév, dátum",
       fill_vars("{dolgozó} — {doktípus} — {fájlnév} — {oldal}/{összes}", ctx)
       == "Kiss Anna — Útlevél — Útlevél — Kiss Anna — 1/3" and ctx["dátum"][:4].isdigit())
    it0 = {k: r for k, _t, r, *_ in decor_items(d10[0].rect, dec, ctx, 0)}
    it1 = {k: r for k, _t, r, *_ in decor_items(d10[1].rect, dec, decor_ctx(d10, "", 1), 1)}
    ck("a fejléc fent, a lábléc lent", it0["fejléc"].y1 < 60 and it0["lábléc"].y0 > 780)
    ck("az oldalszám az első lapon kimarad, a többin ott", "oldalszám" not in it0
       and "oldalszám" in it1)
    ck("a bélyeg alapból a jobb felső sarokban, csak az első lapon",
       it0["bélyeg"].x1 > 540 and it0["bélyeg"].y0 < 60 and "bélyeg" not in it1)
    for pno in range(3):
        write_decor(d10[pno], dec, decor_ctx(d10, "/x/Útlevél — Kiss Anna.pdf", pno), pno)
    ck("kiírás: a második lapon „2/3”", "2/3" in d10[1].get_text() and "1/3" not in d10[0].get_text())
    ck("a vízjel a lapon (halványan)", "MÁSOLAT" in d10[2].get_text())
    d10.close()
    d10 = pymupdf.open()
    g10 = d10.new_page(width=595, height=842)
    add_text(g10, (24, 818), "Lap alján futó szöveg " * 6, FC, 9)
    ck("ütközés: a lap szövegére eső lábléc jelezve, nagyobb margóval nem",
       "lábléc" in decor_overlaps(g10, Decor(footer_on=True), ctx, 0)
       and decor_overlaps(g10, Decor(footer_on=True, margin=60), ctx, 0) == [])
    d10.close()

    print("ŰRLAP KITÖLTÉSE ÉS BEÉGETÉSE (23.6)")
    d11 = pymupdf.open()
    g11 = d11.new_page()
    for i, (nm, typ) in enumerate((("nev", pymupdf.PDF_WIDGET_TYPE_TEXT),
                                   ("ok", pymupdf.PDF_WIDGET_TYPE_CHECKBOX))):
        w = pymupdf.Widget()
        w.field_name, w.field_type = nm, typ
        w.rect = pymupdf.Rect(50, 50 + 40 * i, 300 if i == 0 else 64, 70 + 40 * i)
        g11.add_widget(w)
    ff = form_fields(d11)
    ck("a mezők listája olvasási sorrendben", [f["name"] for f in ff] == ["nev", "ok"])
    set_field(d11, 0, ff[0]["xref"], "Kőműves Győző")
    set_field(d11, 0, ff[1]["xref"], True)
    ck("kitöltés: az érték a mezőben", [f["value"] for f in form_fields(d11)][0] == "Kőműves Győző")
    n11 = flatten_form(d11, "Helvetica")
    ck("beégetés: a mezők eltűntek, az ékezetes érték a lap tartalma (ő, ű)",
       n11 == 2 and not list(d11[0].widgets()) and "Kőműves Győző" in d11[0].get_text(),
       repr(d11[0].get_text()))
    d11.close()
    d12 = pymupdf.open()
    g12 = d12.new_page()
    draw_field_value(g12, pymupdf.Rect(50, 50, 130, 70), "1990", comb=4)
    xs = sorted(w[0] for w in g12.get_text("words"))
    ck("fésűs mező: betűnként a cellák közepére (20 pt-os lépés)",
       len(xs) == 4 and all(abs((b - a) - 20) < 0.5 for a, b in zip(xs, xs[1:])), xs)
    d12.close()

    print("SZÖVEGFELISMERÉS (23.7)")
    d13 = pymupdf.open()
    g13 = d13.new_page()
    add_text(g13, (60, 100), "NYILATKOZAT Kőműves Győző TAJ 123 456 788", FC, 14)
    pix = g13.get_pixmap(dpi=200, colorspace=pymupdf.csGRAY)
    scan_d = pymupdf.open()
    sp13 = scan_d.new_page(width=g13.rect.width, height=g13.rect.height)
    sp13.insert_image(sp13.rect, pixmap=pix)
    ck("szkennelt lap felismerése (kép, szöveg nélkül)", page_is_scan(sp13) and not page_is_scan(g13))
    apply_ocr_words(sp13, [(60, 86, 160, 102, "NYILATKOZAT"), (165, 86, 250, 102, "Kőműves")])
    ck("láthatatlan szövegréteg: kereshető lett, a kép nem változott",
       "Kőműves" in sp13.get_text() and len(sp13.get_images()) == 1
       and not page_is_scan(sp13))
    w13 = [w for w in sp13.get_text("words") if w[4] == "Kőműves"]
    ck("a szó téglalapja a felismert helyén", w13 and abs(w13[0][0] - 165) < 1
       and abs(w13[0][2] - 250) < 3, w13)
    add_text(sp13, (60, 300), "Kézzel írt megjegyzés", FC, 11)    # látható szöveg is
    ck("a keret csak a felismert szavakon, a lap látható szövegén nem",
       len(ocr_word_rects(sp13)) == 2 and ocr_word_rects(g13) == [],
       [tuple(round(v) for v in r) for r in ocr_word_rects(sp13)])
    tess = tessdata_dir()
    if tess:
        scan2 = pymupdf.open()
        sp2 = scan2.new_page(width=g13.rect.width, height=g13.rect.height)
        sp2.insert_image(sp2.rect, pixmap=pix)
        words = ocr_words(sp2, tess, "hun")
        ck("a beépített motor magyarul felismeri (tessdata, telepítés nélkül)",
           any(w[4] == "Kőműves" for w in words) and any(w[4] == "Győző" for w in words),
           [w[4] for w in words])
        with tempfile.TemporaryDirectory() as td:    # ékezetes mappából is (23.7)
            ek = os.path.join(td, "Dániel tessdata")
            os.mkdir(ek)
            shutil.copy(os.path.join(tess, "hun.traineddata"), ek)
            ck("ékezetes útvonalú tessdata mappából is felismer",
               any(w[4] == "Kőműves" for w in ocr_words(sp2, ek, "hun")))
        scan2.close()
    else:
        ck("a magyar nyelvi fájl megvan (tessdata\\hun.traineddata)", False, script_dir())
    d13.close()
    scan_d.close()

    print("MD → DOCX")
    il = md_inline("**fél** *dőlt* snake_case_nev `a*b*` [x](https://e.hu) \\*")
    ck("sorközi: félkövér, dőlt, kód, link, escape; a szó belseji _ marad",
       [(t.strip(), sorted(f)) for t, f in il if t.strip()] == [
           ("fél", ["b"]), ("dőlt", ["i"]), ("snake_case_nev", []), ("a*b*", ["code"]),
           ("x", ["link"]), ("*", [])], il)
    il = md_inline("*a **b** c*")
    ck("dőltben félkövér", [(t, sorted(f)) for t, f in il] ==
       [("a ", ["i"]), ("b", ["b", "i"]), (" c", ["i"])], il)
    il = md_inline("**⚠** = x. **⌄** = y")
    ck("egybetűs félkövér nem nyúlik át a következőig",
       [t for t, f in il if f.get("b")] == ["⚠", "⌄"], il)
    bl = md_blocks(["Cím", "===", "", "- a", "  - b", "    1. c", "- d", "  lusta", "",
                    "3. x", "4. y", "", "1. új", "", "| A | B |", "|:-|-:|", "| 1 | 2 |"])
    ck("címsor (aláhúzásos), beágyazott lista, lusta folytatás",
       bl[0] == ("h", 1, "Cím") and bl[1][0] == "list" and bl[1][3][1][0] == "d lusta"
       and bl[1][3][0][1][0][3][0][1][0][:3] == ("list", True, 1), bl[:2])
    ck("a számozott lista a megadott számtól indul, az „1.” újat kezd",
       bl[2][:3] == ("list", True, 3) and len(bl[2][3]) == 2 and bl[3][:3] == ("list", True, 1),
       bl[2:4])
    ck("táblázat igazítással", bl[4] == ("table", ["A", "B"], ["left", "right"], [["1", "2"]]),
       bl[4])
    if docx_available():
        import docx
        with tempfile.TemporaryDirectory() as td:
            dst = os.path.join(td, "próba.docx")
            st = md_to_docx("---\na: b\n---\n# Árvíztűrő tükörfúrógép\n\n1. egy\n2. kettő\n\n"
                            "1. újra\n\n```\nkód  sor\n```\n\n| a | b |\n|---|---|\n| ő | ű |\n\n"
                            "[link](https://example.com) ![k](x.png)\n", dst)
            d = docx.Document(dst)
            ps = d.paragraphs
            nums = [p._p.pPr.numPr.numId.val for p in ps if p.style.name == "List Number"]
            ck("ékezetes címsor Heading 1-ként, az YAML-előfej kimarad",
               ps[0].style.name == "Heading 1" and ps[0].text == "Árvíztűrő tükörfúrógép",
               [(p.style.name, p.text) for p in ps[:2]])
            ck("két számozott lista, két külön számozással",
               len(nums) == 3 and nums[0] == nums[1] != nums[2], nums)
            ck("a kód szóközei megmaradnak, Consolas betűvel",
               any(p.text == "kód  sor" and p.runs[0].font.name == MD_MONO for p in ps))
            ck("táblázat fejléccel", len(d.tables) == 1 and d.tables[0].cell(1, 1).text == "ű"
               and d.tables[0].cell(0, 0).paragraphs[0].runs[0].font.bold)
            ck("a link valódi hivatkozás", any(
                r.reltype.endswith("/hyperlink") and r.target_ref == "https://example.com"
                for r in d.part.rels.values()))
            ck("A4-es lap, magyar nyelv",
               abs(d.sections[0].page_width.cm - 21) < 0.01
               and 'w:val="hu-HU"' in d.styles["Normal"].element.xml)
            ck("számlálók: címsor, lista, táblázat, kép",
               st == {"h": 1, "table": 1, "list": 2, "img": 1}, st)
    else:
        ck("a python-docx telepítve van (pip install python-docx)", False)

    print()
    print(f"=== {sum(res)}/{len(res)} teszt sikeres ===")
    return 0 if all(res) else 1


if __name__ == "__main__":
    if "--tomorit" in sys.argv:          # külön folyamatban futó tömörítés
        i = sys.argv.index("--tomorit")
        sys.exit(shrink_cli(sys.argv[i + 1:]))
    if "--ocr" in sys.argv:              # külön folyamatban futó szövegfelismerés
        i = sys.argv.index("--ocr")
        sys.exit(ocr_cli(sys.argv[i + 1:]))
    if "--test" in sys.argv:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # átirányítva is (cp1250)
        sys.exit(_selftest())
    # Éles szöveg 125–150%-os Windows-skálázásnál: a GDI-skálázás a Tk szövegét és
    # vonalait a valódi felbontáson rajzolja, a pixelméretek (elrendezés) maradnak.
    # ponytail: a képeket (bélyegkép, előnézet, nagyító) a Windows továbbra is
    # nagyítja; teljes DPI-tudatossághoz minden pixelméretet skálázni kellene.
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-5))
    except Exception:
        pass                    # régebbi Windows: marad a sima (elmosódó) skálázás
    App().mainloop()
