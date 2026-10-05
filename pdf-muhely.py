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
import datetime
import traceback
import subprocess
import unicodedata
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from tkinter import font as tkfont
from dataclasses import dataclass, field, asdict

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


class FileList(ttk.Frame):
    """Listbox + görgetősáv + Frissítés/Tallózás gombpár."""

    def __init__(self, master, title, exts, on_pick, height=7, memory_key=""):
        super().__init__(master)
        self.exts, self.on_pick, self.folder = exts, on_pick, script_dir()
        self.memory_key = memory_key          # a Tallózás megjegyzett mappája
        self._ok = False

        box = ttk.LabelFrame(self, text=title)
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

    def set_folder(self, folder):
        self.folder = folder
        self.refresh()

    def refresh(self):
        keep = self.selected_names()
        files = list_files(self.folder, self.exts)
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
        left = ttk.Frame(self, width=340)
        left.pack(side="left", fill="y", padx=8, pady=8)
        left.pack_propagate(False)

        self.pdfs = FileList(left, "PDF nyomtatványok", (".pdf",), self._open_pdf, height=6,
                             memory_key="nyomtatvanyok")
        self.pdfs.pack(fill="both", expand=True)
        self.imgs = FileList(left, "Arcképek", IMG_EXT, self._load_img, height=6,
                             memory_key="arckepek")
        self.imgs.pack(fill="both", expand=True, pady=(8, 0))
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
        ttk.Button(o, text="Mentés másként…", command=self._save).pack(fill="x", padx=6, pady=6)

        # Iktatás: a kész (fotóval ellátott) irat mindig a feltölthető mappába megy —
        # a fotó épp most került rá. Ez zárja be a kört 01 → fotó → 02.
        ik = ttk.LabelFrame(left, text=f"Iktatás a {DIR_UP} mappába")
        ik.pack(fill="x", pady=(0, 8))
        wr = ttk.Frame(ik)
        wr.pack(fill="x", padx=6, pady=(4, 0))
        ttk.Label(wr, text="Dolgozó:").pack(side="left")
        ttk.Entry(wr, textvariable=self.who_text, width=20).pack(side="left", padx=4)
        self.who_lbl = ttk.Label(ik, textvariable=self.who_msg, wraplength=320)
        self.who_lbl.pack(anchor="w", padx=6)
        tr = ttk.Frame(ik)
        tr.pack(fill="x", padx=6, pady=2)
        ttk.Label(tr, text="Típus:").pack(side="left")
        self.type_cbo = ttk.Combobox(tr, textvariable=self.doc_type, width=24,
                                     state="readonly")
        self.type_cbo.pack(side="left", padx=4)
        ttk.Button(ik, text="Iktatás a feltölthetőbe",
                   command=self._iktat).pack(fill="x", padx=6, pady=6)
        self.who_text.trace_add("write", lambda *a: self._who_changed())

        ttk.Label(left, textvariable=self.pos_info, foreground="#333", wraplength=320).pack(anchor="w")

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
        self.pdfs.set_folder(folder)
        self.imgs.set_folder(folder)
        # A munkamappa a dolgozói mappák szülője; ha egy dolgozó mappáját kaptuk
        # (Áttekintő → „Arckép elhelyezése”), a szülőt vesszük, a nevet kitöltjük.
        base = os.path.basename(os.path.normpath(folder))
        parent = os.path.dirname(os.path.normpath(folder))
        if parent and base and os.path.isdir(os.path.join(parent, base)):
            try:
                if base in worker_dirs(parent):
                    self.parent_dir = parent
                    self.refresh()
                    self.who_text.set(base)
                    return
            except OSError:
                pass
        self.parent_dir = folder
        self.refresh()

    # -- iktatás --
    def refresh(self):
        """Dolgozói mappák és típuslista — fülváltáskor és mappaváltáskor."""
        try:
            self.dirs = worker_dirs(self.parent_dir)
        except OSError:
            self.dirs = []
        ikt = getattr(self.app, "tabs", {}).get("Iktató")
        types = ikt.types if ikt else load_types()
        self.type_cbo.configure(values=types)
        if self.doc_type.get() not in types:
            # A fotóigényes típus az alapértelmezés — ezért van ez a fül.
            rules = self._rules()
            pick = next((t for t in types
                         if (doc_type_rule(t, rules) or Rule("", "", "")).arckep), None)
            self.doc_type.set(pick or (types[0] if types else ""))
        self._who_changed()

    def _rules(self) -> list:
        att = getattr(self.app, "tabs", {}).get("Áttekintő")
        return att.rules if att else rules_from(default_settings())

    def _who_changed(self):
        self.who, hits = resolve_worker(self.who_text.get(), self.dirs)
        if self.who:
            msg, col = f"→ {self.who}\\{DIR_UP}", COL_OK
        elif not self.who_text.get().strip():
            msg, col = "a nevéből elég egy részlet", ""
        else:
            msg, col = (f"{len(hits)} találat — pontosíts" if hits
                        else "nincs ilyen dolgozói mappa"), COL_WARN
        self.who_msg.set(msg)
        self.who_lbl.configure(foreground=col)

    def _iktat(self):
        """A fotóval ellátott irat a dolgozó 02_Feltoltheto mappájába, az Iktató
        közös magjával: szabványos név, ütközéskezelés, 5 MB, napló."""
        if not (self.doc and self.imgpdf):
            messagebox.showwarning("Hiányzik", "PDF és kép is kell az iktatáshoz.")
            return
        if not self.who:
            self.who_msg.set("Előbb válaszd ki a dolgozót.")
            self.who_lbl.configure(foreground=COL_WARN)
            return
        dt = self.doc_type.get()
        if not dt:
            messagebox.showwarning("Hiányzik", "Válassz dokumentumtípust.")
            return
        r = doc_type_rule(dt, self._rules())
        folder = os.path.join(self.parent_dir, self.who, DIR_UP)
        name = target_name(self.who, dt, SUFFIX if (r is None or r.generated) else "")
        dst = os.path.join(folder, name)
        backup = None
        try:
            check_path_len(dst)
            os.makedirs(folder, exist_ok=True)
            if os.path.exists(dst):
                if not messagebox.askyesno(
                        "A fájl már létezik",
                        f"{name}\n\nFelülírjuk? Az előző példány a dolgozó "
                        f"{BACKUP_DIR}\\ mappájába kerül.\n\n"
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
                name, dt, "FELULIRVA (elozo: " + BACKUP_DIR + ")" if backup else "OK")
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
                                           initialfile=f"{stem}_kesz.pdf",
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

    def set_folder(self, folder):
        self.folder = folder
        self.refresh()

    def refresh(self):
        self.lb.delete(0, tk.END)
        for f in list_files(self.folder, (".pdf",)):
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
                toc.append([1, os.path.splitext(n)[0], start + 1])
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
        self.files = FileList(top, "Raszterizálandó PDF", (".pdf",), self._pick, height=8)
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
            messagebox.showwarning("Nincs fájl", "Válassz ki egy PDF-et.")
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
            doc = open_checked(self.path)
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


