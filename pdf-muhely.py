#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PDF Műhely – egyesített offline eszköztár.
Fülek: Arckép elhelyezés | Összefűzés | Képek → PDF | Szétvágás | Raszterizálás |
       Iktató | Áttekintő
Függőség: pymupdf (a tkinter a Python része). Semmilyen hálózati műveletet nem végez.

Öntesztek GUI nélkül:  python pdf-muhely.py --test
"""

import os
import re
import csv
import sys
import json
import math
import shutil
import locale
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


CLEAN_META = {"producer": "pdf-muhely", "creator": "", "title": "",
              "author": "", "subject": "", "keywords": ""}

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


def shrink_pdf(data: bytes, limit: int = UPLOAD_LIMIT):
    """A beágyazott képek újratömörítése egyre erősebb lépcsőkön, amíg a PDF
    a korlát alá nem fér. A szöveg és a vektoros tartalom érintetlen marad.
    -> (PDF-bájtok, (DPI, minőség) | None) — None: így sem fért be, ilyenkor
    a legkisebb változat jön vissza."""
    if not hasattr(pymupdf.Document, "rewrite_images"):
        raise RuntimeError("A tömörítéshez újabb PyMuPDF kell (rewrite_images).")
    best = data
    for dpi, q in SHRINK_STEPS:
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


def write_pdf_verified(data: bytes, dst: str, pages: int):
    """PDF-bájtok kiírása .part néven, oldalszám-ellenőrzés, majd atomi átnevezés."""
    tmp = dst + ".part"
    try:
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


class FileList(ttk.Frame):
    """Listbox + görgetősáv + Frissítés/Tallózás gombpár."""

    def __init__(self, master, title, exts, on_pick, height=7, multi=False):
        super().__init__(master)
        self.exts, self.on_pick, self.folder = exts, on_pick, script_dir()
        self._ok = False

        box = ttk.LabelFrame(self, text=title)
        box.pack(fill="both", expand=True)
        inner = ttk.Frame(box)
        inner.pack(fill="both", expand=True, padx=6, pady=6)
        self.lb = tk.Listbox(inner, height=height, exportselection=False,
                             selectmode="extended" if multi else "browse")
        sb = ttk.Scrollbar(inner, orient="vertical", command=self.lb.yview)
        self.lb.configure(yscrollcommand=sb.set)
        self.lb.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.lb.bind("<<ListboxSelect>>", self._select)

        row = ttk.Frame(box)
        row.pack(fill="x", padx=6, pady=(0, 6))
        ttk.Button(row, text="Frissítés", command=self.refresh).pack(side="left")
        ttk.Button(row, text="Tallózás…", command=self._browse).pack(side="left", padx=6)
        self.extra = row

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

    def all_paths(self):
        return [os.path.join(self.folder, f) for f in list_files(self.folder, self.exts)]

    def select_all(self):
        if self._ok:
            self.lb.selection_set(0, tk.END)

    def _select(self, _e=None):
        if self._ok and self.on_pick:
            p = self.selected_paths()
            if p:
                self.on_pick(p[0])

    def _browse(self):
        pat = " ".join("*" + e for e in (self.exts if isinstance(self.exts, tuple) else (self.exts,)))
        p = filedialog.askopenfilename(title="Fájl kiválasztása", initialdir=self.folder,
                                       filetypes=[("Támogatott", pat), ("Minden fájl", "*.*")])
        if p and self.on_pick:
            self.on_pick(p)


# ───────────────────────────── 1. fül: elhelyezés ─────────────────────────────
class PlacerTab(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.src_path = self.doc = self.imgpdf = self.img_path = None
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
        self._build()

    def _build(self):
        left = ttk.Frame(self, width=340)
        left.pack(side="left", fill="y", padx=8, pady=8)
        left.pack_propagate(False)

        self.pdfs = FileList(left, "PDF nyomtatványok", (".pdf",), self._open_pdf, height=6)
        self.pdfs.pack(fill="both", expand=True)
        self.imgs = FileList(left, "Arcképek", IMG_EXT, self._load_img, height=6)
        self.imgs.pack(fill="both", expand=True, pady=(8, 0))
        self.img_lbl = ttk.Label(left, text="(nincs kép)", foreground="#555", wraplength=320)
        self.img_lbl.pack(anchor="w", pady=(4, 0))

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
        ttk.Label(left, textvariable=self.pos_info, foreground="#333", wraplength=320).pack(anchor="w")

        right = ttk.Frame(self)
        right.pack(side="right", fill="both", expand=True, padx=(0, 8), pady=8)
        self.canvas = tk.Canvas(right, bg="#666", highlightthickness=0, cursor="fleur", takefocus=1)
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
        try:
            src = pymupdf.open(path)
            imgpdf = pymupdf.open("pdf", src.convert_to_pdf())
            src.close()
        except Exception as e:
            messagebox.showerror("Hiba", f"A kép nem tölthető be:\n{e}")
            return
        if self.imgpdf:
            self.imgpdf.close()
        self.imgpdf, self.img_path = imgpdf, path
        r = imgpdf[0].rect
        self.img_lbl.configure(text=f"{os.path.basename(path)}  ({r.width:.0f}×{r.height:.0f} pt)")
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

    def _write(self, dst):
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
            page.show_pdf_page(target, self.imgpdf, 0,
                               rotate=float(self.angle.get()) + rot, keep_proportion=True)
            if not self.raster.get():
                out.save(dst, garbage=4, deflate=True)
                return
            flat = rasterize_doc(out, self.dpi.get())
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


# ───────────────────────────── 3. fül: szétvágás ─────────────────────────────
class SplitTab(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.folder = script_dir()
        self.dry = tk.BooleanVar(value=False)
        self.force = tk.BooleanVar(value=False)
        self._build()

    def _build(self):
        top = ttk.Frame(self)
        top.pack(fill="both", expand=True, padx=10, pady=10)
        self.files = FileList(top, "Szétvágandó PDF-ek (több is kijelölhető)",
                              (".pdf",), None, height=8, multi=True)
        self.files.pack(fill="both", expand=True)
        ttk.Button(self.files.extra, text="Mind kijelöl",
                   command=self.files.select_all).pack(side="left", padx=4)

        opt = ttk.Frame(top)
        opt.pack(fill="x", pady=8)
        ttk.Checkbutton(opt, text="Próbafutás (csak megmutatja, mi történne)",
                        variable=self.dry).pack(side="left")
        ttk.Checkbutton(opt, text="Létező fájlok felülírása",
                        variable=self.force).pack(side="left", padx=16)
        ttk.Button(opt, text="Szétvágás…", command=self._run).pack(side="right")

        self.log = tk.Text(top, height=12, wrap="none", state="disabled", bg="#f7f7f7")
        self.log.pack(fill="both", expand=True)

    def set_folder(self, folder):
        self.folder = folder
        self.files.set_folder(folder)

    def _write_log(self, txt):
        self.log.configure(state="normal")
        self.log.insert(tk.END, txt + "\n")
        self.log.see(tk.END)
        self.log.configure(state="disabled")
        self.update_idletasks()

    def _run(self):
        paths = self.files.selected_paths() or self.files.all_paths()
        if not paths:
            messagebox.showwarning("Nincs fájl", "Nincs szétvágható PDF.")
            return
        outdir = filedialog.askdirectory(title="Kimeneti mappa", initialdir=self.folder)
        if not outdir:
            return
        self.log.configure(state="normal")
        self.log.delete("1.0", tk.END)
        self.log.configure(state="disabled")

        total_all = done_all = 0
        try:
            for src_path in paths:
                t, k = self._split_one(src_path, outdir)
                total_all += t
                done_all += k
        except Exception as e:
            traceback.print_exc()
            messagebox.showerror("Hiba", f"{type(e).__name__}: {e}")
            return

        if self.dry.get():
            self._write_log(f"\n[PRÓBAFUTÁS] {len(paths)} fájl, összesen {total_all} "
                            f"külön PDF készülne itt: {outdir}")
        else:
            ok = done_all == total_all
            self._write_log(f"\nKész: {done_all}/{total_all} oldal, kimenet: {outdir} "
                            f"[{'OK' if ok else 'ELTÉRÉS!'}]")
            self.app.status(f"Szétvágva: {done_all} oldal")

    def _split_one(self, src_path, outdir):
        src = open_checked(src_path)
        total = src.page_count
        width = max(3, len(str(total)))
        stem = safe_stem(os.path.splitext(os.path.basename(src_path))[0])
        target = os.path.join(outdir, stem)
        self._write_log(f"\n{os.path.basename(src_path)}: {total} oldal -> {stem}\\")

        if self.dry.get():
            for i in (1, total):
                self._write_log(f"    pl. {stem}_{i:0{width}d}.pdf")
            src.close()
            return total, 0

        os.makedirs(target, exist_ok=True)
        if not self.force.get():
            exists = [f"{stem}_{i:0{width}d}.pdf" for i in range(1, total + 1)
                      if os.path.exists(os.path.join(target, f"{stem}_{i:0{width}d}.pdf"))]
            if exists:
                src.close()
                raise RuntimeError(f"{len(exists)} fájl már létezik itt: {target}\n"
                                   f"első: {exists[0]}\nKapcsold be a felülírást.")

        done = 0
        for i in range(total):
            one = pymupdf.open()
            one.insert_pdf(src, from_page=i, to_page=i)
            one.set_metadata(dict(CLEAN_META,
                                  title=f"{os.path.splitext(os.path.basename(src_path))[0]} - {i+1}. oldal"))
            one.save(os.path.join(target, f"{stem}_{i+1:0{width}d}.pdf"), garbage=4, deflate=True)
            one.close()
            done += 1
            if total > 50 and (i + 1) % 50 == 0:
                self._write_log(f"    ... {i+1}/{total}")
        src.close()

        bad, big = [], 0
        for i in range(1, total + 1):
            p = os.path.join(target, f"{stem}_{i:0{width}d}.pdf")
            d = pymupdf.open(p)
            if d.page_count != 1:
                bad.append(os.path.basename(p))
            d.close()
            big += os.path.getsize(p) > UPLOAD_LIMIT
        if bad:
            raise RuntimeError(f"nem 1 oldalas darab(ok): {', '.join(bad[:5])}")
        self._write_log(f"    {done}/{total} oldal kiírva [OK]" +
                        (f"  ⚠ {big} darab {mb(UPLOAD_LIMIT)} feletti" if big else ""))
        return total, done


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
TYPES_FILE = "iktato-doktipusok.json"      # a szkript mappájában

TILE_W, TILE_H, GAP = 150, 52, 10
CACHE_MAX = 12
BIG_FILE = 20 * 1024 * 1024        # efölött darabolt másolás
MAX_FULL_PATH = 255

ZOOM_MIN, ZOOM_MAX, ZOOM_STEP = 0.25, 6.0, 1.15

COL_TILE_BG = "#eef1f5"
COL_TILE_BG_HOT = "#cfe6ff"
COL_TILE_LINE = "#9aa7b4"
COL_TILE_LINE_HOT = "#1e6fd9"
COL_CANVAS = "#5f6672"
COL_WARN = "#b00020"
COL_OK = "#1d6b28"
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

        self.doc_type = tk.StringVar(value="")
        self.suffix = tk.StringVar(value=SUFFIX)
        self.filter_text = tk.StringVar(value="")
        self.name_preview = tk.StringVar(value="")
        self.msg = tk.StringVar(value="")
        self.page_lbl = tk.StringVar(value="")
        self.queue_lbl = tk.StringVar(value="nincs betöltött fájl")
        self.pagenav_lbl = tk.StringVar(value="")
        self.zoom_lbl = tk.StringVar(value="illesztve")

        self._build()
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
        self.cbo.bind("<<ComboboxSelected>>", lambda e: self._update_name())
        ttk.Button(bar, text="Típusok…", width=10,
                   command=self._edit_types).pack(side="left")
        ttk.Label(bar, text="Utótag:").pack(side="left", padx=(12, 4))
        ttk.Entry(bar, textvariable=self.suffix, width=10).pack(side="left")
        self.suffix.trace_add("write", lambda *a: self._update_name())

        ttk.Label(bar, text="Szűrő:").pack(side="left", padx=(18, 4))
        ent = ttk.Entry(bar, textvariable=self.filter_text, width=16)
        ent.pack(side="left")
        self.filter_text.trace_add("write", lambda *a: self._relayout())

        ttk.Button(bar, text="Mappák frissítése",
                   command=self._scan_dirs).pack(side="right")

        self.canvas = tk.Canvas(self, bg=COL_CANVAS, highlightthickness=0)
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

        ttk.Label(nav, text="Oldal:").pack(side="left", padx=(18, 4))
        ttk.Button(nav, text="◀", width=3,
                   command=lambda: self._step_page(-1)).pack(side="left")
        ttk.Label(nav, textvariable=self.pagenav_lbl, width=7,
                  anchor="center").pack(side="left")
        ttk.Button(nav, text="▶", width=3,
                   command=lambda: self._step_page(1)).pack(side="left")

        ttk.Label(nav, text="Nagyítás:").pack(side="left", padx=(18, 4))
        ttk.Button(nav, text="−", width=3,
                   command=lambda: self._zoom_by(1 / ZOOM_STEP)).pack(side="left")
        ttk.Label(nav, textvariable=self.zoom_lbl, width=9,
                  anchor="center").pack(side="left")
        ttk.Button(nav, text="+", width=3,
                   command=lambda: self._zoom_by(ZOOM_STEP)).pack(side="left")
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
            names = [d for d in os.listdir(self.parent_dir)
                     if os.path.isdir(os.path.join(self.parent_dir, d))
                     and not d.startswith(".")]
        except OSError as e:
            names = []
            self._info(f"A mappa nem olvasható: {e}", warn=True)
        self.dirs = hu_sorted(names)
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
        r = c.create_rectangle(x, y, x + TILE_W, y + TILE_H,
                               fill=COL_TILE_BG, outline=COL_TILE_LINE, width=1,
                               tags=("tile", f"tile::{name}"))
        label = name if len(name) <= 20 else name[:19] + "…"
        c.create_text(x + TILE_W / 2, y + TILE_H / 2, text=label,
                      font=("Segoe UI", 9), tags=("tile", f"tile::{name}"))
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
            c.create_text(cx, cy - 26, fill="#e8e8e8", justify="center",
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
                c.create_rectangle(bb, outline=COL_CROP if cropped else "#3a3f47",
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
                               fill="#ffffff", outline="#cccccc",
                               tags=("preview",))
            c.create_text(cx, cy - 20, text=note, width=220, justify="center",
                          font=("Segoe UI", 10), tags=("preview",))

        size = os.path.getsize(path) if os.path.isfile(path) else 0
        big = size > UPLOAD_LIMIT
        c.create_text(cx, y2 - 30, fill=COL_CROP if big else "#e8e8e8",
                      text=f"{os.path.basename(path)} · {mb(size)}" +
                           ("  ⚠ korlát fölött — iktatáskor tömöríthető" if big else ""),
                      font=("Segoe UI", 8), tags=("preview",))
        self._btn(cx, y2 - 12, "📂  Tallózás…", self._browse_files)
        self._update_name()

    def _btn(self, cx, cy, text, cmd):
        """Vászonra rajzolt gomb — az előnézetnél, ahol a szem úgyis van."""
        c = self.canvas
        t = c.create_text(cx, cy, text=text, fill="#1b1f24",
                          font=("Segoe UI", 9), tags=("preview", "cbtn"))
        x1, y1, x2, y2 = c.bbox(t)
        r = c.create_rectangle(x1 - 10, y1 - 4, x2 + 10, y2 + 4,
                               fill="#dfe5ec", outline="#8d949e",
                               tags=("preview", "cbtn"))
        c.tag_raise(t, r)
        for i in (r, t):
            c.tag_bind(i, "<Button-1>", lambda e, f=cmd: (f(), "break")[1])
            c.tag_bind(i, "<Enter>",
                       lambda e, rr=r: c.itemconfig(rr, fill="#eef3f9"))
            c.tag_bind(i, "<Leave>",
                       lambda e, rr=r: c.itemconfig(rr, fill="#dfe5ec"))
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
            title="PDF fájlok kiválasztása", initialdir=self.parent_dir,
            filetypes=[("PDF fájlok", "*.pdf")])
        if paths:
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
                added += 1
        if added:
            self.idx = len(self.queue) - added
            self.page_no = 0
            self._render_preview()       # nagyítás és nézet megmarad
        note = f"{added} fájl betöltve."
        if skipped:
            note += f" {skipped} kihagyva (csak .pdf)."
        self._info(note, warn=bool(skipped))

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
        self.canvas.create_text(e.x, e.y, text="⇢ ejtsd a névre",
                                font=("Segoe UI", 8), tags=("ghost",))
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
        if name == self._hot:
            return
        if self._hot:
            for i in self.canvas.find_withtag(f"tile::{self._hot}"):
                if self.canvas.type(i) == "rectangle":
                    self.canvas.itemconfig(i, fill=COL_TILE_BG,
                                           outline=COL_TILE_LINE, width=1)
        if name:
            for i in self.canvas.find_withtag(f"tile::{name}"):
                if self.canvas.type(i) == "rectangle":
                    self.canvas.itemconfig(i, fill=COL_TILE_BG_HOT,
                                           outline=COL_TILE_LINE_HOT, width=2)
        self._hot = name
        self._update_name(name)

    def _flash_combo(self):
        try:
            self.cbo.configure(foreground=COL_WARN)
            self.after(700, lambda: self.cbo.configure(foreground=""))
        except Exception:
            pass

    def _update_name(self, hover=None):
        dt = self.doc_type.get()
        if not dt:
            self.name_preview.set("— válassz dokumentumtípust —")
            return
        who = hover or "<mappanév>"
        self.name_preview.set(target_name(who, dt, self.suffix.get()))

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

        folder = os.path.join(self.parent_dir, dir_name)
        name = target_name(dir_name, self.doc_type.get(), self.suffix.get())
        collision = overwritten = False
        size = os.path.getsize(src)
        shrink = False
        if size > UPLOAD_LIMIT:
            shrink = messagebox.askyesnocancel(
                "5 MB feletti fájl",
                f"{os.path.basename(src)}: {mb(size)}\n"
                f"A feltöltési korlát {mb(UPLOAD_LIMIT)}.\n\n"
                "Tömörítsem iktatás előtt? (A forrásfájl változatlan marad.)\n\n"
                "Igen = tömörítve · Nem = változatlanul · Mégse = megszakítás")
            if shrink is None:
                self._info("Megszakítva — nem történt másolás.")
                return
        try:
            if os.path.exists(os.path.join(folder, name)):
                choice = self._ask_collision(name)
                if choice == "cancel":
                    self._info("Megszakítva — nem történt másolás.")
                    return
                if choice == "new":
                    name, collision = unique_name(folder, name)
                else:                     # felülírás: előzetes törlés NINCS, az os.replace
                    overwritten = True    # atomi — így akkor sem vész el, ha a forrás maga a cél
            dst = os.path.join(folder, name)
            check_path_len(dst)
            if shrink:
                self._info("Tömörítés…")
                self.update_idletasks()
                new_size, step = self._shrink_verified(src, dst)
            else:
                self._copy_verified(src, dst)
        except Exception as e:
            traceback.print_exc()
            self._log(src, dir_name, name, "HIBA: " + str(e)[:120])
            self._info(f"Hiba: {type(e).__name__}: {e}", warn=True)
            messagebox.showerror("A másolás nem sikerült",
                                 f"{type(e).__name__}: {e}")
            return

        self.last_copy = (src, dst)
        result = "UTKOZES-UJ NEV" if collision else ("FELULIRVA" if overwritten else "OK")
        if shrink:
            result += f" TOMORITVE {mb(size)}->{mb(new_size)}"
            if step is None:
                messagebox.showwarning(
                    "Tömörítés",
                    f"A legerősebb tömörítés után is {mb(new_size)} maradt — "
                    f"a feltöltési korlát ({mb(UPLOAD_LIMIT)}) fölött.\n\n"
                    "Érdemes kevesebb oldalra bontani (Szétvágás fül).")
        self._log(src, dir_name, name, result)
        self.queue.pop(self.idx)
        self.idx = min(self.idx, max(0, len(self.queue) - 1))
        self.page_no = 0
        self._render_preview()           # a nézet marad, ahol volt
        if collision:
            self._info("⚠ ÜTKÖZÉS: a mappában már volt ilyen nevű fájl — "
                       "az új példány neve: " + name, warn=True)
            messagebox.showwarning(
                "Névütközés",
                "A mappában már volt ilyen nevű fájl.\n\n"
                "Az új példány neve:\n" + name)
        else:
            self._info(f"✔ {dir_name} → {name}" + (" (felülírva)" if overwritten else "") +
                       (f" · tömörítve: {mb(size)} → {mb(new_size)}" if shrink else ""), ok=True)

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
                       "sorszámmal menti az újat. A felülírás visszavonhatatlan."
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

    def _copy_verified(self, src, dst):
        """Másolás .part néven, ellenőrzés, majd atomi átnevezés."""
        tmp = dst + ".part"
        total = os.path.getsize(src)
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
            os.replace(tmp, dst)
        except Exception:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            raise

    def _shrink_verified(self, src, dst):
        """Tömörítés .part néven, ellenőrzés, majd atomi átnevezés. -> (méret, lépcső)"""
        with open(src, "rb") as f:
            data, step = shrink_pdf(f.read())
        d = pymupdf.open(src)
        pages = d.page_count
        d.close()
        write_pdf_verified(data, dst, pages)
        return len(data), step

    def _undo(self):
        if not self.last_copy:
            self._info("Nincs mit visszavonni.", warn=True)
            return
        src, dst = self.last_copy
        if os.path.normcase(os.path.abspath(src)) == os.path.normcase(os.path.abspath(dst)):
            self._info("Helyben felülírt fájl nem vonható vissza (az eredeti nincs meg).",
                       warn=True)
            return
        try:
            if os.path.exists(dst):
                os.remove(dst)
        except OSError as e:
            self._info(f"A visszavonás nem sikerült: {e}", warn=True)
            return
        self.last_copy = None
        if os.path.isfile(src) and src not in self.queue:
            self.queue.insert(self.idx, src)       # vissza a sorba
            self._render_preview()
        self._log(src, os.path.basename(os.path.dirname(dst)),
                  os.path.basename(dst), "VISSZAVONVA")
        self._info(f"Visszavonva: {os.path.basename(dst)} törölve.")

    # ---------------- napló és üzenet ----------------
    def _log(self, src, folder, name, result):
        path = os.path.join(self.parent_dir, LOG_NAME)
        new = not os.path.exists(path)
        try:
            with open(path, "a", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f, delimiter=";")
                if new:
                    w.writerow(["időbélyeg", "forrás", "célmappa", "célfájl",
                                "doktípus", "eredmény"])
                w.writerow([datetime.datetime.now().isoformat(timespec="seconds"),
                            src, folder, name, self.doc_type.get(), result])
        except OSError:
            pass                        # a napló sosem állítja meg a munkát

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


DEFAULT_RULES = [
    # ── KÖTELEZŐ ────────────────────────────────────────────────────────────
    Rule("forma", "Aláírt formanyomtatvány", "Forma",
         [], ["formanyomtatvany"], True, True),
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
]

NOISE_EXACT = {"thumbs.db", "desktop.ini", ".ds_store",
               "iktato-naplo.csv", "iktato-doktipusok.json"}

# ── színek ──────────────────────────────────────────────────────────────────
C_BG = "#ffffff"
C_GRID = "#d6dbe1"
C_HDR = "#eef1f5"
C_HDR_OPT = "#f6f7f9"
C_TEXT = "#1b1f24"
C_MUTED = "#8a929b"
C_P = "#cdeccd"
C_D = "#ffeaa7"
C_DP = "#b6e3b6"
C_NONE = "#f4f6f8"
C_AMB = "#ffd0a0"
C_BIG = "#ffb3b3"          # 5 MB feletti (nem feltölthető) PDF
C_ROW_ALT = "#fafbfc"
C_SEL = "#cfe6ff"
C_CUR = "#1e6fd9"
C_OK = "#1d6b28"
C_WARN = "#b00020"

ROW_H = 24
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
                ))
            except Exception:
                continue
        if out:
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

    @property
    def cell(self) -> str:
        if self.ambiguous:
            return "?"
        if self.pdf and self.docx:
            return "DP"
        if self.pdf:
            return "P"
        if self.docx:
            return "D"
        return "·"


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
    subdirs: int = 0
    error: str = None

    def _req(self):
        return [r for r in self.rules if r.required]

    def _opt(self):
        return [r for r in self.rules if not r.required]

    def _ok(self, r) -> bool:
        """Van-e ehhez a típushoz FELTÖLTHETŐ (korlát alatti) PDF."""
        return any(p not in self.big for p in self.docs[r.id].pdf)

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
        return [r.name for r in self.rules
                if r.generated and self.docs[r.id].docx and not self.docs[r.id].pdf]

    @property
    def missing_required(self) -> list:
        return [r.name for r in self._req()
                if r.generated and not self.docs[r.id].docx
                and not self.docs[r.id].pdf]

    @property
    def to_obtain(self) -> list:
        return [r.name for r in self._req()
                if not r.generated and not self.docs[r.id].pdf]

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
        row.subdirs = sum(1 for e in os.scandir(folder)
                          if e.is_dir() and not e.name.startswith("."))
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
                    ("name_width", "scan_depth", "row_height")}
        self.cur = None

        self.v_name = tk.StringVar()
        self.v_short = tk.StringVar()
        self.v_all = tk.StringVar()
        self.v_any = tk.StringVar()
        self.v_req = tk.BooleanVar()
        self.v_gen = tk.BooleanVar()
        self.v_width = tk.IntVar(value=56)
        self.v_depth = tk.IntVar(value=self.gen["scan_depth"])
        self.v_namew = tk.IntVar(value=self.gen["name_width"])
        self.v_rowh = tk.IntVar(value=self.gen["row_height"])
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
        ttk.Label(d, foreground=C_MUTED, justify="left", wraplength=700,
                  text="Az oszlopszélesség a táblázatban is állítható: húzd az "
                       "oszlophatárt a fejlécben, vagy Ctrl+← / Ctrl+→ a "
                       "kijelölt oszlopon."
                  ).grid(row=2, column=0, columnspan=2, sticky="w", padx=8,
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
                 row_height=int(self.v_rowh.get()))
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

        for c in (self.c_name, self.c_data):
            c.bind("<MouseWheel>", self._wheel)
            c.bind("<Button-1>", lambda e, cv=c: self._click(e, cv))
            c.bind("<Double-Button-1>", lambda e, cv=c: self._dclick(e, cv))
            c.bind("<Button-3>", lambda e, cv=c: self._rclick(e, cv))
            c.bind("<Configure>", lambda e: self._redraw())
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
        ttk.Label(foot, textvariable=self.summary).pack(side="left", padx=16)
        self.msg_lbl = ttk.Label(foot, textvariable=self.msg)
        self.msg_lbl.pack(side="right")

    def _yview(self, *a):
        self.c_name.yview(*a)
        self.c_data.yview(*a)
        self._pin_all()

    def _wheel(self, e):
        d = -1 if e.delta > 0 else 1
        self.c_name.yview_scroll(d, "units")
        self.c_data.yview_scroll(d, "units")
        self._pin_all()
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
            order = {"P": 0, "DP": 0, "D": 1, "?": 2, "·": 3}
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
        sub = sum(r.subdirs for r in self.rows)
        extra = f" · {sub} almappa" if sub else ""
        extra += f" · {big} mappában 5 MB feletti PDF" if big else ""
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
        for i, r in enumerate(self.view_rows):
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
        for i, row in enumerate(self.view_rows):
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
                fill = {"P": C_P, "DP": C_DP, "D": C_D, "?": C_AMB}.get(txt, C_NONE)
                if txt == "·":
                    fill = base
                if st and any(p in row.big for p in st.pdf):
                    txt, fill = txt + "!", C_BIG      # 5 MB fölött: nem feltölthető
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
            j = self.cur_c - 1
            if j < len(cols):
                cx, cw = xs[j], cols[j].width
            elif j == len(cols):
                cx, cw = x_photo, W_SMALL
            elif j == len(cols) + 1:
                cx, cw = x_extra, W_SMALL
            else:
                cx, cw = x_ready, W_READY
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
                               "maradhat; minden más fotó PDF-be (Képek → PDF)",
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
            if not r.photos:
                L.append("    arckép hiányzik")
            elif len(r.photos) > 1:
                L.append(f"    {len(r.photos)} kép — csak az arckép maradhat, "
                         "a többi PDF-be (Képek → PDF)")
            L.append("")

        L.append(f"╔═ BEADHATÓ ({len(good)}) " + "═" * 44)
        L.append("")
        for r in good:
            extra = "   ⚠ arckép hiányzik" if not r.photos else ""
            if len(r.photos) > 1:
                extra += f"   ⚠ {len(r.photos)} kép (csak az arckép maradhat)"
            if r.big:
                extra += f"   ⚠ {len(r.big)} db 5 MB feletti PDF"
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
                            "Beadható", "5 MB feletti PDF"])
                for row in self.rows:
                    w.writerow([row.name] +
                               [row.docs[r.id].cell for r in self.rules] +
                               [len(row.photos), len(row.extra_pdfs),
                                f"{row.ready_required}/{nreq}",
                                f"{row.ready_optional}/{nopt}",
                                "igen" if row.beadhato else "nem", len(row.big)])
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



# ─────────────────────────── 7. fül: képek → pdf ───────────────────────────
# Fotókból / szkennelt képekből EGY tömörített PDF. A névadás nem itt történik:
# a kész PDF az Iktató várólistájába kerül, ott kap nevet és helyet.
THUMB = 160                                   # bélyegkép befoglaló mérete (px)
CELL_W, CELL_H = THUMB + 16, THUMB + 34       # csempe: kép + fájlnév
PRESETS = (("Irodai · 200 DPI", 200, 75),     # (felirat, DPI, JPEG-minőség)
           ("Archív · 300 DPI", 300, 85),
           ("E-mail · 150 DPI", 150, 65))
A4_LONG_IN = 842 / 72                         # az A4 hosszabb oldala hüvelykben


def image_page_jpeg(path, rot, dpi, quality, gray):
    """Egy kép -> (JPEG-bájtok, szélesség px, magasság px, oldalszám).
    A hosszabb oldal legfeljebb dpi × A4 hosszabb oldala; nagyítás soha.
    Az EXIF-forgatást a MuPDF magától alkalmazza, a `rot` a felhasználói ráadás."""
    src = pymupdf.open(path)
    try:
        page = src[0]
        info = page.get_image_info()
        native = max(info[0]["width"], info[0]["height"]) if info else \
            max(page.rect.width, page.rect.height)
        z = min(native, dpi * A4_LONG_IN) / max(page.rect.width, page.rect.height)
        pix = page.get_pixmap(matrix=pymupdf.Matrix(z, z).prerotate(rot))
        if gray:
            pix = pymupdf.Pixmap(pymupdf.csGRAY, pix)
        return pix.tobytes("jpeg", jpg_quality=quality), pix.width, pix.height, src.page_count
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


@dataclass
class ImgItem:
    path: str
    rot: int = 0                 # felhasználói forgatás: 0 / 90 / 180 / 270
    thumb: object = None         # tk.PhotoImage, ha már elkészült
    bad: str = ""                # hibaüzenet, ha a kép nem olvasható


class ImagesToPdfTab(ttk.Frame):
    """Bélyegképrács vonszolásos sorrendezéssel. Szálak nincsenek: a bélyegképek
    és a feldolgozás is after()-láncban, képenként futnak, így a felület élő marad
    (és a PyMuPDF szálbiztonsága sem kérdés)."""

    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.folder = script_dir()
        self.last_dir = None
        self.items = []
        self.sel = None
        self.preset = tk.IntVar(value=0)
        self.gray = tk.BooleanVar(value=False)
        self.fit_a4 = tk.BooleanVar(value=True)
        self.info = tk.StringVar(value="")
        self._drag = None            # (index, kezdő x, kezdő y)
        self._thumb_job = None
        self._b = None               # a futó feldolgozás állapota
        self._build()
        self._redraw()

    def _build(self):
        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=8, pady=(8, 4))
        ttk.Button(bar, text="Képek hozzáadása…", command=self._add_files).pack(side="left")
        ttk.Button(bar, text="Mappa hozzáadása…", command=self._add_dir).pack(side="left", padx=4)
        ttk.Button(bar, text="↺", width=3, command=lambda: self._rotate(-90)).pack(side="left", padx=(16, 2))
        ttk.Button(bar, text="↻", width=3, command=lambda: self._rotate(90)).pack(side="left")
        ttk.Button(bar, text="Kijelölt törlése", command=self._remove).pack(side="left", padx=(16, 4))
        ttk.Button(bar, text="Mind törlése", command=self._clear).pack(side="left")
        ttk.Label(bar, textvariable=self.info).pack(side="right")

        grid = ttk.Frame(self)
        grid.pack(fill="both", expand=True, padx=8, pady=4)
        self.canvas = tk.Canvas(grid, bg=COL_CANVAS, highlightthickness=0, takefocus=1)
        sb = ttk.Scrollbar(grid, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=sb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.canvas.bind("<Configure>", lambda e: self._redraw())
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._motion)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.canvas.bind("<Delete>", lambda e: self._remove())
        self.canvas.bind("<MouseWheel>", lambda e: (
            self.canvas.yview_scroll(-1 if e.delta > 0 else 1, "units"), "break")[1])

        opt = ttk.Frame(self)
        opt.pack(fill="x", padx=8, pady=4)
        ttk.Label(opt, text="Minőség:").pack(side="left")
        for i, (label, _d, _q) in enumerate(PRESETS):
            ttk.Radiobutton(opt, text=label, value=i, variable=self.preset).pack(side="left", padx=4)
        ttk.Checkbutton(opt, text="Szürkeárnyalatos",
                        variable=self.gray).pack(side="left", padx=(16, 0))
        ttk.Checkbutton(opt, text="A4-es lapra illesztve (különben lap = kép)",
                        variable=self.fit_a4).pack(side="left", padx=16)

        run = ttk.Frame(self)
        run.pack(fill="x", padx=8, pady=4)
        self.pb = ttk.Progressbar(run, mode="determinate")
        self.pb.pack(side="left", fill="x", expand=True)
        self.btn = ttk.Button(run, text="PDF készítése → Iktató…", command=self._run)
        self.btn.pack(side="left", padx=8)
        ttk.Button(run, text="Mégsem", command=self._cancel).pack(side="left")

        self.log = tk.Text(self, height=5, wrap="none", state="disabled", bg="#f7f7f7")
        self.log.pack(fill="x", padx=8, pady=(0, 8))

    def set_folder(self, folder):
        self.folder = folder         # a képek külön mappából jönnek — a lista marad

    def _write_log(self, txt):
        self.log.configure(state="normal")
        self.log.insert(tk.END, txt + "\n")
        self.log.see(tk.END)
        self.log.configure(state="disabled")

    # ---------------- lista ----------------
    def _add_files(self):
        pat = " ".join("*" + e for e in IMG_EXT)
        self._add(filedialog.askopenfilenames(title="Képek kiválasztása",
                                              initialdir=self.last_dir or self.folder,
                                              filetypes=[("Képek", pat)]))

    def _add_dir(self):
        d = filedialog.askdirectory(title="Képek mappája", initialdir=self.last_dir or self.folder)
        if d:
            self._add([os.path.join(d, f) for f in list_files(d, IMG_EXT)])

    def _add(self, paths):
        known = {it.path for it in self.items}
        new = {os.path.abspath(p) for p in paths if p.lower().endswith(IMG_EXT)} - known
        new = sorted(new, key=lambda p: natural_key(os.path.basename(p)))
        if not new:
            return
        self.last_dir = os.path.dirname(new[0])
        self.items += [ImgItem(p) for p in new]
        self._redraw()
        self._thumbs()

    def _rotate(self, d):
        if self.sel is None:
            return
        it = self.items[self.sel]
        it.rot = (it.rot + d) % 360
        it.thumb = None
        self._redraw()
        self._thumbs()

    def _remove(self):
        if self.sel is None or self._b:
            return
        self.items.pop(self.sel)
        self.sel = min(self.sel, len(self.items) - 1) if self.items else None
        self._redraw()

    def _clear(self):
        if not self._b:
            self.items, self.sel = [], None
            self._redraw()

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
                p = d[0]
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

    def _redraw(self):
        c = self.canvas
        c.delete("all")
        for i, it in enumerate(self.items):
            x, y = self._xy(i)
            hot = i == self.sel
            c.create_rectangle(x, y, x + CELL_W, y + CELL_H,
                               fill=COL_TILE_BG_HOT if hot else COL_TILE_BG,
                               outline=COL_TILE_LINE_HOT if hot else COL_TILE_LINE,
                               width=2 if hot else 1)
            cx, cy = x + CELL_W / 2, y + 8 + THUMB / 2
            if it.thumb:
                c.create_image(cx, cy, image=it.thumb)
            else:
                c.create_text(cx, cy, text=it.bad or "…", font=("Segoe UI", 9),
                              fill=COL_WARN if it.bad else "#8a929b")
            name = os.path.basename(it.path)
            name = name if len(name) <= 20 else name[:19] + "…"
            c.create_text(cx, y + CELL_H - 12, text=f"{i + 1}. {name}", font=("Segoe UI", 8))
        n = len(self.items)
        rows = (n + self._cols() - 1) // self._cols()
        c.configure(scrollregion=(0, 0, c.winfo_width(), GAP + rows * (CELL_H + GAP)))
        if not n:
            c.create_text(max(200, c.winfo_width()) / 2, 80, fill="#e8e8e8", justify="center",
                          font=("Segoe UI", 11),
                          text="Nincs kép.\nAdj hozzá képeket vagy egy mappát — a sorrend "
                               "vonszolással állítható.")
        bad = sum(1 for it in self.items if it.bad)
        self.info.set(f"{n} kép" + (f" · {bad} nem olvasható (kimarad)" if bad else ""))

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

    def _press(self, e):
        self.canvas.focus_set()
        x, y = self.canvas.canvasx(e.x), self.canvas.canvasy(e.y)
        self.sel = self._index_at(x, y)
        self._drag = (self.sel, x, y) if self.sel is not None and not self._b else None
        self._redraw()

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
        c.create_text(x, y, text=os.path.basename(self.items[i].path)[:22],
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
        self.sel = j
        self._redraw()

    # ---------------- feldolgozás ----------------
    def _run(self):
        if self._b:
            return
        todo = [it for it in self.items if not it.bad]
        if not todo:
            messagebox.showwarning("Nincs kép", "Adj hozzá legalább egy olvasható képet.")
            return
        first = todo[0].path
        dst = filedialog.asksaveasfilename(
            title="A kész PDF mentése (utána az Iktatóban kap végleges nevet)",
            initialdir=os.path.dirname(first),
            initialfile=os.path.splitext(os.path.basename(first))[0] + ".pdf",
            defaultextension=".pdf", filetypes=[("PDF fájlok", "*.pdf")])
        if not dst:
            return
        _, dpi, q = PRESETS[self.preset.get()]
        self._b = dict(todo=todo, i=0, out=pymupdf.open(), dst=dst, dpi=dpi, q=q,
                       gray=self.gray.get(), a4=self.fit_a4.get(), cancel=False)
        self.log.configure(state="normal")
        self.log.delete("1.0", tk.END)
        self.log.configure(state="disabled")
        self.pb.configure(maximum=len(todo), value=0)
        self.btn.state(["disabled"])
        self.after(1, self._step)

    def _cancel(self):
        if self._b:
            self._b["cancel"] = True

    def _step(self):
        b = self._b
        if b["cancel"]:
            b["out"].close()
            self._done("Megszakítva — nem készült fájl.")
            return
        if b["i"] < len(b["todo"]):
            it = b["todo"][b["i"]]
            name = os.path.basename(it.path)
            try:
                jpeg, w, h, npages = image_page_jpeg(it.path, it.rot, b["dpi"], b["q"], b["gray"])
                add_image_page(b["out"], jpeg, w, h, b["dpi"], b["a4"])
                if npages > 1:     # ponytail: többoldalas TIFF-ből csak az 1. oldal; ha kell, ciklus az oldalakon
                    self._write_log(f"  ! {name}: {npages} oldalas — csak az 1. oldal került be")
            except Exception as e:
                self._write_log(f"  ⚠ kihagyva: {name} ({type(e).__name__}: {e})")
            b["i"] += 1
            self.pb.configure(value=b["i"])
            self.app.status(f"{b['i']}/{len(b['todo'])} kép feldolgozva")
            self.after(1, self._step)
            return
        self._finish()

    def _finish(self):
        out, dst = self._b["out"], self._b["dst"]
        try:
            pages = out.page_count
            if not pages:
                raise RuntimeError("Egyetlen kép sem volt feldolgozható.")
            out.set_metadata(dict(CLEAN_META, title=os.path.splitext(os.path.basename(dst))[0]))
            data = out.tobytes(garbage=4, deflate=True)
            out.close()
            if len(data) > UPLOAD_LIMIT:
                self._write_log(f"{mb(len(data))} — a feltöltési korlát ({mb(UPLOAD_LIMIT)}) "
                                "fölött, tömörítés…")
                self.update_idletasks()
                data, step = shrink_pdf(data)
                self._write_log(f"  → {mb(len(data))}" + (f" ({step[0]} DPI, Q{step[1]})" if step
                                                          else " — a legerősebb lépcsővel sem fért be!"))
            write_pdf_verified(data, dst, pages)
        except Exception as e:
            traceback.print_exc()
            if not out.is_closed:
                out.close()
            self._done(f"Hiba: {type(e).__name__}: {e}")
            messagebox.showerror("Hiba", f"{type(e).__name__}: {e}")
            return
        self._done(f"\n{os.path.basename(dst)} kész – {pages} oldal, {mb(len(data))} {size_note(dst)}")
        ikt = self.app.tabs["Iktató"]
        ikt._enqueue([dst])
        self.app.nb.select(ikt)

    def _done(self, msg):
        self._b = None
        self.btn.state(["!disabled"])
        self._write_log(msg)
        self.app.status(msg.strip())


# ───────────────────────────────── főablak ─────────────────────────────────
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PDF Műhely – offline")
        self.geometry("1200x840")
        self.minsize(960, 680)
        self.folder = tk.StringVar(value=script_dir())
        self._status = tk.StringVar(value="Kész.")

        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=10, pady=(10, 0))
        ttk.Label(bar, text="Munkamappa:").pack(side="left")
        ttk.Entry(bar, textvariable=self.folder).pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(bar, text="Módosítás…", command=self._pick_folder).pack(side="left")
        ttk.Button(bar, text="Frissítés", command=self.refresh_all).pack(side="left", padx=6)

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=10, pady=10)
        self.tabs = {
            "Arckép elhelyezés": PlacerTab(self.nb, self),
            "Összefűzés": MergeTab(self.nb, self),
            "Képek → PDF": ImagesToPdfTab(self.nb, self),
            "Szétvágás": SplitTab(self.nb, self),
            "Raszterizálás": RasterTab(self.nb, self),
            "Iktató": IktatoTab(self.nb, self),
            "Áttekintő": AttekintoTab(self.nb, self),
        }
        for name, tab in self.tabs.items():
            self.nb.add(tab, text=name)
        self.nb.bind("<<NotebookTabChanged>>", self._tab_changed)

        ttk.Label(self, textvariable=self._status, relief="sunken", anchor="w").pack(
            fill="x", side="bottom")
        self.refresh_all()

    def _pick_folder(self):
        d = filedialog.askdirectory(title="Munkamappa", initialdir=self.folder.get())
        if d:
            self.folder.set(d)
            self.refresh_all()

    def refresh_all(self):
        for tab in self.tabs.values():
            tab.set_folder(self.folder.get())

    def active_tab(self):
        try:
            return self.nametowidget(self.nb.select())
        except Exception:
            return None

    def status(self, txt):
        self._status.set(txt)

    def _tab_changed(self, _e=None):
        if self.active_tab() is self.tabs["Áttekintő"]:
            self.tabs["Áttekintő"].refresh()        # iktatás után is friss állapot

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
        ikt._update_name()
        self.nb.select(ikt)

    def goto_arckep(self, folder):
        self.tabs["Arckép elhelyezés"].set_folder(folder)
        self.nb.select(self.tabs["Arckép elhelyezés"])


# ── önteszt ─────────────────────────────────────────────────────────────────
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
    ck("alapból 11 szabály", len(s["rules"]) == 11, len(s["rules"]))
    ck("6 kötelező", sum(1 for d in s["rules"] if d["required"]) == 6)
    ck("azonosítók egyediek",
       len({d["id"] for d in s["rules"]}) == len(s["rules"]))
    ck("alap mélység 1", s["scan_depth"] == 1)
    ck("kör: Rule -> dict -> Rule",
       rules_from({"rules": [asdict(x) for x in RULES]})[1].any_of ==
       RULES[1].any_of)

    print("BEOLVASÁS ALMAPPÁKKAL")
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        who = os.path.join(td, "Teszt Elek")
        os.makedirs(os.path.join(who, "Mellekletek", "Regi"))
        for p, fn in [
                (who, "Teszt Elek Aláírt formanyomtatvány aláírt.pdf"),
                (who, "Teszt Elek Előzetes próbaidő nélkül_ukran_alairt.pdf"),
                (who, "Teszt Elek Elfogadó nyilatkozat aláírt.pdf"),
                (who, "Teszt Elek Egyoldalú hozzájárulási nyilatkozat.pdf"),
                (who, "Teszt Elek Belföldi meghatalmazás aláírt.pdf"),
                (who, "Teszt Elek.jpg"),
                (who, "~$zar.docx"),
                (os.path.join(who, "Mellekletek"), "utlevel.pdf"),
                (os.path.join(who, "Mellekletek", "Regi"), "nav_igazolas.pdf")]:
            open(os.path.join(p, fn), "w").close()

        r0 = scan(td, RULES, 0)[0]
        ck("mélység 0: útlevél nem látszik -> 5/6",
           r0.ready_required == 5 and not r0.beadhato, r0.ready_required)
        r1 = scan(td, RULES, 1)[0]
        ck("mélység 1: útlevél megvan -> BEADHATÓ",
           r1.beadhato, r1.ready_required)
        ck("mélység 1: NAV még nem látszik", not r1.docs["nav"].pdf)
        r2 = scan(td, RULES, 2)[0]
        ck("mélység 2: NAV is megvan", bool(r2.docs["nav"].pdf),
           r2.docs["nav"].pdf)
        ck("almappa-szám 1", r1.subdirs == 1, r1.subdirs)
        ck("relatív út marad meg",
           any(os.sep in f for f in r1.docs["utlevel"].pdf),
           r1.docs["utlevel"].pdf)
        ck("zaj kimaradt", not r1.other, r1.other)

        big = os.path.join(who, "Mellekletek", "utlevel.pdf")
        with open(big, "wb") as f:
            f.truncate(UPLOAD_LIMIT + 1)
        rb = scan(td, RULES, 1)[0]
        ck("5 MB feletti útlevél -> nem feltölthető, NEM beadható",
           not rb.beadhato and rb.ready_required == 5 and big.endswith(next(iter(rb.big))),
           (rb.ready_required, list(rb.big)))
        open(os.path.join(who, "Teszt Elek Útlevél.pdf"), "w").close()
        ck("mellette egy korlát alatti útlevél -> beadható",
           scan(td, RULES, 1)[0].beadhato)

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
    small, step = shrink_pdf(raw)
    chk = pymupdf.open("pdf", small)
    ck("tömörítés a korlát alá, oldalszám marad",
       len(raw) > UPLOAD_LIMIT >= len(small) and chk.page_count == 2 and step,
       f"{mb(len(raw))} -> {mb(len(small))}, {step}")
    chk.close()
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
        jpeg, w, h, _ = image_page_jpeg(p, 0, 200, 75, False)
        ck("kis kép nem nagyítódik", (w, h) == (400, 200), (w, h))
        jpeg, w, h, _ = image_page_jpeg(p, 90, 200, 75, True)
        px = pymupdf.Pixmap(jpeg)
        ck("↻ 90° = óramutató szerint (a bal fehér fél felülre kerül)",
           (w, h) == (200, 400) and px.pixel(100, 40)[0] > 200 and px.pixel(100, 360)[0] < 60,
           (w, h, px.pixel(100, 40), px.pixel(100, 360)))
        ck("szürkeárnyalat -> 1 csatorna", px.n == 1, px.n)
        big = os.path.join(td, "nagy.jpg")
        with open(big, "wb") as f:
            f.write(pymupdf.Pixmap(pymupdf.csRGB, 4000, 3000, bytes(4000 * 3000 * 3), False)
                    .tobytes("jpeg"))
        _, w, h, _ = image_page_jpeg(big, 0, 150, 65, False)
        ck("nagy kép -> hosszabb oldal 150 DPI × A4", abs(max(w, h) - 150 * A4_LONG_IN) <= 1, (w, h))
        out = pymupdf.open()
        jpeg, w, h, _ = image_page_jpeg(p, 0, 200, 75, False)
        add_image_page(out, jpeg, w, h, 200, True)
        pg = out[0]
        ck("fekvő kép -> fekvő A4, a JPEG bájtra azonos",
           pg.rect.width > pg.rect.height and
           out.xref_stream_raw(pg.get_images()[0][0]) == jpeg)
        out.close()

    print()
    print(f"=== {sum(res)}/{len(res)} teszt sikeres ===")
    return 0 if all(res) else 1


if __name__ == "__main__":
    if "--test" in sys.argv:
        sys.exit(_selftest())
    App().mainloop()
