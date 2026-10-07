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
pm.messagebox.askyesno = lambda *a, **k: True                # átnevezés / áthelyezés: igen
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


def tidy_sorok(win):
    """A Rendezés jelölőnégyzetes listájának sorai szövegként. (Korábban egy Text
    widget volt; most CheckList/Treeview — iratonkénti jelölőnégyzettel.)"""
    out = []
    stack = list(win.winfo_children())
    while stack:
        w = stack.pop()
        stack.extend(w.winfo_children())
        if w.winfo_class() == "Treeview":
            out += [" ".join(str(v) for v in w.item(i, "values")) for i in w.get_children()]
    return out


def mentes_ut(worker, stem):
    """A jelölt felülírás-mentés teljes útja a dolgozó 01_Elokeszitett mappájában,
    vagy None. Az időbélyeg miatt nem lehet a nevet előre kiszámolni."""
    d = os.path.join(worker, pm.DIR_PREP)
    if not os.path.isdir(d):
        return None
    stem = stem.split(" (")[0]      # a jelölők egy zárójelbe olvadnak össze
    hit = [f for f in os.listdir(d) if f.startswith(stem) and pm.MARK_BACKUP in f]
    return os.path.join(d, hit[0]) if hit else None


def mentes_van(worker, stem):
    """A felülírás mentése: a dolgozó 01_Elokeszitett mappájában, „(előző példány
    <időbélyeg>)” jelölővel. Külön .eredeti mappa már nincs."""
    d = os.path.join(worker, pm.DIR_PREP)
    if not os.path.isdir(d):
        return False
    stem = stem.split(" (")[0]
    return any(f.startswith(stem) and pm.MARK_BACKUP in f for f in os.listdir(d))


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

    # A mátrix csak a LÁTHATÓ sorokat rajzolja (13.10), ezért előbb odagörgetünk;
    # ez egyben azt is méri, hogy görgetés után a frissen látható sor kirajzolódik.
    cd.yview_moveto(1.0)
    att._after_scroll()
    pump(0.2)
    texts = {cd.itemcget(i, "text") for i in cd.find_all() if cd.type(i) == "text"}
    ck("görgetés után a frissen látható sorok is ki vannak rajzolva", len(texts) > 10,
       len(texts))
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
    body = tidy_sorok(tidy)
    ck("a Rendezés előnézete felsorolja a mozgatandó fájlt",
       any("Lapos Lajos Útlevél aláírt.pdf" in r for r in body), body)
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
    body2 = tidy_sorok(tidy2)
    ck("a kapu jelzi a kihagyott, nem dolgozói mappát",
       "nyaralas 2026" in labels2 and "kihagyok" in labels2, labels2[:200])
    ck("a kihagyott mappa nincs a mozgatási előnézetben",
       not any("IMG_0001.jpg" in r for r in body2), body2)
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
    ikt.doc_type.set("Tartózkodási engedély formanyomtatvány")
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
    ck("helyben tömörítve 5 MB alá", os.path.getsize(big_pdf) <= pm.UPLOAD_LIMIT < size0,
       f"{pm.mb(size0)} -> {pm.mb(os.path.getsize(big_pdf))}")
    sb = pm.read_stamp(big_pdf)
    ck("a tömörített példány is bélyeget kap (dolgozó + típus)",
       (sb.get("dolgozo"), sb.get("tipus"), sb.get("hely")) ==
       ("Nagy Béla", "Útlevél", pm.DIR_UP), sb)
    bak = mentes_ut(bela, "Nagy Béla Útlevél")
    ck("az eredeti jelölt mentésként a 01_Elokeszitett-ben",
       bak and os.path.getsize(bak) == size0, bak)
    app.nb.select(att)
    pump(0.4)
    rb = next(x for x in att.rows if x.name == "Nagy Béla")
    ck("az Áttekintő nem számolja iratnak a jelölt mentést",
       len(rb.docs["utlevel"].pdf) == 1 and not rb.big, rb.docs["utlevel"].pdf)
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
    # A billentyűesemény a Tk szerinti fókuszhoz megy. Ha a teszt ablaka épp nincs
    # előtérben (a Windows megtagadja az új ablak aktiválását), a nagyító nem kapja
    # meg magától — ezért ad néha négy hamis bukást. A fókuszt ezért mi adjuk át.
    v.focus_force()
    pump(0.1)
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
    c.focus_force()
    pump(0.1)
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
       pl.doc_type.get() == "Tartózkodási engedély formanyomtatvány", pl.doc_type.get())
    pl.angle.set(0)
    pl._render_photo()
    pl._iktat()
    pump(0.2)
    # A fotó épp most került rá: a jelölő a névben is ott van (egységes metodika).
    kesz2 = os.path.join(
        anna_up, "Kiss Anna Tartózkodási engedély formanyomtatvány (aláírt, fotóval ellátva).pdf")
    ck("az arcképes irat a feltölthetőbe került, „fotóval ellátva” jelölővel",
       os.path.isfile(kesz2), (kesz2, os.listdir(anna_up)))
    sp = pm.read_stamp(kesz2)
    ck("az arcképes irat bélyeget kap",
       (sp.get("dolgozo"), sp.get("tipus")) == ("Kiss Anna", "Tartózkodási engedély formanyomtatvány"),
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
    elo = os.path.join(anna_up, "Kiss Anna Előzetes megállapodás (aláírt).pdf")
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
       asked == [(["Kiss Anna Előzetes megállapodás (aláírt).pdf"], 1)], asked)

    def pdf_info(fn, sub=None):
        d = P.open(os.path.join(anna, sub or pm.DIR_UP, fn))
        r = [pg.get_text().strip() for pg in d], [pg.rotation for pg in d]
        d.close()
        return r

    forma, elo2, utl = ("Kiss Anna Tartózkodási engedély formanyomtatvány (aláírt).pdf",
                        "Kiss Anna Előzetes megállapodás (aláírt) (2).pdf",
                        "Kiss Anna Útlevél (másolat).pdf")
    # A formanyomtatványra arcképet is kell helyezni, a jelölő nincs bepipálva:
    # ezért NEM a feltölthetőbe, hanem az előkészítettbe kerül.
    ck("Forma (fotó nélkül) az előkészítettbe, a vonszolt sorrendben",
       pdf_info(forma, pm.DIR_PREP)[0] == ["oldal 2", "oldal 1"],
       pdf_info(forma, pm.DIR_PREP))
    sf = pm.read_stamp(os.path.join(anna, pm.DIR_PREP, forma))
    ck("Összeállító: iratonkénti bélyeg a cél alkönyvtárával",
       (sf.get("dolgozo"), sf.get("tipus"), sf.get("hely")) ==
       ("Kiss Anna", "Tartózkodási engedély formanyomtatvány", pm.DIR_PREP), sf)
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
    ck("felülírás: az új példány a helyén, az előző jelölt mentésként a 01-ben",
       pdf_info(os.path.basename(elo))[0] == ["oldal 3", "oldal 4"] and
       mentes_van(anna, os.path.splitext(os.path.basename(elo))[0]))
    kt._undo()
    ck("visszavonás felülírás után: az előző példány visszaállt",
       pdf_info(os.path.basename(elo))[0] == [""] and
       not mentes_van(anna, os.path.splitext(os.path.basename(elo))[0]))

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

    print("TELJESÍTMÉNY")
    # A mátrix csak a látható sávot rajzolja; a fixture-ben 40+ dolgozó van.
    app.show(att)
    att.refresh()
    pump(0.4)
    sorok = len(att.view_rows)
    kezd, veg = att._rows_view(att.c_data)
    ck("a látható sortartomány a sorokon belül van",
       0 <= kezd <= veg <= sorok, (kezd, veg, sorok))
    eredeti_sorok = att.view_rows
    att.view_rows = eredeti_sorok * 12                 # ~500 dolgozó szimulálva
    k2, v2 = att._rows_view(att.c_data, pm.ROW_BUFFER)
    ck("sok dolgozónál a kirajzolandó sáv KORLÁTOS (virtualizálás)",
       (v2 - k2) < 90 and len(att.view_rows) > 400,
       f"{len(att.view_rows)} sorból {v2 - k2} rajzolódna")
    att.view_rows = eredeti_sorok
    att._redraw()
    pump(0.2)
    elemek = len(att.c_data.find_all()) + len(att.c_name.find_all())
    ck("a kirajzolt elemek száma a sávhoz igazodik",
       elemek < (veg - kezd + 2 * pm.ROW_BUFFER + 4) * 25,
       f"{sorok} sor, {elemek} vászonelem")
    # A tömörítés külön folyamatban fut: a felület közben válaszol.
    nagy_adat = open(big_pdf, "rb").read() if os.path.getsize(big_pdf) > pm.UPLOAD_LIMIT else None
    if nagy_adat:
        kesz = {}
        t0 = time.time()
        pm.shrink_process(app, nagy_adat,
                          on_done=lambda out, step, err: kesz.update(
                              ok=True, n=len(out or b""), err=err))
        lassu = 0
        while "ok" not in kesz and time.time() - t0 < 90:
            t1 = time.time()
            app.update()
            if time.time() - t1 > 0.25:
                lassu += 1
            time.sleep(0.01)
        ck("a felület él a külön folyamatos tömörítés alatt",
           kesz.get("ok") and not kesz.get("err") and lassu == 0,
           (kesz.get("n"), kesz.get("err"), f"{lassu} akadás"))

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
    ck("az előző példány jelölt mentésként a 01_Elokeszitett-ben van",
       mentes_van(bela, "Nagy Béla Útlevél"))
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

    print("ÖSSZEÁLLÍTÓ: SOK TÍPUS, ALACSONY ABLAK")
    # Korlát nélkül a paletta a típusok számával nőtt, és 650 px magas ablakban
    # 15 típustól az Iktatás gomb kicsúszott a látható részből (szerkeszto-terv.md 17.).
    app.geometry("1280x650")
    plusz = [pm.Rule(f"xx{i}", f"Saját típus {i}", f"S{i}", [], [f"xxteszt{i}"]) for i in range(6)]
    att.rules.extend(plusz)
    app.nb.select(kt)
    pump(0.3)
    kt.refresh()
    pump(0.4)
    b = kt.btn_go
    ck("16 típusnál is látszik az Iktatás gomb",
       len(kt.palette) >= 16 and b.winfo_ismapped() and
       b.winfo_rooty() + b.winfo_height() <= kt.winfo_rooty() + kt.winfo_height(),
       (len(kt.palette), b.winfo_rooty() + b.winfo_height() - kt.winfo_rooty(), kt.winfo_height()))
    ck("a paletta legfeljebb PAL_ROWS sort mutat, görgetősávval",
       int(kt.pal.cget("height")) == pm.PAL_ROWS and kt.pal_sb.winfo_ismapped())
    for r in plusz:
        att.rules.remove(r)
    kt.refresh()
    pump(0.2)
    ck("kevés típusnál nincs görgetősáv", not kt.pal_sb.winfo_ismapped())
    app.geometry("1200x840")
    pump(0.3)

    print("SZERKESZTÉS")
    # Word-szerű lap: táblázat vékony téglalapokból, betűnkénti cellák, jelölőnégyzet.
    szp = os.path.join(anna_up, "Kiss Anna TAJ-megrendelő.pdf")
    d = P.open()
    pg = d.new_page(width=595, height=842)
    sh = pg.new_shape()
    for y in (100, 120, 140):
        sh.draw_rect(P.Rect(50, y - 0.25, 400, y + 0.25))
    for x in (50, 150, 400):
        sh.draw_rect(P.Rect(x - 0.25, 100, x + 0.25, 120))
    for x in (50, 150, 175, 190, 215, 400):
        sh.draw_rect(P.Rect(x - 0.25, 120, x + 0.25, 140))
    sh.finish(color=None, fill=(0, 0, 0))
    sh.draw_rect(P.Rect(60, 200, 71, 211))
    sh.finish(color=(0, 0, 0), fill=None, width=0.6)
    sh.commit()
    pm.add_text(pg, (55, 114), "Régi szöveg", P.Font("helv"), 10)
    pm.add_text(pg, (60, 300), "Kitakarandó", P.Font("helv"), 10)
    # Négysoros balra zárt bekezdés a Bekezdés eszköz próbájához (hasáb: 60..520).
    FN = pm.edit_font("Calibri")
    PAR = ("Alulírott munkavállaló kijelentem, hogy a bejelentett magyarországi "
           "szálláshelyem a kérelem benyújtása óta változatlan maradt, és az ott "
           "megadott adataim a valóságnak minden tekintetben megfelelnek. A "
           "szálláshely címe és a bérleti jogviszony időtartama az iratokkal "
           "egyezik, azokat időközben nem módosítottuk.").split()
    _wd = [FN.text_length(w, 10.5) for w in PAR]
    _sp = FN.text_length(" ", 10.5)
    for _r, _row in enumerate(pm.wrap_words(_wd, _sp, 460.0)):
        _xs = pm.line_positions([_wd[i] for i in _row], 60.0, 520.0, _sp, "left")
        for _i, _x in zip(_row, _xs):
            pm.add_text(pg, (_x, 400 + _r * 14), PAR[_i], FN, 10.5)
    d.set_metadata({"keywords": "pdf-muhely=1;dolgozo=Kiss Anna;hely=02_Feltoltheto"})
    d.save(szp)
    d.close()

    ed = app.tabs["Szerkesztés"]
    app.goto_szerkeszto(szp, root)
    pump(0.4)
    ck("Áttekintőből: a Szerkesztés fülön, a fájllal", app.active_tab() is ed and ed.path == szp)
    c = ed.canvas

    def katt(x, y, x2=None, y2=None):
        """Kattintás (vagy húzás x2,y2-ig) lapkoordinátában."""
        z = ed.zoom
        c.event_generate("<ButtonPress-1>", x=int(x * z), y=int(y * z))
        if x2 is not None:
            c.event_generate("<B1-Motion>", x=int(x2 * z), y=int(y2 * z))
        c.event_generate("<ButtonRelease-1>", x=int((x2 or x) * z), y=int((y2 or y) * z))
        pump(0.2)

    def beir(t):
        e = ed._entry
        if e is None:
            return False
        e.delete(0, "end")
        e.insert(0, t)
        e.focus_force()
        pump(0.1)
        e.event_generate("<Return>")
        pump(0.3)
        return True

    katt(70, 110)
    ck("szövegre kattintva a régi szöveg a beírómezőben",
       ed._entry is not None and ed._entry.get() == "Régi szöveg")
    beir("Kőműves Győző")
    t = ed.doc[0].get_text()
    ck("átírás: a régi eltűnt, az új (ő/ű) a lapon", "Régi" not in t and "Kőműves Győző" in t, t)
    katt(65, 205)
    ck("jelölőnégyzetbe kattintva X", "X" in ed.doc[0].get_text("text", clip=P.Rect(60, 200, 71, 211)))
    katt(300, 130)
    beir("Új sor")
    ck("üres cellába új szöveg", "Új sor" in ed.doc[0].get_text())

    ed.mode.set("field")
    ed._mode_changed()
    katt(100, 110)
    beir("surname")
    katt(160, 130, 200, 135)
    beir("date_of_birth_year")
    katt(65, 205)
    beir("Neme=male")
    names = sorted(w.field_name for w in ed.doc[0].widgets())
    ck("mezők: kattintás, húzás (betűnként), jelölőnégyzet",
       names == ["Neme=male", "date_of_birth_year#1", "date_of_birth_year#2",
                 "date_of_birth_year#3", "surname"], names)
    katt(100, 110)
    ck("mezőre kattintva kijelölés, a név a panelen", ed.field_name.get() == "surname")
    ed.field_name.set("forename")
    ed._rename()
    pump(0.2)
    ck("átnevezés", "forename" in [w.field_name for w in ed.doc[0].widgets()])
    katt(100, 110)
    c.focus_force()
    pump(0.1)
    c.event_generate("<Delete>")
    pump(0.2)
    ck("Delete: a kijelölt mező törlődik", "forename" not in [w.field_name for w in ed.doc[0].widgets()])

    ed.mode.set("erase")
    ed._mode_changed()
    katt(55, 290, 140, 305)
    ck("kitakarás: a terület szövege eltűnt", "Kitakarandó" not in ed.doc[0].get_text())
    c.focus_force()
    pump(0.1)
    c.event_generate("<Control-z>")
    pump(0.2)
    ck("Ctrl+Z: a kitakarás előtti állapot", "Kitakarandó" in ed.doc[0].get_text())

    print("BEKEZDÉS")
    ed.mode.set("para")
    ed._mode_changed()
    pump(0.2)
    ck("Bekezdés eszköz: a bekezdéspanel látszik, a mezőpanel nem",
       ed.parabox.winfo_ismapped() and not ed.fieldbox.winfo_ismapped())
    katt(200, 399)
    pr = ed.para
    ck("kattintásra felismeri a négysoros bekezdést",
       pr is not None and len(pr["lines"]) == 4, None if pr is None else len(pr["lines"]))
    ck("a panel a bekezdés mai értékeivel töltődött ki",
       ed.p_align.get() == "left" and abs(ed.p_gap.get() - 14) < 0.5
       and abs(ed.p_size.get() - 10.5) < 0.1 and ed.p_family.get() == "Calibri",
       (ed.p_align.get(), ed.p_gap.get(), ed.p_size.get(), ed.p_family.get()))
    ck("a vásznon ott a bekezdés kerete", bool(c.find_withtag("para")))
    R = pr["right"]
    ed.p_align.set("justify")
    ed._apply_para()
    pump(0.3)
    ck("Alkalmaz után a dokumentum módosított", ed.dirty)
    q = pm.paragraph_at(ed.doc[0], 200, 399)
    ck("sorkizárt: minden sor a jobb szélen, az utolsó kivételével",
       q is not None and len(q["lines"]) == 4
       and all(abs(ln["bbox"][2] - R) < 0.6 for ln in q["lines"][:-1]),
       None if q is None else [round(ln["bbox"][2], 1) for ln in q["lines"]])
    ck("a bekezdés szövege változatlan", pm.para_text(q).split() == PAR)
    ck("a kijelölés a formázás után is megvan (jöhet a következő művelet)",
       ed.para is not None and len(ed.para["lines"]) == 4)
    ed.p_gap.set(21.0)
    ed._apply_para()
    pump(0.3)
    q2 = pm.paragraph_at(ed.doc[0], 200, 399)
    ck("második művelet ugyanazon a bekezdésen: sortávolság 1,5×",
       q2 is not None and abs(q2["gap"] - 21) < 0.5 and len(q2["lines"]) == 4,
       None if q2 is None else (round(q2["gap"], 1), len(q2["lines"])))
    c.focus_force()
    pump(0.1)
    c.event_generate("<Control-z>")
    pump(0.3)
    q3 = pm.paragraph_at(ed.doc[0], 200, 399)
    ck("Ctrl+Z: a sortávolság visszaállt, a sorkizárás megmaradt",
       q3 is not None and abs(q3["gap"] - 14) < 0.5
       and all(abs(ln["bbox"][2] - R) < 0.6 for ln in q3["lines"][:-1]),
       None if q3 is None else round(q3["gap"], 1))
    ed.mode.set("text")
    ed._mode_changed()
    pump(0.2)
    ck("eszközváltás: a mezőpanel visszajött, a keret eltűnt",
       ed.fieldbox.winfo_ismapped() and not ed.parabox.winfo_ismapped()
       and not c.find_withtag("para") and ed.para is None)

    ed.upper.set(True)
    ed._upper_changed()
    pump(0.2)
    ck("nagybetűs jelölő a dokumentumon", pm.get_upper(ed.doc))
    ed._save()
    pump(0.3)
    d = P.open(szp)
    ok = ("Kőműves Győző" in d[0].get_text() and
          sum(1 for _ in d[0].widgets()) == 4 and
          "dolgozo=Kiss Anna" in (d.metadata.get("keywords") or "") and pm.get_upper(d))
    qs = pm.paragraph_at(d[0], 200, 399)
    ok_par = (qs is not None and len(qs["lines"]) == 4
              and all(abs(ln["bbox"][2] - R) < 0.6 for ln in qs["lines"][:-1]))
    d.close()
    ck("mentés helyben: a szöveg, a mezők és a bélyeg is megvan", ok)
    ck("a sorkizárt bekezdés a mentett fájlban is sorkizárt", ok_par)
    ck("az előző példány jelölt mentésként a dolgozó 01_Elokeszitett mappájában",
       mentes_van(anna, "Kiss Anna TAJ-megrendelő"))
    with open(os.path.join(root, pm.LOG_NAME), encoding="utf-8-sig") as f:
        last = list(csv.reader(f, delimiter=";"))[-1]
    ck("naplósor a szerkesztésről", last[5].startswith("SZERKESZTVE") and
       last[3] == "Kiss Anna TAJ-megrendelő.pdf", last)
    ck("mentés után nincs „nincs mentve”", not ed.dirty)

    print("ELLENŐRZŐ: ROSSZ HELY, JELÖLŐNÉGYZETEK, VISSZAMENŐLEGES ÁTNEVEZÉS")
    # A gyökérben hagyott, felismert nevű irat eddig az „unknown” kosárba esett, és
    # a párbeszéd azt írta rá, hogy a nevét sem ismerjük fel — ez volt az Áttekintő
    # „hibás adat” panasz valódi oka (kepek-pdf-terv.md 15.1).
    audit_root = mkdir(TMP, "ellenorzo")
    jd = mkdir(audit_root, "John Doe")
    jd_up, jd_pr = mkdir(jd, pm.DIR_UP), mkdir(jd, pm.DIR_PREP)
    empty_pdf(os.path.join(jd, "John Doe Egyoldalu hozzajarulasi nyilatkozat alairt.pdf"))
    empty_pdf(os.path.join(jd_up, "John Doe Tart_eng_formanyomtatvany alairt_kesz.pdf"))
    empty_pdf(os.path.join(jd_up, "John Doe Utlevel.pdf"))
    empty_pdf(os.path.join(jd_pr, "IMG_20260101.pdf"))
    belyeges = os.path.join(jd_pr, "szkennelt_0042.pdf")
    d = P.open()
    d.new_page()
    pm.set_stamp(d, "John Doe", "Meghatalmazás", "meghat", pm.DIR_UP)
    d.save(belyeges)
    d.close()

    ares = pm.audit_folder(audit_root, att.rules)
    ck("ékezet nélküli név is felismerhető (nem ezen bukik az ellenőrző)",
       pm.match_rule("John Doe Meghatalmazas alairt.pdf", att.rules)[0].id == "meghat")
    ck("a gyökérben fekvő, felismert nevű irat „rossz helyen”, nem „ismeretlen”",
       [r[1] for r in ares["misplaced"]] ==
       ["John Doe Egyoldalu hozzajarulasi nyilatkozat alairt.pdf"] and
       len(ares["unknown"]) == 1, (ares["misplaced"], ares["unknown"]))

    # Átnevezés: a bélyeg a bizonyíték, a név a tartalék, az eldönthetetlen kimarad.
    terv = pm.rename_plan(audit_root, att.rules, ikt.types)
    ujak = {os.path.basename(r[1]): r[2] for r in terv}
    ck("átnevezési terv: a bélyegből és a névből is az egységes alak jön",
       ujak.get("szkennelt_0042.pdf") == "John Doe Meghatalmazás (aláírt).pdf" and
       ujak.get("John Doe Tart_eng_formanyomtatvany alairt_kesz.pdf") ==
       "John Doe Tartózkodási engedély formanyomtatvány (aláírt, fotóval ellátva).pdf" and
       ujak.get("John Doe Utlevel.pdf") == "John Doe Útlevél.pdf", ujak)
    ck("amit nem lehet eldönteni, azt nem nevezi át",
       ujak.get("IMG_20260101.pdf") is None and
       any(r[1].endswith("IMG_20260101.pdf") and not r[4] for r in terv), terv)

    # A jelölőnégyzetes párbeszéd: Mind / Egyiket se, és legalább egy kell.
    att.parent_dir = audit_root
    att.refresh()
    pump(0.3)
    att._open_rename()
    pump(0.5)
    rwin = [w for w in att.winfo_children() if w.winfo_class() == "Toplevel"][-1]

    def deep(win, cls=None, prefix=None):
        out, stack = [], list(win.winfo_children())
        while stack:
            w = stack.pop()
            stack.extend(w.winfo_children())
            if cls and w.winfo_class() == cls:
                out.append(w)
            if prefix and "text" in w.keys() and str(w.cget("text")).startswith(prefix):
                out.append(w)
        return out

    cl = att.rename_cl
    gomb = deep(rwin, prefix="Átnevezés")[0]
    ck("átnevezés: minden sor alapból kijelölve", len(cl.selected()) == 4,
       len(cl.selected()))
    cl.set_all(False)
    pump(0.2)
    ck("„Egyiket se” után a gomb tiltott (legalább egy irat kell)",
       not cl.selected() and "disabled" in gomb.state(), gomb.state())
    cl.set_all(True)
    pump(0.2)
    ck("„Mind kijelöl” visszakapcsol, a gomb a darabszámot mutatja",
       len(cl.selected()) == 4 and "disabled" not in gomb.state(), gomb.cget("text"))
    gomb.invoke()
    pump(0.8)
    ck("átnevezés után az egységes nevek vannak a lemezen",
       sorted(os.listdir(jd_up)) ==
       ["John Doe Előzetes megállapodás (aláírt).pdf"] * 0 +
       ["John Doe Tartózkodási engedély formanyomtatvány (aláírt, fotóval ellátva).pdf",
        "John Doe Útlevél.pdf"] and
       "John Doe Meghatalmazás (aláírt).pdf" in os.listdir(jd_pr),
       (os.listdir(jd_up), os.listdir(jd_pr)))
    ck("az eldönthetetlen irat érintetlen", os.path.isfile(os.path.join(jd_pr, "IMG_20260101.pdf")))
    att.parent_dir = root
    att.refresh()
    pump(0.3)

    print("MINDEN FÜL: A LEGKISEBB ABLAKBAN SEM LÓG LE GOMB")
    # Az Arckép fülön a Mentés és az Iktatás MINDEN ablakméretben levágódott (a bal
    # panel 990 px-et kért, a legnagyobb ablakban is 658 jutott). A görgethető
    # panel + fix alsó gombsáv ezt oldja meg; ez a teszt a visszaesést fogja meg.
    app.geometry("940x620")               # az app minsize-ja
    pump(0.8)

    def latszik(w, tab):
        return (w.winfo_ismapped() and
                w.winfo_rooty() + w.winfo_height() <= tab.winfo_rooty() + tab.winfo_height())

    for nev, gomb in (("Arckép elhelyezés", "btn_iktat"), ("Összeállító", "btn_go")):
        tab = app.tabs[nev]
        app.show(tab)
        pump(0.6)
        b = getattr(tab, gomb)
        ck(f"{nev}: a záró gomb görgetés nélkül is látszik", latszik(b, tab),
           (b.winfo_rooty() + b.winfo_height() - tab.winfo_rooty(), tab.winfo_height()))

    # A görgethető panelen MINDEN vezérlő elérhető: a végére görgetve látszik az alja.
    pl = app.tabs["Arckép elhelyezés"]
    app.show(pl)
    pump(0.5)
    vaszon = next(c for c in pl.shell.winfo_children() if c.winfo_class() == "Canvas")
    sav = next(c for c in pl.shell.winfo_children() if c.winfo_class() == "TScrollbar")
    ck("Arckép: a panel görgetősávja megjelenik, ha nem fér ki", sav.winfo_ismapped())
    vaszon.yview_moveto(1.0)
    pump(0.4)
    ck("Arckép: a végére görgetve a Típus legördülő látszik",
       latszik(pl.type_cbo, pl), (pl.type_cbo.winfo_rooty() - pl.winfo_rooty(), pl.winfo_height()))
    # Az Összeállító panelje a szokásos ablakban KIFÉR: ott nincs görgetősáv.
    app.geometry("1200x840")
    pump(0.5)
    kt2 = app.tabs["Összeállító"]
    app.show(kt2)
    pump(0.5)
    ksav = next(c for c in kt2.winfo_children()[0].winfo_children()
                if c.winfo_class() == "TScrollbar")
    ck("Összeállító: szokásos ablakban nincs panelgörgetés", not ksav.winfo_ismapped())
finally:
    app.destroy()
    shutil.rmtree(TMP, ignore_errors=True)

print(f"\n=== GUI: {sum(res)}/{len(res)} sikeres ===")
sys.exit(0 if all(res) else 1)
