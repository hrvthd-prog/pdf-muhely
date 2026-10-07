# Terv — „Képek → PDF” modul a PDF Műhelybe

**Státusz:** megvalósítva (v1) — lásd a 11. fejezetet · **Készült:** 2026-09-25
**2026-09-28 óta** a fül az **Összeállító** része (kötegelt címkézés és iktatás) — lásd `szetvago-terv.md`, 14. fejezet.
**Érintett fájl:** `pdf-muhely.py` (egyesített, már tartalmazza az Iktató fület)

---

## 0. Ami már elkészült (nem része ennek a tervnek)

| # | Feladat | Állapot |
|---|---------|---------|
| 1 | Az Iktató modul beépítése a PDF Műhelybe önálló `.py` helyett | ✅ kész |
| 2 | Hibajavítás: a keretezett DnD/előnézeti rész jobbra átlógott a mappacsempékre | ✅ kész |

### 0.1 Az integráció módja

- Az `iktato _2_.py` **konfigurációtól a `_App` osztályig** tartó törzse (konstansok, `load_types`/`save_types`, `target_name`, `hu_sorted`, `ring_positions`, `visible_clip`, `TypeEditor`, `IktatoTab`) szó szerint bekerült a `pdf-muhely.py`-ba, közvetlenül a főablak szekció elé, **5. fül: iktató** címmel.
- A duplikált segédfüggvények (`script_dir`, `tkimg`, `safe_stem`, `open_checked`) **nem** kerültek be újra — az Iktató mostantól a PDF Műhely közös magját használja. AST-ellenőrzés: nincs kétszer definiált modulszintű név.
- Az import-blokk kiegészült: `csv`, `json`, `shutil`, `locale`, `datetime`, `unicodedata`, `simpledialog`.
- A fül regisztrálva: `App.tabs["Iktató"] = IktatoTab(self.nb, self)`. Az `App.refresh_all()` így automatikusan hívja az `IktatoTab.set_folder()`-t is.
- A fájl lefordul (`compile()` hibátlan), 1920 sor, 8 osztály.

### 0.2 A DnD-keret hibájának oka és javítása

**Ok.** A csempék balra igazított rácsban ülnek (`ring_positions`), így a vászon jobb szélén és alján marad egy kihasználatlan, `(tw+gap)`-nél keskenyebb sáv. Az előnézet kerete viszont a **vászon széléhez** volt igazítva:

```python
right, bottom = cw - left, ch - top   # cw = teljes vászonszélesség
```

Emiatt a keret jobbra annyival lógott túl, amennyi ez a maradéksáv volt — és rárajzolódott a jobb oszlop mappacsempéire.

**Javítás.** Új `ring_metrics()` függvény adja vissza a jobb oszlop bal élét és az alsó sor felső élét; az előnézet ezekhez igazodik, nem a vászonhoz:

```python
def ring_metrics(cw, ch, tw=TILE_W, th=TILE_H, gap=GAP):
    cols = max(1, (cw - gap) // (tw + gap))
    rows = max(1, (ch - gap) // (th + gap))
    ring_left = gap + (cols - 1) * (tw + gap)      # a jobb oszlop BAL éle
    ring_top  = gap + (rows - 1) * (th + gap)      # az alsó sor FELSŐ éle
    return cols, rows, ring_left, ring_top
```

```python
right  = (ring_left - GAP) if cols > 1 else cw - GAP
bottom = (ring_top  - GAP) if rows > 1 else ch - GAP
```

A `ring_positions()` ugyanezt a metrikát használja, így a két számítás nem tud elcsúszni egymástól.

**Megmaradt korlát (szándékos):** ha az így kapott belső terület kisebb, mint `PREVIEW_MIN_W × PREVIEW_MIN_H` (260×320), a kód a régi „vedd az egész vásznat” tartalékágra vált, és ilyenkor az átfedés visszatérhet. A 960×680-as `minsize` mellett ez a gyakorlatban nem fordul elő. → **1. kérdés.**

---

## 1. Az új modul célja

Nagy méretű bemeneti képekből (telefonos fotó, szkennelt lap) **egyetlen, tömörített PDF** készítése úgy, hogy

1. a képek előnézetben látszanak,
2. a sorrend **vonszolással** átrendezhető,
3. a kimenet neve az Iktató metodikáját követi: `{mappanév} {doktípus} {utótag}.pdf`.

Új fül neve: **„Képek → PDF”**, a Notebookban az *Összefűzés* után.

---

## 2. Felépítés

### 2.1 Osztályok

| Osztály | Szerep |
|---------|--------|
| `ImgItem` | Egy kép adatai: `path`, `w`, `h`, `bytes`, `exif_rot`, `thumb` (PhotoImage), `enabled` (be/kikapcsolt), `rot` (felhasználói forgatás 0/90/180/270) |
| `ThumbGrid(ttk.Frame)` | Görgethető `tk.Canvas` bélyegkép-ráccsal, vonszolásos átrendezéssel, többes kijelöléssel |
| `ImagesToPdfTab(ttk.Frame)` | A fül: betöltés, beállítások, névképzés, futtatás, napló |

### 2.2 Képernyőterv

```
┌─ Képek → PDF ───────────────────────────────────────────────────────────┐
│ [Képek hozzáadása…] [Mappa hozzáadása…] [Kijelölt törlése] [Mind törlése]│
│ [↺ balra] [↻ jobbra] [Név szerint rendez] [Dátum szerint rendez]         │
├──────────────────────────────────────────────────────────────────────────┤
│  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐   ← vonszolható bélyegképek│
│  │  1   │ │  2   │ │  3   │ │  4   │ │  5   │      (ThumbGrid, görgethető)│
│  │ IMG  │ │ IMG  │ │ IMG  │ │ IMG  │ │ IMG  │                            │
│  └──────┘ └──────┘ └──────┘ └──────┘ └──────┘                            │
│   4032×3024 · 6,1 MB                                                     │
├─ Tömörítés ──────────────────────────────────────────────────────────────┤
│ Előbeállítás: ( ) Archív 300 DPI  (•) Irodai 200 DPI  ( ) E-mail 150 DPI │
│ Hosszabb oldal max: [2480] px    JPEG minőség: [====|====] 75            │
│ [x] Szürkeárnyalatos  [ ] Eredeti felbontás megtartása                   │
│ Lapméret: (•) A4 álló, kitöltő  ( ) A4 illesztett, fehér kerettel        │
│           ( ) Lapméret = képméret       Margó: [0] mm                    │
│ Becsült kimenet: ~ 3,4 MB  (12 kép)                                      │
├─ Elnevezés ──────────────────────────────────────────────────────────────┤
│ Dolgozó (mappa): [Horváth Dániel      ▼] [Mappák frissítése]             │
│ Dokumentum típusa: [Előzetes megállapodás ▼] [Típusok…]                  │
│ Utótag: [aláírt]                                                         │
│ → Horváth Dániel Előzetes megállapodás aláírt.pdf                        │
│ Célmappa: (•) a dolgozó mappája   ( ) egyedi hely…                       │
├──────────────────────────────────────────────────────────────────────────┤
│ [████████████░░░░░░] 7/12 kép feldolgozva        [PDF készítése]         │
│ napló…                                                                   │
└──────────────────────────────────────────────────────────────────────────┘
```

### 2.3 A vonszolásos átrendezés

A meglévő `IktatoTab` vonszoláslogikájának mintájára, `tk.Canvas`-on:

- `<ButtonPress-1>` a bélyegképen → a kép indexének megjegyzése, „szellemkép” létrehozása (félig átlátszó helyett: szaggatott keret + fájlnév, ahogy az Iktatóban);
- `<B1-Motion>` → a szellemkép mozgatása, **beszúrási jel** (2 px vastag függőleges vonal) kirajzolása a legközelebbi rés elé;
- `<ButtonRelease-1>` → `list.insert(new_idx, list.pop(old_idx))`, majd újrarajzolás;
- automatikus görgetés, ha a kurzor a rács felső/alsó 20 px-es sávjába ér;
- `Ctrl+kattintás` / `Shift+kattintás` → többes kijelölés, a blokk együtt mozog;
- `Home`/`End`/nyilak billentyűvel is léptethető a kijelölt elem (`Ctrl+↑/↓` = eggyel előre/hátra).

**Miért canvas és nem `ttk.Treeview`?** A bélyegképes rács vizuális sorrendezéshez lényegesen jobb, és a projektben már van bejáratott canvas-vonszolás.

### 2.4 Bélyegképek

- Méret: 160×160 px befoglaló (→ **7. kérdés**).
- **Háttérszálon** készülnek (`threading.Thread`), a kész `PhotoImage`-et a főszál veszi át `after()`-rel — 40–60 db 8 MP-es fotónál ez másodpercek különbsége.
- Lemezes gyorsítótár nincs; memóriában `dict[path] = PhotoImage`, korlát nélkül (egy bélyegkép ~80 KB).
- Betöltés közben helyőrző szürke téglalap + „…”.

---

## 3. Tömörítési folyamat

Képenként:

```
beolvasás → EXIF-forgatás → felhasználói forgatás → átméretezés
   → (opc.) szürkeárnyalat → JPEG-újrakódolás Q minőséggel
   → beágyazás PDF-lapra (DCTDecode, újrakódolás nélkül)
```

### 3.1 Átméretezés

A cél a **hosszabb oldal** pixelben:

```
max_px = DPI × (lap hosszabb oldala hüvelykben)
# A4 esetén: 300 DPI → 3508 px, 200 DPI → 2339 px, 150 DPI → 1754 px
```

Nagyítás soha nem történik: `scale = min(1.0, max_px / max(w, h))`.

### 3.2 A kódoló

| Motor | Előny | Hátrány |
|-------|-------|---------|
| **Pillow** | pontos JPEG-minőség, `subsampling`, `optimize`, EXIF-kezelés, jó minőségű LANCZOS átméretezés | új függőség |
| **PyMuPDF egyedül** | nincs új függőség | `Pixmap.shrink(n)` csak 2 hatványaival kicsinyít, a JPEG-minőség szabályozása korlátozott |

**Javaslat:** Pillow, ha telepítve van; ha nincs, automatikus visszaesés a PyMuPDF-ágra és egy figyelmeztető sor a naplóban. → **8. kérdés.**

### 3.3 Beágyazás

A már JPEG-re kódolt bájtsorozat **újrakódolás nélkül** kerül a PDF-be:

```python
imgdoc = pymupdf.open(stream=jpeg_bytes, filetype="jpeg")
pdfbytes = imgdoc.convert_to_pdf()
page.show_pdf_page(target_rect, pymupdf.open("pdf", pdfbytes), 0, keep_proportion=True)
```

Ez ugyanaz a bejáratott út, amit a `PlacerTab._load_img()` használ, és garantálja, hogy a beállított JPEG-minőség pontosan az lesz a fájlban is.

Mentés: `out.save(dst, garbage=4, deflate=True)`, metaadat `CLEAN_META`.

### 3.4 Méretbecslés

A „Becsült kimenet” érték az **első három kép** tényleges újrakódolásából extrapolál (memóriában, fájlba írás nélkül), és a beállítás minden változásakor frissül, 300 ms-os késleltetéssel.

---

## 4. Névképzés

Teljes egészében a már beépített Iktató-logika újrahasznosítása:

```python
target_name(dir_name, doc_type, suffix)   # → "Horváth Dániel Előzetes megállapodás aláírt.pdf"
unique_name(folder, name)                 # ütközésnél (2), (3) …
check_path_len(full)                      # 255 karakteres korlát
load_types() / save_types()               # közös iktato-doktipusok.json
```

- A **dolgozó mappája** legördülőből választható, a munkamappa almappáiból, `hu_sorted()` rendezéssel — ugyanaz a forrás, mint az Iktató csempéié.
- A **doktípus** legördülő ugyanazt a `self.types` listát mutatja, és a „Típusok…” gomb ugyanazt a `TypeEditor`-t nyitja. A mentés mindkét fület frissíti (→ **13. kérdés**).
- Névütközésnél ugyanaz a háromgombos párbeszéd (`_ask_collision`): *Új néven (2)* / *Felülírás* / *Mégsem*.
- A művelet ugyanabba a `iktato-naplo.csv`-be kerül, `KEPEK-PDF` eredményjelzéssel (→ **14. kérdés**).

---

## 5. Hibakezelés

