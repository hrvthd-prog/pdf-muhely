# -*- coding: utf-8 -*-
"""Felületfotó: elindítja az appot egy demó-munkamappával, és lefotózza az ablakot.
Így a felületen dolgozó (ember vagy AI) LÁTJA, mit változtatott — a GUI-teszt a
működést méri, a megjelenést nem.

    python tools/ui-kep.py 0 osszeallito.png     # 0–2: a három fő fül
    python tools/ui-kep.py 3 eszkozok.png        # 3: Eszközök (Arckép elhelyezés)
    python tools/ui-kep.py 4 ellenorzes.png      # 4: az Ellenőrzés dialógus
    python tools/ui-kep.py 5 szerkesztes.png     # 5: Eszközök → Szerkesztés (mező mód)
    python tools/ui-kep.py 6 bekezdes.png        # 6: Szerkesztés → Bekezdés formázása

A valódi beállításfájlokhoz nem nyúl: a script_dir-t ideiglenes mappára irányítja.
"""
import ctypes
import importlib.util
import os
import sys
import tempfile

GY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("pm", os.path.join(GY, "pdf-muhely.py"))
pm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pm)
P = pm.pymupdf

tab_i = int(sys.argv[1]) if len(sys.argv) > 1 else 0
out = sys.argv[2] if len(sys.argv) > 2 else "ui.png"

TMP = tempfile.mkdtemp(prefix="ui-demo-")
pm.script_dir = lambda: TMP
root = os.path.join(TMP, "gyujto")
for who in ("Kiss Anna", "Nagy Béla", "Ökrös Zsófia", "Tran Van Minh",
            "Horváth Dániel", "Kovács Péter"):
    up = os.path.join(root, who, pm.DIR_UP)
    pr = os.path.join(root, who, pm.DIR_PREP)
    os.makedirs(up, exist_ok=True)
    os.makedirs(pr, exist_ok=True)
    for t in ("Aláírt formanyomtatvány aláírt", "Előzetes megállapodás aláírt",
              "Elfogadó nyilatkozat aláírt", "Útlevél"):
        d = P.open()
        d.new_page().insert_text((72, 100), f"{who} — {t}", fontsize=14)
        d.save(os.path.join(up if who != "Nagy Béla" else pr, f"{who} {t}.pdf"))
        d.close()
    open(os.path.join(pr, f"{who}.jpg"), "wb").close()

app = pm.App()
app.folder.set(root)
app.refresh_all()
app.geometry("1280x740+20+20")
app.nb.select(app.nb.tabs()[min(tab_i, len(app.nb.tabs()) - 1)])
if tab_i == 1:                                  # Iktató: tegyünk a sorba egy PDF-et
    ikt = app.tabs["Iktató"]
    ikt.doc_type.set("Tartózkodási engedély formanyomtatvány")
    ikt._type_chosen()
    d = P.open()
    for k in range(3):
        d.new_page().insert_text((72, 100), f"szkennelt oldal {k + 1}", fontsize=20)
    sp = os.path.join(TMP, "koteg.pdf")
    d.save(sp)
    d.close()
    ikt._enqueue([sp])
    ikt.page_mode.set(True)                     # oldalankénti szétosztás látszódjon
    ikt._page_mode_changed()
if tab_i == 0:                                  # Összeállító: pár oldal a rácsba
    kt = app.tabs["Összeállító"]
    kt.who_text.set("Kiss Anna")
    d = P.open()
    for k in range(6):
        d.new_page(width=595, height=842).insert_text((72, 120), f"oldal {k + 1}",
                                                      fontsize=28)
    sp = os.path.join(TMP, "koteg2.pdf")
    d.save(sp)
    d.close()
    kt._add([sp])
if tab_i == 3:                                  # Eszközök: Arckép elhelyezés
    app.show(app.tabs["Arckép elhelyezés"])
if tab_i == 5:                                  # Eszközök: Szerkesztés, mező módban
    d = P.open()
    pg = d.new_page(width=595, height=842)
    sh = pg.new_shape()
    for y in (100, 120, 140, 160):
        sh.draw_rect(P.Rect(50, y - 0.25, 450, y + 0.25))
    for x in (50, 200, 450):
        sh.draw_rect(P.Rect(x - 0.25, 100, x + 0.25, 160))
    sh.finish(color=None, fill=(0, 0, 0))
    sh.commit()
    for i, t in enumerate(("Vezetéknév", "Utónév", "Születési hely")):
        pm.add_text(pg, (55, 114 + 20 * i), t, P.Font("helv"), 10)
    for i, n in enumerate(("surname", "forename",
                           "{place_of_birth_locality}, {place_of_birth_country}")):
        pm.add_field(pg, P.Rect(200, 100 + 20 * i, 450, 120 + 20 * i), n)
    sp = os.path.join(TMP, "sablon.pdf")
    d.save(sp)
    d.close()
    ed = app.tabs["Szerkesztés"]
    app.show(ed)
    app.update()
    ed.open_file(sp)
    ed.mode.set("field")
    ed._mode_changed()
