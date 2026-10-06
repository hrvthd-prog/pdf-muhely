# Terv — PDF-kitöltő („szerkesztő”) a PDF Műhelybe

Kiinduló igény (2026-10-05): az egyik formanyomtatvány **csak PDF-ben**
tölthető le. Vektoros (nem szkennelt), de nincs benne kitölthető mező, ezért
nem lehet szerkeszteni. A DocGen `.docx` sablonokból dolgozik, így ezt az iratot
nem tudja előállítani.

---

## 0. Kiindulás — mi van ma

### 0.1 A legközelebbi rokon: Arckép elhelyezés (`PlacerTab`)

Ugyanaz a mozdulat, csak kép helyett szöveggel: a lapot kirajzolja a vásznon
(`get_pixmap` → `tkimg`), egérrel mozgatható réteget tesz rá, nagyít, lapoz,
a forgatott lapot is kezeli (`derotation_matrix`), az eredeti fájlt nem
írja felül, és van iktatása (`target_name`, `backup_existing`, `log_row`,
`set_stamp`). **A kitöltő ennek a mintáját követi**, a vászonkezelést és az
iktatást újrahasznosítja, új függőség nem kell.

### 0.2 Mérés: ékezetes szöveg a PDF-ben (PyMuPDF 1.26.7)

A magyar `ő`/`ű` (Latin Extended-A) a buktató. Öt módszert próbáltam ki az
`Árvíztűrő tükörfúrógép ŐŰ őű` szöveggel, visszaolvasással és rajzolt képpel:

| módszer | ő/ű | fájlméret (1 sor) | megjegyzés |
|---|---|---|---|
| `insert_text(fontname="helv")` | **elromlik** (`·`) | — | WinAnsi kódolás, nincs benne ő/ű |
| `TextWriter` + `Font("helv")` | jó | 33 KB | beépített Nimbus Sans, Identity-H |
| ugyanez + `doc.subset_fonts()` | jó | **11 KB** | csak a használt betűk maradnak |
| `insert_font(arial.ttf)` | jó | 586 KB (részhalmazzal 40 KB) | rendszer-betűkészlettől függ |
| FreeText annotáció | jó (MuPDF-ben) | 34 KB | más nézőben az újrarajzolás elronthatja |

**Döntési javaslat:** `TextWriter` + `Font("helv")` + `subset_fonts()`. Nincs
rendszerfüggés (a céges gépen is ugyanaz), kicsi, az 5 MB-os korlátot nem
fenyegeti, és a lap tartalmába kerül (nem annotáció), tehát minden néző és a
portál is ugyanazt látja. Az `insert_text(fontname="helv")`-t kifejezetten
**tilos** használni — az öntesztbe kerüljön erre egy ő/ű-visszaolvasás.

---

## 1. A cél — és mit jelenthet a „szerkesztés”

Négy értelmezés lehetséges; a terv az **A**-ra épül, a többi kérdés (12. fejezet).

| | értelmezés | munka | javaslat |
|---|---|---|---|
| **A** | **Kitöltés ráírással:** az üres helyekre szöveg, a jelölőnégyzetekbe X | közepes | **ez az alap** |
| B | A nyomtatvány **meglévő szövegének átírása** | nagy, kockázatos | csak ha tényleg kell (lásd 10.) |
| C | Kitölthető AcroForm-mezők gyártása a PDF-be, kitöltés máshol | közepes | nem: a kitöltés úgyis nálunk történne |
| D | Átalakítás Wordbe, és DocGen-sablon belőle | kicsi | **elvetve:** a hatósági nyomtatvány képe elcsúszik, és nem az eredeti marad |

Az eredeti oldal tartalmához **nem nyúlunk**: a kitöltés egy új réteg a lap
tetején. Így a nyomtatvány képe bitre azonos marad az eredetivel.

---

## 2. Az alapötlet: kattints a helyre, gépelj

A vektoros PDF itt előny: a nyomtatvány **vonalai és dobozai adatként
olvashatók** (`page.get_drawings()`), nem csak képpontok. Ezért a kattintás
nem pontatlan szabadkézi elhelyezés, hanem **illesztés**:

| hová kattintasz | mi történik |
|---|---|
| keretes mezőbe (téglalap) | a szöveg a doboz bal aljához igazodik, 2 pt belső margóval |
| vízszintes vonal fölé (aláhúzásos mező) | az alapvonal a vonal fölé kerül |
| kis négyzetbe (≤ 14 pt, közel négyzetes) | középre egy **X** — újabb kattintás leveszi |
| egymás melletti egyforma kis cellák sorába | **cellás mód:** betűnként egy cella (lásd 12. B) |
| üres területre | szabad elhelyezés ott, ahol kattintottál |

Az illesztés kikapcsolható (Alt + kattintás = szabad elhelyezés), mert a
nyomtatványok rajzolata néha meglepő.

---

## 3. Képernyőterv

Az **Eszközök** alá új alfül: **Kitöltés** (a fő sáv a munka sorrendje, ez eseti
eszköz — `kepek-pdf-terv.md` 13.2).

```
┌ Eszközök ─ [Arckép elhelyezés] [Kitöltés] [Összefűzés] [Raszterizálás] ──────────┐
│ ┌ PDF nyomtatványok ─────┐ │                                                     │
│ │ szallasado_nyil.pdf    │ │      ┌───────────────────────────────┐              │
│ │ ...                    │ │      │  SZÁLLÁSADÓI NYILATKOZAT      │              │
│ └────────────────────────┘ │      │  Név: [Kiss Anna_________]    │  ← vászon    │
│ ┌ Kijelölt mező ─────────┐ │      │  Szül. idő: [1990.01.02]      │              │
│ │ Szöveg: [Kiss Anna   ] │ │      │  ☒ igen   ☐ nem               │              │
│ │ Méret: [10] pt         │ │      └───────────────────────────────┘              │
│ │ [Törlés]               │ │                                                     │
│ └────────────────────────┘ │  Oldal [1]/2   [−] [+] [Illeszt]                    │
│ ┌ Mentés / iktatás ──────┐ │                                                     │
│ │ Dolgozó: [Kiss   ] → … │ │                                                     │
│ │ Típus:  [Szálláshely…] │ │                                                     │
│ │ [Mentés másként…]      │ │                                                     │
│ │ [Iktatás az előkészítettbe] │                                                │
│ └────────────────────────┘ │                                                     │
└──────────────────────────────────────────────────────────────────────────────────┘
```