| Eset | Viselkedés |
|------|-----------|
| Nem olvasható / sérült kép | átugorja, naplósor, a bélyegkép helyén piros „⚠ nem olvasható” |
| CMYK / 16 bites / alfacsatornás kép | RGB-re konvertálás, alfa fehér háttérre lapítva |
| Többoldalas TIFF | → **10. kérdés** |
| Nincs kijelölt dolgozó vagy doktípus | a „PDF készítése” gomb letiltva, a hiányzó mező kivillan (`_flash_combo` mintájára) |
| Nincs szabad hely / írási hiba | `.part` fájlba írás, ellenőrzés, majd `os.replace()` — az Iktató `_copy_verified()` mintája |
| Megszakítás | „Mégsem” gomb; a `.part` fájl törlődik |

---

## 6. Teljesítmény

- A feldolgozás **háttérszálon** fut, a felület nem fagy be; folyamatjelző + „Mégsem”.
- Egyszerre egy szál (a PyMuPDF dokumentumobjektumai nem szálbiztosak); a képdekódolás és -átméretezés viszont `ThreadPoolExecutor`-ral párhuzamosítható, mert az tisztán Pillow-oldali. → **16. kérdés**
- Memória: a képek **nem** maradnak dekódolva a memóriában; csak a bélyegkép és a végleges JPEG-bájtok.

---

## 7. Tesztterv

1. 30 db 12 MP-es JPEG → 200 DPI, Q75, szürkeárnyalat: kimenet < 8 MB, feldolgozás < 30 s.
2. Vegyes tájolás (álló + fekvő) → A4 illesztett módban nincs levágás.
3. EXIF-forgatott fotó (orientation=6) → a PDF-ben állva jelenik meg.
4. Ugyanaz a fájlnév kétszer a dolgozó mappájában → „(2)” utótag, naplósor.
5. Ékezetes dolgozónév (`Ökrös Zsófia`) → NFC-normalizált fájlnév, Windowson helyesen nyílik.
6. 40 elem átrendezése vonszolással, majd PDF: a lapsorrend pontosan a rácsban látott sorrend.
7. Üres kijelölés / 0 kép → a gomb letiltva, nem dob kivételt.
8. 260 karakteres célútvonal → érthető hibaüzenet, nem `OSError`.

---

## 8. Megvalósítási fázisok

| Fázis | Tartalom | Becslés |
|-------|----------|---------|
| F1 | `ImgItem`, betöltés, bélyegképrács megjelenítéssel (vonszolás nélkül) | ~200 sor |
| F2 | Vonszolásos átrendezés, többes kijelölés, forgatás | ~150 sor |
| F3 | Tömörítési folyamat + méretbecslés | ~180 sor |
| F4 | Névképzés, célmappa, ütközéskezelés, napló | ~100 sor |
| F5 | Háttérszál, folyamatjelző, megszakítás | ~80 sor |

Összesen ~700 sor, a `pdf-muhely.py` így ~2600 sorra nő. → **20. kérdés**

---

## 9. Kérdések, amiket tisztázni kell

### A) A már elvégzett hibajavításról

1. A 260×320-as minimumnál kisebb belső területnél a kód ma az egész vászonra teríti az előnézetet, és ilyenkor az átfedés visszatérhet. Inkább **tiltsam le** ezt a tartalékágat (a keret sose lógjon a csempékre, akkor is, ha emiatt apró lesz), vagy maradjon a mai viselkedés?
2. A javítás után a jobb oldalon marad egy kihasználatlan sáv. Akarod, hogy a csempék **középre** vagy **szélre igazítva** töltsék ki a vásznat, hogy ne legyen üres rés?

### B) A bemeneti képekről

3. Milyen **formátumok** fordulnak elő ténylegesen? A mai `IMG_EXT` a `.jpg .jpeg .png .tif .tiff .bmp`. Kell **HEIC/HEIF** (iPhone) és **WEBP** is? (HEIC külön csomagot igényel: `pillow-heif`.)
4. Mekkorák a képek jellemzően (MP és MB), és **hány** kerül egy PDF-be? Ez dönti el, kell-e párhuzamosítás és lemezes gyorsítótár.
5. A képek **szkennelt dokumentumok** (fehér alap, fekete szöveg) vagy **fényképek**? Szkennelt lapnál a szürkeárnyalat + magasabb DPI + alacsonyabb JPEG-minőség a jó irány, fotónál épp fordítva.
6. Érkezhetnek a képek **Explorerből húzva** az ablakba, vagy elég a „Tallózás…” gomb? A rendszerszintű fogadáshoz `tkinterdnd2` kell — ez új, nem szabványos függőség.
7. Mekkora legyen a **bélyegkép**? A javaslat 160×160 px. Fontosabb, hogy sok férjen ki (kisebb), vagy hogy olvasható legyen rajta a szöveg (nagyobb, pl. 220 px)?

### C) A tömörítésről

8. Telepíthető-e a **Pillow**, vagy kőkeményen a „csak pymupdf” szabály érvényes? Ez a legfontosabb kérdés az egész modulban: Pillow nélkül a minőség/méret szabályozása durvább lesz.
9. Mi a **cél**: fix DPI/minőség (kiszámítható minőség, változó méret), vagy **célméret** (pl. „legyen 5 MB alatt” — iteratív minőségkereséssel, lassabb)? Van valahol kötelező felső méretkorlát (pl. hatósági feltöltés)?
10. **Többoldalas TIFF** esetén minden oldal külön PDF-lap legyen, vagy csak az első oldal?
11. Az **eredeti képeket** meg kell őrizni valahol a PDF elkészülte után (átmozgatás egy `feldolgozott` almappába), vagy maradnak érintetlenül a helyükön?
12. Kell-e a PDF-be **OCR-szöveg** vagy kereshetőség? (Ez külön motort — Tesseract — igényelne, és felrúgná az „offline, csak pymupdf” elvet.)

### D) Az elnevezésről és az integrációról

13. A doktípus-lista **közös** legyen a két fül közt (ugyanaz a `iktato-doktipusok.json`), vagy a képmodulnak **saját** listája legyen (pl. „Fotó”, „Szkennelt igazolvány”)?
14. A kész PDF bekerüljön-e az **`iktato-naplo.csv`**-be, vagy külön naplót vezessen? Ha közös: milyen jelzéssel különböztessük meg a másolástól?
15. Az **utótag** mindig „aláírt”, mint az Iktatóban? Képekből összefűzött doksinál ez félrevezető lehet — legyen inkább szerkeszthető mező, alapértelmezés nélkül, vagy pl. „szkennelt”?
16. Az elkészült PDF **automatikusan bekerüljön-e az Iktató fül várólistájába** (akkor a nevet ott is lehetne véglegesíteni), vagy a képmodul maga írja ki készre a dolgozó mappájába? Mindkettő megépíthető, de a kettő együtt zavaró lehet.
17. A **célmappa** mindig a dolgozó mappája a munkamappán belül, vagy kelljen tudni máshová is menteni (pl. ideiglenes „kimenet” mappába)?
18. A dolgozó választása **legördülő** legyen, vagy itt is a csempés vonszolás (ejtsd a névre), mint az Iktatóban? A legördülő egyszerűbb, a csempe viszont egységes élményt ad.

### E) Egyéb

19. Kell-e **üres oldal beszúrása** vagy **oldalszámozás / fejléc** a kész PDF-be?
20. A `pdf-muhely.py` ~2600 sorra nőne. Maradjon **egyetlen fájl** (könnyű másolni, nincs csomagolás), vagy bontsuk **modulokra** (`pdf_muhely/`, `tabs/`)? Az egyfájlos változatot a jelenlegi `try: from pdf_muhely import …` mintája is támogatja.
21. Van **PyInstaller-es EXE** build? Ha igen, minden új függőség (Pillow, pillow-heif, tkinterdnd2) növeli a csomagot, és `--hidden-import`-ot igényelhet.
22. Milyen **Python- és PyMuPDF-verzió** fut a célgépen? A `Pixmap.tobytes("jpeg", jpg_quality=…)` csak újabb PyMuPDF-ben létezik, és a Pillow nélküli tartalékág ettől függ.

---

## 10. Mire várok választ, mielőtt kódolok

A **8., 9., 13. és 16.** kérdés érdemi válasza nélkül nem érdemes elkezdeni: ezek a modul gerincét (kódoló, minőségi cél, névforrás, munkafolyamat) határozzák meg. A többi menet közben is pontosítható.

---

## 11. Döntések és megvalósítás (2026-09-25)

### 11.1 A felhasználó döntései

| Kérdés | Döntés |
|--------|--------|
| Áttekintő beépítése | igen, a műhely 7. füleként (az Iktató után); az `attekinto.py` innentől csak régi másolat |
| Névadás (13., 14., 16.–18.) | **az Iktatón át**: a kész PDF az Iktató várólistájára kerül; új „Utótag” mező az Iktatóban |
| Képek forrása | külön mappából, a dolgozói mappákkal nincs átfedés |
| Méretkorlát (9.) | **5 MB fájlonként** a feltöltésnél — minden modul jelezzen, és legyen tömörítési ág |
| Fotók a dolgozói mappákban | csak az arckép maradhat, minden más fotó PDF-be (ezért kell a modul) |

### 11.2 Mérésen alapuló eltérések a tervtől

- **Csak PyMuPDF, nincs Pillow (8.):** a képdokumentum tetszőleges léptékkel renderelhető, az EXIF-forgatást magától alkalmazza, a `tobytes("jpeg", jpg_quality=…)` működik, az `insert_image(stream=jpeg)` bájtra azonos DCTDecode-ot ír (1.26.7-en mérve).
- **Nincs szál:** a bélyegkép ~50 ms, a feldolgozás ~0,5 s/kép → `after()`-lánc, képenként; „Mégsem” flaggel.
- **Nincs méretbecslés (3.4)**, helyette a kész méret a naplóban, és 5 MB fölött automatikus tömörítés.
- **A 0.2-es állítás nem igaz:** 960×680-nál (és teljes képernyős 1366×768-as laptopon) a belső terület 470×300, ilyenkor a tartalékág fut → az átfedés visszatér. **Megoldva:** a tartalékág és a `PREVIEW_MIN_*` konstansok törölve (1. kérdés); 960×680-nál az előnézet 470×300, átfedés nélkül.

### 11.3 Ami elkészült a `pdf-muhely.py`-ban (a korábbi állapot: `Downloads\pdf-muhely.py.bak`; 2026-09-25 óta a `pdf-muhely` git-repóban)

- **Közös mag:** `UPLOAD_LIMIT = 5_000_000` (tizedes MB, szigorúbb az 5 MiB-nál), `mb()`, `size_note()`, `shrink_pdf()` (a képek újratömörítése `rewrite_images`-szel, lépcsők: 200/Q75 → 150/Q65 → 120/Q55 → 100/Q45; a szöveg érintetlen marad), `write_pdf_verified()` (.part → oldalszám-ellenőrzés → `os.replace`).
- **5 MB-os jelzés:** Arckép, Összefűzés, Szétvágás, Raszterizálás (mentés után), Iktató (az előnézetben + iktatáskor Igen/Nem/Mégse: tömörítve iktat, a forrás változatlan marad), Áttekintő (`P!` cella, összegzés, hiánylista „tömöríteni:”, CSV-oszlop, jobb klikk: „tömörítés az Iktatóban”; a csak túlméretes PDF-fel rendelkező típus NEM számít beadhatónak).
- **Iktató:** Utótag mező; felülírásnál nincs előzetes `os.remove` (így ha a forrás maga a cél, akkor sem vész el — ezen az úton megy a helyben tömörítés); a helyben felülírt fájl visszavonása le van tiltva.
- **Áttekintő:** két hibajavítás — a Beállítások mentése megtartja a `header_lines`-t; az oszlophatár húzása nem vált rendezést. Frissítés fülváltáskor. A fotószabály szövegei (tooltip, hiánylista, összegzés). **Rögzített fejléc** (a „hdr” címkéjű elemek görgetéskor a látható rész tetejére kerülnek, a sorok fölé); **egy kattintás kijelöl, dupla kattintás / Enter nyit meg**. **Vízszintes görgetés** a sáv húzásán túl: Shift+görgő és touchpad-söprés a táblán, görgő a vízszintes sávon; ←/→ esetén a kurzor oszlopa mindig látszik (`_col_span`). **„Fejléc sorai” (1–4)** a Beállítások → Megjelenés fülön — eddig csak a JSON-ban volt állítható, és az 1 sor miatt lettek túl szélesek az oszlopok.
- **`attekinto.py`:** kivezetve — minden funkciója (és az önteszt) a műhelyben van; a régi fájl az 5 MB-os logikát és a javításokat nem tartalmazza, ne fusson párhuzamosan (ugyanazt a szabályfájlt írja).
- **Képek → PDF fül:** bélyegképrács vonszolásos sorrendezéssel (beszúrási jel, automatikus görgetés), ↺/↻, törlés (Delete), 3 előbeállítás, szürkeárnyalat, A4-illesztés / lap = kép; a kész PDF → Iktató. **Többes kijelölés** (Ctrl+kattintás: be/ki, Shift+kattintás: tartomány, mint az Intézőben); **„Kijelöltekből PDF”**: csak a kijelölt képekből, rácssorrendben készül külön PDF, a lista megmarad a következő köteghez. A ↺/↻ és a törlés minden kijelöltre hat. **Nagyító** (dupla kattintás egy bélyegképen): külön, nem modális ablak, görgő = nagyítás a kurzor körül (felső határ a natív felbontás), húzás = mozgatás, ←/→ = lapozás a rács sorrendjében (a nagyítás és a nézet megmarad, a kijelölés követi), dupla kattintás = illesztés.
- **Önteszt:** `python pdf-muhely.py --test` (az Áttekintő 35 tesztjéből indult).

