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

import csv
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


def find_btn(w, prefix):
    """ttk.Button a dialógusban, felirat-előtag szerint (a gombok Frame-ben élnek)."""
    for c in w.winfo_children():
        if c.winfo_class() == "TButton" and str(c.cget("text")).startswith(prefix):
            return c
        got = find_btn(c, prefix)
        if got is not None:
            return got
    return None


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
# A dolgozói mappa szerkezete: 01_Elokeszitett / 02_Feltoltheto
anna = mkdir(root, "Kiss Anna")
anna_up = mkdir(anna, pm.DIR_UP)
anna_prep = mkdir(anna, pm.DIR_PREP)
for fn in ("Kiss Anna Útlevél.pdf", "Kiss Anna Útlevél (2).pdf"):
    empty_pdf(os.path.join(anna_up, fn))
bela = mkdir(root, "Nagy Béla")
bela_up = mkdir(bela, pm.DIR_UP)
mkdir(bela, pm.DIR_PREP)
# A helyben tömörítés útja: a forrás MAGA a cél — ezért a 02-ben él.
big_pdf = os.path.join(bela_up, "Nagy Béla Útlevél.pdf")
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


att, ikt, kt = app.tabs["Áttekintő"], app.tabs["Iktató"], app.tabs["Összeállító"]
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
    ck("két útlevél-PDF a feltölthetőben: „F×2”, 5 MB fölött: „F!”",
       "F×2" in texts and "F!" in texts,
       sorted(t for t in texts if t.startswith(("F", "E", "~"))))

    # Rendezés: előnézet a besorolatlan fájlokról, mozgatás nélkül is bezárható
    lapos = mkdir(root, "Lapos Lajos")
    empty_pdf(os.path.join(lapos, "Lapos Lajos Útlevél aláírt.pdf"))
    att.refresh()
    pump(0.2)
    rl = next(x for x in att.rows if x.name == "Lapos Lajos")
    ck("a lapos szerkezet besorolatlan és nem beadható",
       not rl.beadhato and len(rl.unsorted) == 1, (rl.beadhato, rl.unsorted))
    att._open_tidy()
    pump(0.2)
    tidy = [w for w in att.winfo_children() if w.winfo_class() == "Toplevel"][-1]
    body = [w for w in tidy.winfo_children() if w.winfo_class() == "Text"]
    ck("a Rendezés előnézete felsorolja a mozgatandó fájlt",
       bool(body) and "Lapos Lajos Útlevél aláírt.pdf" in body[0].get("1.0", "end"),
       body[0].get("1.0", "end")[:200] if body else "nincs Text")
    tidy.destroy()
    pump(0.2)
    ck("mozgatás nélkül semmi nem változott",
       os.path.isfile(os.path.join(lapos, "Lapos Lajos Útlevél aláírt.pdf")))

    # Munkamappa-kapu: egy nem dolgozói almappa képeit NEM mozgatja
    idegen = mkdir(root, "nyaralas 2026")
    empty_pdf(os.path.join(idegen, "nem-irat.pdf"))
    open(os.path.join(idegen, "IMG_0001.jpg"), "wb").close()
    att.refresh()
    pump(0.2)
    att._open_tidy()
    pump(0.2)
    tidy2 = [w for w in att.winfo_children() if w.winfo_class() == "Toplevel"][-1]
    labels2 = " ".join(w.cget("text") for w in tidy2.winfo_children()
                       if w.winfo_class() == "TLabel")
    body2 = [w for w in tidy2.winfo_children() if w.winfo_class() == "Text"]
    ck("a kapu jelzi a kihagyott, nem dolgozói mappát",
       "nyaralas 2026" in labels2 and "kihagyok" in labels2, labels2[:200])
    ck("a kihagyott mappa nincs a mozgatási előnézetben",
       bool(body2) and "IMG_0001.jpg" not in body2[0].get("1.0", "end"))
    tidy2.destroy()
    pump(0.2)
    ck("a kép a helyén maradt",
       os.path.isfile(os.path.join(idegen, "IMG_0001.jpg")))
    shutil.rmtree(idegen)
    done, errs = pm.migracio_vegrehajt(lapos, pm.migracio_terv(lapos, att.rules))
    ck("a rendezés a 02-be teszi az aláírt iratot",
       (done, errs) == (1, []) and
       os.path.isfile(os.path.join(lapos, pm.DIR_UP, "Lapos Lajos Útlevél aláírt.pdf")),
       (done, errs))
    att.refresh()
    pump(0.2)
    rl = next(x for x in att.rows if x.name == "Lapos Lajos")
    ck("rendezés után beadható lenne, ha minden irat megvolna",
       rl.docs["utlevel"].cell == "F" and not rl.unsorted, rl.docs["utlevel"].cell)

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

    # Arckép-jelölő: csak a fotóigényes típusnál él, és típusváltáskor kiürül
    ck("a jelölő tiltva az útlevélnél",
       ikt.arckep_cb.instate(["disabled"]) and not ikt.arckep_kesz.get())
    ikt.doc_type.set("Tart_eng_formanyomtatvány")
    ikt._type_chosen()
    ck("a jelölő él a formanyomtatványnál", ikt.arckep_cb.instate(["!disabled"]))
    ck("fotó nélkül az előkészítettbe megy",
       ikt.name_preview.get().startswith(pm.DIR_PREP), ikt.name_preview.get())
    ikt.arckep_kesz.set(True)
    ikt._update_name()
    ck("fotóval a feltölthetőbe megy",
       ikt.name_preview.get().startswith(pm.DIR_UP), ikt.name_preview.get())
    ikt.doc_type.set("Útlevél")
    ikt._type_chosen()
    ck("típusváltáskor a jelölő kiürül, nem ragad be",
       not ikt.arckep_kesz.get() and ikt.arckep_cb.instate(["disabled"]))

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
    sb = pm.read_stamp(big_pdf)
    ck("a tömörített példány is bélyeget kap (dolgozó + típus)",
       (sb.get("dolgozo"), sb.get("tipus"), sb.get("hely")) ==
       ("Nagy Béla", "Útlevél", pm.DIR_UP), sb)
    ck("az eredeti a .eredeti\\ mappában", os.path.exists(bak) and os.path.getsize(bak) == size0)
    app.nb.select(att)
    pump(0.4)
    rb = next(x for x in att.rows if x.name == "Nagy Béla")
    ck("az Áttekintő nem látja a .eredeti mappát", len(rb.docs["utlevel"].pdf) == 1 and not rb.big,
       rb.docs["utlevel"].pdf)
    ikt._undo()
    ck("Visszavonás: az eredeti visszaállt", os.path.getsize(big_pdf) == size0 and
       not os.path.exists(bak), ikt.msg.get())

    # Sima (nem tömörítő) iktatás: a bélyeg növekményes függelék, a forrás bájtjai
    # a célban is megvannak — a bájtazonos másolás helyére ez az ellenőrzés lép.
    kicsi = os.path.join(TMP, "kicsi.pdf")
    empty_pdf(kicsi)
    ikt.queue.clear()
    ikt.doc_type.set("Szálláshely-igazolás")
    ikt._type_chosen()
    ikt._enqueue([kicsi])
    ikt._do_copy("Kiss Anna")
    pump(0.3)
    cel = os.path.join(anna_up, "Kiss Anna Szálláshely-igazolás.pdf")
    sk = pm.read_stamp(cel)
    ck("sima iktatás: bélyeg és a forrás bájtjai a célban",
       (sk.get("dolgozo"), sk.get("tipus")) == ("Kiss Anna", "Szálláshely-igazolás") and
       open(cel, "rb").read().startswith(open(kicsi, "rb").read()) and ikt.stamped,
       sk)
    # Átnevezve is felismeri: a mátrix a bélyegből sorol be
    atnevezve = os.path.join(anna_up, "IMG_20260101_0001.pdf")
    os.replace(cel, atnevezve)
    app.show(att)
    att.refresh()
    pump(0.4)
    ra = next(x for x in att.rows if x.name == "Kiss Anna")
    ck("átnevezett iktatott irat: a bélyeg alapján a helyén számít",
       ra.docs["szalli"].cell == "F" and
       ra.by_stamp == [os.path.join(pm.DIR_UP, "IMG_20260101_0001.pdf")],
       (ra.docs["szalli"].cell, ra.by_stamp))
    os.remove(atnevezve)

    # ═══════════════════════════ Összeállító ═══════════════════════════════
    print("ÖSSZEÁLLÍTÓ: KÉPEK")
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
    v.event_generate("<Left>")
    pump(0.2)
    v.event_generate("<Key>", keysym="1")
    pump(0.3)
    ck("nagyítóban 1: a látott kép címkét kap, a nagyító továbblapoz",
       kt.items[nb].doc and kt.items[nb].doc.doc_type == kt.palette[0][0] and
       v.item is kt.items[nb + 1], (kt.items[nb].doc, v.title()))
    v.event_generate("<Escape>")
    pump(0.2)
    ck("Esc: bezár", kt.viewer is None)

    n_before = len(kt.items)
    at(0)
    c.event_generate("<Delete>")
    pump(0.1)
    ck("Delete: a kijelölt törlődik", len(kt.items) == n_before - 1)

    print("ARCKÉP ELHELYEZÉS")
    pl = app.tabs["Arckép elhelyezés"]
    app.show(pl)
    pump(0.2)
    ck("az Eszközök alfülére váltás: a gyorsbillentyűk is ide szólnak",
       app.active_tab() is pl, app.active_tab())
    arc = os.path.join(TMP, "arc.png")              # álló kép, felső negyede piros
    P.Pixmap(P.csRGB, 100, 200, bytes((255, 0, 0) * 5000 + (0, 0, 255) * 15000), False).save(arc)

    def red_side(pix, x0, y0, x1, y1):             # a doboz melyik szélén piros a kép?
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        pr = {"fent": (mx, y0 + (y1 - y0) * .1), "jobb": (x0 + (x1 - x0) * .9, my),
              "lent": (mx, y0 + (y1 - y0) * .9), "bal": (x0 + (x1 - x0) * .1, my)}
        return [k for k, (x, y) in pr.items()
                if pix.pixel(int(x), int(y))[0] > 200 and pix.pixel(int(x), int(y))[2] < 80]

    shown = []                                      # az előnézetbe ténylegesen rajzolt pixmap
    tkimg0 = pm.tkimg
    pm.tkimg = lambda pix, fmt: (shown.append(pix), tkimg0(pix, fmt))[1]
    got = []
    for page_rot in (0, 90):
        lap = os.path.join(TMP, f"lap{page_rot}.pdf")
        d = P.open()
        d.new_page(width=595, height=842).set_rotation(page_rot)
        d.save(lap)
        d.close()
        pl._open_pdf(lap)
        pl._load_img(arc)
        pump(0.2)
        for ang in (90, -90, 180):
            pl.angle.set(ang)
            pl._render_photo()
            prev = red_side(shown[-1], 0, 0, pl.pw_px, pl.ph_px)
            kesz = os.path.join(TMP, "kesz.pdf")
            pl._write(kesz)
            d = P.open(kesz)
            bw, bh = pl.pw_px / pl.zoom, pl.ph_px / pl.zoom
            outp = red_side(d[0].get_pixmap(), pl.cx_pt - bw / 2, pl.cy_pt - bh / 2,
                            pl.cx_pt + bw / 2, pl.cy_pt + bh / 2)
            d.close()
            got.append((page_rot, ang, prev, outp))
    pm.tkimg = tkimg0
    ck("forgatott arckép: a mentett PDF = előnézet (lapforgatással is)",
       all(p == o and len(p) == 1 for _, _, p, o in got), got)

    # Körülvágás: a felső negyed (piros) marad meg
    pl._load_img(arc)
    pump(0.2)
    before = pl.imgpdf[0].rect
    cd = pm.CropDialog(pl, arc, None, pl._apply_crop)
    pump(0.2)
    cdc = cd.canvas
    cdc.event_generate("<ButtonPress-1>", x=2, y=2)
    cdc.event_generate("<B1-Motion>", x=cd.w - 2, y=int(cd.h * 0.2))
    pump(0.2)
    ck("vonszolás: a Körülvág gomb él", str(cd.btn["state"]) == "normal", cd.btn["state"])
    cd._apply()
    pump(0.2)
    after = pl.imgpdf[0].rect
    pcrop = pl.imgpdf[0].get_pixmap()
    ck("körülvágás: a kép lapja szűkül, a megtartott (piros) rész marad",
       after.height < before.height / 2 and
       pcrop.pixel(pcrop.width // 2, pcrop.height // 2)[0] > 200 and
       "körülvágva" in pl.img_lbl.cget("text"),
       (before, after, pcrop.pixel(pcrop.width // 2, pcrop.height // 2)))
    kesz3 = os.path.join(TMP, "vagott.pdf")
    pl._write(kesz3)
    d = P.open(kesz3)
    ck("a vágott arckép a mentett PDF-ben is vágott",
       abs(pl.pw_px / pl.ph_px - after.width / after.height) < 0.05, (pl.pw_px, pl.ph_px))
    d.close()
    # Fényerő/kontraszt: élő előnézet, majd alkalmazás vágás nélkül is
    cdl = pm.CropDialog(pl, arc, None, pl._apply_crop)
    pump(0.2)
    ck("szintezés nélkül az Alkalmaz tiltva", str(cdl.btn["state"]) == "disabled",
       cdl.btn["state"])
    cdl.br.set(60)
    cdl._levels_changed()
    pump(0.2)
    ck("fényerő-csúszka: az Alkalmaz él", str(cdl.btn["state"]) == "normal")
    cdl._apply()
    pump(0.3)
    piros = pl.imgpdf[0].get_pixmap().pixel(10, 10)
    ck("a szintezett arckép világosabb, és a címke jelzi",
       pl.img_levels == (60, 0) and piros[2] > 60 and
       "szintezve" in pl.img_lbl.cget("text"), (pl.img_levels, piros))
    pl._load_img(arc)
    pump(0.2)
    ck("új kép betöltése törli a szintezést", pl.img_levels is None)

    cd2 = pm.CropDialog(pl, arc, pl.img_crop, pl._apply_crop)
    pump(0.1)
    cd2._done(None)                                 # „Teljes kép”: a vágás visszavonva
    pump(0.2)
    ck("Teljes kép: a vágás visszavonható",
       pl.img_crop is None and pl.imgpdf[0].rect == before, pl.imgpdf[0].rect)
    pl._load_img(arc)
    pump(0.2)

    # Iktatás a feltölthetőbe: a kör zárása 01 -> fotó -> 02
    pl.set_folder(anna)
    ck("a dolgozó mappáját kapva a szülő lesz a munkamappa, a név kitöltve",
       pl.parent_dir == root and pl.who == "Kiss Anna", (pl.parent_dir, pl.who))
    ck("alapértelmezett típus a fotóigényes nyomtatvány",
       pl.doc_type.get() == "Tart_eng_formanyomtatvány", pl.doc_type.get())
    pl.angle.set(0)
    pl._render_photo()
    pl._iktat()
    pump(0.2)
    kesz2 = os.path.join(anna_up, "Kiss Anna Tart_eng_formanyomtatvány aláírt.pdf")
    ck("az arcképes irat a feltölthető mappába került", os.path.isfile(kesz2), kesz2)
    sp = pm.read_stamp(kesz2)
    ck("az arcképes irat bélyeget kap",
       (sp.get("dolgozo"), sp.get("tipus")) == ("Kiss Anna", "Tart_eng_formanyomtatvány"),
       sp)
    with open(os.path.join(root, pm.LOG_NAME), encoding="utf-8-sig") as f:
        last = list(csv.reader(f, delimiter=";"))[-1]
    ck("naplósor az arckép-iktatásról",
       last[2] == os.path.join("Kiss Anna", pm.DIR_UP) and last[5] == "OK", last)
    os.remove(kesz2)

    print("OLDAL MINT ELEM")
    ketlap = os.path.join(TMP, "ketlap.pdf")         # 1. oldal négyzet, 2. oldal fekvő 2:1
    d = P.open()
    d.new_page(width=300, height=300)
    d.new_page(width=600, height=300)
    d.save(ketlap)
    d.close()
    it = pm.PageItem(ketlap, page=1)
    kt.items.append(it)
    kt._thumbs()
    wait(lambda: kt._thumb_job is None, 20)
    ck("bélyegkép a megadott oldalról", it.thumb and
       (it.thumb.width(), it.thumb.height()) == (pm.THUMB, pm.THUMB // 2),
       it.thumb and (it.thumb.width(), it.thumb.height()))
    v = kt.viewer = pm.PageViewer(kt)
    v.show(it)
    pump(0.3)
    ck("a nagyító is azt az oldalt mutatja", abs(v.photo.width() / v.photo.height() - 2) < 0.02,
       (v.photo.width(), v.photo.height()))
    v.close()

    print("ÖSSZEÁLLÍTÓ: KÖTEG")
    app.nb.select(kt)
    pump(0.3)
    kt._clear()
    koteg = os.path.join(TMP, "koteg.pdf")               # 6 oldal, „oldal N” szöveggel
    d = P.open()
    for k in range(6):
        d.new_page(width=595, height=842).insert_text((72, 100), f"oldal {k + 1}", fontsize=30)
    d.save(koteg)
    d.close()
    elo = os.path.join(anna_up, "Kiss Anna Előzetes megállapodás aláírt.pdf")
    empty_pdf(elo)                                        # ütközni fog
    kt._add([koteg])
    wait(lambda: kt._thumb_job is None, 20)
    ck("PDF-köteg: oldalanként egy bélyegkép",
       [it.page for it in kt.items] == list(range(6)) and all(it.thumb for it in kt.items))
    kt.who_text.set("kiss")
    ck("dolgozó a mező részletéből", kt.who == "Kiss Anna", kt.who_msg.get())
    kt.who_text.set("dolgozó 1")          # kétes részlet: 11 találat
    kt._fill_who()
    szukitett = list(kt.who_cb.cget("values"))
    kt.who_text.set("Kiss Anna")          # már EGY dolgozót jelöl
    kt._fill_who()
    ck("a legördülő kiválasztás után is mind a nevet adja (nem kell visszatörölni)",
       len(kt.who_cb.cget("values")) == len(kt.dirs) > 11,
       (len(kt.who_cb.cget("values")), len(kt.dirs)))
    ck("kétes részletnél viszont szűkít",
       len(szukitett) == 10 and all(x.startswith("Dolgozó 1") for x in szukitett),
       szukitett)
    kt.who_text.set("kiss anna")
    ck("a forrásmappa megjegyezve", pm.recall("mellekletek") == os.path.dirname(koteg),
       pm.recall("mellekletek"))

    def key(k, w=None):
        w = w or c
        w.focus_force()
        w.event_generate("<Key>", keysym=k)
        pump(0.1)

    def labels():
        return [kt._look(it.doc.doc_type)[0] if it.doc else None for it in kt.items]

    at(0)
    at(1, "Shift-")
    key("1")
    ck("szám: a kijelöltek címkét kapnak, a kijelölés továbblép",
       labels()[:2] == ["Forma", "Forma"] and kt.sel == {kt.items[2]}, (labels(), idx()))
    for k in "226":
        key(k)
    ck("billentyűvel végig a kötegen: 2 2 6",
       labels() == ["Forma", "Forma", "Előz", "Előz", "Útl", None], labels())
    ck("kimenet: 3 irat, a meglévő jelölve, 1 oldal címke nélkül",
       len(kt.tree.get_children()) == 3 and kt.tree.set("1", "note") == "⚠ létezik" and
       kt.out_info.get().startswith("1 oldal"), (kt.tree.get_children(), kt.out_info.get()))

    x0, y0 = kt._xy(0)
    x1, _ = kt._xy(1)
    c.event_generate("<ButtonPress-1>", x=x1 + 60, y=y0 + 60)
    for k in range(1, 11):
        c.event_generate("<B1-Motion>", x=int(x1 + 60 - (x1 + 50 - x0) * k / 10), y=y0 + 60)
        pump(0.02)
    c.event_generate("<ButtonRelease-1>", x=x0 + 10, y=y0 + 60)
    pump(0.2)
    ck("vonszolás: az iraton belüli sorrend is változik", [it.page for it in kt.items[:2]] == [1, 0])
    at(4)
    kt._rotate(90)
    kt.tree.selection_set("2")                            # Útlevél: saját utótag
    pump(0.2)
    kt.suffix.set("másolat")
    pump(0.1)
    ck("a kimeneti sorra kattintva az irat oldalai kijelölődnek, az utótag szerkeszthető",
       kt.sel == {kt.items[4]} and kt.tree.set("2", "name") == "Útlevél másolat")

    app.geometry("960x680")
    pump(0.6)
    bg = kt.btn_go
    ck("960×680: az Iktatás gomb teljesen látszik",
       bg.winfo_ismapped() and bg.winfo_rooty() + bg.winfo_height() <= app.winfo_rooty() +
       app.winfo_height(), (bg.winfo_rooty() + bg.winfo_height(), app.winfo_rooty() + app.winfo_height()))
    app.geometry("1200x840")
    pump(0.3)

    asked = []
    kt._ask_batch = lambda jobs, free: (asked.append(
        ([j["name"] for j in jobs if j["exists"]], free)), "new")[1]
    kt._iktat()
    ck("iktatás közben a gomb tiltva", kt.btn_go.instate(["disabled"]))
    wait(lambda: kt._b is None, 60)
    ck("összegzés: az ütközés és a kimaradó oldal",
       asked == [(["Kiss Anna Előzetes megállapodás aláírt.pdf"], 1)], asked)

    def pdf_info(fn, sub=None):
        d = P.open(os.path.join(anna, sub or pm.DIR_UP, fn))
        r = [pg.get_text().strip() for pg in d], [pg.rotation for pg in d]
        d.close()
        return r

    forma, elo2, utl = ("Kiss Anna Tart_eng_formanyomtatvány aláírt.pdf",
                        "Kiss Anna Előzetes megállapodás aláírt (2).pdf", "Kiss Anna Útlevél másolat.pdf")
    # A formanyomtatványra arcképet is kell helyezni, a jelölő nincs bepipálva:
    # ezért NEM a feltölthetőbe, hanem az előkészítettbe kerül.
    ck("Forma (fotó nélkül) az előkészítettbe, a vonszolt sorrendben",
       pdf_info(forma, pm.DIR_PREP)[0] == ["oldal 2", "oldal 1"],
       pdf_info(forma, pm.DIR_PREP))
    sf = pm.read_stamp(os.path.join(anna, pm.DIR_PREP, forma))
    ck("Összeállító: iratonkénti bélyeg a cél alkönyvtárával",
       (sf.get("dolgozo"), sf.get("tipus"), sf.get("hely")) ==
       ("Kiss Anna", "Tart_eng_formanyomtatvány", pm.DIR_PREP), sf)
    ck("ütközés: új néven (2), a régi érintetlen",
       pdf_info(elo2)[0] == ["oldal 3", "oldal 4"] and pdf_info(os.path.basename(elo))[0] == [""])
    ck("Útlevél: a szerkesztett utótaggal, elforgatva (/Rotate 90)",
       pdf_info(utl) == (["oldal 5"], [90]), pdf_info(utl))
    with open(os.path.join(root, pm.LOG_NAME), encoding="utf-8-sig") as f:
        rows = list(csv.reader(f, delimiter=";"))[-3:]
    ck("napló: iratonként egy sor, a forrás oldalakkal és az alkönyvtárral",
       [r[5] for r in rows] == ["OK", "UTKOZES-UJ NEV", "OK"] and
       rows[0][1].endswith("koteg.pdf [2,1]") and
       rows[0][2] == os.path.join("Kiss Anna", pm.DIR_PREP), rows)
    ck("az iktatott oldalak kikerültek, a címke nélküli maradt", [it.page for it in kt.items] == [5])

    kt._undo()
    ck("visszavonás: a köteg fájljai törlődnek, a régi Előzetes megmarad",
       not os.path.exists(os.path.join(anna, pm.DIR_PREP, forma)) and
       not any(os.path.exists(os.path.join(anna_up, f)) for f in (elo2, utl)) and
       os.path.exists(elo))
    ck("visszavonás: az oldalak a helyükre kerülnek, címkével",
       [it.page for it in kt.items] == [1, 0, 2, 3, 4, 5] and labels()[0] == "Forma",
       [it.page for it in kt.items])

    kt._ask_batch = lambda jobs, free: "overwrite"
    kt._iktat()
    wait(lambda: kt._b is None, 60)
    ck("felülírás: az új példány a helyén, az előző a .eredeti\\-ben",
       pdf_info(os.path.basename(elo))[0] == ["oldal 3", "oldal 4"] and
       os.path.exists(os.path.join(anna, pm.BACKUP_DIR, os.path.basename(elo))))
    kt._undo()
    ck("visszavonás felülírás után: az előző példány visszaállt",
       pdf_info(os.path.basename(elo))[0] == [""] and
       not os.path.exists(os.path.join(anna, pm.BACKUP_DIR, os.path.basename(elo))))

    print("ÖSSZEÁLLÍTÓ: TÖMÖRÍTÉS")
    kt._clear()
    kt._add([os.path.join(big_imgs, f) for f in sorted(os.listdir(big_imgs))])
    wait(lambda: kt._thumb_job is None, 20)
    at(0)
    at(3, "Shift-")
    key("8")                                               # Szálláshely-igazolás, utótag nélkül
    kt._ask_batch = lambda jobs, free: "new"
    kt._iktat()
    wait(lambda: kt._b is None, 180)
    out2 = os.path.join(anna_up, "Kiss Anna Szálláshely-igazolás.pdf")
    log = kt.log.get("1.0", "end")
    ck("képekből: 5 MB fölött lépcsőzetes tömörítés, a kész PDF alatta",
       "lépcső:" in log and os.path.exists(out2) and os.path.getsize(out2) <= pm.UPLOAD_LIMIT,
       log[-300:])

    print("FELÜLET")
    stl = pm.ttk.Style(app)
    ck("a kódból rajzolt elemek a témában vannak",
       {"Modern.button", "Accent.button", "Modern.tab", "Modern.check"} <=
       set(stl.element_names()),
       [e for e in ("Modern.button", "Accent.button", "Modern.tab", "Modern.check")
        if e not in stl.element_names()])
    gombok = []
    def gyujt(w):
        for c in w.winfo_children():
            if c.winfo_class() == "TButton":
                gombok.append(c)
            gyujt(c)
    gyujt(app)
    ikonos = [b for b in gombok if b.cget("image")]
    ck("a gombok többsége ikont kapott a feliratából",
       len(ikonos) >= 20 and len(gombok) >= 40, (len(ikonos), len(gombok)))
    iktat = next(b for b in gombok if str(b.cget("text")).startswith("Iktatás"))
    ck("az elsődleges műveletek kiemelt stílust kapnak",
       str(iktat.cget("style")) == "Accent.TButton", iktat.cget("style"))
    ck("a gombok továbbra is igazi ttk.Button-ök (állapot, invoke működik)",
       iktat.winfo_class() == "TButton" and iktat.instate(["!disabled"]))
    ck("az ablak befér a képernyőbe (a tálca alá se lóg)",
       app.winfo_reqheight() <= app.winfo_screenheight() and
       app.winfo_width() <= app.winfo_screenwidth(),
       (app.winfo_width(), app.winfo_height(), app.winfo_screenheight()))
    # A legördülő: a widget ABLAKÁT a ttk a stílus background-jával tölti ki.
    # Ha az nem a környezet színe, a lekerekített sarkon kívüli rész kiszínesedik,
    # és a mező sarka levágottnak látszik.
    ck("a legördülő mező háttere a környezeté (nem vágódik le a sarka)",
       stl.lookup("TCombobox", "background") == pm.UI["bg"],
       stl.lookup("TCombobox", "background"))
    # A felugró ablak sarka: Windows-ablakrégióval vágjuk kerekre (13.8).
    app.tk.call("ttk::combobox::Post", ikt.cbo)
    pump(0.4)
    _pd = app.tk.call("ttk::combobox::PopdownWindow", ikt.cbo)
    try:
        import ctypes
        _h = int(app.tk.call("winfo", "id", _pd), 0)
        _rgn = ctypes.windll.gdi32.CreateRectRgn(0, 0, 1, 1)
        _van = ctypes.windll.user32.GetWindowRgn(_h, _rgn)
    except Exception as _e:
        _van = f"nem mérhető: {_e}"
    ck("a nyitott lista sarka le van kerekítve (ablakrégió)", _van in (2, 3), _van)
    app.tk.call("ttk::combobox::Unpost", ikt.cbo)
    pump(0.2)

    pdw = app.tk.call("ttk::combobox::PopdownWindow", ikt.cbo)
    lb = pdw + ".f.l"
    ck("a nyitott lista: fehér lap, akcentus kijelölés, világos keret",
       (app.tk.call(lb, "cget", "-background"), app.tk.call(lb, "cget", "-selectbackground"),
        stl.lookup("ComboboxPopdownFrame", "bordercolor")) ==
       (pm.UI["card"], pm.UI["accent_bg"], pm.UI["line"]),
       (app.tk.call(lb, "cget", "-background"),
        app.tk.call(lb, "cget", "-selectbackground"),
        stl.lookup("ComboboxPopdownFrame", "bordercolor")))

    allapot = [w for w in app.winfo_children()
               if str(w.cget("style")) == "Foot.TFrame"]
    ck("az állapotsor a helyén van és látszik",
       bool(allapot) and allapot[0].winfo_ismapped() and
       allapot[0].winfo_y() > app.nb.winfo_y(), allapot)

    print("IKTATÓ: OLDALANKÉNTI SZÉTOSZTÁS")
    app.show(ikt)
    pump(0.3)
    sokoldalas = os.path.join(TMP, "harom_dolgozo.pdf")
    d = P.open()
    for who in ("Kiss Anna", "Nagy Béla", "Dolgozó 00"):
        d.new_page(width=595, height=842).insert_text((72, 100), f"{who} utlevele",
                                                      fontsize=20)
    d.save(sokoldalas)
    d.close()
    ikt.queue.clear()
    ikt.doc_type.set("Útlevél")
    ikt._type_chosen()
    ikt._enqueue([sokoldalas])
    ikt.page_mode.set(True)
    ikt._page_mode_changed()
    pump(0.4)
    ck("oldalanként mód: a köteg 3 oldala látszik",
       ikt._by_page() and ikt.page_count == 3, (ikt._by_page(), ikt.page_count))

    def ejt(nev):
        """Valódi vonszolás: az előnézetről a dolgozó csempéjére."""
        ikt.filter_text.set(nev)                 # egy csempe maradjon
        pump(0.3)
        cv = ikt.canvas
        l, t, r, b = ikt.prev_box
        px, py = int((l + r) / 2), int((t + b) / 2)
        tx1, ty1, tx2, ty2 = ikt.tile_rects[nev]
        tx, ty = int((tx1 + tx2) / 2), int((ty1 + ty2) / 2)
        cv.event_generate("<ButtonPress-1>", x=px, y=py)
        cv.event_generate("<B1-Motion>", x=tx, y=ty)
        pump(0.15)
        kiemelt = any(cv.itemcget(i, "fill") == pm.COL_TILE_BG_HOT
                      for i in cv.find_withtag(f"tile::{nev}")
                      if cv.type(i) in ("rectangle", "polygon"))
        cv.event_generate("<ButtonRelease-1>", x=tx, y=ty)
        pump(0.4)
        return kiemelt

    kiemelt1 = ejt("Kiss Anna")
    ck("vonszolás közben a célcsempe kiemelődik", kiemelt1)
    ck("az 1. oldal Kiss Annához került, és a nézet a 2.-ra lépett",
       ikt.page_no == 1 and len(ikt.queue) == 1 and
       "1/3 oldal kész" in ikt.msg.get(), (ikt.page_no, ikt.msg.get()[:90]))
    ejt("Nagy Béla")
    ejt("Dolgozó 00")
    ck("a harmadik oldal után a köteg kikerült a sorból",
       not ikt.queue and "mind a 3 oldal elosztva" in ikt.msg.get(),
       (len(ikt.queue), ikt.msg.get()[:90]))
    jo = []
    for who in ("Kiss Anna", "Nagy Béla", "Dolgozó 00"):
        f = os.path.join(root, who, pm.DIR_UP, f"{who} Útlevél.pdf")
        if os.path.isfile(f):
            dd = P.open(f)
            jo.append(dd.page_count == 1 and dd[0].get_text().strip().startswith(who))
            dd.close()
        else:
            jo.append(False)
    ck("mindhárom dolgozónál a SAJÁT oldala, egyoldalas PDF-ben", all(jo), jo)
    with open(os.path.join(root, pm.LOG_NAME), encoding="utf-8-sig") as f:
        utolso = list(csv.reader(f, delimiter=";"))[-1]
    ck("a napló az oldalszámot is rögzíti",
       utolso[1].endswith("[3]") and utolso[3] == "Dolgozó 00 Útlevél.pdf", utolso[1][-30:])
    ikt._undo()
    pump(0.3)
    ck("visszavonás: az oldal újra elosztható, a köteg visszakerült",
       len(ikt.queue) == 1 and ikt.page_no == 2 and
       not os.path.isfile(os.path.join(root, "Dolgozó 00", pm.DIR_UP,
                                       "Dolgozó 00 Útlevél.pdf")),
       (len(ikt.queue), ikt.page_no))
    for who in ("Kiss Anna", "Nagy Béla"):
        os.remove(os.path.join(root, who, pm.DIR_UP, f"{who} Útlevél.pdf"))
    ikt.page_mode.set(False)
    ikt._page_mode_changed()
    ikt.queue.clear()
    ikt.filter_text.set("")
    pump(0.2)

    print("CÍMKE A SZÖVEGRÉTEGBŐL")
    szoveges = os.path.join(TMP, "generalt.pdf")
    d = P.open()
    for title in ("Belföldi meghatalmazás", "Szálláshely-igazolás"):
        pg = d.new_page()
        pg.insert_text((72, 100), title, fontsize=20)
        pg.insert_text((72, 140), "Alulírott az alábbi nyilatkozatot teszem, "
                                  "a jogkövetkezmények ismeretében.", fontsize=11)
    d.new_page()                                   # üres oldal: marad kézi címkézésre
    d.save(szoveges)
    d.close()
    app.show(kt)
    kt._clear()
    kt._add([szoveges])
    wait(lambda: kt._thumb_job is None, 20)
    kt._label_from_text()
    pump(0.3)
    got = [it.doc.doc_type if it.doc else None for it in kt.items]
    ck("a szövegréteg szerint címkézve, az üres oldal érintetlen",
       got[:2] == ["Belföldi meghatalmazás", "Szálláshely-igazolás"] and got[2] is None,
       got)
    kt._clear()

    print("ELLENŐRZÉS ÉS UTÓLAGOS BÉLYEGZÉS")
    kezi = os.path.join(anna_up, "scan0001.pdf")             # felismerhetetlen név
    empty_pdf(kezi)
    utolag = os.path.join(anna_up, "Kiss Anna Végzettséget igazoló okirat.pdf")
    empty_pdf(utolag)                                        # bélyegezhető utólag
    app.show(att)
    att.refresh()
    pump(0.3)
    att._open_audit()
    pump(0.3)
    aw = [w for w in att.winfo_children() if w.winfo_class() == "Toplevel"][-1]
    body = [w for w in aw.winfo_children() if w.winfo_class() == "Text"][0]
    report = body.get("1.0", "end")
    ck("az ellenőrzés felsorolja a bélyegezhetőt és a kézit",
       "Végzettséget igazoló okirat.pdf" in report and "scan0001.pdf" in report,
       report[:160])
    ck("a dialógus gombjai is megkapják a témát (ikon, kiemelés)",
       bool(find_btn(aw, "Bélyegzés").cget("image")) and
       str(find_btn(aw, "Bélyegzés").cget("style")) == "Accent.TButton",
       find_btn(aw, "Bélyegzés").cget("style"))
    b = find_btn(aw, "Bélyegzés")
    ck("van bélyegzés-gomb a találatok számával", b is not None and "(" in b.cget("text"),
       b.cget("text") if b else "nincs")
    b.invoke()
    pump(0.5)
    sv = pm.read_stamp(utolag)
    ck("utólagos bélyegzés: a névből és a helyből",
       (sv.get("dolgozo"), sv.get("szabaly"), sv.get("hely")) ==
       ("Kiss Anna", "vegzett", pm.DIR_UP), sv)
    ck("a felismerhetetlen nevű bélyeg nélkül maradt", pm.read_stamp(kezi) == {})
    os.remove(kezi)
    os.remove(utolag)

    print("KÖTEGELT TÖMÖRÍTÉS")
    noisy_pdf(big_pdf)                                 # újra 5 MB fölé
    nagy0 = os.path.getsize(big_pdf)
    att.refresh()
    pump(0.3)
    ck("az Áttekintő látja az 5 MB feletti PDF-et",
       any(big_pdf.endswith(rel.replace("/", os.sep))
           for r in att.rows for rel in r.big), nagy0)
    att._open_shrink()
    pump(0.3)
    sw = [w for w in att.winfo_children() if w.winfo_class() == "Toplevel"][-1]
    stxt = [w for w in sw.winfo_children() if w.winfo_class() == "Text"][0]
    ck("a tömörítés előnézete felsorolja a fájlt",
       "Nagy Béla Útlevél.pdf" in stxt.get("1.0", "end"), stxt.get("1.0", "end")[:120])
    find_btn(sw, "Tömörítés").invoke()
    ok = wait(lambda: os.path.getsize(big_pdf) <= pm.UPLOAD_LIMIT, 120)
    pump(0.3)
    ck("kötegelt tömörítés: a fájl a korlát alá került",
       ok and os.path.getsize(big_pdf) < nagy0,
       f"{pm.mb(nagy0)} -> {pm.mb(os.path.getsize(big_pdf))}")
    ck("az előző példány a .eredeti mappában van",
       os.path.isfile(os.path.join(bela, pm.BACKUP_DIR, "Nagy Béla Útlevél.pdf")))
    with open(os.path.join(root, pm.LOG_NAME), encoding="utf-8-sig") as f:
        last = list(csv.reader(f, delimiter=";"))[-1]
    ck("naplósor a kötegelt tömörítésről",
       last[5].startswith("TOMORITVE") and last[3] == "Nagy Béla Útlevél.pdf", last)

    print("IKTATÓ → ÖSSZEÁLLÍTÓ")
    kt._clear()
    kt.who_text.set("")
    app.nb.select(ikt)
    pump(0.3)
    ikt.queue.clear()
    ikt.filter_text.set("Nagy Béla")
    ikt._enqueue([koteg])
    pump(0.3)
    cv = ikt.canvas
    ck("többoldalas kötegnél „Szétosztás…” az előnézet alatt",
       any("Szétosztás" in cv.itemcget(i, "text") for i in cv.find_withtag("cbtn")
           if cv.type(i) == "text"))
    ikt._to_composer()
    pump(0.3)
    ck("Szétosztás: az Összeállítóban, a dolgozóval, a sorból kivéve",
       app.active_tab() is kt and len(kt.items) == 6 and kt.who == "Nagy Béla" and
       os.path.abspath(koteg) not in ikt.queue, (len(kt.items), kt.who))
    ikt.filter_text.set("")
finally:
    app.destroy()
    shutil.rmtree(TMP, ignore_errors=True)

print(f"\n=== GUI: {sum(res)}/{len(res)} sikeres ===")
sys.exit(0 if all(res) else 1)