if tab_i == 6:                                  # Szerkesztés: Bekezdés formázása
    d = P.open()
    pg = d.new_page(width=595, height=842)
    FN, FB = pm.edit_font("Calibri"), pm.edit_font("Calibri", True)
    pm.add_text(pg, (60, 100), "NYILATKOZAT A SZÁLLÁSHELY VÁLTOZATLANSÁGÁRÓL", FB, 12)
    PAR = ("Alulírott munkavállaló kijelentem, hogy a bejelentett magyarországi "
           "szálláshelyem a kérelem benyújtása óta változatlan maradt, és az ott "
           "megadott adataim a valóságnak minden tekintetben megfelelnek. A "
           "szálláshely címe, a befogadó nyilatkozata és a bérleti jogviszony "
           "időtartama a benyújtott iratokkal egyezik.").split()
    wd = [FN.text_length(w, 10.5) for w in PAR]
    spw = FN.text_length(" ", 10.5)
    for r, row in enumerate(pm.wrap_words(wd, spw, 460.0)):
        for i, x in zip(row, pm.line_positions([wd[i] for i in row], 60.0, 520.0,
                                               spw, "left")):
            pm.add_text(pg, (x, 150 + r * 14), PAR[i], FN, 10.5)
    sp = os.path.join(TMP, "nyilatkozat.pdf")
    d.save(sp)
    d.close()
    ed = app.tabs["Szerkesztés"]
    app.show(ed)
    app.update()
    ed.open_file(sp)
    ed.mode.set("para")
    ed._mode_changed()
    app.update()
    ed._para_click(ed.doc[0], 200, 149)         # a bekezdés kijelölve, kerettel
if tab_i == 4:                                  # dialógus: Ellenőrzés
    app.show(app.tabs["Áttekintő"])
    app.update()
    app.tabs["Áttekintő"]._open_audit()
app.update()
import time as _t                                 # a késleltetett újrarajzolások
_end = _t.time() + 0.8                            # (debounce) is fussanak le
while _t.time() < _end:
    app.update()
    _t.sleep(0.01)


def shot(path, win=None):
    """Az ablak tartalma PNG-be (PrintWindow, PW_RENDERFULLCONTENT)."""
    hwnd = int((win or app).wm_frame(), 16)
    u, g = ctypes.windll.user32, ctypes.windll.gdi32
    rect = ctypes.wintypes.RECT() if hasattr(ctypes, "wintypes") else None
    import ctypes.wintypes as wt
    rect = wt.RECT()
    u.GetWindowRect(hwnd, ctypes.byref(rect))
    w, h = rect.right - rect.left, rect.bottom - rect.top
    hdc = u.GetWindowDC(hwnd)
    mem = g.CreateCompatibleDC(hdc)
    bmp = g.CreateCompatibleBitmap(hdc, w, h)
    g.SelectObject(mem, bmp)
    u.PrintWindow(hwnd, mem, 2)
    class BI(ctypes.Structure):
        _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
                    ("biPlanes", wt.WORD), ("biBitCount", wt.WORD),
                    ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
                    ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG),
                    ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD)]
    bi = BI(ctypes.sizeof(BI), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    buf = ctypes.create_string_buffer(w * h * 4)
    g.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bi), 0)
    raw = bytearray(buf.raw)
    rgb = bytearray(w * h * 3)
    rgb[0::3] = raw[2::4]
    rgb[1::3] = raw[1::4]
    rgb[2::3] = raw[0::4]
    P.Pixmap(P.csRGB, w, h, bytes(rgb), False).save(path)
    g.DeleteObject(bmp)
    g.DeleteDC(mem)
    u.ReleaseDC(hwnd, hdc)


tops = [w for w in app.winfo_children() if w.winfo_class() == "Toplevel"]
for t in app.tabs.values():
    tops += [w for w in t.winfo_children() if w.winfo_class() == "Toplevel"]
shot(out, tops[-1] if (tab_i == 4 and tops) else None)
print("mentve:", out)
app.destroy()