### 11.5 Második kör (2026-09-25): biztonság, kényelem, karbantartás

- **`.eredeti\` mentés:** Iktatóban felülírás előtt az előző példány a dolgozó mappájában a `.eredeti\` almappába kerül (a ponttal kezdődő mappát az Áttekintő és az Iktató kihagyja); a **Visszavonás** ezt állítja vissza. Addig a helyben tömörítés az egyetlen példányt írta felül.
- **Több PDF ugyanahhoz a típushoz:** az Áttekintőben `P×2` (a hiánylistában „több PDF”) — eddig egyetlen „P” volt, és dupla kattintásra a `(2)`-es nyílt meg.
- **Utótag a doktípusból:** a DocGen-ből készülő (generated) típusnál „aláírt”, a többinél üres — az Áttekintő szabályaiból, új beállítás nélkül.
- **Éles szöveg 125%-os skálázásnál:** GDI-skálázás (`SetProcessDpiAwarenessContext(-5)`), egy sor; lemérve, hogy a Tk szövege éles lesz. A képeket a Windows továbbra is nagyítja — teljes DPI-tudatossághoz minden pixelméretet skálázni kellene, azt nem érte meg.
- **Lépcsőzetes tömörítés:** `shrink_steps` generátor + `shrink_later` after()-lánc; a lépcsők között a felület él, közben az Iktató foglalt (új iktatás, visszavonás vár). Egy lépcsőn belül még áll — teljesen csak külön folyamatban lehetne.
- **Verziózás és frissítés a DocGen sémájával:** `fő.al` (`verzio.json`, pre-/post-commit hook, annotált tag), `tools/kiadas.py` (tesztek + klón-próba + főverzió), `tools/frissit.vbs` (ZIP-ből, sosem töröl; a beállításfájlokat csak akkor hozza létre, ha még nincsenek). Induláskor ellenőrzi a PyMuPDF képességeit.
- **Tesztek a repóban:** `test/run-all.py` — önteszt, `test/verzio.py`, `test/frissit.py`, `test/gui.py`. README és CLAUDE.md.
- **Nem készült el (a felhasználó döntése):** a portálpróba az 5 MB értelmezéséről, és az elvárt oldalszám ellenőrzése.

### 11.4 Szándékos egyszerűsítések (később bővíthető)

- Többoldalas TIFF-ből csak az 1. oldal kerül be (naplósor jelzi).
- Vonszolás: egyszerre egy elem (a többes kijelölés nem mozog blokkban); nincs billentyűs léptetés.
- A tömörítés lépcsőnként fut; egy lépcsőn belül (nagy fájlnál 1–3 s) a felület még áll.
- HEIC nem támogatott (a MuPDF nem olvassa) — ha kell, `pillow-heif`.

## 12. Dolgozónkénti két alkönyvtár (2026-09-29)

Az igény: dolgozónként két alkönyvtár, hogy **ránézésre látszódjon, mi van kész és mi nincs**. A mai lapos szerkezetben a DocGen által generált, még alá nem írt PDF és a szkennelt-aláírt PDF megkülönböztethetetlen — mindkettő „P” a mátrixban, és mindkettő beadhatónak számít. A két alkönyvtár tehát nem csak rendezés: **ez adja meg az Áttekintőnek azt az információt, ami ma nincs benne.**

### 12.1 A felhasználó döntései

| Kérdés | Döntés |
|--------|--------|
| A két mappa jelentése | **nyomtatandó vs. aláírt**: `01_Elokeszitett` = a DocGen kimenete, ami nyomtatásra/aláírásra vár; `02_Feltoltheto` = a szkennelt, aláírt, korlát alatti végleges PDF |
| Mappanevek | `01_Elokeszitett` / `02_Feltoltheto` — **ékezet nélkül, számozva**: az Intézőben a folyamat sorrendjében látszanak, és csak 15/14 karaktert vesznek el a `MAX_FULL_PATH` büdzséből |
| Áttekintő | **hely-alapú cella** (E/F); a docx/pdf jel a cellából megszűnik, és a „beadható” csak a `02`-t számolja |
| Gyökérben hagyott fájl | **besorolatlan jel, NEM beadható** — a szigorú értelmezés: a mátrix ne mondjon készre olyat, ami nincs a helyén |
| Migráció | **egyszeri eszköz előnézettel**; a fel nem ismert fájl marad a gyökérben, felsorolva |
| Iktatás célja | mindig `02` — **kivéve** a fotót igénylő formanyomtatványt: ott iratonkénti jelölő dönt, mindkét modulban |
| Arckép elhelyezés eredménye | **mindig `02`** — és ehhez a fül igazi iktatást kap (dolgozó, szabványos név, napló) |
| Arckép (jpg/png) helye | `01_Elokeszitett` — nyersanyag, nem feltölthető irat |
| `.eredeti\` helye | **közös, a dolgozó gyökerében** (nem almappánként) |
| Almappák létrehozása | **gomb az Áttekintőn**: a hiányzó 01/02 minden dolgozónál egyszerre |
| DocGen-bélyeg | igen, **csak a generált PDF-en** (`producer`/`keywords`) — docx-bélyeg nincs, és az Iktató bájtazonossága érintetlen |

### 12.2 A szerkezet

```
<munkamappa>\
  <Dolgozó Név>\
    01_Elokeszitett\   ← DocGen-kimenet (docx + nyomtatandó PDF), arckép (jpg/png),
                         és az aláírt formanyomtatvány, amin még nincs fotó
    02_Feltoltheto\    ← szkennelt, aláírt, korlát alatti végleges PDF-ek
    .eredeti\          ← közös, a dolgozó gyökerében (felülírt példányok)
  iktato-naplo.csv
```

A `scan_depth = 1` alapértelmezés miatt az Áttekintő **ma is megtalálja** ezeket a fájlokat: nem a keresést kell átírni, hanem a jelentésadást. A `walk_files` relatív utat ad (`01_Elokeszitett\Xy.pdf`), tehát **az első útvonalelem dönt** — egy egysoros helper elég hozzá.

### 12.3 Az Áttekintő: hely-alapú állapot

| jel | jelentés |
|---|---|
| `F` | van a `02_Feltoltheto`-ban → kész |
| `EF` | mindkét mappában van |
| `E` | csak az előkészítettben → még nem aláírt/szkennelt |
| `~` | csak a gyökérben vagy más almappában → **besorolatlan, nem beadható** |
| `?` | kétértelmű illeszkedés (marad) |
| `·` | nincs semmi |

A `!` utótag (5 MB fölött, `C_BIG` színnel) **változatlan marad**: `F!`, `~!`. Ezért nem lehetett a besorolatlan jele `!` — az már foglalt. A docx/pdf tény átkerül a tooltipbe.

Érintett kód:

- `DocState`: `+loc: set`, a `cell` property átírva. A `docx`/`pdf` listák maradnak (tooltip, `duplicates`).
- `PersonRow._ok`: csak `F`-beli, korlát alatti PDF számít — ezen áll a `beadhato`, a `ready_required` és a CSV.
- `to_print`: ma „docx van, PDF nincs”; új: „`E`-ben van, `F`-ben nincs” — pontosabb, mert a nyomtatandó DocGen-**PDF**-et is elkapja, nem csak a docx-et.
- `missing_required`: sem `E`, sem `F`, sem `~`.
- új `unsorted` property + darabszám a fejléc-összegzőben és +1 CSV-oszlop.
- `subdirs`: a 01/02 ne számítson „extra almappának”.

### 12.4 Írási cél és a formanyomtatvány-jelölő

Célmappát ma két hely dönt, mindkettő egy sor: `IktatoTab._do_copy` és `ComposerTab._iktat`. Mindkettő egy közös helperen megy át:

```python
def target_subdir(doc_type, rules, arckep_kesz: bool) -> str:
    """02_Feltoltheto — kivéve a fotót igénylő formanyomtatvány, fotó nélkül."""