Mozdulatok: **kattintás** üres helyre = új mező és azonnal gépelhetsz (a vásznon
ülő `Entry`, Enter = kész, Esc = mégse); **kattintás** meglévő mezőre = kijelölés,
**húzás** = mozgatás; nyilak = 1 pt, Shift+nyíl = 10 pt; **Del** = törlés;
**Ctrl+Z** = utolsó lépés visszavonása; Tab = következő mező.

---

## 4. Adatmodell

```python
@dataclass
class FillItem:
    page: int
    x: float          # alapvonal bal pontja, lapkoordinátában (pt), forgatatlan térben
    y: float
    text: str
    size: float = 10.0
    kind: str = "text"          # "text" | "check" | "cells"
    cell_w: float = 0.0         # cellás módban a cellák lépésköze
```

A fül állapota egy `list[FillItem]` és egy visszavonási verem (a lista
másolatai — a pár tucat elem miatt a legegyszerűbb, ami helyes).

---

## 5. Kiírás

1. `open_checked(src)` — az eredeti újra megnyitva, a memóriabeli példányt
   nem módosítjuk.
2. Oldalanként egy `TextWriter`, `Font("helv")`; a forgatott lapon
   `page.derotation_matrix`-szal, mint a `PlacerTab._write`-ban.
3. `write_text(page)`, majd `doc.subset_fonts()`, `save(garbage=4, deflate=True)`.
4. Ellenőrzés: visszaolvassuk a lap szövegét, és minden kitöltött érték
   szerepeljen benne (ha nem: hibaüzenet, a fájl nem marad ott).
5. Iktatáskor `write_pdf_verified` + bélyeg; a cél **`01_Elokeszitett`** —
   a kitöltött, de még alá nem írt nyomtatvány nyomtatásra vár. A kör innen a
   megszokott: nyomtatás → aláírás → szkennelés → Iktató/Összeállító → `02`.
   Fotóigényes típusnál ezután jön az Arckép elhelyezés, ahogy ma.
6. Az eredetit soha nem írjuk felül (ugyanaz az őr, mint a `PlacerTab._save`-ben).

---

## 6. Sablon: a mezők helye nyomtatványonként (2. fázis)

Ha ugyanazt a nyomtatványt sok dolgozónak kell kitölteni, a mezők helyét
egyszer kell megadni. A sablon a mezők listája (hely, méret, fajta, **címke**,
pl. „Név”), érték nélkül, a szkript mappájában: `kitolto-sablonok.json`.

- **Azonosítás:** az oldalszám + oldalméretek + az 1. oldal szövegének SHA-1-e.
  Ha a hatóság új változatot ad ki, a sablon nem illeszkedik → szól, nem
  csúsztat el csendben.
- Megnyitáskor, ha van illeszkedő sablon, a mezők üresen ott várnak, Tab-bal
  végig lehet menni rajtuk.
- A `.gitignore` engedélyező lista miatt a sablonfájl **nem** kerül a repóba
  (felhasználói beállítás, mint az `emlekezet.json`).

---

## 7. Mit nem tud a kitöltő (szándékosan)

- **Meglévő szöveg átírása** — külön döntés (10. fejezet).
- **Újraszerkesztés a kész PDF-ből:** a kiírt szöveg a lap tartalmának része,
  utólag nem emelhető ki tisztán. Elírásnál: az ablakban még javítható és újra
  menthető; később sablonnal (6.) pár mozdulat újra kitölteni. Bővítési út: az
  értékeket JSON-ként a kimenetbe ágyazni (`embfile_add`), és az üres
  nyomtatványra visszatölteni.
- **Betűtípus-választás:** egy betűkészlet (Helvetica-szerű Nimbus Sans), egy
  szín (fekete). A hatósági nyomtatványhoz ennyi kell.
- **Többsoros szövegdoboz tördeléssel:** az első körben egy mező egy sor.
- **Aláírás, rajzolás, kiemelés.**

---

## 8. Hibakezelés

| eset | viselkedés |
|---|---|
| a PDF titkosított / jelszavas | az `open_checked` ma is jelzi; jelszót nem kérünk |
| XFA-űrlap (a lap csak „Please wait…” szöveget mutat) | felismerjük (`doc.is_form_pdf` + XFA-kulcs), és szólunk: ez nem tölthető ki így |
| a PDF-ben **mégis vannak** AcroForm-mezők | szólunk; a mezők helyét kitöltő-mezőkké alakítjuk, a widgeteket mentéskor eltávolítjuk (a widget saját betűje ugyanúgy elrontaná az ő/ű-t) |
| a szöveg kilóg a dobozból | a mező pirosan keretezve, mentéskor figyelmeztetés (nem tiltás) |
| a kiírt fájl visszaolvasása eltér | a `.part` törlődik, hibaüzenet |
| 5 MB fölött | `size_note`, mint mindenhol |

---

## 9. Tesztterv

**Önteszt (`--test`):**
- ő/ű-visszaolvasás: `FillItem`-ekből kiírt PDF szövegének vissza kell adnia
  az `Árvíztűrő tükörfúrógép ŐŰ őű`-t (ez fogja meg, ha valaki `insert_text`-re
  „egyszerűsít”).
- forgatott (90°) lapon a szöveg a kattintott helyen van (visszaolvasott
  `bbox` a várt pont körül).
- illesztés: generált lapon téglalap / aláhúzás / kis négyzet / cellasor —
  a kattintásból a várt `FillItem` lesz.
- a kimenet mérete: 1 oldal, 20 mező < az eredeti + 30 KB.
- sablon-azonosítás: más szövegű lap nem illeszkedik.