# ─────────────────────── Eszközök: szerkesztés (PDF-szerkesztő) ───────────────────────
# Általános szerkesztő kész PDF-ekhez (szerkeszto-terv.md 16.): szöveg átírása, új
# szöveg és X, űrlapmezők (a DocGen PDF-sablonjához), kitakarás. Szöveg mindig
# TextWriterrel kerül a lapra: az insert_text(fontname="helv") elrontja az ő/ű-t (0.2).
# ponytail: forgatott lapot (/Rotate) nem szerkesztünk — a fül szól; ha kell, a
# koordinátákat a page.derotation_matrix-szal kell átváltani, mint a PlacerTab-ban.

EDIT_FONTS = {"Helvetica": None, "Calibri": "calibri.ttf", "Arial": "arial.ttf",
              "Times New Roman": "times.ttf"}
LINE_MAX = 1.6            # ennél vékonyabb kitöltött téglalap vonalnak számít (pt)
SNAP_MAX = 60             # a kattintástól legfeljebb ennyire keresünk vonalat (pt)
BOX_MIN, BOX_MAX = 6, 16  # a jelölőnégyzet oldala (pt)
UNDERLINE_H = 14          # aláhúzásos rovat: ilyen magas sáv a vonal fölött


def _font_path(name: str) -> str:
    f = EDIT_FONTS.get(name)
    return os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", f) if f else ""


def edit_fonts() -> list:
    """A választható betűk: a beépített Helvetica és a gépen meglévő rendszerbetűk."""
    return [n for n in EDIT_FONTS if not EDIT_FONTS[n] or os.path.exists(_font_path(n))]


def edit_font(name: str) -> "pymupdf.Font":
    p = _font_path(name)
    return pymupdf.Font(fontfile=p) if p and os.path.exists(p) else pymupdf.Font("helv")


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


def _redact(page, rect, fill=False, images=pymupdf.PDF_REDACT_IMAGE_NONE,
            graphics=pymupdf.PDF_REDACT_LINE_ART_NONE):
    page.add_redact_annot(rect, fill=fill)
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