```

A fotóigény **nem beégetett név**: a `Rule` kap egy `arckep` jelölőt a `required`/`generated` mintájára (dataclass + `load_settings` + egy új jelölőmező a szabályszerkesztőben), alapból a `forma` szabályon. A típus→szabály összekötést a már létező `palette_types`/`match_rule` adja — ugyanaz a mechanizmus, ami a paletta sorrendjét is.

- **Iktató:** jelölő a doktípus-combo mellett („Az arckép már rajta van”), csak a fotóigényes típusnál élesedik, és **típusváltáskor magától kiürül** — téves `02` rosszabb, mint téves `01`, mert az előbbi aláírás nélküli iratot mond beadhatónak.
- **Összeállító:** iratonként kell, nem kötegenként (lásd `szetvago-terv.md` 15.), mert egy köteg formanyomtatványt és mást is tartalmaz.
- A napló `célmappa` mezője `Dolgozó\02_Feltoltheto` legyen, hogy visszakereshető maradjon.
- `check_path_len` nagyobb utakat kap; a leghosszabb valós eset (`Nyilatkozat feltöltött dokumentumok elismeréséről aláírt.pdf` + hosszú dolgozónév + a mai munkamappa) ~170–180 karakter, tehát belül van a 255-ön, de a `.eredeti\` és a `(2)` utótag tovább növel.

### 12.5 Arckép elhelyezés: igazi iktatás

Ez a fül ma **nem iktat**: `asksaveasfilename`, a forrás mappájába, `..._kesz.pdf` néven — nem ismeri a dolgozót, nem ad szabványos nevet, nem naplóz. Az iktatómag viszont már modulszintű függvényekben van (`target_name`, `unique_name`, `backup_existing`, `check_path_len`, `write_pdf_verified`, `shrink_later`, `log_row`), tehát újrahasználható, nem kell duplikálni.

A fül kap: Dolgozó mezőt (`resolve_worker` + `worker_dirs`, ahogy az Összeállítóban), doktípus-combót (alapból a formanyomtatvány), és egy „Iktatás a feltölthetőbe” gombot a mai „Mentés másként” mellett. A cél **mindig `02`** — a fotó épp most került rá. Ha a forrás PDF egy dolgozói mappából jött, a dolgozó magától kitöltődik: ez zárja be a kört `01` → fotó → `02`.

### 12.6 Migráció

Előnézetes egyszeri eszköz, ugyanabban a párbeszédben, mint a mappalétrehozás („Rendezés…”). A besorolás **nem új logika** — ugyanaz a `match_rule`, ami a mátrixot hajtja:

| forrás | cél | a jel erőssége |
|---|---|---|
| PDF DocGen-bélyeggel | `01_Elokeszitett` | **bizonyíték** |
| PDF bélyeg nélkül, a névben `aláírt` utótag | `02_Feltoltheto` | **bizonyíték** (az Iktatón át jött) |
| PDF bélyeg nélkül és utótag nélkül | `01_Elokeszitett`, külön szakaszban jelölve | **tipp** — átnézésre |
| kép (`IMG_EXT`), `.docx` | `01_Elokeszitett` | bizonyíték |
| szabályra nem illeszkedik, vagy `is_noise` | marad a gyökérben, felsorolva | — |
| `.eredeti\`, `iktato-naplo.csv` | nem mozdul | — |

**A bizonytalan eset szándékosan `01` felé téved** (terv-ellenőrzés, 2026-09-29): egy bélyeg és utótag nélküli PDF lehet bélyeg előtti DocGen-kimenet is. Ha ilyet `02`-be tennénk, a mátrix **aláírás nélküli iratot mondana beadhatónak** — ez a legdrágább hiba. A `01` felé tévedés csak annyit mond, hogy még nincs kész. Ugyanaz az aszimmetria, mint az arckép-jelölőnél (12.4).

A besorolás tiszta függvény (`migracio_terv(folder, rules) -> [(rel, cél|None, indok)]`), ezért öntesztelhető; a mozgatás `os.replace` + **előzetes** `check_path_len` (nem közben). **Visszavonás nincs** — egyszeri eszköz, a védelem az előnézet; `ponytail:` kommenttel jelölve, hogy ez tudatos, és mi a bővítés útja (naplósor + fordított mozgatás).

#### 12.6.1 A munkamappa-kapu (2026-09-29, utólagos kérdésből)

A felhasználó rákérdezett, épült-e a kiválasztott mappa **ellenőrzése** — és nem épült. Ez valódi hiányosság volt: a `_pick_folder` bármit elfogad, a Rendezés pedig a kiválasztott mappa **minden** almappájára hatott. Mivel a képeket szabály-illesztés **nélkül** sorolja be (az arckép jellemzően nem illeszkedik irattípusra), egy tévesen kiválasztott munkamappában — Letöltések, képmappa — az összes kép elmozdult volna, visszavonhatatlanul.

**Nem globális heurisztika került be, hanem mappánkénti kapu** (`is_worker_folder`). A globális „az almappák többsége dolgozó-szerű” változat két okból rosszabb: a névforma-vizsgálat könnyen téved (a `Dolgozó 00` alakú tesztmappa és az `Adobe Premiere Pro` is elbukna/átmenne), és egy jó munkamappában sok friss, üres mappa mellett tévesen blokkolna.

A kapu három jelet fogad el: van már 01/02 · van felismert irat · teljesen üres (frissen létrehozott mappa, nincs is mit mozgatni). A többi almappa **kimarad**, felsorolva; ha egy sem felel meg, a párbeszéd nem engedi a mozgatást, csak a kiválasztott útvonalat mutatja. A „Csak a mappák létrehozása” is ugyanerre a szűkített körre hat.

**A képek feltétel nélküli besorolása maradt** (a felhasználó döntése): a dolgozói mappában lévő kép definíció szerint nyersanyag, akárhogy hívják — így a rosszul elnevezett arckép is a helyére kerül, és ezt a kapu önmagában elég biztonságossá teszi.

Önteszt: +7 eset (`MUNKAMAPPA-KAPU`), köztük az is, hogy a kapu **nélkül** a képek valóban elmozdulnának — egy ellenőrzés, ami nem tud bukni, semmit nem ér. GUI: +3 eset.

### 12.7 Metaadat: miért csak a generált PDF-en

Felmerült, hogy a metaadat vegye át az azonosítást. A kód ma **szándékosan kitörli** a metaadatot (`CLEAN_META`), és csak a `title`-t tölti a fájlnévből; a `subject`/`keywords` szabad. Egy mérésen alapuló részlet: a `shrink_steps` újra megnyitja és visszaírja a dokumentumot, tehát a metaadat **átéli az 5 MB-os tömörítést**; a `rasterize_doc` viszont újra `CLEAN_META`-t tesz rá, ott elveszik.

Amiért mégis csak egy ponton használjuk:

- **A szkennelt fájlon nincs semmi** — épp az, amit osztályozni akarunk, a szkennerből jön. A bélyeg tehát nem azonosít, csak **kizár**: a hiánya a jel.
- **A nyomtatás–aláírás–szkennelés kör mindent elveszít.** A docx metaadatából papír lesz; a docx-bélyeg ezért nem ér semmit, amit a `D`/`E` jel ne adna meg.
- **Az Iktató bájtazonos másolatot készít és ellenőriz** (`_copy_verified`, `write_pdf_verified`). Iktatáskori bélyegzés ezt a mért tulajdonságot törné fel.
- **Ránézésre nem látszik:** a PDF `keywords` az Intézőben alapból nincs oszlopként. Az átláthatóságot a mappaszerkezet adja, nem a metaadat.
- **Második igazság kockázata:** ma a fájlnév az egyetlen igazság, az egész felismerés arra épül. Ha a kettő szétcsúszik (átnevezés), el kell dönteni, melyiket hisszük.

Ezért a bélyeg **egyetlen dolgot dönt el**: generált-e a PDF vagy szkennelt (12.6). Ott bizonyíték, és nem lehet átnevezéssel elrontani.

> **2026-10-01:** ez a döntés **bővült** — a bélyeg immár a dolgozót és a doktípust is hordozza, a fájlnév elsődlegességének megtartásával. Lásd **13.5**.

**Ami nagyságrenddel többet adna, de nincs a tervben:** a papírra nyomtatott QR/vonalkód az egyetlen jel, ami átéli a kört — akkor a szkennelt köteget az Összeállító magától szét tudná osztani, és a kézi címkézés nagyrészt elmaradna. Ára: dekóder-dependencia (`zxing-cpp`/`pyzbar`) egy ma kétfüggőségű offline eszközben, plusz mérés, hogy a helyi szkennerbeállítással olvasható-e. Csak mérés után döntendő.

### 12.8 Fázisok

```
F1    konstansok, célmappa, makedirs, hely-alapú E/F cella, mappalétrehozó gomb
      → ellenőrzés: --test zöld; kézi kör egy próbadolgozón (iktatás → F,
        DocGen-fájl → E, gyökérben hagyott PDF → ~)
F4.5  DocGen: fs-service felújítás (DocGen/TERV-mappaszerkezet.md)   ← blokkoló
F5    DocGen: célmappa 01_Elokeszitett + bélyeg a generált PDF-en
F2    migrációs előnézet + mozgatás (a bélyegre épül)
      → ellenőrzés: migracio_terv önteszt; éles futtatás előnézetből
F3    arckep szabály-flag + a jelölő az Iktatóban és az Összeállítóban
      → ellenőrzés: target_subdir mindkét állásra; test/gui.py bővítés
F4    Arckép fül iktatása
      → ellenőrzés: GUI-teszt, naplósor, a 01 → fotó → 02 kör végigjátszása