**GUI-teszt (`test/gui.py`):** kattintás → gépelés → Enter → mező a listában;
húzás mozgat; Del töröl; Ctrl+Z visszaállít; iktatás a `01_Elokeszitett`-be,
naplósorral és bélyeggel.

**Megjelenés:** `tools/ui-kep.py` bővítése a Kitöltés alfüllel.

---

## 10. B értelmezés: a meglévő szöveg átírása (csak ha kell)

Ha a nyomtatvány **előre nyomtatott szövegét** is módosítani kell (nem csak
üres helyet kitölteni), az redakcióval megy: a régi szöveg helyét
`add_redact_annot` + `apply_redactions` **kitörli** (nem csak letakarja), és
ugyanoda a fenti módon új szöveg kerül. Korlátok, amiket előre tudni kell:

- A beágyazott betűkészlet szinte mindig **részhalmaz**: az eredeti betűtípussal
  új betűt írni általában nem lehet, ezért az új szöveg Helvetica-szerű lesz —
  egy hatósági nyomtatványon ez feltűnhet.
- A redakció a vonalakhoz/képekhez is hozzányúlhat, ha belelógnak a dobozba
  (`graphics=False`, `images=False` beállítással ez kezelhető).
- Hatósági nyomtatvány szövegének átírása tartalmilag is kérdés — érdemes
  megnézni, elfogadja-e így a hatóság.

---

## 11. Megvalósítási fázisok

| fázis | tartalom | ellenőrzés |
|---|---|---|
| **F0** | A konkrét nyomtatvány vizsgálata: mezők, XFA, titkosítás, forgatás, rajzolat (téglalapok/vonalak/cellák), betűkészletek | rövid jelentés ide, a 13. fejezetbe |
| **F1** | `fill_pdf(src, items) -> bytes` (TextWriter + subset) és az öntesztjei | önteszt zöld, ő/ű visszaolvasható |
| **F2** | Kitöltés alfül: vászon, szabad elhelyezés, gépelés, mozgatás, törlés, visszavonás, Mentés másként | GUI-teszt, `ui-kep.py` kép |
| **F3** | Illesztés a rajzolathoz: doboz, aláhúzás, jelölőnégyzet (X), cellasor | önteszt generált lapokon + a valódi nyomtatványon |
| **F4** | Iktatás a `01_Elokeszitett`-be (a `PlacerTab` iktatási magjával) | GUI-teszt: fájl, napló, bélyeg |
| **F5** *(opcionális)* | Sablon (6.) | önteszt: illeszkedés / nem illeszkedés |
| **F6** *(opcionális)* | Adatok a DocGen nyilvántartásából (12. D) | — |

F1–F4 együtt a használható első változat; F5-öt akkor érdemes megépíteni, ha a
nyomtatványt rendszeresen, sok dolgozónak töltitek ki.

---

## 12. Nyitott kérdések

### A) A nyomtatványról
1. **Melyik nyomtatvány?** Kérem a PDF-et (vagy az elérési útját) az F0
   vizsgálathoz — a terv több pontja (cellás mező, XFA, forgatás) ezen múlik.
   Dolgozói adat ne legyen rajta: az üres példány kell.
2. Kitöltés után **aláírják** (nyomtatás → aláírás → szkennelés), vagy
   kitöltve már feltölthető? Ettől függ, hogy `01` vagy `02` a cél.
3. Kell rá **arckép**? (Ha igen, a meglévő Arckép elhelyezés jön utána.)

### B) A kitöltésről
4. Vannak **betűnkénti cellák** („egy négyzetbe egy betű”)? Ha igen, a cellás
   mód az F3 része, különben kimarad.
5. Elég az A értelmezés (üres helyek kitöltése), vagy **meglévő szöveget is**
   át kell írni (10. fejezet)?

### C) A mennyiségről
6. Hány dolgozónak kell kitölteni, milyen gyakran? Néhány alkalomnál a sablon
   (F5) felesleges; tucatnyinál már megéri.

### D) A DocGen-kapcsolat (később)
7. A kitöltendő adatok (név, születési idő, útlevélszám…) a DocGen
   nyilvántartásában (`docgen-employees.json`) már megvannak. Érdemes-e később
   onnan tölteni a sablon mezőit? Ez a két app között új függés, ezért külön
   döntés — az első változat **nem** építi.

---

## 13. Mire várok választ, mielőtt kódolok

- **A1** (a PDF maga) — enélkül az F0 nem indul.
- **A2, B4, B5** — ezek alakítják az F3 tartalmát és a célmappát.
- **C6** — eldönti, hogy az F5 belekerül-e az első körbe.

---

## 14. Döntések (2026-10-05) — a feladat a DocGenbe kerül

### 14.1 A felhasználó válaszai

- **A1:** a nyomtatvány a **NEAK NYT.52 – Megrendelő TAJ-igazolványhoz**
  (`NYT.52.K.pdf`).
- **A2:** aláírás nem kell, a kész irat a **`02_Feltoltheto`**-be megy.
- **B5:** csak az üres helyek kitöltése; a nyomtatvány szövege nem változik
  (a 10. fejezet nem épül).
- **C6:** több dolgozónak kell. A felhasználó felvetette, hogy a DocGenben
  jobb helye lehet.

### 14.2 Az F0 vizsgálat eredménye

1 oldal, A4, Word 2007-ből készült; nincs AcroForm, XFA, titkosítás, forgatás.
A táblázat vonalaiból minden cella (a betűnkéntiek is) pontosan kiszámolható,
és a 10 jelölőnégyzet külön keretes téglalap. A próbakitöltés minden cellába
pontosan esett. Részletek: `DocGen/TERV-pdf-nyomtatvany.md`, 0.1.

### 14.3 Döntés: DocGen, és a Műhelyben nem épül kitöltő

