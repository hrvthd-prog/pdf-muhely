# Terv — „Képek → PDF” modul a PDF Műhelybe

**Státusz:** megvalósítva (v1) — lásd a 11. fejezetet · **Készült:** 2026-09-25
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