```

**A sorrend nem cserélhető:** az F5-nek az F2 **előtt** kell lennie, különben a migráció a bélyeg nélküli régi DocGen-kimenetet „szkennelt”-nek látja, és tévesen `02`-be tenné. Amíg az F5 nincs kész, minden új generálás után besorolatlan (`~`) sorok jelennek meg a mátrixban — ez a szigorú jel választott ára.

### 12.9 Tesztterv

- **Önteszt:** a szkennelt fixture átírása 01/02 szerkezetre (ma `who\Mellekletek\utlevel.pdf`-et használ, ami az új rendben `~` lenne); új esetek: hely-osztályozás, `_ok` csak `F`-re, `target_subdir` mindkét jelölőállásra, `backup_existing` a dolgozó gyökerébe, `migracio_terv` besorolás.
- **`test/gui.py`:** az új jelölő, a mappalétrehozó és a migrációs párbeszéd.
- **`test/frissit.py`:** a hamis „céges gép” fixture-je kapjon 01/02 szerkezetet — annak igazolására, hogy a frissítő a dolgozói mappákhoz nem nyúl.
- **`.gitignore`:** új projektfájl nem keletkezik (minden a `pdf-muhely.py`-ba megy), tehát az engedélyező listát nem kell bővíteni. Külön `tools/migracio.py` esetén fel kell venni, különben a klón-próba bukik.

### 12.9.1 Elkészült (2026-09-29) — és amit a megvalósítás megtanított

**F1–F4 kész**, a tervek szerint. Önteszt: 74 → **116**, GUI: 54 → **71** (a munkamappa-kapuval együtt, 12.6.1).

Három dolog derült ki menet közben, és mindhárom javítást igényelt a terven túl:

- **A `norm()` szándékosan kitörli az „alairt” szót** (a szabályillesztéshez), tehát az `aláírt` utótagot **soha nem** találná meg. A migráció ezért `strip_accents`-et használ. Az első változat emiatt *minden* PDF-et a feltölthetőbe tett volna — az önteszt kapta el.
- **Az előkészített + aláírt példány nem „több PDF”.** A `duplicates` eddig minden azonos típusú PDF-et ütközésnek vett; a 01/02 szerkezetben viszont az `EF` állapot a **normális**. A `duplicates` innentől csak a `02_Feltoltheto`-n belüli többes példányt jelzi — feltöltéskor csak ott van mit eldönteni.
- **A „helyben tömörítés” útja a forrás = cél egyezésen áll** (Áttekintő → jobb klikk → tömörítés az Iktatóban). Ez csak akkor működik, ha a túlméretes PDF már a `02_Feltoltheto`-ban van — ott a célmappa ugyanaz. A GUI-teszt fixture-je ezért a 02-be került; a gyökérben hagyott túlméretes PDF-et előbb be kell sorolni.

**A bizonytalan migrációs eset iránya a terv-ellenőrzésen javult** `02`-ről `01`-re (12.6), mielőtt egy sor kód is készült volna.

### 12.10 Amit szándékosan nem építünk

- Nincs beállítható mappanév — a két név konstans.
- Nincs undó a migrációra (az előnézet a védelem).
- Nincs harmadik mappa (`00_Egyeb`) a fel nem ismert fájloknak.
- Nincs általános 01/02 célválasztó az iktatásban — csak a formanyomtatvány jelölője. Egy ott hagyott kapcsoló csendben kivenné az iratot a beadhatóságból.
- Nincs docx-metaadat és nincs iktatáskori bélyegzés (12.7).

## 13. Egyszerűbb felület, körülvágás, emlékezet (2026-10-01)

### 13.1 Hibajavítás: a fotó nélküli formanyomtatvány a feltölthetőbe ment

**A tünet:** az aláírt formanyomtatvány arckép nélkül is a `02_Feltoltheto`-ba
került, pedig a 12.4 szerint csak bepipált jelölővel kerülhet oda.

**A gyökér-ok nem a logikában volt**, hanem a mentett szabályfájlban: a repóval
szállított `attekinto-szabalyok.json` még az `arckep` mező **előtt** készült, a
betöltő pedig `d.get("arckep", False)`-szal olvasta. Így a `forma` szabály
`arckep`-je minden valódi gépen `False` lett — és a `target_subdir` helyesen,
de hamis adatból dolgozva `02`-t adott. A GUI-teszt épp ezért **nem** fogta meg:
ideiglenes mappában fut, szabályfájl nélkül, tehát a beépített (jó)
alapértelmezést látta.

**A javítás két rétegű**, mert a felhasználók gépén már ott van a régi fájl:

1. `DEFAULT_ARCKEP = {r.id: r.arckep for r in DEFAULT_RULES}` — a kulcs nélküli
   (régi) szabályfájlnál a jelölő a beépített alapértelmezésből pótlódik, nem
   `False`-ra esik. Az id szerinti pótlás azért jó, mert a saját szabályokat
   nem érinti (azoknál `False`), a `forma`-t viszont helyreteszi.
2. A szállított JSON újraírva, benne a mezővel — friss telepítésnél se múljon
   a pótláson.

**Tanulság a hibaosztályra:** új `Rule`-mező esetén a `get(..., False)`
alapértelmezés néma adatvesztés a már kint lévő fájlokban. Az önteszt ezért
kapott egy esetet, ami **mezőt nem ismerő** szabályfájlt ír ki, és ellenőrzi,
hogy a formanyomtatvány célja `01` marad.

### 13.2 Felület: három munkafolyamat-fül + Eszközök

A hat egyenrangú fül nem mutatta a munka sorrendjét, és a napi munkához csak
három kell. Az új szerkezet (a felhasználó választása):

| felső sáv | tartalom |
|---|---|
| `1 · Összeállító` | szkennelt köteg → iratok |
| `2 · Iktató` | egy PDF a dolgozó mappájába |
| `3 · Áttekintő` | mátrix: ki adható be |
| `Eszközök` | alfülek: Arckép elhelyezés, Összefűzés, Raszterizálás |

A sorszám a sorrendet mondja ki, az eseti műveletek egy szinttel lejjebb
kerültek. Az `App.tabs` **kulcsai nem változtak** (a fülök egymást név szerint
érik el) — csak a szülő widget és a feliratok. Két helyen kellett hozzányúlni:

- `active_tab()` lemegy az Eszközök alfülére — különben az Arckép fül globális
  gyorsbillentyűi (`Ctrl+←/→`) csendben elhallgatnának, mert a `_guard` az
  `active_tab() is self` egyezésen áll.
- `App.show(tab)` váltja a fület: alfülnél előbb a belső notebookot állítja.
  A `goto_*` átirányítások ezt használják (`nb.select` helyett).

Ritkítás a két legzsúfoltabb sávon (Iktató): a „Mappák frissítése” elhagyva —
a felső sáv **Frissítés** gombja ugyanezt teszi —, a nagyítás `−`/`+` gombjai
is, mert a görgő ugyanaz, és a mérték a címkén látszik. Az **Illeszt** maradt.

### 13.3 Minimális képszerkesztő: körülvágás

Eddig a szkennelt arckép szegélyét Paintben kellett leszedni. Az Arckép fül
`Körülvágás…` gombja egy dialógust nyit: a képen téglalapot húzva a megtartandó
rész jelölhető ki, a `Körülvág` alkalmazza, a `Teljes kép` visszavonja.

**A megvalósítás egy sor**, mert a kép eddig is egylapos PDF-ként élt
(`convert_to_pdf`): a vágás a lap **cropboxának** szűkítése
(`open_image_pdf(path, crop)`). Innentől a `page.rect` is szűkebb, tehát az
alapméret-számítás, az előnézet és a `show_pdf_page` **változtatás nélkül** a
vágott képpel dolgozik. A kép fájlja soha nem módosul: a vágás a betöltött
példány tulajdonsága, ezért visszavonható, és új kép betöltésekor nem öröklődik.

Szándékosan **csak vágás** van: forgatás az elhelyezésnél amúgy adott,
fényerő/kontraszt a szkennelt fotóknál nem volt kérés. Ha kell, ugyanebben a
dialógusban a pixmapra tehető szűrő.

### 13.4 Emlékezet: utoljára használt útvonalak és doktípus

Új fájl a program mappájában: `emlekezet.json` (`recall` / `remember`).
Megjegyzi a **munkamappát**, a **mellékletek** mappáját (Iktató és Összeállító
forrásválasztója), a nyomtatvány- és arcképmappát, valamint az Iktatóban
utoljára választott **doktípust**.

Döntések:

- **Külön fájl**, nem a szabályfájlban: gépenként más, és a `.gitignore`
  engedélyező listája így automatikusan kihagyja — dolgozói útvonal nem kerül
  a repóba. A frissítő sem nyúl hozzá (nincs a ZIP-ben).
- **Útvonalat csak létező mappára ad vissza** (`recall`): pendrive vagy hálózati
  meghajtó közben eltűnhet, és egy halott `initialdir` a párbeszédet
  kiszámíthatatlan helyre nyitná.
- **Csendben bukik** mentéskor: kényelmi funkció, nem akadályozhatja a munkát.
- Az **arckép-jelölőt szándékosan NEM jegyzi meg** — az beragadva téves `02`-t
  okozna (12.4). A doktípus megjegyzése ártalmatlan: a jelölő típusváltáskor
  amúgy visszaáll.

### 13.5 Bélyeg: dolgozó és doktípus a metaadatban (2026-10-01)

**A kérdés:** elhelyezhető-e a PDF-ben, hogy tőlünk származik, melyik dolgozóé
és milyen típusú — hogy egy **átnevezés** ne vigye el ezt a tudást.

Igen, és a 12.7 tiltása nem volt elvi, hanem a „második igazság" kockázatáról
szólt. A bővítés ezért **két felhasználói döntésen** áll:

1. **Bélyeg az Iktató másolatára is** (nem csak amit a program újraír) — ez a
   napi fő útvonal, a szkennerből jövő PDF.
2. **A fájlnév marad az elsődleges igazság**, a bélyeg tartalék.

#### A bélyeg helye és alakja

A PDF `/Keywords` mezője, pontosvesszős `kulcs=érték` párokban:

```
pdf-muhely=1;dolgozo=Kiss Anna;tipus=Útlevél;szabaly=utlevel;hely=02_Feltoltheto;datum=2026-10-01
```

- **Miért a `keywords`:** átnevezést és másolást túlél, és mérés szerint az
  5 MB-os tömörítést is (12.7) — a `shrink_steps` újra megnyitja és visszaírja.
- **Az idegen kulcsszavak megmaradnak:** a `stamp_keywords` csak a *saját*
  kulcsait cseréli. Így a **DocGen-bélyeg sem sérül** (azt a `producer` és a
  `keywords` együtt hordozza), tehát a Rendezés generált/szkennelt döntése áll.
- A `szabaly` (szabály-id) a gépi azonosító, a `tipus` az olvasható név; a
  `hely` az az alkönyvtár, ahova iktattuk. A `;` és `=` az értékekből kiesik.

#### Hogyan kerül rá — és mit adtunk fel

| útvonal | hogyan |
|---|---|
| Összeállító | `set_stamp` a memóriabeli iraton, kiírás előtt (iratonként, a saját `hely`-ével) |
| Arckép elhelyezés | ugyanaz, a raszterizálás **után** (a `rasterize_doc` `CLEAN_META`-t tesz rá, ott elveszne) |
| Iktató, sima másolás | `stamp_pdf_file` a `.part`-on, **növekményes** mentéssel |
| Iktató, tömörítő útvonal | `write_pdf_verified(..., stamp=…)` |

**A bájtazonos másolás garanciája helyére a növekményes bélyegzés lépett**
(a felhasználó döntése). Ez a lehető legkisebb engedmény: a növekményes mentés
**függelékként** írja a változást, tehát a forrásfájl bájtjai a célban
*előtagként* továbbra is bitre ott vannak — ezt a GUI-teszt közvetlenül méri
(`startswith`), nem csak a méretet. Az ellenőrzés sorrendje: méret = forrás →
megnyitható PDF → bélyegzés → oldalszám és visszaolvasott bélyeg. Ha a
bélyegzés bármiért nem megy, **tiszta másolat kerül ki** (az üzenet végén
„· bélyeg nélkül"): a bélyeg kényelmi adat, nem iktatási feltétel.

#### Mire használjuk (a név az elsődleges)

- **Áttekintő:** csak ott nyitja meg a PDF-et, ahol a **fájlnevet egyik szabály
  sem ismerte fel**. Ha ott van bélyeg, az irat a típusához számít — tehát egy
  átnevezett (`IMG_20260101_0001.pdf`) iktatott irat nem esik ki a mátrixból.
  A hiánylista jelzi: „átnevezve … (a bélyeg alapján felismerve)".
- **Rendezés:** a bélyeg **bizonyíték, nem tipp** — a `hely` szerint viszi
  vissza a fájlt (`biztos=True`), a találgatós ág elé.
- **Idegen irat:** ha a bélyeg más dolgozót nevez meg, a hiánylistában
  `IDEGEN` sor, a beadható soroknál `⚠ idegen bélyeg`. Ez **csak** a név szerint
  fel nem ismert fájlokra néz — minden PDF megnyitása egy 40 dolgozós
  munkamappában lassú lenne, és a név szerint felismert fájl amúgy is a saját
  helyén van.

#### Amit a bélyeg nem tud

- **A nyomtatás–aláírás–szkennelés kör mindent elveszít.** A szkennerből jövő
  lap csak az iktatáskor kap bélyeget — azelőtt nincs mit olvasni. Ezt továbbra
  is csak papírra nyomott QR/vonalkód oldaná meg (12.7 vége).
- **Visszamenőleg nincs bélyeg:** a már kint lévő iratok csak újraiktatással
  kapnák meg.
- **Az Intézőben nem látszik** (a `keywords` nincs oszlopként) — az
  átláthatóságot továbbra is a mappaszerkezet adja.
- **Ütközéskor a fájlnév nyer.** Ha a név felismerhető, a bélyeget meg sem
  nézzük: egy igazság van, a második csak ott szólal meg, ahol az első hallgat.

### 13.6 Hat kért funkció (2026-10-01)

A felhasználó választása egy javaslatlistából. Az **arckép auto-trim**, az
**üres oldalak kiszűrése** és a **QR** szándékosan kimaradt (az utóbbi két repót
és új függőséget érint, előbb mérés kell).

#### Fényerő és kontraszt a vágódialógusban

A `CropDialog` két csúszkát kapott (−100…100). A számolás **256 bájtos
átalakító táblával** megy (`level_lut`), amit a `bytes.translate()` C-sebességgel
alkalmaz — pixelenkénti Python-ciklus egy 2000×3000-es fotón másodpercekig
tartana. Az élő előnézet a **kicsi, megjelenített** pixmapra fut, ezért azonnali.

Egy fontos eltérés a vágástól: a vágás a cropbox szűkítése, tehát
**veszteségmentes**; a szintezés viszont a képpontokat írja át, ezért
**újrakódolja** a képet (JPEG, Q92). Ezért csak akkor fut le, ha tényleg
állítottak rajta (`if not levels or not any(levels)`), és a felbontás nem a
`get_pixmap()` 72 DPI-s alapja, hanem a beágyazott kép valódi mérete
(`image_px_scale`) — különben a szkennelt fotó élessége elúszna.

#### Ellenőrzés és utólagos bélyegzés (Áttekintő → „Ellenőrzés…")

Ez tömi be a 13.5 egyetlen lyukát: a **már kint lévő iratokon nincs bélyeg**.
Az `audit_folder` **egyszer** nyit meg minden dolgozói PDF-et, és öt dolgot ad:

| csoport | mit jelent | tehetünk vele |
|---|---|---|
| `stampable` | nincs bélyeg, de a **név és a hely együtt** megadja, mit írjunk | egy gombbal bélyegezhető |
| `unknown` | se bélyeg, se felismert név | kézi munka — **találgatva nem bélyegzünk** |
| `foreign` | a bélyeg más dolgozót nevez meg | eltévedt irat, nézd meg |
| `mismatch` | a bélyeg típusa ≠ a fájlnév típusa | a **név** az igazság (13.5) |
| `dupes` | tartalom-azonos PDF-ek (SHA-1) két néven | melyik a jó? |

Az `audit_folder` az **egyetlen** hely, ahol minden PDF-et megnyitunk; a mátrix
szándékosan csak a név szerint fel nem ismerteket nézi meg (13.5), mert 40
dolgozónál az összes PDF megnyitása minden frissítésnél lassú lenne. Ez tehát
kézi, gombra induló művelet, ami állapotjelzést ad közben.

Az utólagos bélyeg a **szabály nevét** írja `tipus`-nak (az Iktató-oldali
típusnév a fájlnévből nem visszafejthető), a `szabaly`-t pedig a szabály
id-jéből — az olvasó amúgy is az id-t keresi először.

#### Kötegelt tömörítés (Áttekintő → „Tömörítés…")

Eddig minden 5 MB feletti PDF-et egyenként kellett az Iktatóban tömöríteni.
Most egy előnézet (dolgozó, fájl, méret), majd egy lánc, fájlonként
`shrink_later`-rel — a felület a lépcsők között él, mint az Iktatóban. Minden
fájlnál: `backup_existing` (a `.eredeti\` marad a visszaút), `write_pdf_verified`
oldalszám-ellenőrzéssel, és **naplósor** (`TOMORITVE 18.3 MB->0.7 MB`). A bélyeg
a tömörítést átéli (12.7), tehát nem kell újrabélyegezni.

Ha a legerősebb lépcső után is a korlát fölött marad, a fájl **akkor is** a
tömörített változatra cserélődik (az kisebb), de a dialógus végén névvel
felsorolja őket — ott kevesebb oldalra kell bontani.

#### Címke a szövegrétegből (Összeállító)

Lásd `szetvago-terv.md` **17.**


### 13.7 A felület: kódból rajzolt gombok és modern téma (2026-10-02)

**A kérés:** impozáns, de jól használható felület, saját magunk generálta
gombokkal, modern megjelenésben.

#### A kulcsdöntés: a grafika a miénk, a widget marad ttk

A gombok, mezők, fülek, jelölők és csúszkák háttérgrafikáját **futásidőben
rajzoljuk** (pymupdf → élsimított PNG → `PhotoImage`), és
`ttk.Style.element_create(..., "image", …)`-szal **9-slice képelemként** kötjük
a témába. Ettől a widget **igazi `ttk.Button` marad**:

- minden meglévő hívás (`state(["disabled"])`, `invoke()`, `cget("text")`),
- a 98 GUI-teszt egy sora sem változott emiatt,
- az állapotok (`active`, `pressed`, `disabled`, `focus`, `selected`) a ttk
  motorjától jönnek, nem nekünk kell egérfigyelést írni.

Az alternatíva (saját `Canvas`-gomb osztály) ugyanezt a látványt adta volna, de
újra kellett volna írni az állapotkezelést, a fókuszt, a billentyűkezelést és a
teszteket. **A legkisebb kód, ami a kért látványt adja.**

#### Mi készül kódból

| elem | hogyan |
|---|---|
| gomb, mező, fül, kártya | `round_png` — lekerekített téglalap, opcionális árnyékkal és színátmenettel |
| lágy árnyék | három egyre nagyobb, egyre halványabb lekerekített alak a forma alatt (nincs elmosás-szűrő, és nem is kell) |
| színátmenet | vízszintes sávok; a sáv **a sarok köríve szerint beljebb kezd**, különben az utolsó sáv visszaszögletesítené a formát |
| 17 ikon | `ICON_PATHS` — vonalrajz 24-es rácson, a feliratból társítva (`BTN_LOOK`) |
| jelölő, rádió, chevron, csúszkagomb | `_box_png`, `_radio_png`, `_chev_png`, `_dot_png` |
| vászon-elemek (csempe, oldalkártya, vászongomb) | `round_pts` + `canvas_card` — a Tk vászon nem tud rádiuszt |

Két apró, de fontos részlet, amit mérés derített ki:

- A ttk a **`*.Scale.slider`** és **`*.Scrollbar.thumb`** *nevű* elem alapján
  pozicionál. Saját néven (`Modern.sthumb`) a csúszkagomb a bal szélre ragadt —
  ezért a beépített neveket írjuk felül.
- A `pix.n` **tartalmazza** az alfát, a minta lépésköze tehát `n`, nem `n+1`.

#### Az ikonok társítása a feliratból

A `BTN_LOOK` egy helyen mondja meg, melyik feliratú gomb melyik ikont és
stílust kapja; a `decorate()` ezt járja végig rekurzívan. Így a kódban lévő
~60 gombhívás egyike sem változott, és **a dialógusok is megkapják**: a
`root.bind_class("Toplevel", "<Map>", …)` minden később nyíló ablakra lefuttatja.
ponytail: felirat szerinti társítás — új gomb ikon nélkül is rendben van, és az
önteszt méri, hogy minden bejegyzés létező ikonra mutat.

#### Szerkezet

- **Sötét parancsfejléc**: név, verzió, munkamappa — és a fülsáv is **ebben**
  folytatódik, fehér „pirula” a kiválasztott fülön. Így egy összefüggő fejléc
  lett belőle, a tartalom pedig világos lapon ül.
- **Állapotsor** alul, színes ponttal; a `pack` miatt a **fülek előtt** kerül a
  helyére, különben kis ablakban kiszorulna.
- **Egy paletta** (`UI`) adja a ttk-téma, a vásznak és a mátrix színeit is —
  eddig kétféle rajzolás kétféle színkészlettel ment.
- A **doktípus-színek** (`LABEL_COLORS`) azonos tónusú készletre cserélve; az
  önteszt méri, hogy mindegyiken olvasható marad a fehér szöveg.
- Az ablak mérete a **képernyőhöz** igazodik: a fix 1200×840 egy 864 képpont
  magas munkaállomáson a tálca alá lógott.

#### Világos felület — az első kör visszajelzése után

Az első változat sötét parancsfejlécet és sötét („fotós") munkavásznat kapott.
A használó visszajelzése: **túl sötét és kevésbé átlátható**. Egy egész napos
irodai munkához igaza van: a sötét nagy felületek fárasztanak, és a fehér
iratbélyegképek mellett a kontraszt is ugrál. A javítás:

- a fejléc **világos**, vékony színátmenetes akcentuscsík zárja;
- a fülsáv a lapon ül, a kiválasztott fül fehér lap akcentus-aláhúzással;
- az előnézeti és bélyegkép-vászon **világos „világítóasztal"** (`#e9edf5`) —
  a rajta lévő feliratok sötétre fordultak, az árnyékok világos szürkére;