A nyomtatvány mezőinek forrása (név, anyja neve, születés, cím, belépés, a
cégadatok) a DocGen nyilvántartása; a DocGen eleve dolgozók csoportjára generál,
és van ékezetbiztos PDF-rajzolója (pdf-lib + Carlito). A Műhelyben ugyanezt
az adatot dolgozónként újra be kellene gépelni. Egy **rögzített** nyomtatványnál
a 2–3. fejezet interaktív vászna is felesleges: a mezők helyét egyszer kiszámoljuk
a rajzolatból, és adatként tároljuk.

Ezért a fenti F1–F6 fázisok **nem épülnek**. A terv megmarad arra az esetre,
ha egyszer olyan PDF-et kell kitölteni, amelynek az adatai nincsenek a
nyilvántartásban (eseti irat). A 0.2 mérés (a `insert_text(fontname="helv")`
elrontja az ő/ű-t) addig is érvényes minden PyMuPDF-es szövegírásra.

### 14.4 Ami a Műhelyre marad

- A DocGen a NYT.52 kimenetére a **Műhely bélyegét** írja (`stamp_keywords`
  formátum, `hely=02_Feltoltheto`), DocGen-bélyeget **nem** — mert a Műhely
  szemében a DocGen-bélyeg azt jelenti, hogy az irat még nincs aláírva, és a
  Rendezés `01`-be sorolná. A bélyeg formátuma ettől két repó közös szerződése:
  változtatni csak mindkét oldalon együtt szabad.
- Ha az Áttekintőben is látszania kell, új szabály kell a `DEFAULT_RULES`-ba
  (nyitott kérdés, `DocGen/TERV-pdf-nyomtatvany.md` 6. fejezet).

---

## 15. Második kör (2026-10-05): a szerkesztő mégis kell — a kész PDF javítására

### 15.1 A felhasználó kérése

Az Áttekintőben kapjon oszlopot a TAJ-megrendelő, **„és ott még lehessen átírni
esetleg a pdf-et, tehát ott is kell a pdf szerkesztő”**. A 14.3 döntés („a
Műhelyben kitöltő nem épül”) ezzel módosul: nem *kitöltő* kell (azt a DocGen
végzi), hanem **javító** — egy már kész PDF szövegének átírása.

### 15.2 Ami már elkészült

- Áttekintő: új alapszabály, `taj` (`DEFAULT_RULES`), kulcsszavai `nyt 52`,
  `taj megrendelo`. `generated=True`, mert a jelző itt azt dönti el, hogy
  szkennelt irat-e (Összeállító-paletta) — a TAJ soha nem az.
- **Szabályfájl-összefésülés:** a mentett `attekinto-szabalyok.json` az
  alapszabályokat egészben felülírja, a frissítő pedig soha nem írja felül —
  így az új szabály az éles gépen meg sem jelent volna. Mostantól a fájl
  `ismert_alapok` listája mondja meg, mely alapszabályokat látta már: ami
  ezután születik, hozzáadódik; amit a felhasználó törölt, nem jön vissza.
- Buktató, amit a GUI-teszt fogott meg: `generated=False`-szal a TAJ a
  palettára került, a 13 soros lista megnövelte a panelt, és a nagyító
  billentyűi elvesztették a fókuszt (4 bukás). A paletta magassága amúgy is
  a típusok számával nő — 13 saját típusnál ugyanez jönne elő (lásd 15.6).

### 15.3 A javító — mérés a DocGen kimenetén

A DocGen a kitöltött értékeket a lap tartalmába írja, **teljes** (nem
részhalmazos) Carlito betűvel. Kipróbálva PyMuPDF-fel:

1. `get_text("dict")` → a kitöltött érték spanja: szöveg, betű, méret, alapvonal;
2. `extract_font(xref)` → a beágyazott Carlito (622 KB, ő/ű/č is benne);
3. redakció a span dobozára `images=NONE, graphics=LINE_ART_NONE` mellett → a
   régi szöveg **ténylegesen törlődik**, a táblázat 442 vonala megmarad;
4. `TextWriter` ugyanarra az alapvonalra, ugyanazzal a betűvel és mérettel.

Eredmény: „Kovacevic” → „Kovačević Őrs”, ránézésre azonos betűvel, a
szomszéd rovatok érintetlenek, a Műhely-bélyeg megmaradt. (Egy MuPDF-figyelmeztetés
— `cannot find object in xref` — megjelent a műveletnél, de a kimenet hibátlanul
nyílik; a megvalósításnál a visszaolvasás ellenőrzi.)

### 15.4 Javasolt terjedelem (megerősítésre vár)

