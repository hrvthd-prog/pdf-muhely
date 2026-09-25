#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Élő GUI-teszt: valódi ablak, valódi egér- és billentyűesemények.
Futtatás: python test/gui.py        (pár másodpercre ablakok nyílnak meg)

Miért kell: a vonszolás, a nagyító, a görgetés, a kijelölés és az iktatás
folyamata az önteszttel (--test) nem mérhető. A fejlesztés során az ilyen
mérések fogták meg a valódi hibákat (felülírásos adatvesztés, header_lines-
vesztés, rendezés oszlophúzáskor). A valódi beállításfájlokhoz nem nyúl: a
szkript mappáját egy ideiglenes mappára irányítja.
"""

import importlib.util
import json
import os
import shutil
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
GYOKER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("pm", os.path.join(GYOKER, "pdf-muhely.py"))
pm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pm)
P = pm.pymupdf

TMP = tempfile.mkdtemp(prefix="pdf-muhely-gui-")
pm.script_dir = lambda: TMP                     # beállítások, doktípusok: ideiglenes helyen
msgs, opened = [], []
for n in ("showinfo", "showwarning", "showerror"):
    setattr(pm.messagebox, n, lambda *a, _n=n, **k: msgs.append((_n, a[0] if a else "")))
pm.messagebox.askyesnocancel = lambda *a, **k: True          # 5 MB fölött: tömörítve
pm.open_path = lambda p: opened.append(p)
res = []


def ck(label, ok, info=""):
    res.append(bool(ok))
    print(("  PASS  " if ok else "  FAIL  ") + label + (f"   -> {info}" if info != "" else ""))


def mkdir(*p):
    d = os.path.join(*p)
    os.makedirs(d, exist_ok=True)
    return d


def empty_pdf(path):
    d = P.open()
    d.new_page()
    d.save(path)
    d.close()


def noisy_jpeg_bytes(w, h, q=95):
    return P.Pixmap(P.csRGB, w, h, os.urandom(w * h * 3), False).tobytes("jpeg", jpg_quality=q)


def noisy_pdf(path, pages=2):
    d = P.open()
    for _ in range(pages):
        pg = d.new_page(width=595, height=842)
        pg.insert_image(pg.rect, stream=noisy_jpeg_bytes(1800, 2500))
    d.save(path)
    d.close()


# ── adatok ──────────────────────────────────────────────────────────────────
root = mkdir(TMP, "gyujto")
for i in range(40):
    mkdir(root, f"Dolgozó {i:02d}")
anna = mkdir(root, "Kiss Anna")
for fn in ("Kiss Anna Útlevél.pdf", "Kiss Anna Útlevél (2).pdf"):
    empty_pdf(os.path.join(anna, fn))
bela = mkdir(root, "Nagy Béla")
big_pdf = os.path.join(bela, "Nagy Béla Útlevél.pdf")
noisy_pdf(big_pdf)

imgs = mkdir(TMP, "kepek")
for i in range(6):                  # szélesség = azonosító: 400, 500, … 900 px
    w = 400 + 100 * i
    with open(os.path.join(imgs, f"K{i}.jpg"), "wb") as f:
        f.write(P.Pixmap(P.csRGB, w, 300, bytes([40 * i]) * (w * 300 * 3), False).tobytes("jpeg"))
with open(os.path.join(imgs, "K9.jpg"), "w") as f:
    f.write("nem kép")
big_imgs = mkdir(TMP, "nagykepek")
for i in range(4):
    with open(os.path.join(big_imgs, f"N{i}.jpg"), "wb") as f:
        f.write(noisy_jpeg_bytes(2000, 2800, 90))

app = pm.App()
app.geometry("1200x840")
app.folder.set(root)
app.refresh_all()


def pump(t=0.15):
    end = time.time() + t
    while time.time() < end:
        app.update()
        time.sleep(0.01)


def wait(cond, t=90):
    end = time.time() + t
    while time.time() < end and not cond():
        pump(0.05)
    return cond()


def dbl(c, x, y):
    for _ in range(2):
        c.event_generate("<ButtonPress-1>", x=x, y=y, time=5000)
        c.event_generate("<ButtonRelease-1>", x=x, y=y, time=5001)
    pump(0.4)


att, ikt, kt = app.tabs["Áttekintő"], app.tabs["Iktató"], app.tabs["Képek → PDF"]
try:
    # ════════════════════════════ Áttekintő ════════════════════════════════
    print("ÁTTEKINTŐ")
    app.nb.select(att)
    pump(0.6)
    cd, cn = att.c_data, att.c_name

    def hdr_y(c):
        return min(c.bbox(i)[1] for i in c.find_withtag("hdr"))

    off0 = hdr_y(cd) - cd.canvasy(0)
    for _ in range(15):
        cd.event_generate("<MouseWheel>", delta=-120, x=200, y=200)
    pump(0.2)
    ck("rögzített fejléc: görgetés után is felül", cd.canvasy(0) > 100 and
       hdr_y(cd) - cd.canvasy(0) == off0 and "hdr" in cd.gettags(cd.find_all()[-1]))
    cols = att._cols()
    xs, _ = att._xs(cols)
    cd.event_generate("<Button-1>", x=xs[1] + 20, y=att.hdr_h - 8)
    pump(0.2)
    ck("görgetve a fejlécre kattintás rendez", att.sort_col == cols[1].id, att.sort_col)
    att.sort_col = "name"
    att._apply()
    pump(0.2)
    edge = xs[0] + cols[0].width
    cd.event_generate("<ButtonPress-1>", x=edge - 1, y=att.hdr_h - 8)
    cd.event_generate("<ButtonRelease-1>", x=edge - 1, y=att.hdr_h - 8)
    pump(0.1)
    ck("oszlophatár megfogása nem rendez", att.sort_col == "name", att.sort_col)
    n0 = len(opened)
    cd.event_generate("<Button-1>", x=xs[1] + 20, y=att.hdr_h + 30)
    pump(0.2)
    ck("egy kattintás kijelöl, nem nyit meg", att.sel is not None and len(opened) == n0)
    dbl(cn, 40, att.hdr_h + 30)             # névoszlop: a dolgozó mappája nyílik meg
    ck("dupla kattintás megnyit", len(opened) == n0 + 1, opened[n0:])

    for r in att.rules:                    # széles oszlopok: legyen mit görgetni
        r.width = 200
    att._redraw()
    cols = att._cols()
    cd.xview_moveto(0)
    pump(0.1)
    cd.event_generate("<Shift-MouseWheel>", delta=-120, x=300, y=200)
    pump(0.1)
    ck("Shift+görgő / touchpad: vízszintes görgetés", cd.xview()[0] > 0, cd.xview())
    cd.focus_set()
    att._goto(0, 1)
    for _ in range(len(cols) + 3):
        att._move_cur(0, 1)
    pump(0.2)
    (cx, cw), _ = att._col_span(att.cur_c - 1)
    ck("→ billentyű: a kurzor oszlopa látszik",
       cd.canvasx(0) - 1 <= cx and cx + cw <= cd.canvasx(0) + cd.winfo_width() + 1)

    texts = {cd.itemcget(i, "text") for i in cd.find_all() if cd.type(i) == "text"}
    ck("két útlevél-PDF: „P×2”, 5 MB fölött: „P!”", "P×2" in texts and "P!" in texts,
       sorted(t for t in texts if t.startswith("P")))

    h1 = att.hdr_h
    dlg = pm.SettingsDialog(att, att.settings, att._apply_settings)
    dlg.v_hdrl.set(1)
    dlg._save()
    pump(0.3)
    with open(pm.settings_path(), encoding="utf-8") as f:
        saved = json.load(f)
    ck("„Fejléc sorai” = 1: alacsonyabb fejléc, a JSON-ban is", att.hdr_h < h1 and
       saved["header_lines"] == 1, (h1, att.hdr_h))

    # ════════════════════════════ Iktató ═══════════════════════════════════
    print("IKTATÓ")
    app.geometry("960x680")
    app.nb.select(ikt)
    pump(0.6)
    l, t, r, b = ikt.prev_box
    over = [tr for tr in ikt.tile_rects.values()
            if not (tr[2] <= l or tr[0] >= r or tr[3] <= t or tr[1] >= b)]
    ck("960×680: az előnézet nem fedi a csempéket", not over and r - l > 200 and b - t > 200,
       ikt.prev_box)
    app.geometry("1200x840")
    pump(0.3)

    ikt.types = ikt.types + ["Útlevél"]
    for typ, want in (("Útlevél", ""), ("Előzetes megállapodás", "aláírt")):
        ikt.doc_type.set(typ)
        ikt._type_chosen()
        ck(f"utótag a típusból: {typ} -> „{want}”", ikt.suffix.get() == want, ikt.suffix.get())

    app.goto_iktato("Kiss Anna", "Előzetes megállapodás")
    pump(0.2)
    ck("→ Iktatás: Iktató fül, szűrő, típus, utótag",
       app.active_tab() is ikt and ikt.filter_text.get() == "Kiss Anna" and
       ikt.doc_type.get() == "Előzetes megállapodás" and ikt.suffix.get() == "aláírt")

    size0 = os.path.getsize(big_pdf)
    ikt.queue.clear()
    ikt.doc_type.set("Útlevél")
    ikt._type_chosen()
    ikt._enqueue([big_pdf])
    ikt._ask_collision = lambda name: "overwrite"
    ikt._do_copy("Nagy Béla")
    ck("tömörítés közben foglalt", ikt._busy)
    ikt._undo()
    ck("foglalt állapotban a Visszavonás vár", "várd meg" in ikt.msg.get(), ikt.msg.get())
    wait(lambda: not ikt._busy)
    bak = os.path.join(bela, pm.BACKUP_DIR, "Nagy Béla Útlevél.pdf")
    ck("helyben tömörítve 5 MB alá", os.path.getsize(big_pdf) <= pm.UPLOAD_LIMIT < size0,
       f"{pm.mb(size0)} -> {pm.mb(os.path.getsize(big_pdf))}")
    ck("az eredeti a .eredeti\\ mappában", os.path.exists(bak) and os.path.getsize(bak) == size0)
    app.nb.select(att)
    pump(0.4)
    rb = next(x for x in att.rows if x.name == "Nagy Béla")
    ck("az Áttekintő nem látja a .eredeti mappát", len(rb.docs["utlevel"].pdf) == 1 and not rb.big,
       rb.docs["utlevel"].pdf)
    ikt._undo()
    ck("Visszavonás: az eredeti visszaállt", os.path.getsize(big_pdf) == size0 and
       not os.path.exists(bak), ikt.msg.get())

    # ═══════════════════════════ Képek → PDF ═══════════════════════════════
    print("KÉPEK → PDF")
    app.nb.select(kt)
    pump(0.3)
    kt._add([os.path.join(imgs, f) for f in sorted(os.listdir(imgs))])
    wait(lambda: kt._thumb_job is None, 20)
    ck("bélyegképek; a hibás kép megjelölve", sum(1 for it in kt.items if it.bad) == 1 and
       all(it.thumb for it in kt.items if not it.bad), kt.info.get())
    c = kt.canvas

    def at(i, mod=""):
        x, y = kt._xy(i)
        c.event_generate(f"<{mod}ButtonPress-1>" if mod else "<ButtonPress-1>", x=x + 50, y=y + 50)
        c.event_generate("<ButtonRelease-1>", x=x + 50, y=y + 50)
        pump(0.1)

    def idx():
        return sorted(kt.items.index(it) for it in kt.sel)

    at(2)
    at(4, "Shift-")
    at(0, "Control-")
    ck("kijelölés: sima + Shift-tartomány + Ctrl", idx() == [0, 2, 3, 4], idx())
    kt.fit_a4.set(False)
    out = os.path.join(TMP, "kijelolt.pdf")
    pm.filedialog.asksaveasfilename = lambda **k: out
    kt._run(only_sel=True)
    wait(lambda: kt._b is None, 60)
    d = P.open(out)
    widths = [round(p.rect.width * 200 / 72) for p in d]
    d.close()
    ck("külön PDF a kijelöltekből, rácssorrendben", widths == [400, 600, 700, 800], widths)
    app.nb.select(kt)
    pump(0.2)
    kt._rotate(90)
    ck("forgatás minden kijelöltre", [it.rot for it in kt.items][:6] == [90, 0, 90, 90, 90, 0])

    x0, y0 = kt._xy(0)
    x2, _ = kt._xy(2)
    names = [os.path.basename(it.path) for it in kt.items]
    c.event_generate("<ButtonPress-1>", x=x0 + 40, y=y0 + 40)
    for k in range(1, 11):
        c.event_generate("<B1-Motion>", x=int(x0 + 40 + (x2 + pm.CELL_W - 20 - x0 - 40) * k / 10),
                         y=y0 + 40)
        pump(0.02)
    c.event_generate("<ButtonRelease-1>", x=x2 + pm.CELL_W - 20, y=y0 + 40)
    pump(0.2)
    now = [os.path.basename(it.path) for it in kt.items]
    ck("vonszolás: az 1. kép a 3. mögé", now[:3] == names[1:3] + names[:1], now[:4])

    print("NAGYÍTÓ")
    kt._add([os.path.join(big_imgs, "N0.jpg"), os.path.join(big_imgs, "N1.jpg")])
    wait(lambda: kt._thumb_job is None, 20)
    nb = len(kt.items) - 2                  # nagy kép: a natív felbontásig van hova nagyítani
    dbl(c, kt._xy(nb)[0] + 50, kt._xy(nb)[1] + 50)
    v = kt.viewer
    ck("dupla kattintás: nagyító a kattintott képpel", v is not None and v.item is kt.items[nb])
    cw_, ch_ = v.c.winfo_width(), v.c.winfo_height()
    ex, ey = cw_ // 3, ch_ // 4
    fx0 = v.c.canvasx(ex) / v.W
    for _ in range(4):
        v.c.event_generate("<MouseWheel>", delta=120, x=ex, y=ey)
    pump(0.5)
    ck("görgő: nagyít, a kurzor alatti pont helyben", v.zk and abs(v.zk - 1.15 ** 4) < 0.01 and
       abs(v.c.canvasx(ex) / v.W - fx0) < 0.02, (v.zk, v.title()))
    zk = v.zk
    v.event_generate("<Right>")
    pump(0.3)
    ck("→: következő kép, a nagyítás marad, a kijelölés követi",
       v.item is kt.items[nb + 1] and v.zk == zk and kt.sel == {kt.items[nb + 1]})
    v.event_generate("<Escape>")
    pump(0.2)
    ck("Esc: bezár", kt.viewer is None)

    n_before = len(kt.items)
    at(0)
    c.event_generate("<Delete>")
    pump(0.1)
    ck("Delete: a kijelölt törlődik", len(kt.items) == n_before - 1)

    print("TÖMÖRÍTÉS KÉPEKBŐL")
    kt._clear()
    kt.fit_a4.set(True)
    kt._add([os.path.join(big_imgs, f) for f in sorted(os.listdir(big_imgs))])
    wait(lambda: kt._thumb_job is None, 20)
    out2 = os.path.join(TMP, "nagy.pdf")
    pm.filedialog.asksaveasfilename = lambda **k: out2
    kt._run()
    ck("feldolgozás közben a gombok tiltva", all(b.instate(["disabled"]) for b in kt.btns))
    wait(lambda: kt._b is None, 120)
    log = kt.log.get("1.0", "end")
    ck("5 MB fölött lépcsőzetes tömörítés, a kész PDF alatta",
       "lépcső:" in log and os.path.getsize(out2) <= pm.UPLOAD_LIMIT, pm.mb(os.path.getsize(out2)))
    ck("a kész PDF az Iktató várólistáján, az Iktató aktív",
       os.path.abspath(out2) in ikt.queue and app.active_tab() is ikt)
finally:
    app.destroy()
    shutil.rmtree(TMP, ignore_errors=True)

print(f"\n=== GUI: {sum(res)}/{len(res)} sikeres ===")
sys.exit(0 if all(res) else 1)