- a doktípus-lista **halvány árnyalatokat** kap sötét szöveggel (`tint()`), a
  telített szín csak a bélyegkép címkesávján marad, ahol egy-egy folt van;
- **egy felület**: a panelek (LabelFrame) is a lap színén ülnek, csak kerettel.
  Így a jelölők és feliratok mögött nincs eltérő színű folt — a korábbi
  fehér-kártya/szürke-lap keverék pont ezt okozta.

#### A lekerekített él levágódása

Nagyításban több gomb jobb oldala **szögletesre vágódott**: a kódból rajzolt
grafika rendben volt, de a gomb nem fért el. A fix szélességű jobb panelen
(`PANEL_W`) az ikon és a nagyobb belső margó miatt a gombsor túlnyúlt, és a
szülő levágta a kerekítést. Három helyen javítva: kisebb gombmargó (10 px),
kisebb ikon (15 px), szélesebb panel (318 px) — és ahol két vezérlő egy sorban
már nem fért el (Utótag + jelölő), ott **két sor** lett belőle. Tanulság: a
grafika és az elrendezés együtt jár; a szép él nem ér semmit, ha a widget
kisebb, mint a kép.

#### A legördülő levágott sarka — a ttk ablakháttere

A gombok után a **legördülő mezők** sarka látszott levágottnak. Az ok más volt,
mint a gomboknál: a ttk a widget **ablakát** a stílus `background` színével
tölti ki, MIELŐTT az elemek rajzolnának. A `TCombobox`-ra fehér (`card`) háttér
volt beállítva, így a lekerekített sarkon kívüli — szándékosan átlátszó —
képpontok is fehérek lettek, és a sarok szögletesnek látszott a világosszürke
lapon. A háttér tehát a **környezet** színe kell legyen (`bg`), a mező fehérjét
a rajzolt kép adja. Ahol a mező fehér lapon ül (fejléc), ott külön stílus
(`Head.TEntry`) viszi a fehér hátteret.

A **nyitott** lista külön ablak (`ComboboxPopdown`): kerete a clam sötét,
szögletes `ComboboxPopdownFrame` stílusa volt, háttere rendszerszürke. Mindkettő
a palettából jön. Mérés: a GUI-teszt a stílus háttérszínét és a valódi popup
listájának színeit nézi.

#### Hogyan látja a következő fejlesztő, mit változtatott

`python tools/ui-kep.py <fül> <kimenet.png>` — demóadattal elindítja az appot és
lefotózza az ablakot (a dialógust is). A GUI-teszt a **működést** méri, a
megjelenést nem: ez a fotó az egyetlen visszacsatolás a látványra.

### 13.8 A felület sebessége — mérés és három ok (2026-10-02)

**A bejelentés:** „a GUI rettentő lassan reagál, a fülváltás és az átméretezés
laggol, az alkalmazás használhatatlan". Jogos volt; a mérés három különböző okot
talált, és egyik sem a saját rajzolókód futásideje volt.

#### Mérés először, javítás utána

Izolált próba (64 gomb, ablak-átméretezés 20 lépésben):

| változat | idő / átméretezés |
|---|---|
| alap clam téma (kép nélkül) | 46 ms |
| saját téma, **alfás** PNG-kkel | **888 ms** |
| saját téma, átlátszatlan PNG-kkel | 360 ms |
| saját téma, **széles** átlátszatlan PNG-kkel | **38 ms** |

A `cProfile` nem mutatta meg, mert minden idő a `tk.call`-on belül telt: a Tk-t
nem lehet Pythonból profilozni. A választ az összehasonlító mérés adta.

#### 1. ok: az alfacsatorna szoftveres kompozitálása

A Tk **minden egyes újrarajzolásnál** összemossa az alfás képet a háttérrel.
A lekerekített sarkokhoz átlátszó PNG-t használtam, tehát ez minden gombon,
mezőn és fülön lefutott, folyamatosan. A javítás: a kép a saját felületére
**előre ráégetve** készül (`round_png(..., bg=…)`), így átlátszatlan. Mivel a
panelek és a lap színe immár egységes (13.7), két változat elég: lapra és fehér
kártyára (fejléc). Alfa csak a kis ikonokon maradt.

#### 2. ok: a Tk CSEMPÉZI a 9-slice nyújtható sávját

Nem skálázza. Egy 30×30-as képből egy 100 képpontos gombhoz tucatnyi csempe
lesz; **minél kisebb a kép, annál lassabb** (12×12: 1596 ms, 30×30: 321 ms,
240×40: 50 ms, 420×48: 37 ms). A felületi képek ezért **420×48**-asak.

Ennek ára volt: a képelem alapértelmezésben a kép méretét kéri minimumként, így
minden gomb 420×48-ra hízott. A `width=1, height=1` elemopció oldja meg — a kép
marad széles, a widget a tartalmához igazodik.

#### 3. ok: minden `<Configure>` eseményre azonnali újrarajzolás

Átméretezés közben ez másodpercenként tucatszor jön. A fejléc akcentuscsíkja,
az Összeállító rácsa és a mátrix mostantól **késleltetve** rajzol újra
(`debounce`, 60 ms), és a csík fix 28 sávból áll, nem képpontonkéntiből.
A vásznon a kártyák sarka 5 helyett 3 pontból áll soronként, és elmaradt a
vászon-árnyék: a mélységet a widgetek adják.

#### Eredmény és ami marad

| művelet (40 dolgozó, 1200×760) | előtte | utána |
|---|---|---|
| fülváltás → Összeállító | 372 ms | **16 ms** |
| fülváltás → Áttekintő | 199 ms | **30 ms** |
| fülváltás → Iktató | 76 ms | **8 ms** |
| átméretezés (Iktató) | ~90 ms | ~80 ms |
| átméretezés (Áttekintő mátrix) | ~135 ms | ~135 ms |

**Amit nem javítottam, és miért:** a mátrix átméretezése a felület-átalakítás
ELŐTT (v1.16) is 108 ms volt — a vászon ~1500 elemét a Tk minden expose-ra
újrafesti. Ez nem a téma költsége, hanem a mátrixé; a megoldás a láthatatlan
sorok kihagyása (virtualizálás) lenne, ami a találati/görgetési logikát is
érinti. Külön feladat, mérés után.

#### Két apró, de makacs hiba ugyanebből a körből

- **A hover „éles sarka":** az árnyék kilógott a kép szélén, és a 9-slice a
  levágott szélt csempézte végig. A `pad` megnövelése (4 képpont) megoldotta.
- **A fejléc gombjainak sarka:** a `decorate()` felülírta a kézzel megadott
  `Head.TButton` stílust, így a gombok a lap (szürkés) hátterét kapták a fehér
  fejlécen. A `decorate()` mostantól nem nyúl a kézzel beállított stílushoz.

#### A nyitott legördülő éles sarka

A lista **külön ablak** (`ComboboxPopdown`), a sarkát CSS-szerűen nem lehet
lekerekíteni: a Windows **ablakrégióját** vágjuk körbe
(`CreateRoundRectRgn` + `SetWindowRgn`). Buktató: a Tkinter ennél az ablaknál az
eseményben csak egy **útvonal-sztringet** ad, nem widgetet — ezért kell az
értelmezőt külön átadni. A GUI-teszt a `GetWindowRgn`-nel ellenőrzi, hogy a
régió tényleg fent van.

#### Ikonok