| | mit tud | megjegyzés |
|---|---|---|
| **megnyitás** | Áttekintő → a cella PDF-je → *Szerkesztés…*; és Eszközök → **Szerkesztés** alfül bármely PDF-re | a `PlacerTab` vásznának mintájára |
| **átírás** | kattintás egy szövegre → a vásznon szerkeszthető mező → Enter | redakció + újraírás (15.3); a DocGen-értékeknél ugyanaz a Carlito |
| **új szöveg** | kattintás üres helyre | a 0.2 mérés szerint `TextWriter`, nem `insert_text` |
| **X** | jelölőnégyzetre kattintás: be / ki | az „X” is szöveg, ugyanígy törölhető |
| **mentés** | helyben; az előző példány a dolgozó `.eredeti\` mappájába; naplósor; a bélyeg marad | a meglévő `backup_existing` / `log_row` |

Ha a nyomtatvány **saját** (részhalmazos) betűjével írt szöveget írnak át, az
új betűi hiányozhatnak belőle → Helvetica-szerű betűre esik vissza, és szól.

### 15.5 Fázisok

| fázis | tartalom | ellenőrzés |
|---|---|---|
| S1 | `rewrite_span(doc, page, span, text)` + `add_text` + önteszt (ő/ű, a vonalak száma változatlan, a régi szöveg eltűnt) | `--test` zöld |
| S2 | Szerkesztés alfül: vászon, kattintás → mező, Enter/Esc, visszavonás (a dokumentum bájtjainak verme) | `test/gui.py`, `ui-kep.py` |
| S3 | mentés helyben, `.eredeti`, napló; Áttekintő → *Szerkesztés…* | GUI-teszt: fájl, mentés, napló |

### 15.6 Mellékszál, nem része a tervnek

Az Összeállító palettalistája (`self.pal`) a típusok számával együtt nő. 13
típusnál a panel megnyúlik, és a nagyító elveszti a fókuszt (15.2). Ma 12 a
típus, tehát nem jön elő, de egy 13. saját Iktató-típus előhozná. A javítás
egy magasságkorlát görgetéssel (`min(12, len(...))`) — kimérve 120/120.

---

## 16. Harmadik kör (2026-10-05): általános PDF-szerkesztő

### 16.1 A kérés és a döntések

A felhasználó: a fejlesztés legyen **általános** — a DocGen a PDF-nyomtatványok
kitöltését célozza, a Műhely **általános PDF-szerkesztést**. A szerkesztő
képességei (a felhasználó választása): **szöveg átírása, új szöveg és X,
űrlapmezők elhelyezése, kitakarás**. A DocGen-sablon formátuma kitölthető PDF,
a mező neve a DocGen-jelölő (`DocGen/TERV-pdf-nyomtatvany.md` 11.) — a Műhely
szerkesztője ezért mezőt is tud rakni bármely PDF-re. A 15.4 terjedelme ezzel
kibővült és megvalósult.

### 16.2 Felépítés

**Magfüggvények** (tesztelhetők, a felülettől függetlenek; a `pdf-muhely.py`
„Eszközök: szerkesztés” szakaszában):

| függvény | mit tud |
|---|---|
| `page_lines`, `snap_cell`, `snap_cells`, `snap_box` | a lap vonalaiból cella, aláhúzásos sáv, betűnkénti cellasor, jelölőnégyzet — a kattintás ehhez igazodik |
| `span_at`, `span_font`, `rewrite_span` | a kattintott szöveg cseréje redakcióval: a régi **ténylegesen** törlődik (a vonalak és képek maradnak), az új a saját beágyazott betűvel, ha minden betűje megvan benne, különben a választott betűvel |
| `add_text`, `toggle_x` | új szöveg (`TextWriter`), X be/ki a négyzetben |
| `add_field`, `rename_field`, `field_at`, `field_name_error` | űrlapmező a DocGen-jelölő nevével (keret, háttér nélkül, automatikus méret) |
| `erase_area` | kitakarás: szöveg, képpont, a teljesen benne lévő vonal végleg törlődik, a hely fehér |
| `edit_fonts`, `edit_font` | Helvetica (beépített) + a gépen lévő Calibri, Arial, Times New Roman |

**A fül** (`EditorTab`, Eszközök → Szerkesztés): bal oldalt fájllista, az eszköz
(Szöveg és X / Űrlapmező / Kitakarás), betű és méret, a kijelölt mező neve
(átnevezés, törlés); a vászon fölött Visszavonás, Mentés, Mentés másként, lapozás,
nagyítás. A vászon szélességre illeszt. Mező módban a mezők kerete és neve
látszik (a PDF-ben láthatatlanok). Mozdulatok: kattintás szövegre = átírás (a
beírómezőben a régi szöveg); üres helyre = új szöveg a cellába illesztve;
négyzetbe = X; mező módban kattintás = mező a cellába, **húzás több kis cellán át =
betűnkénti mezők** (`név#1…#n`); Delete = a kijelölt mező törlése; Ctrl+Z =
visszavonás.