class EditorTab(ttk.Frame):
    """Eszközök → Szerkesztés: kész PDF általános szerkesztése. Három eszköz:
    szöveg (átírás, új szöveg, X), űrlapmező (DocGen-sablon), kitakarás. Minden
    lépés visszavonható a mentésig; a mentés helyben megy, az előző példány a
    dolgozó .eredeti\\ mappájába kerül (szerkeszto-terv.md 16.)."""

    HINTS = {
        "text":  "Kattints egy szövegre: átírod. Üres helyre: új szöveg (cellába "
                 "illesztve). Jelölőnégyzetbe: X be / ki.",
        "field": "Kattintás: mező a cellába (a négyzetbe jelölőnégyzet). Húzás több "
                 "kis cellán át: betűnkénti mezők (név#1, #2 …). Mezőre kattintás: "
                 "kijelölés — átnevezés, törlés (Delete).",
        "erase": "Húzd körbe a területet: a tartalma végleg törlődik (szöveg, kép, "
                 "vonal), a helye fehér lesz.",
    }
    UNDO_MAX = 30

    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.path = self.doc = None
        self.log_parent = None           # az Áttekintőből nyitva: ide naplózunk
        self.page_no = 0
        self.view_zoom, self.zoom = 1.0, 1.0
        self.undo = []
        self.dirty = False
        self.page_tk = None
        self._dr, self._lines = [], ([], [])
        self._press = self._entry = None
        self.sel_xref = None              # a kijelölt mező
        self.mode = tk.StringVar(value="text")
        fonts = edit_fonts()
        self.font_name = tk.StringVar(value="Calibri" if "Calibri" in fonts else fonts[0])
        self.font_size = tk.DoubleVar(value=10.5)
        self.field_name = tk.StringVar(value="")
        self.info = tk.StringVar(value="Válassz egy PDF-et.")
        self._build(fonts)

    def _build(self, fonts):
        left = ttk.Frame(self, width=340)
        left.pack(side="left", fill="y", padx=8, pady=8)
        left.pack_propagate(False)
        self.files = FileList(left, "PDF-ek", (".pdf",), self._pick, height=4,
                              memory_key="szerkesztes")
        self.files.pack(fill="both", expand=True)

        m = ttk.LabelFrame(left, text="Eszköz")
        m.pack(fill="x", pady=8)
        for txt, val in (("Szöveg és X", "text"), ("Űrlapmező (DocGen-sablon)", "field"),
                         ("Kitakarás", "erase")):
            ttk.Radiobutton(m, text=txt, value=val, variable=self.mode,
                            command=self._mode_changed).pack(anchor="w", padx=6, pady=1)
        self.hint = ttk.Label(m, text=self.HINTS["text"], wraplength=310, foreground="#555")
        self.hint.pack(anchor="w", padx=6, pady=(2, 4))
        t = ttk.Frame(m)
        t.pack(fill="x", padx=6, pady=(0, 6))
        ttk.Label(t, text="Új szöveg:").pack(side="left")
        ttk.Combobox(t, textvariable=self.font_name, values=fonts, state="readonly",
                     width=14).pack(side="left", padx=4)
        ttk.Spinbox(t, from_=5, to=40, increment=0.5, textvariable=self.font_size,
                    width=5).pack(side="left")

        f = ttk.LabelFrame(left, text="Kijelölt mező — a neve a DocGen-jelölő")
        f.pack(fill="x")
        ttk.Entry(f, textvariable=self.field_name).pack(fill="x", padx=6, pady=(6, 2))
        fr = ttk.Frame(f)
        fr.pack(fill="x", padx=6, pady=(0, 6))
        ttk.Button(fr, text="Átnevezés", command=self._rename).pack(side="left")
        ttk.Button(fr, text="Mező törlése", command=self._delete_field).pack(side="left", padx=6)
        ttk.Label(left, textvariable=self.info, wraplength=320, foreground="#333").pack(anchor="w", pady=6)

        # A dokumentum műveletei a vászon fölött: a bal panel így alacsony
        # képernyőn is elfér.
        right = ttk.Frame(self)
        right.pack(side="right", fill="both", expand=True, padx=(0, 8), pady=8)
        bar = ttk.Frame(right)
        bar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        ttk.Button(bar, text="Visszavonás", command=self._undo).pack(side="left")
        ttk.Button(bar, text="Mentés", command=self._save).pack(side="left", padx=6)
        ttk.Button(bar, text="Mentés másként…", command=self._save_as).pack(side="left")
        self.page_var = tk.StringVar(value="1")
        ttk.Button(bar, text="Illeszt", command=lambda: self._view_zoom(0)).pack(side="right")
        ttk.Button(bar, text="+", width=3, command=lambda: self._view_zoom(1.25)).pack(side="right", padx=2)
        ttk.Button(bar, text="−", width=3, command=lambda: self._view_zoom(1 / 1.25)).pack(side="right", padx=(12, 2))
        self.page_spin = ttk.Spinbox(bar, from_=1, to=1, textvariable=self.page_var, width=5,
                                     command=self._change_page)
        self.page_spin.pack(side="right")
        ttk.Label(bar, text="Oldal:").pack(side="right", padx=4)
        self.canvas = tk.Canvas(right, bg=COL_CANVAS, highlightthickness=0, takefocus=1,
                                cursor="crosshair", height=180)
        hb = ttk.Scrollbar(right, orient="horizontal", command=self.canvas.xview)
        vb = ttk.Scrollbar(right, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=hb.set, yscrollcommand=vb.set)
        self.canvas.grid(row=1, column=0, sticky="nsew")
        vb.grid(row=1, column=1, sticky="ns")
        hb.grid(row=2, column=0, sticky="ew")
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)
        c = self.canvas
        c.bind("<ButtonPress-1>", self._down)
        c.bind("<B1-Motion>", self._drag)
        c.bind("<ButtonRelease-1>", self._up)
        c.bind("<Configure>", lambda e: debounce(self, "_cfg_job", self._render, 60))
        c.bind("<Control-MouseWheel>", lambda e: self._view_zoom(1.25 if e.delta > 0 else 1 / 1.25))
        c.bind("<MouseWheel>", lambda e: c.yview_scroll(-1 if e.delta > 0 else 1, "units"))
        c.bind("<Delete>", lambda e: self._delete_field())
        # A vásznon, nem bind_all-lal: a globális Ctrl+Z kötés a nagyító (PageViewer)
        # billentyűit is elrontotta (a GUI-teszt mérte). A vászon kattintásra
        # amúgy is megkapja a fókuszt.
        c.bind("<Control-z>", lambda e: (self._undo(), "break")[1])

    # -- fájl --
    def set_folder(self, folder):
        self.files.set_folder(folder)

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
        self.sel_xref = None
        self.field_name.set("")
        self.page_spin.configure(to=doc.page_count)
        self.page_var.set("1")
        self._render()
        return True

    def _say(self, txt=""):
        name = os.path.basename(self.path) if self.path else ""
        self.info.set(f"{name}{' — módosítva' if self.dirty else ''}" + (f"\n{txt}" if txt else ""))

    # -- rajzolás --
    def _page(self):
        return self.doc[self.page_no] if self.doc else None

    def _change_page(self):
        if not self.doc:
            return
        try:
            self.page_no = max(1, min(self.doc.page_count, int(self.page_var.get()))) - 1
        except ValueError:
            return
        self.sel_xref = None
        self._render()

    def _view_zoom(self, k):
        self.view_zoom = 1.0 if not k else max(0.3, min(6.0, self.view_zoom * k))
        self._render()

    def _render(self):
        self._cancel_entry()
        page = self._page()
        if not page:
            return
        # Szélességre illesztünk: egy űrlapon a betű mérete számít, nem az, hogy
        # az egész lap látsszon (függőlegesen görgethető).
        cw = max(50, self.canvas.winfo_width())
        self.zoom = cw / page.rect.width * self.view_zoom
        pix = page.get_pixmap(matrix=pymupdf.Matrix(self.zoom, self.zoom), annots=True)
        self.page_tk = tkimg(pix, "ppm")
        c = self.canvas
        c.delete("all")
        c.create_image(0, 0, anchor="nw", image=self.page_tk, tags="page")
        c.configure(scrollregion=(0, 0, pix.width, pix.height))
        self._dr = page.get_drawings()
        self._lines = page_lines(self._dr)
        self._draw_fields()
        n = sum(1 for _ in page.widgets())
        self._say(f"{self.page_no + 1}/{self.doc.page_count}. oldal · {n} űrlapmező")

    def _draw_fields(self):
        """Mező módban a mezők kerete és neve — a PDF-ben láthatatlanok."""
        c, z = self.canvas, self.zoom
        c.delete("fld")
        if self.mode.get() != "field":
            return
        for w in self._page().widgets():
            r = w.rect
            sel = w.xref == self.sel_xref
            c.create_rectangle(r.x0 * z, r.y0 * z, r.x1 * z, r.y1 * z, tags="fld",
                               outline=UI["warn"] if sel else UI["accent"],
                               width=2 if sel else 1, dash=() if sel else (3, 2))
            c.create_text(r.x0 * z + 2, r.y0 * z + 1, anchor="nw", text=w.field_name,
                          font=("Segoe UI", 7), fill=UI["accent"], tags="fld")

    def _mode_changed(self):
        self.hint.configure(text=self.HINTS[self.mode.get()])
        self._cancel_entry()
        self._draw_fields()

    # -- egér --
    def _pt(self, e):
        return (self.canvas.canvasx(e.x) / self.zoom, self.canvas.canvasy(e.y) / self.zoom)

    def _down(self, e):
        self.canvas.focus_set()
        self._press = self._pt(e) if self.doc else None
        self.canvas.delete("band")

    def _drag(self, e):
        if not self._press or self.mode.get() == "text":
            return
        (x0, y0), (x1, y1), z = self._press, self._pt(e), self.zoom
        self.canvas.delete("band")
        self.canvas.create_rectangle(x0 * z, y0 * z, x1 * z, y1 * z, tags="band",
                                     outline=UI["warn"], dash=(4, 2))

    def _up(self, e):
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
                self._change(lambda: erase_area(page, rect), "Kitakarva.")
        elif mode == "field":
            self._field_drag(page, rect) if drag else self._field_click(page, x1, y1)
        else:
            self._text_click(page, x1, y1)

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
        size = float(self.font_size.get())
        cell = snap_cell(self._lines, x, y)
        origin = ((cell.x0 + 3, (cell.y0 + cell.y1) / 2 + size * 0.35) if cell else (x, y))
        width = cell.width if cell else 160
        self._ask(origin[0], origin[1] + 3, "", width,
                  lambda t: t.strip() and self._change(
                      lambda: add_text(page, origin, t, edit_font(self.font_name.get()), size),
                      "Szöveg hozzáadva."))

    def _rewrite(self, page, span, text):
        if text == span["text"]:
            return
        fb = edit_font(self.font_name.get())
        own = []
        self._change(lambda: own.append(rewrite_span(self.doc, page, span, text, fb)), "Átírva.")
        if own and not own[0] and text.strip():
            self._say(f"Az eredeti betűben nincs meg minden betű — {self.font_name.get()} betűvel írtam.")

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
    def _change(self, fn, msg=""):
        """Egy lépés: előtte a dokumentum bájtjai a visszavonási verembe."""
        if not self.doc:
            return None
        self.undo.append(self.doc.tobytes())
        del self.undo[:-self.UNDO_MAX]
        try:
            out = fn()
        except Exception as e:
            traceback.print_exc()
            self._restore(self.undo.pop())
            messagebox.showerror("Hiba", f"{type(e).__name__}: {e}")
            return None
        self.dirty = True
        self._render()
        self._say(msg)
        return out

    def _restore(self, data):
        self.doc.close()
        self.doc = pymupdf.open("pdf", data)

    def _undo(self):
        if not self.undo:
            self._say("Nincs mit visszavonni.")
            return
        self._restore(self.undo.pop())
        self.dirty = bool(self.undo)
        self.sel_xref = None
        self._render()

    def _bytes(self) -> bytes:
        """Mentendő bájtok: a használt betűk részhalmaza, tömörítve."""
        d = pymupdf.open("pdf", self.doc.tobytes())
        try:
            try:
                d.subset_fonts()
            except Exception:
                pass                      # a részhalmazolás kényelem, nem feltétel
            return d.tobytes(garbage=3, deflate=True)
        finally:
            d.close()

    def _write(self, dst) -> str:
        data, pages = self._bytes(), self.doc.page_count
        backup = backup_existing(dst) if os.path.exists(dst) else ""
        write_pdf_verified(data, dst, pages)
        return backup

    def _save(self):
        if self.doc:
            self._save_to(self.path)

    def _save_as(self):
        if not self.doc:
            return
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
                    "SZERKESZTVE" + (f" (elozo: {BACKUP_DIR})" if backup else ""))
        self.path, self.dirty = dst, False
        note = size_note(dst)
        self.app.status(f"Mentve: {os.path.basename(dst)} {note}")
        self.app.refresh_all()
        self._say("Mentve." + (f" Az előző példány: {backup}" if backup else "") +
                  (f"\n{note}" if note else ""))