A „Visszavonás" és a „Frissítés" jele értelmezhetetlen volt. Az ikonok mostantól
körívet is tudnak (`_arc`), és hét jel újrarajzolva: visszavonás (balra forduló
nyíl), frissítés (körbe futó nyíl nyílheggyel), nagyító (valódi kör), tömörítés
(két nyíl egy vonal felé), irat (behajtott sarkú lap), szétosztás (olló),
mentés (lemez — eddig ugyanaz volt, mint az „archiválás"). A módszer: az egész
készletet egy lapra rajzolva, nagyítva **megnézni** — így derült ki, hogy a
`doc` törött, a `split` és a `close` ugyanaz, az `archive` és a `save` pedig
megkülönböztethetetlen.

### 13.9 Oldalankénti szétosztás az Iktatóban (2026-10-02)

**A helyzet:** egy 18 oldalas PDF érkezik, benne **18 dolgozó** ugyanolyan típusú
irata. Szét kell szedni dolgozónként — és erre a vonszolás a legjobb.

Eddig egyik fül sem tudta ezt:

- az **Iktató** a *teljes fájlt* viszi egy dolgozóhoz;
- az **Összeállító** több iratot tud, de **egy köteg = egy dolgozó** (14.1), itt
  viszont egy köteg = 18 dolgozó. A típus ellenben mindenkinél ugyanaz, tehát a
  címkézés sem kellene.

#### A megoldás: az Iktató „Oldalanként" módja

Bekapcsolva a vonszolás a **látott oldalt** viszi, nem a fájlt:

1. a felső sávban be az **Oldalanként (szétosztás)** jelölő,
2. az oldalt ráejted a dolgozó csempéjére,
3. a program **azonnal a következő, még el nem osztott oldalra lép**,
4. az utolsó oldal után a köteg kikerül a sorból („mind a 18 oldal elosztva").

Az oldal `extract_page`-dzsel kerül önálló, egyoldalas PDF-be: `insert_pdf`,
tehát **nincs újrarajzolás** — a szkennelt kép bitre ugyanaz marad. Innentől a
meglévő iktatómag fut: szabványos név, ütközéskezelés, `.eredeti\` mentés,
bélyeg (13.5), 5 MB fölött tömörítés, napló, visszavonás.

#### Döntések

- **Nem a fájl mellé, hanem a sorba:** oldalmódban a köteg a várólistában
  marad, amíg van el nem osztott oldala. Így látszik, mi van hátra, és a
  `↔ Oldal` lapozóval vissza lehet ugrani egy kihagyotthoz.
- **Fájlonként tartjuk, mely oldal ment el** (`done_pages`), nem egy számlálót:
  a sorrend nem kötelező, és a **Visszavonás** az oldalt vissza is adja a
  készletbe (a nézet is visszaugrik rá).
- **A napló az oldalszámot is rögzíti** (`…\koteg.pdf [3]`), különben a sorból
  nem derülne ki, melyik oldal hova került.
- **Egyoldalas fájlnál a mód nem él**: ott a bájtazonos másolás a jobb (13.5),
  nincs értelme újraírni a PDF-et.
- **Nem automatikus:** a mód kézi kapcsoló. Egy vegyes köteg (egy dolgozó több
  irata) továbbra is az Összeállítóba való; ha magától kapcsolna be, a gyakori
  eset romlana el a ritka kedvéért.

#### Egy hiba, amit ez a munka hozott felszínre

A vonszolás **célkiemelése** néma volt v1.17 óta: a csempe lekerekített
polygon lett (13.7), a kiemelés viszont `canvas.type(i) == "rectangle"`-t
keresett. Ejteni lehetett, de nem látszott, hova. Javítva, és a GUI-teszt
mostantól **valódi vonszolással** méri (press → motion → release), nem a
`_do_copy` közvetlen hívásával — így ez a hibaosztály nem jöhet vissza.

### 13.10 Szálak? Nem. Folyamat és virtualizálás (2026-10-02)

**A kérdés:** van-e értelme több szálra emelni az appot, mert „laggol a
műveleteknél”. **Mérés nélkül nem lehet eldönteni, ezért mértem.**

#### A szál itt rosszabb, mint a semmi

| mérés (27 MB-os szkennelt PDF, 16 magos gép) | eredmény |
|---|---|
| 4 tömörítés sorosan | 11 594 ms |
| ugyanaz **4 szálon** | 11 655 ms (**0,99×** — semmi gyorsulás) |
| a főszál ütemezése, miközben egy szál tömörít | **4,5 %** |

A PyMuPDF a tömörítés alatt **végig fogja a GIL-t**. Tehát a szál nemhogy nem
gyorsít, hanem a felületet *jobban* befagyasztja, mint a mai `after()`-lánc.
Ugyanez áll a bélyegképekre és az oldalrenderelésre is: mind PyMuPDF.

**Amire a szál jó:** a lemezműveletre. A `scan()` (150 dolgozó, 750 fájl, 64 ms)
alatt a főszál **98,8 %**-ot kap — a rendszerhívások elengedik a GIL-t. Ez a
jövőben hasznos lehet lassú hálózati meghajtón; most nem ez a szűk keresztmetszet.

#### Ami viszont működik: külön FOLYAMAT

| mérés | eredmény |
|---|---|
| 27 MB tömörítése a fő folyamatban | 9 778 ms, **a felület végig fagy** |
| ugyanaz külön folyamatban | 10 082 ms (+3 % indulás és adatmozgatás) |
| a fő folyamat ütemezése közben | **92,4 %** |
| a felület válaszideje közben (mérve) | átlag **0,1 ms**, max 25 ms |

Ezért a tömörítés mostantól külön folyamatban fut: `shrink_process()` elindítja
ugyanezt a szkriptet `--tomorit be.pdf ki.pdf` kapcsolóval, a lépcsőket a
gyermek a kimenetére írja, egy **olvasószál** (ez I/O, ott a GIL szabad) adja
tovább a felületnek. Ha a folyamat nem indítható, visszaesünk a régi
`after()`-láncra — a funkció nem veszhet el.

Miért nem `multiprocessing`: a Windows `spawn` a szülő `__main__` modulját
importálja újra a gyermekben. Az app `importlib`-bel is betölthető (GUI-teszt),
ott a gyermek a *tesztet* futtatná újra. A saját CLI-kapcsoló kiszámítható, és
az önteszt közvetlenül méri (`shrink_cli`).

#### A mátrix: csak a látható sávot rajzoljuk

A másik nagy tétel nem PDF-munka volt, hanem a Tk. 150 dolgozónál az Áttekintő
**4714 vászonelemet** tartott, pedig egyszerre ~25 sor látszik; minden
újrafestés (fülváltás, átméretezés, teljes képernyő) mindet átrajzolta.

- `_rows_view()` megadja a látható sortartományt, a rajzolás csak azon megy
  végig. A **puffer** (±14 sor) azért kell, hogy görgetéskor ne kelljen minden
  lépésnél újrarajzolni — csak akkor, ha a látható sáv kicsúszott a kirajzoltból.
- Az **üres cella** (`·`) háttértéglalapja elmaradt: a sor hátterével azonos
  színű, tehát láthatatlan volt, de a Tk minden festéskor átrajzolta. 150
  dolgozónál ez a cellák harmada.
- A találatvizsgálat koordináta-alapú (`int((y - hdr) // rh)`), ezért a
  virtualizálás a kattintást, a kurzort és a görgetést nem érinti.

| mérés, 150 dolgozó | előtte | utána |
|---|---|---|
| vászonelemek | 4714 | ~900 |
| mátrix újrarajzolás | 183 ms | 79 ms |
| teljes képernyő ↔ vissza | 203 ms | 155 ms |

#### Ami szándékosan maradt

A folyamatos ablak-átméretezés (az egérrel húzva) továbbra is ~90–150 ms/lépés:
ez a Tk teljes ablak-újrafestése, nem a mi kódunk. A fülváltás, a görgetés, a
szűrés és az iktatás viszont mind 10–90 ms, a tömörítés pedig már nem fagyaszt.

---

## 14. Egységes névmetodika és a megszűnt `.eredeti` mappa (2026-10-07)

### 14.1 A jelölők egy zárójelbe kerülnek

Eddig háromféle jelölés élt egymás mellett: `… aláírt.pdf` (Iktató),
`…_kesz.pdf` (Arckép → Mentés másként), és a `(2)` ütközés-sorszám. Mostantól a
jelölők **egy zárójelben, vesszővel, ékezettel és szóközzel** állnak:

```
Kiss Anna Útlevél (aláírt).pdf
Kiss Anna Tartózkodási engedély formanyomtatvány (aláírt, fotóval ellátva).pdf
```

- `MARK_SIGNED = "aláírt"`, `MARK_PHOTO = "fotóval ellátva"`.
- `target_name(..., photo=True)` teszi be a fotójelölőt. Ott kapcsol be, ahol a
  fotó ténylegesen felkerült: az Arckép fül iktatásánál mindig, az Iktatóban és az
  Összeállítóban az „arckép rajta” jelölő szerint — és csak `rule.arckep` típusnál.
- `add_mark(stem, mark)` a meglévő zárójelhez fűz, vagy újat nyit; idempotens, és
  a `(2)` ütközés-sorszámot nem olvasztja magába (az nem jelölőzárójel).

**Az illesztés nem romolhat el tőle.** A `norm()` a jelölőket az összehasonlítás
előtt kitörli (`alairt|signed|fotoval ellatva|kesz`), majd a kiürült zárójelet is.
Mérve: mind az 5 kötelező típus mind a 10 név-változatban (régi és új alak, fotóval
és anélkül) a helyes szabályra illeszkedik.

### 14.2 `.eredeti` mappa nincs többé

A felülírt példány eddig a dolgozó `.eredeti\` almappájába került. Mostantól a
**`01_Elokeszitett`** mappába megy, `(előző példány <időbélyeg>)` jelölővel:

```
Kiss Anna Előzetes megállapodás (aláírt, előző példány 2026-10-07 11-28-33).pdf
```

Így a felhasználó ott látja a mentést, ahol dolgozik, és nem kell rejtett mappát
keresnie. Az időbélyeg miatt több mentés sem ütközik.

**A buktató, amit ez okozna, és a védelem.** A 01-ben fekvő másolat ugyanarra a
doktípusra illeszkedne, mint az élő irat — minden felülírás után hamis
„több PDF ugyanahhoz” jelzést kapna az Áttekintő. Ezért a jelölőt az `is_noise()`
ismeri: a mentés nem irat. Egy helyen kellett megfogni, mert a mátrix
(`scan_person`), az ellenőrzés (`audit_folder`) és a Rendezés is ezen a szűrőn megy át.

### 14.3 Ellenőrzés

Önteszt 255/255 (új: „a mentést az is_noise kiszűri”), GUI 156/156. Valódi
mappaszerkezeten mérve: az új nevek a helyes szabályra illeszkednek, a 01-ben
fekvő mentés nem kap duplikátum-jelzést, és `.eredeti` mappa nem jön létre.

---

## 15. Az Áttekintő „hibás adat” panasza — a valódi ok (2026-10-07)

### 15.1 Amit a gyanú mondott, és amit a mérés

A bejelentés szerint az ellenőrző az **ékezetes betűkön** bukik el (`…alairt.pdf`),
illetve azon, hogy az irat **nem a megfelelő mappában** van.

**Az ékezet nem hibás.** A `norm()` mindkét oldalon ékezetet bont (`strip_accents`),
a `kw_hit` szintén. Mérve: `Meghatalmazas alairt.pdf` és `Meghatalmazás aláírt.pdf`
is a `meghat` szabályra illeszkedik; 5 név-változatból 5 helyes.

**A hely viszont hibás volt, és rosszabbul, mint hittük.** Az `audit_folder`-ben:

```python
if rule is not None and not amb and sub in WORK_DIRS:
    res["stampable"].append(…)
else:
    res["unknown"].append((who, rel))      # ← ide esett a gyökérben fekvő irat
```

A dolgozói mappa gyökerében fekvő iratnál `sub == ""`, tehát az `unknown` ágra
futott — és a párbeszéd azt írta rá, hogy **„BÉLYEG ÉS FELISMERT NÉV SINCS — kézzel”**,
holott a nevét tökéletesen felismertük. Mérve: 6 teszt-iratból 3 esett ide.
Ez a „hibás adat”.

Javítás: külön `misplaced` kategória (felismert név, rossz hely), saját szakasszal
a jelentésben és saját darabszámmal a fejlécben.

### 15.2 Áthelyezés iratonkénti jelölőnégyzettel

A mozgatás **nem visszavonható**, ezért nem lehet „mindent vagy semmit”. A Rendezés
párbeszéd olvasható `Text` előnézete helyett **`CheckList`**: soronként
jelölőnégyzet, „Mind kijelöl” / „Egyiket se” gomb, és az Áthelyezés gomb **tiltott,
amíg nulla az kijelölés** — legalább egy iratot ki kell választani.

`CheckList` = Treeview egy „☑/☐” oszloppal, nem sok `ttk.Checkbutton` egy görgetett
vásznon: 150 dolgozó × több irat mellett az utóbbi érezhetően lassú, a Treeview
viszont virtualizál. A bizonytalan („TIPP”) sorok halványan jelennek meg.

Az Ellenőrzés párbeszédből az *Áthelyezés…* gomb ugyanide vezet — nem építettünk
belőle másodikat.

**Buktató, amibe belefutottam:** a `CheckList.keys` attribútum **elfedi a Tk
`widget.keys()` metódusát**. Minden widgetfa-bejáró (teszt, segéd) elromlik tőle,
csendben és távol a hibahelytől. Ezért `_keys`.

### 15.3 Visszamenőleges átnevezés (`rename_plan` / `rename_apply`)

A meglévő iratok átnevezése a 14.1-es metodikára. A forrás sorrendje:

1. **a bélyeg** (`read_stamp`) — ez bizonyíték: oda iktattuk, az a típus;
2. a **felismert név** (`match_rule`), ebből az **Iktató doktípusa** (`rule_type`),
   nem a szabály neve — a szabály `name`-je oszlopcímke („Aláírt formanyomtatvány”),
   nem dokumentumnév. Enélkül `Kiss Anna Aláírt formanyomtatvány (aláírt)…` lenne (mérve).
3. ahol egyik sem dönt: **nem tippelünk** — a sor `biztos=False`, kijelöletlen,
   és a párbeszéd külön kiírja, hogy azokhoz nem nyúlunk.

Az „aláírt” jelölőt a bélyeg helye (`02_Feltoltheto`) vagy a név adja; a fotójelölőt
a név (`fotóval ellátva` vagy a régi `_kesz`). Nem generált iratra (útlevél, diploma)
nem kerül „aláírt”. Az átnevezés **soha nem ír felül** meglévő iratot: ütközésnél (2), (3).

Valódi iratokon mérve, egy körben:

```
szkennelt_0042.pdf                              -> John Doe Meghatalmazás (aláírt).pdf          [bélyeg]
John Doe Tart_eng_formanyomtatvany alairt_kesz  -> John Doe Tartózkodási engedély formanyomtatvány (aláírt, fotóval ellátva).pdf
John Doe Utlevel.pdf                            -> John Doe Útlevél.pdf
IMG_20260101.pdf                                -> (érintetlen: se bélyeg, se egyértelmű név)
```

A `DOC_TYPES_DEFAULT` első eleme ezért lett `Tart_eng_formanyomtatvány` helyett
**`Tartózkodási engedély formanyomtatvány`**: a fájlnévbe ez kerül.

### 15.4 Ellenőrzés

Önteszt 255/255, GUI **165/165** (új: „ELLENŐRZŐ: ROSSZ HELY, JELÖLŐNÉGYZETEK,
VISSZAMENŐLEGES ÁTNEVEZÉS” — 9 ellenőrzés: az ékezet nem bukik el, a gyökérben
fekvő irat „rossz helyen” és nem „ismeretlen”, a terv a bélyegből és a névből is
helyes, az eldönthetetlent békén hagyja, a Mind/Egyiket se működik, nulla
kijelölésnél a gomb tiltott, és az átnevezés után a lemezen az egységes nevek
vannak).

---

## 16. Felületi javítások (2026-10-07)

### 16.1 A kiválasztott fül: telt gomb, nem aláhúzás

A kiválasztott fül eddig fehér kártya volt, alul egy 3 képpontos akcentuscsíkkal
(`accent_bar`). Mostantól a **teljes felülete** akcentuskék, a felirat fehér
(`st.map(..., foreground=[("selected", "#ffffff")])`) — olvasható marad, és nem kell
a vékony csíkot keresni, hogy melyik fül aktív. Ugyanez az Eszközök alfülsávján.

### 16.2 Doktípus: nincs többé számbillentyű

16-nál több egyedi doktípusnál az 1–9 billentyű csak az **első kilencet** érte el, a
többi néma maradt — a felhasználó joggal hitte hibásnak. Egy fél megoldás rosszabb,
mint a kattintás, ezért a számbillentyűs címkézés megszűnt, és a sorszám a paletta
feliratai elől is eltűnt. A **Backspace** (címke le) marad, a nagyítóban is.
A súgószövegek és a „0 · címke le” gomb felirata ehhez igazodtak.

### 16.3 Raszterizálás: kép is

A fül fájllistája és a Tallózás ablaka eddig csak PDF-et mutatott; a képeket kézzel
kellett átállítani „Minden fájl”-ra. Mostantól `(".pdf",) + IMG_EXT`, és a futtatás
képnél `open_image_pdf`-fel nyit (egyoldalas PDF) — onnantól a lépés ugyanaz.

### 16.4 Az alkalmazás jele: irat köteg, nem „PM” monogram

Lekerekített jelvényen egy irat behajtott sarokkal, mögötte egy második lap. A két
egymásra csúsztatott lap a köteget mondja, a behajtott sarok az irat bevett jele —
ugyanaz a forma, mint az `ICON_PATHS["doc"]`, tehát a jel és az ikonkészlet egy
nyelvet beszél. A monogram betűfüggő volt és 32 képpontban mosódott.

**Két buktató, mérve a 10× nagyításon:**

- A korábbi „felső derengés” külön lekerekített kártya volt: az **alsó** sarkai is
  lekerekedtek, és félmagasságban benyomták a jelvény oldalát — nyolcszögnek látszott.
  Most egyetlen alakzat.
- A `round_pts` **sarkonként három pontot** ad (bélyegképekhez ez a gyors), amitől a
  32 képpontos jelvény szögletes. Itt egyszer rajzolunk, úgyhogy `smooth=True` —
  ingyen van, és valódi körívet ad.

### 16.5 A verzió utáni dátum levágódása

Az app **DPI-unaware**, GDI-skálázással fut (`SetProcessDpiAwarenessContext(-5)`, a
`__main__`-ban, szándékos egyszerűsítés). 125–150%-os Windows-nagyításnál a GDI
szélesebben rajzolja a szöveget, mint ahogy a Tk a logikai pixeleken kimérte — a sor
**vége** csúszik le, vagyis épp a verzió utáni dátum. A fejléc két felirata ezért
`DPI_SLACK = 14` képpont jobb oldali ráhagyást kap, ami a különbséget elnyeli.

**Amit nem tudtam igazolni:** ez a gép 100%-os nagításon fut, ott a felirat
mérve sosem vágódott le (`req_w == width == 214`). A javítás a kódban dokumentált
GDI-skálázásos egyszerűsítésre céloz; 125–150%-on érdemes visszanézni.

A `tools/ui-kep.py` mostantól átmásolja a `verzio.json`-t az ideiglenes mappába —
enélkül a felületfotón „ismeretlen verzió” állt, és épp ezt a sort nem lehetett megnézni.

### 16.6 Dialógusok: mérve rendben

Hat párbeszédet mértem egy 768 képpont magas képernyőre (Ellenőrzés, Rendezés,
Átnevezés, Beállítások, Hiánylista, Típusok): mind kifér. A Beállítások és a Típusok
magassága a szabályok/típusok számától **független** (12, 20 és 30 szabállyal is
618–620 px) — a listák belül görgetnek. Nincs mit javítani.

### 16.7 Ellenőrzés

Önteszt 255/255, GUI **173/173** (új: „FELÜLET: SZÁMOZÁS, FÜLSTÍLUS, RASZTERIZÁLÁS,
DIALÓGUSOK” — 7 ellenőrzés).

---

## 17. Egységes dolgozóválasztó (2026-10-07)

### 17.1 Hol választunk dolgozót, és hogyan

| Fül | Eddig | Most |
|---|---|---|
| Összeállító | legördülő (Combobox) | **közös `WorkerPicker`** |
| Arckép elhelyezés | **sima szövegmező** | **közös `WorkerPicker`** |
| Iktató | kattintás a dolgozói csempék rácsán + szűrőmező | változatlan |
| Áttekintő | `filter_text` — a mátrixot szűri | nem választó, változatlan |

Az Arckép fülön a nevet fejből kellett tudni, vagy a munkamappát átállítani a
dolgozó mappájára — pedig a lista ott volt a kezünkben. Az **Iktató nem kapott
legördülőt**: ott a dolgozói csempék rácsa *maga* a választéklista, és gazdagabb
is (látszik, hány irat van kint) — legördülővé alakítani visszalépés lenne.

A két fül nem két egyforma Combobox lett, hanem **egy közös widget**
(`WorkerPicker`): ugyanaz a szűkítés, ugyanaz a szóhasználat, ugyanaz az Enter-
viselkedés. Az `arrow_suffix` az egyetlen eltérés — az Arckép fülön a találat mögé
kiírja a célt (`→ Nagy Béla\02_Feltoltheto`).

A régi `ComposerTab._fill_who` / `_who_enter` / `_who_changed` hármasból így egy
`_who_changed` maradt, ami csak a `self.who`-t tükrözi.

### 17.2 A közben kiesett valódi hiba: a `set_folder` találgatása

A `PlacerTab.set_folder` eddig így döntötte el, hogy munkamappát vagy dolgozói
mappát kapott:

```python
if base in worker_dirs(parent):      # „a mappa benne van a szülője almappái között”
```

Ez viszont **szinte minden mappára igaz**, a munkamappára is — a `worker_dirs`
egyszerűen listázza az almappákat. Következmény: a `parent_dir` a munkamappa
SZÜLŐJE lett, és a dolgozóválasztóba a munkamappa neve került a dolgozók helyett
(mérve: a legördülő egyetlen eleme `gyujto` volt). Szövegmezővel ez évekig nem
tűnt fel, mert a felhasználó úgyis beírta a nevet; legördülővel azonnal látszott.

Van rá **pontos** jel, nem kell találgatni: a felső sáv munkamappája. A
`refresh_all` azt adja át, az Áttekintő „Arckép elhelyezése” menüje pedig a
dolgozó mappáját — tehát „a kapott mappa ≠ a munkamappa” pontosan azt jelenti,
hogy dolgozói mappát kaptunk.

### 17.3 Ellenőrzés

Önteszt 255/255, GUI **179/179** (új: „DOLGOZÓVÁLASZTÓ: EGYSÉGES LEGÖRDÜLŐ MINDKÉT
FÜLÖN” — 6 ellenőrzés: azonos osztály mindkét fülön, üres mezőnél a dolgozói
mappákat kínálja (nem a munkamappát), a `parent_dir` a munkamappa marad, ékezet
nélküli részlet feloldása a céllal együtt, kétes részletnél szűkítés és
figyelmeztetés, és az Áttekintőből hívva a dolgozó kitöltődik úgy, hogy a
munkamappa NEM változik).

---

## 18. A PDF-metaadat zsákutcája, és a névsorrend megfordítása (2026-10-07)

### 18.1 A kérdés

Felvihetők-e utólag a felismert iratokra metaadatok (cím, kategória), hogy a
Windows Intézőben *azokra* lehessen szűrni — így a fájlnév elejéről eltűnhetne a
dolgozó neve, és a szem a doktípusra esne.

### 18.2 A mérés: az Intéző nem olvas PDF-metaadatot

Írni triviális lenne: a `stamp_pdf_file` növekményes mentéssel már ma is hozzáír a
kész fájlhoz, és a `rename_plan` logikája minden meglévő iratról kitalálja, micsoda.

A fogadó oldal viszont nem tudja elolvasni. Készítettem egy PDF-et kitöltött
`title`, `subject`, `author` és `keywords` mezővel, majd a Windows Shell API-ján
(`Shell.Application` → `GetDetailsOf`, ugyanaz, amiből az Intéző oszlopai jönnek)
lekérdeztem:

```
Címkék  (18) = ''      Cím        (21) = ''      Kategóriák (23) = ''
Szerzők (20) = ''      Tárgy      (22) = ''      Megjegyzések (24) = ''
```

Mind üres — pedig a fájlban benne vannak. Kontroll: ugyanez a lekérdezés egy
XLSX-en `Szerzők = DocGen`-t ad, tehát a módszer jó, és konkrétan a PDF-nél bukik.

Az ok a registryben: a
`HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\PropertySystem\PropertyHandlers\.pdf`
kulcs **nem létezik**. Ami `.pdf`-hez regisztrálva van, az az Adobe
`pdfprevhndlr.dll`-je — de az *előnézet*-kezelő, nem tulajdonság-kezelő.

Mérve a fejlesztői ÉS az éles (céges) gépen is: nincs property handler. Az
ellenőrzés egysoros, ha a helyzet valaha változna:

```powershell
Test-Path "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\PropertySystem\PropertyHandlers\.pdf"
```

Ami viszont **van**: beépített tartalom-indexelő (`Windows.Data.Pdf.dll`), tehát a
Windows Kereső a PDF-ek *szövegében* tud keresni — a metaadat-mezőkben nem.

**Következtetés: metaadatot nem írunk.** Láthatatlan maradna, cserébe minden
iktatás egy újabb írási lépéssel járna.

### 18.3 Amit helyette csináltunk: a doktípus áll elöl

```
NAV jövedelemigazolás — Kiss Anna (aláírt).pdf
Tartózkodási engedély formanyomtatvány — John Doe (aláírt, fotóval ellátva).pdf
```

Ez telepítés nélkül, ma megoldja a kimondott célt: a szem a típusra esik, és a név
szerinti rendezés típusonként csoportosít.

Az indok, amiért ez nem veszteség: **az iratok dolgozónkénti mappában vannak**
(`Kiss Anna\02_Feltoltheto\`). Ott a névvel kezdődő fájlnév semmit nem
csoportosít — minden fájl ugyanazé a dolgozóé —, viszont épp azt a karakterhelyet
foglalja, ahol a típust keressük. A név megmarad a fájlnévben (a feltöltéshez),
csak hátrébb.

Elválasztó: `NAME_SEP = " — "`. A `norm()` a gondolatjelet is elválasztónak veszi
(`[_\-.\u2013\u2014]+`), így a szabályillesztés nem romlik — mérve mind a 4
kötelező típusra.

**A migráció már készen volt:** a 15.3-as visszamenőleges átnevező egy körben
átviszi a meglévő iratokat, mert a célnevet mindig a `target_name`-ből számolja.
Valódi mappán mérve 5/5 irat átnevezve, az eldönthetetlen érintetlen.

A `test/gui.py` fixture-nevei mostantól szintén `target_name`-ből jönnek, nem
beégetve — így a következő névváltoztatás nem töri el a teszteket.

### 18.4 Ellenőrzés

Önteszt **260/260** (új: „NÉVSORREND: A DOKTÍPUS ELÖL”, 5 ellenőrzés), GUI 179/179.