**Mentés:** helyben; az előző példány a dolgozó `.eredeti\` mappájába kerül, a
mentés atomi (`write_pdf_verified`), a betűk részhalmazolva. Az Áttekintőből
nyitva (jobb klikk → *✎ Szerkesztés: <fájl>*) naplósor is készül (`SZERKESZTVE`). A
bélyeg (metaadat) megmarad.

### 16.3 A NYT.52 sablon — a szerkesztő próbája

A DocGen NYT.52-sablonja (`DocGen/pdf-sablonok/TAJ-megrendelő (NYT.52).pdf`) ezekkel a
függvényekkel készült, kattintási pontokból — ahogy a fülön kattintgatva készülne. A
cellaillesztés pontosan visszaadta a korábban kézzel mért cellákat (az egyenetlen
év-cellákat is). A DocGen tesztje ezt a sablont tölti ki: a lánc két vége össze
van mérve.

### 16.4 Buktatók, amiket a tesztek fogtak meg

- **Nem-törő szóköz:** a Calibrivel (és Ariallal) `TextWriter`-rel kiírt szóköz a
  szövegrétegben U+00A0-ként jön vissza — keresésnél, másolásnál és a szövegrétegből
  címkézésnél zavar. Az `add_text` szavanként ír, a szóköz szélességével léptetve.
- **A mező és a lap egy objektum legyen:** a `doc[i]` minden hívásra új Page-példányt
  ad; egy másik példányon kapott mezőt a `delete_widget` „laphoz nem kötött”-nek lát.
- **`Widget.update()` nem nevez át:** az átnevezés a `/T` kulcs közvetlen írásával megy.
- **Redakció kitöltés nélkül:** az `add_redact_annot` alapból fehér téglalapot fest
  a helyére, ami a táblázatvonalat is eltakarná — átírásnál `fill=False`.
- **Jelölőnégyzet a rajzcsoportban:** egy csoportban több alakzat lehet, ezért a
  négyzetet téglalaponként keressük, nem a csoport befoglaló dobozával.
- **Globális Ctrl+Z:** a `bind_all("<Control-z>")` az Összeállító nagyítójának
  billentyűit is elrontotta (4 GUI-bukás). A Ctrl+Z a vászonra került.
- **Windows-fájlzár:** a szerkesztő memóriában tartja a PDF-et, így a forrás helyben
  felülírható.

### 16.5 Ellenőrzés

Önteszt 202/202 (új: SZERKESZTŐ, 18 ellenőrzés generált lapon), GUI 135/135 (új:
SZERKESZTÉS, 15 ellenőrzés valódi egér- és billentyűeseményekkel, mentéssel,
`.eredeti`-vel, naplóval), verzió 11/11, frissítő 13/13. Felületfotó:
`python tools/ui-kep.py 5 szerkesztes.png`.

### 16.6 Szándékos egyszerűsítések

- Forgatott lapot (`/Rotate`) a szerkesztő nem kezel — szól. Bővítés: a koordináták
  átváltása a `derotation_matrix`-szal, mint a `PlacerTab`-ban.
- A jelölőnégyzetet keretes négyzetből ismeri fel; négy külön vonalból rajzoltat nem.
- A pontsoros rovat („Kelt, ………”) betű, nem vonal: oda szabad elhelyezés jut.
- Új szöveg egy sor; a szín fekete; a kitakarás fehér (nem fekete sáv).

---

## 17. Javítás (2026-10-05): a paletta valódi hibája — és a téves diagnózis

### 17.1 Ami a 15.2, 15.6 és 16.4 pontban téves

Ott azt írtam, hogy a 12–13 soros típuspaletta (illetve a globális Ctrl+Z kötés)
**fókuszhibát** okoz, és a nagyító billentyűi ettől nem működnek. Újramérve
**egyik sem reprodukálható**: a pontos akkori helyzet (TAJ `generated=False`, 12
soros paletta) és a visszatett `bind_all("<Control-z>")` mellett is 135/135. A
négy nagyító-bukás **környezetfüggő** volt: a billentyűesemény a Tk szerinti
fókuszhoz megy, és ha a teszt ablaka épp nincs előtérben, a Windows megtagadja az
új nagyító-ablak aktiválását — a fókusz nem kerül át, az esemény máshova megy.
Ez a GUI-teszt gyengesége volt, nem a programé. Javítás: a teszt a billentyű-
események előtt maga adja át a fókuszt (`focus_force`). A Ctrl+Z a szerkesztő
vásznán marad: szűkebb hatókörű, és így is helyes.

### 17.2 A valódi hiba

A palettalista a típusok számával együtt nőtt. Mérve 650 px magas ablakban
(ennyit nyit az app legalább): 11 és 13 típusnál az Iktatás gomb látszik, **15
típustól kicsúszik a látható részből** — nem lehet iktatni. Javítás: a lista
legfeljebb `PAL_ROWS = 11` sort mutat, a többi görgetősávval érhető el; az
1–9 billentyűk változatlanok. Utána 11, 13, 15 és 19 típusnál is látszik a gomb,
teljes magasságban.

Regressziós teszt: `test/gui.py` „ÖSSZEÁLLÍTÓ: SOK TÍPUS, ALACSONY ABLAK” —
1280×650, 16+ típus: az Iktatás gomb a fülön belül, a görgetősáv látszik; kevés
típusnál nincs görgetősáv. Önteszt 202/202, GUI 138/138.

---

## 18. A TAJ-igénylés másik két irata (2026-10-05)

A DocGen két új sablont kapott a TAJ-igényléshez (`DocGen/TERV-pdf-nyomtatvany.md`
12.): a NEAK **NYT.53** igénylőlapot és egy saját, kétnyelvű **TAJ-meghatalmazást**.
Mindkettő a Szerkesztés fül függvényeivel készült, kattintási pontokból; a
cellaillesztés a NYT.53 egyenetlen cellasorait is pontosan adta.

A Műhely-oldal változásai:
- **Nagybetűs sablon:** a NYT.53 „nyomtatott nagybetűkkel” kéri a kitöltést. A
  Szerkesztés fülön új jelölő: „A DocGen nagybetűvel töltse ki” — a sablon
  `/Keywords`-jébe a `docgen-nagybetu` kerül (`get_upper` / `set_upper`), a többi
  kulcsszó (bélyeg) megmarad; visszavonható, mint minden lépés.
- **Áttekintő:** két új alapszabály, `tajigeny` (`nyt 53`, `taj igenylolap`) és
  `tajmeghat` (`taj meghatalmazas`). A „taj meghatalmazas” hosszabb kulcsszó, ezért
  nyer a „meghat” szabály „meghatalmazas”-a ellen — a sima meghatalmazás marad
  „meghat”. A régi szabályfájlokhoz az `ismert_alapok` összefésülés adja hozzá őket.
- **Az állapotsor** (fájlnév, üzenetek) a bal panel aljáról az eszköztárba került:
  740 px-es ablakban az új jelölő alatt levágódott (`ui-kep.py 5`).

Tesztek: önteszt (szabályillesztés, nagybetű-jelölő), GUI (a jelölő a mentett
fájlon), `python test/run-all.py` zöld.

---

## 19. Negyedik kör (2026-10-06): bekezdés-formázás vektoros PDF-en

### 19.1 A kérés

A szerkesztő kapjon **formázási beállításokat**: a vektoros (nem szkennelt) PDF-ek
szövegét lehessen formázni — a példa a balra zárt bekezdés sorkizárttá tétele.
**Ne csak soronként, hanem bekezdésenként is** működjön.

### 19.2 Mérés a valódi iraton (a terv alapja)

A `DocGen/pdf-sablonok/TAJ-meghatalmazás.pdf` 7 soros magyar bekezdésén (Calibri
10,5; a lap Identity-H Type0 részhalmazokkal ágyazza be a betűt):

| mit mértem | eredmény |
|---|---|
| a beágyazott részhalmaz `has_glyph` | a bekezdés 38 karakterének **egyikére sem** igaz (az Identity-H cmap glyph-ID-s, nem Unicode-os) |
| a beágyazott betű `text_length` | **531,3 pt** a valódi 453,2 helyett — **17% hiba** |
| a gépen lévő `calibri.ttf` `text_length` | **453,6 pt** — 0,4 pt (0,1%) eltérés |
| `get_text("words")` szóbboxai | a valódi rajzolt szélességek, mérés nélkül |
| prototípus: 6 sor sorkizárása | minden sor 533,1–533,25-ig ér (cél 533,57), az `ő á ‐` megmaradt, a rajzok száma változatlan (3 → 3) |

**Ebből két döntés következik:**

1. A formázás **a gépen lévő rendszerbetűvel** mér és ír, nem a beágyazottal. A
   `span_font` (16.2) beágyazott-betű útja ilyen lapon amúgy is mindig elbukik és
   helyettesít — ezt eddig nem írtuk le, most igen.
2. Ha a bekezdés betűcsaládja nincs meg a gépen, a formázás **megtagadja magát**, és
   megnevezi a betűt. A mért 17%-os szélességhiba miatt a csendes helyettesítés
   láthatóan elrontaná a lapot.

### 19.3 A felhasználó döntései

| kérdés | válasz |
|---|---|
| sorkizárás módja | **mindkettő, választható**: alapból a sortörések megtartása (szóköznyújtás), jelölővel újratördelés |
| funkciókör | **mind a négy**: igazítás · sortávolság és térköz · betű (család, méret, félkövér, dőlt, aláhúzás, szín) · behúzás és a bekezdés szövegének átírása |
| vegyes formázású bekezdés | **megtartja, ahol tudja; ahol nem, szól** és jóváhagyást kér |
| hiányzó betű | **megtagadja**, és megnevezi a betűt |

### 19.4 Magfüggvények

A felülettől függetlenül tesztelhetők, az „Eszközök: szerkesztés” szakaszban.

| függvény | mit tud |
|---|---|
| `EDIT_VARIANTS`, `edit_font(name, bold, italic)` | a négy betűváltozat fájlja (`calibrib.ttf`, `calibriz.ttf` …); Helveticánál a PDF beépített base14 nevei (`HELV14`) |
| `span_style(span)` | a span stílusa → `(család, félkövér, dőlt)`. A családot a PDF-betűnévből (a `ABCDEF+` részhalmaz-előtag és a stílusvégződés levágva, `FONT_ALIAS`-szal), a vastagságot és a dőlést a MuPDF `flags`-éből |
| `style_font(span)` | a span stílusához tartozó **mérhető** betű, vagy `None` — ez a megtagadás kapuja |
| `text_lines(page)`, `_overlaps` | a lap összes szövegsora alapvonal szerint; két sor egy hasábban van-e |
| `paragraph_at(page, x, y)` | a **bekezdés**: sorok, bal és jobb szél, alapvonal-távolság, első sor behúzása, méret, vegyes-e, befoglaló doboz |
| `line_words(line)` | a sor szavai részenként a saját span-jukkal — ettől marad meg a vegyes formázás |
| `para_text(para)` | a bekezdés szövege egy sorban (a szövegszerkesztő ebből indul) |
| `guess_align(para)` | a bekezdés mai igazítása — csak a panel előtöltéséhez |
| `line_positions(…)` | **tiszta függvény**: egy sor szavainak x-pozíciói a kért igazítással |
| `wrap_words(…)` | **tiszta függvény**: tördelés, az első sor szélessége külön adható meg |
| `para_reflows(fmt)`, `REFLOW_KEYS` | a művelet újratördel-e (ettől függ a vegyes formázás sorsa) |
| `para_font_error(para, fmt)` | a két kapu egy helyen: mérhető-e a betű, és kirajzolható-e minden karakter |
| `para_format(doc, page, para, fmt)` | **egyetlen belépési pont**: redakció + újrarajzolás; visszaad egy figyelmeztetést (`""` ha tiszta) |

Az `fmt` szótárba **csak a megváltoztatott** kulcsok kerülnek — ezért nem kényszerít
például a méret megadása feleslegesen újratördelést. A felület a `_fill_para`-ban
rögzített alapértékekhez méri a különbséget.

### 19.5 A bekezdés felismerése — és miért nem a MuPDF blokkjaiból

Az első változat a MuPDF szövegblokkján belül dolgozott. **Mérés buktatta meg:**
1,5-es sortávolság beállítása után a MuPDF ugyanannak a bekezdésnek **mind a 7 sorát
külön blokkba** tette — a bekezdés nem volt újra felismerhető, és a *második* művelet
elbukott volna rajta. A felismerés ezért a lap **összes sorából** dolgozik:

1. a kattintott sorral **vízszintesen fedő** sorok (hasábszűrés — hasábos lapon a másik
   hasáb sorai alapvonal szerint közéjük keverednének),
2. az alapvonal-távolság becslése a szomszédokból, **`PARA_MAX_GAP`-pel sapkázva** (a
   betűméret háromszorosánál nagyobb távolság már nem sortávolság, hanem bekezdések
   közti térköz — e nélkül az egysoros bekezdés összevonódott a következővel),
3. futam a távolság- és mérettartó sorokból → ebből becsüljük a **hasáb** jobb szélét,
4. vágás ott, ahol egy sor **bekezdést zár**: a hasáb `PARA_RAGGED` (0,65) részénél
   hamarabb ér véget.

A 4. pont küszöbét mérés adta: ugyanazon a bekezdésen a belső sorok a hasáb 82–100%-áig
érnek (a magyar szavak hossza miatt), a valódi utolsó sor 36%-ig.

Ismert korlát: a bekezdés **jobb széle a leghosszabb soráé**, nem a valódi hasábé. Ha
minden sor rövid, a hasáb szűkebbnek látszik — a „Behúzás jobb” mezővel igazítható.
Ezért ad `guess_align` **legalább három sor** alatt mindig „balra”: a jobb szél magukból
a sorokból jön, így a leghosszabb sor definíció szerint a jobb szélen van, és két sornál
a balra zárt bekezdés is sorkizártnak látszana.

### 19.6 Két út: eltolás és újratördelés

| művelet | út | vegyes formázás |
|---|---|---|
| igazítás (balra / közép / jobbra / **sorkizárt**), sortávolság, térköz, szín, aláhúzás | **eltolás**: a sortörések és a szavak maradnak | **megmarad** (szavanként a saját betűjével írunk újra) |
| betűméret, betűcsalád, félkövér, dőlt, behúzás, a szöveg átírása | **újratördelés** | **elveszik** → vegyes bekezdésnél jóváhagyást kér |

A sorkizárás mindkét úton elérhető: alapból eltolással, az „Újratördelés” jelölővel a
szebb, egyenletesebb változat.

A sorkizárás őre **nem a hézag nagyságát korlátozza** (ez volt a terv első változata),
hanem a sor kitöltöttségét: `JUSTIFY_MIN_FILL = 0,6`. Mérés indokolta — egy hosszú magyar
szó („Társadalombiztosítási”, 10,5 pt-on ~100 pt) legitim lyukat hagy a sor végén, amit a
Word is megnyújt; a 4× hézagkorlát ezt tévesen elutasította, és a bekezdés közepén hagyott
egy balra zárt sort. A kitöltési arány viszont jól elválasztja a valódi bekezdésvéget
(36%) a hosszú szó okozta lyuktól (82%).

### 19.7 A felület

Új eszköz a rádiócsoportban: **Bekezdés formázása**. A panel a „Kijelölt mező” panel
helyén jelenik meg, és az „Új szöveg” betűválasztó (a Szöveg eszközé) a többi módban
elrejtőzik.

Ez **nem volt elég**: méréssel 740 px-es ablakban **110 px hiányzott**. Két lépés oldotta meg:

- a **bal panel görgethetővé** vált (vászon + görgetősáv, a sáv csak ha kell — az
  Összeállító típuspalettájának mintájára, 17.2). Két buktató: packkel a kiterjedő vászon
  elvette a görgetősáv helyét, ezért **grid** kell; és a téma sávja 1 px szélességet kér,
  ezért `sticky="nsew"` kell, különben 1 px-esen jelenik meg;
- a **gombsor (Bekezdés szövege… / Alkalmaz) a görgethető részen kívülre**, fix alsó
  sávba került — az Alkalmazért ne kelljen görgetni.

A vásznon a felismert bekezdés szaggatott keretet kap, a jobb szélét függőleges vonal
jelzi. A panel a kijelöléskor a bekezdés mai értékeivel töltődik ki, és minden művelet
után újra — így a következő művelet különbsége jól mérhető. Formázás után a bekezdést a
kattintás pontjából ismerjük fel újra; ha az elmozdult sorok miatt a pont két sor közé
esne, a `_repara` a bekezdés sávjában több ponton próbálkozik, hogy a kijelölés megmaradjon.

### 19.8 Amit a megvalósítás mért, és a terven módosított

| felfedezés | következmény |
|---|---|
| a beágyazott Identity-H részhalmaz `text_length`-e 17%-ot téved, `has_glyph`-je minden karakterre hamis | a formázás rendszerbetűvel mér; a `span_font` (16.2) beágyazott-betű útja ilyen lapon amúgy is mindig elbukik |
| **az Arial Bold nem ismeri a nem-törő kötőjelet (U+2010)** — a magyar iratok cégjegyzékszáma és címe használja; a karakter csendben eltűnt a lapról | második kapu: karakterfedés-vizsgálat a `para_font_error`-ban |
| a MuPDF a formázott bekezdést soronként külön blokkba teszi | a felismerés nem blokkalapú (19.5) |
| egysoros bekezdésnél a távolságbecslés a következő bekezdésig mért | `PARA_MAX_GAP` sapka |
| a 4× hézagkorlát legitim hosszú-szavas sorokat utasított el | `JUSTIFY_MIN_FILL` |
| a `pymupdf.Font("helv")` **NimbusSans**-ként ágyazódik be | `FONT_ALIAS`-ba került, különben a szerkesztő saját szövegét sem lehetne formázni |
| fájl nélkül az Űrlapmező eszközre váltva a `_draw_fields` elszállt (régi hiba) | egysoros őr, a `_page() is None` ágra |

### 19.9 Szándékos egyszerűsítések

- **Elválasztás nincs**: újratördelésnél a szavak egészben mozognak.
- **A térköz nem tördeli újra a lapot**: a bekezdés eltolódik, a lap többi tartalma nem
  mozdul. Ezért a panelon „Térköz előtte” van, „utána” nincs — az e nélkül semmit nem
  csinálna. Ütközésre a keret és az azonnal látható eredmény figyelmeztet.
- A kiírt szöveg a **tartalomfolyam végére** kerül, ezért a nyers kinyerési sorrend
  változik; a geometriai olvasási sorrend (`get_text(sort=True)`) és a megjelenés nem.
  Ez a szerkesztő régi tulajdonsága (`rewrite_span`, `add_text`), nem új.
- **Times New Roman**: a `;` a szövegrétegből U+037E-ként (görög kérdőjel, vizuálisan
  azonos) jön vissza. Csak akkor fordul elő, ha a felhasználó erre a családra vált.
- A sorok szóközei a formázás után **egységesek** lesznek (a dupla szóköz összevonódik).
- Forgatott lapot (`/Rotate`) a szerkesztő most sem kezel, jobbról balra író szöveget sem.
- Az aláhúzás rajzolt vonal: a PDF-ben nincs „aláhúzott szöveg”.
- Hasábos lapon a bekezdés a vízszintes fedés alapján marad egy hasábban; külön
  hasábfelismerés nincs.

### 19.10 Ellenőrzés

Önteszt **254/254** (új: BEKEZDÉS, 52 ellenőrzés — felismerés, a két tiszta függvény, mind
a tizenegy művelet, vegyes formázás, a két kapu), GUI **151/151** (új: BEKEZDÉS, 11
ellenőrzés valódi egéreseményekkel: kijelölés, panel-előtöltés, keret, sorkizárás,
második művelet ugyanazon a bekezdésen, Ctrl+Z, eszközváltás, mentés), verzió, frissítő
zöld. Valódi iraton mérve (`DocGen/pdf-sablonok/TAJ-meghatalmazás.pdf`): a 7 soros
bekezdés sorkizárása után minden sor 533,0–533,3-ig ér (cél 533,57), a szöveg
karakterre azonos, a rajzok száma változatlan.

Felületfotó: `python tools/ui-kep.py 6 bekezdes.png`.