# ───────────────────────────── 5. fül: iktató ─────────────────────────────
# ── konfiguráció ────────────────────────────────────────────────────────────
DOC_TYPES_DEFAULT = [
    "Tart_eng_formanyomtatvány",
    "Nyilatkozat szálláshely változatlanságáról",
    "Előzetes megállapodás",
    "Elfogadó nyilatkozat",
    "Egyoldalú hozzájárulási nyilatkozat",
    "Belföldi meghatalmazás",
]
SUFFIX = "aláírt"
LOG_NAME = "iktato-naplo.csv"
BACKUP_DIR = ".eredeti"                    # felülírt példányok a dolgozó mappáján belül
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


def target_name(dir_name: str, doc_type: str, suffix: str = SUFFIX) -> str:
    """Horváth Dániel + Előzetes megállapodás -> teljes fájlnév."""
    parts = [dir_name.strip(), doc_type.strip(), suffix.strip()]
    stem = " ".join(p for p in parts if p)
    stem = re.sub(r"\s+", " ", stem)
    stem = unicodedata.normalize("NFC", stem)      # Windows NFC-t vár
    return safe_stem(stem) + ".pdf"


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
    """Felülírás előtt az előző példány másolata a dolgozó mappájában a
    .eredeti\\ almappába kerül — a ponttal kezdődő mappát az Áttekintő és az
    Iktató is kihagyja. A mentés a dolgozó GYÖKERÉBEN közös, nem a 01/02 alatt:
    egy helyen legyen minden visszaállítható példány. -> a másolat útja"""
    d = os.path.join(worker_root(os.path.dirname(dst)), BACKUP_DIR)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, unique_name(d, os.path.basename(dst))[0])
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
        self.name_preview.set(sub + "\\" + target_name(who, dt, self.suffix.get()) +
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
                   name=target_name(dir_name, self.doc_type.get(), self.suffix.get()),
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
            result += " (elozo: " + BACKUP_DIR + ")"
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
                       (f" (felülírva, az előző: {BACKUP_DIR}\\)" if job["overwritten"] else "") +
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
    s = re.sub(r"\b(alairt|signed)\b", " ", s)
    s = re.sub(r"[_\-.]+", " ", s)                  # elválasztók szóközzé
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
        "unknown": [(dolgozó, rel)],            # se bélyeg, se felismert név
        "foreign": [(dolgozó, rel, bélyeg dolgozója)],
        "mismatch": [(dolgozó, rel, bélyeg típusa, név szerinti típus)],
        "dupes": [[(dolgozó, rel), …]], "seen": n}"""
    res = {"stampable": [], "unknown": [], "foreign": [], "mismatch": [],
           "dupes": [], "seen": 0}
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

        txt = tk.Text(win, width=88, height=22, wrap="none")
        txt.pack(fill="both", expand=True, padx=14)
        for name in hu_sorted(list(plans)):
            _folder, t = plans[name]
            txt.insert(tk.END, f"{name}\n")
            for rel, dst, reason, sure in t:
                mark = "  →  " if dst else "  ·  "
                txt.insert(tk.END, f"   {rel}{mark}{dst or 'marad'}"
                                   f"    [{'' if sure else 'TIPP: '}{reason}]\n")
            txt.insert(tk.END, "\n")
        txt.configure(state="disabled")

        row = ttk.Frame(win)
        row.pack(fill="x", padx=14, pady=12)

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
            if not messagebox.askyesno(
                    "Rendezés",
                    f"{movable} fájl mozgatása a helyére.\n\n"
                    "Ez NEM visszavonható (a fájlok a mappán belül mozognak).\n"
                    "Folytatjuk?", parent=win):
                return
            done, errs = 0, []
            for _name, (folder, t) in plans.items():
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
        if movable:
            ttk.Button(row, text=f"Mappák + {movable} fájl mozgatása",
                       command=move_all).pack(side="left", padx=8)
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
        ttk.Button(row, text="Bezárás", command=win.destroy).pack(side="right")
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
                       f"lépcsőnként; az előző példány a dolgozó {BACKUP_DIR} "
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
    számbillentyű itt is címkéz. A nagyítás az illesztéshez képest értendő,
    lapozáskor a nézettel együtt megmarad; képnél a felső határa a natív felbontás."""

    HINT = ("1–9: címke és tovább · görgő: nagyítás · húzás: mozgatás · "
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
        right = ttk.Frame(self, width=PANEL_W)
        right.pack(side="right", fill="y", padx=(0, 8), pady=8)
        right.pack_propagate(False)
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
        self.who_cb = ttk.Combobox(w, textvariable=self.who_text, postcommand=self._fill_who)
        self.who_cb.pack(fill="x", padx=6, pady=(6, 2))
        self.who_cb.bind("<Return>", lambda e: self._who_enter())
        self.who_cb.bind("<<ComboboxSelected>>", lambda e: self.canvas.focus_set())
        self.who_text.trace_add("write", lambda *a: self._who_changed())
        self.who_lbl = ttk.Label(w, textvariable=self.who_msg)
        self.who_lbl.pack(anchor="w", padx=6, pady=(0, 6))

        p = ttk.LabelFrame(right, text="Doktípus — kattintás vagy számbillentyű")
        p.pack(fill="x", pady=8)
        self.pal = tk.Listbox(p, height=11, activestyle="none", exportselection=False,
                              font=("Segoe UI", 9), highlightthickness=0, borderwidth=0)
        self.pal.pack(fill="x", padx=6, pady=(6, 2))
        self.pal.bind("<ButtonRelease-1>", self._pal_click)
        row = ttk.Frame(p)
        row.pack(fill="x", padx=6, pady=(2, 6))
        ttk.Button(row, text="0 · címke le", command=lambda: self._label(None)).pack(side="left")
        ttk.Button(row, text="Típusok…", command=self._edit_types).pack(side="right")
        ttk.Button(p, text="Címke a szövegből (ahol van)",
                   command=self._label_from_text).pack(fill="x", padx=6, pady=(0, 6))

        o = ttk.LabelFrame(right, text="Kimenet")
        o.pack(fill="both", expand=True)
        go = ttk.Frame(o)                  # alulra: kis ablakban is látsszon
        go.pack(side="bottom", fill="x", padx=6, pady=(2, 6))
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
        self.tree = ttk.Treeview(o, columns=("name", "n", "note"), show="", height=4,
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

    def refresh(self):
        """Dolgozói mappák és típuspaletta újra — mappaváltáskor és fülváltáskor
        (közben új dolgozói mappa vagy doktípus jöhetett)."""
        try:
            self.dirs = worker_dirs(self.folder)
        except OSError:
            self.dirs = []
        ikt, att = self.app.tabs["Iktató"], self.app.tabs["Áttekintő"]
        self.palette = palette_types(ikt.types, att.rules)
        self.pal.delete(0, tk.END)
        for i, (t, _r) in enumerate(self.palette):
            self.pal.insert(tk.END, f" {i + 1 if i < 9 else ' '}   {t}")
            c = LABEL_COLORS[i % len(LABEL_COLORS)]
            self.pal.itemconfig(i, background=tint(c), foreground=UI["ink"],
                                selectbackground=tint(c, 0.72),
                                selectforeground=UI["ink"])
        self.pal.configure(height=max(1, len(self.palette)))
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

    def _fill_who(self):
        """A legördülő tartalma: a beírt részletre illeszkedő nevek — de ha a mező
        már EGY dolgozót jelöl, mind a név, különben váltani csak visszatörölve
        lehetne."""
        who, hits = resolve_worker(self.who_text.get(), self.dirs)
        self.who_cb.configure(values=self.dirs if who else hits)

    def _who_changed(self):
        self.who, hits = resolve_worker(self.who_text.get(), self.dirs)
        if self.who:
            msg, col = f"→ {self.who}", COL_OK
        elif not self.who_text.get().strip():
            msg, col = "írd be a nevét (elég egy részlete)", ""
        else:
            msg, col = (f"{len(hits)} találat — pontosíts" if hits
                        else "nincs ilyen dolgozói mappa"), COL_WARN
        self.who_msg.set(msg)
        self.who_lbl.configure(foreground=col)
        self._refresh_out()

    def _who_enter(self):
        if self.who:
            self.who_text.set(self.who)
            self.canvas.focus_set()

    # ---------------- címkézés ----------------
    def _pal_click(self, e):
        i = self.pal.nearest(e.y)
        self.pal.selection_clear(0, tk.END)
        if 0 <= i < len(self.palette):
            self._label(self.palette[i][0])
        self.canvas.focus_set()

    def _key(self, e, item=None):
        """1–9: a kijelöltek (a nagyítóban a látott oldal) címkéje a paletta
        ennyiedik típusa, utána tovább a következő oldalra; 0 / Backspace: címke le."""
        k = "0" if e.keysym == "BackSpace" else e.char
        if len(k) != 1 or not k.isdigit():
            return None
        if item is not None:
            self.sel = {item}
        if k == "0":
            self._label(None)
        elif int(k) <= len(self.palette):
            self._label(self.palette[int(k) - 1][0])
        return "break"

    def _label(self, doc_type):
        """A kijelölt oldalak címkéje (None: le). Utána a kijelölés az utolsó
        kijelölt utáni oldalra lép — így billentyűvel végig lehet menni a kötegen."""
        todo = [it for it in self.items if it in self.sel and not it.bad]
        if self._b or not todo:
            if not todo:
                self.app.status("Jelöld ki az oldalakat (kattintás, Ctrl/Shift+kattintás), "
                                "aztán nyomj számot.")
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
        return target_name(self.who or "Dolgozó", d.doc_type, d.suffix)

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
                               "számot (1–9): ez lesz a doktípusuk.\nCtrl+kattintás: több oldal · "
                               "Shift+kattintás: tartomány · dupla kattintás: nagyítás")
        bad = sum(1 for it in self.items if it.bad)
        self.info.set(f"{n} oldal · {len(self.sel)} kijelölve · 1–9: címke · 0: címke le · "
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
                                                 "és nyomj számot (1–9).")
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
                    result = f"FELULIRVA (elozo: {BACKUP_DIR})"
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
                        (f" · felülírva, az előző: {BACKUP_DIR}\\" if backup else ""))
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

    def nine(name, specs, border, padding, sticky="nsew"):
        """9-slice képelem: az első kép az alap, a többi állapotonként.
        `width/height=1`: a kép SZÉLES (a csempézés miatt, 13.8), de a widget
        mérete a tartalmához igazodjon, ne a képhez."""
        base, rest = specs[0], specs[1:]
        spec = [(*states, img(data)) for states, data in rest]
        st.element_create(name, "image", img(base), *spec, border=border,
                          sticky=sticky, padding=padding, width=1, height=1)

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
            (("selected",), round_png(S, R, W, UI["line"], 1.1, shadow=1.6, pad=P,
                                      accent_bar=(UI["accent"], 3), bg=B)),
            (("active",), round_png(S, R, UI["hover"], None, 0, pad=P, bg=B)),
        ], R + P, (17, 7))
        nine("Light.tab", [
            round_png(S, R, B, None, 0, pad=P, bg=B),
            (("selected",), round_png(S, R, W, UI["line"], 1.1, shadow=1.4, pad=P,
                                      bg=B)),
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
            nine(f"{o}.Scrollbar.trough", [round_png(SB, 0, B, None, 0, bg=B)],
                 2, (0, 0))
            nine(f"{o}.Scrollbar.thumb", [
                round_png(SB, 5, "#c6cfdf", None, 0, pad=2.5, bg=B),
                (("pressed",), round_png(SB, 5, UI["accent"], None, 0, pad=2.5,
                                         bg=B)),
                (("active",), round_png(SB, 5, "#9fabc2", None, 0, pad=2.5, bg=B)),
            ], 7, (0, 0))
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
    st.map("TNotebook.Tab", foreground=[("selected", UI["accent"]),
                                        ("active", UI["ink"])])
    st.configure("Light.TNotebook", background=UI["bg"], borderwidth=0,
                 tabmargins=(2, 6, 2, 0))
    st.configure("Light.TNotebook.Tab", font=FONT_SB, foreground=UI["ink_soft"],
                 padding=0)
    st.map("Light.TNotebook.Tab", foreground=[("selected", UI["accent"])])
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
        canvas_card(mark, 1, 1, 31, 31, 9, fill=UI["accent"])
        canvas_card(mark, 1, 1, 31, 17, 9, fill="#3b74f0")
        mark.create_text(16, 17, text="PM", fill="#ffffff",
                         font=("Segoe UI Semibold", 11))
        tit = ttk.Frame(inner, style="Head.TFrame")
        tit.pack(side="left", padx=(12, 28))
        ttk.Label(tit, text="PDF Műhely", style="HeadTitle.TLabel").pack(anchor="w")
        ttk.Label(tit, text=f"offline eszköztár · {app_version()}",
                  style="HeadMuted.TLabel").pack(anchor="w")
        ttk.Button(inner, text="Frissítés", style="Head.TButton",
                   command=self.refresh_all).pack(side="right")
        ttk.Button(inner, text="Módosítás…", style="Head.TButton",
                   command=self._pick_folder).pack(side="right", padx=8)
        ttk.Entry(inner, textvariable=self.folder, style="Head.TEntry",
                  font=FONT_SM).pack(side="right", fill="x", expand=True,
                                     padx=(0, 6))
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
        }
        for i, name in enumerate(("Összeállító", "Iktató", "Áttekintő"), 1):
            self.nb.add(self.tabs[name], text=f"{i} · {name}")
        self.nb.add(self.tools, text="Eszközök")
        for name in ("Arckép elhelyezés", "Szerkesztés", "Összefűzés", "Raszterizálás"):
            self.tools.add(self.tabs[name], text=name)
        self.nb.bind("<<NotebookTabChanged>>", self._tab_changed)
        self.tools.bind("<<NotebookTabChanged>>", self._tab_changed)

        decorate(self)                   # ikonok és elsődleges stílus a gombokra
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
        for tab in self.tabs.values():
            tab.set_folder(self.folder.get())

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
    ck("alapból 12 szabály", len(s["rules"]) == 12, len(s["rules"]))
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
               target_subdir("Tart_eng_formanyomtatvány", R, False) == DIR_PREP)
            # A „taj” később született: a régi fájlhoz hozzáadódik…
            regi = [asdict(r) for r in DEFAULT_RULES if r.id != "taj"]
            with open(settings_path(), "w", encoding="utf-8") as f:
                json.dump({"rules": regi}, f)
            R = rules_from(load_settings())
            ck("régi szabályfájl: az új alapszabály (taj) hozzáadódik",
               [r.id for r in R].count("taj") == 1, [r.id for r in R])
            ck("…és felismeri a DocGen kimenetét",
               match_rule("Kovacevic Milan NYT.52.K.pdf", R)[0].id == "taj")
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

        os.makedirs(os.path.join(who, BACKUP_DIR))
        open(os.path.join(who, BACKUP_DIR, "Teszt Elek Előzetes megállapodás aláírt.pdf"),
             "w").close()
        re_ = scan(td, RULES, 1)[0]
        ck(f"a {BACKUP_DIR} mappát nem látja (se irat, se almappa)",
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
       target_subdir("Tart_eng_formanyomtatvány", RULES, False) == DIR_PREP)
    ck("célmappa: formanyomtatvány fotóval -> 02",
       target_subdir("Tart_eng_formanyomtatvány", RULES, True) == DIR_UP)
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
       pal[0][0] == "Tart_eng_formanyomtatvány" and pal[5][0] == "Útlevél")
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
        ck("felülírás előtt: másolat a .eredeti\\-ben",
           bak == os.path.join(who, BACKUP_DIR, "Kiss Anna Útlevél.pdf") and
           open(bak).read() == "régi", bak)
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
    erase_area(pg, pymupdf.Rect(52, 102, 148, 118))
    ck("kitakarás: a terület szövege eltűnt", "Árvíztűrő" not in pg.get_text())
    d2 = pymupdf.open("pdf", d.tobytes())
    ck("mentés után is olvasható mezők", sum(1 for _ in d2[0].widgets()) == 2)
    d2.close()
    d.close()

    print()
    print(f"=== {sum(res)}/{len(res)} teszt sikeres ===")
    return 0 if all(res) else 1


if __name__ == "__main__":
    if "--tomorit" in sys.argv:          # külön folyamatban futó tömörítés
        i = sys.argv.index("--tomorit")
        sys.exit(shrink_cli(sys.argv[i + 1:]))
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
