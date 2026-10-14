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

---

## 20. Javítás (2026-10-07): a levágódó oldalpanelek — közös `scroll_panel`

### 20.1 A mérés

Az **Arckép elhelyezés** fül bal panelje **990 px**-et kért. A program legnagyobb
ablakában (1900×1150) is csak **658 px** jutott neki, a minimálisban (940×620)
**433**. Vagyis a *Mentés másként…* és az *Iktatás a feltölthetőbe* gomb — a fül
két záró művelete — **soha, egyetlen ablakméretben sem volt elérhető**. A modul
emiatt használhatatlan volt, nem csak kényelmetlen.

Ugyanez az **Összeállító** jobb paneljén a minimális ablakban jelentkezett
(647 px kellett, 466 jutott): az *Utótag* mező és az *„arckép rajta”* jelölő esett ki.

Az Iktató, az Áttekintő, az Összefűzés és a Raszterizálás mérve rendben volt.

### 20.2 A megoldás

A Szerkesztés fül már hordozott egy görgethető bal panelt (19.7). Ez most közös
segédfüggvény: **`scroll_panel(parent, width, side, padx) -> (shell, inner)`**, és
mindhárom fül ezt használja.

Három dolgot tud, amit az eredeti nem:

1. **Ha van hely, a panel kifeszül** (`height=max(req, have)` a vászonablakon), így
   az `expand=True`-s részek — Összeállító *Kimenet* — nagy ablakban is kitöltik az
   aljat, pontosan mint görgetés előtt. Nincs visszacsatolás: a *kért* magasság
   független a kiosztottól.
2. **A görgő a panel bármely pontján működik.** A Tk a `<MouseWheel>`-t a kurzor
   alatti widgetnek adja, és az **nem bugyborékol a szülőhöz** — ezért widgetenként
   kötjük, a `<Configure>`-ben (a tartalom építés közben nő). Kimarad, aminek saját
   görgetése van: `_NO_WHEEL` (Listbox, Treeview, Text, Canvas, legördülők).
3. A görgetősáv **csak akkor látszik, ha tényleg kell**.

### 20.3 Fix alsó gombsáv — mert a görgetés önmagában kevés

A görgethetőség azt garantálja, hogy egy vezérlő *elérhető*; a záró művelethez ez
kevés, azt *látni* kell. A Szerkesztés „Alkalmaz” sávjának mintájára a shell 1. sora
fix, görgetésen kívüli gombsáv:

- **Arckép**: *Mentés másként…* + *Iktatás a feltölthetőbe*
- **Összeállító**: *Iktatás* + *Visszavonás* (a `btn_go` látszódását a 17.2-es
  regressziós teszt már méri — a pusztán görgethető változat elbukott rajta, jól)

### 20.4 Két méretcsökkentés, hogy ne kelljen feleslegesen görgetni

- Arckép: a két fájllista 6 → **4 sor**, és már nem `expand=True` (ketten elvitték a
  teljes magasságot, minden más a látható rész alá csúszott). Így a fül lényege, az
  *Igazítás*, görgetés nélkül látszik.
- Összeállító: a *Kimenet* fa kért magassága 4 → **2 sor**; ha van hely, az
  `expand=True` kifeszíti. Négy sort kérve a panel a szokásos ablakban is görgetett.

### 20.5 Ellenőrzés

Önteszt 254/254, GUI **156/156** (új: „MINDEN FÜL: A LEGKISEBB ABLAKBAN SEM LÓG LE
GOMB” — 940×620-ban mindkét záró gomb látszik; az Arckép panelja görgetősávot mutat
és a végére görgetve a Típus legördülő is látszik; az Összeállító panelja szokásos
ablakban nem görget), verzió, frissítő zöld.

Felületfotó: `python tools/ui-kep.py 3 arckep.png` és `... 0 osszeallito.png`.

---

## 21. Ötödik kör (2026-10-14): élő szöveg, valós idejű formázás, lapozás

### 21.1 A kérés

1. Nagyításkor nincs oldalsó csúszka: függőlegesen csak görgővel, vízszintesen sehogy.
2. A lapozás csak a legördülőnek látszó beíróval megy — legyenek **lapozógombok**.
3. A modullal elhelyezett szöveg (raszterizálás nélkül, ugyanabban a futásban) nem
   mozgatható — kell **drag-and-drop** és **nyilas** mozgatás.
4. A formázás (betű, méret, félkövér, dőlt, aláhúzás…) csak az **Alkalmaz** után látszik —
   legyen **valós idejű**.
5. Nagyított kijelzőn a bal panel feliratai levágódnak — ez közös felületi ügy,
   `kepek-pdf-terv.md` 19.2.

### 21.2 Élő szöveg: `PlacedText`

Eddig az új szöveg a kattintás pillanatában a lap tartalomfolyamába került
(`add_text`), onnan pedig csak redakcióval lehetett volna kivenni — ami a környező,
eredeti betűket is vinné (16.4). Ezért az új szöveg most **a mentésig objektum marad**:

```python
@dataclass(eq=False)
class PlacedText:            # lap, alapvonal (x, y), szöveg, betű, méret,
    ...                      # félkövér, dőlt, aláhúzott, szín, uid
```

| függvény | mit tud |
|---|---|
| `placed_bbox` | a befoglaló a betű fel- és lenyúlásával, az aláhúzással; üres szövegnél is kijelölhető |
| `write_placed` | kiírás a lapra — a **mentés és az előnézet ugyanezt hívja**, ezért az látszik, ami a lapra kerül |
| `placed_pixmap` | átlátszó kép a vászon nagyításán, befoglaló méretű ideiglenes lapon (a MuPDF rajzolja, a valódi betűvel) |
| `bake_placed` | mentéskor a dokumentum **másolatába** írja; a szerkesztett példány érintetlen, így a szöveg a mentés után is mozgatható |
| `placed_missing` | a választott betűből hiányzó karakter (csendben eltűnne) — az állapotsor szól |

**A vásznon** a szöveg külön képelem a lap fölött: húzáskor csak ezt mozgatjuk
(`canvas.move`), a lapot nem kell újrarajzolni — ez teszi folyamatossá a húzást.

**Mozdulatok** (Szöveg és X eszköz):

- kattintás a szövegen: kijelölés (kék szaggatott keret) — **húzás**: mozgatás;
- **nyilak**: 1 pt, **Shift+nyíl**: 10 pt; kijelölés nélkül a nyíl a nézetet görgeti;
- **dupla kattintás**: átírás a helyén; **Delete**: törlés; **Esc**: kijelölés vége;
- üres helyre kattintva, ha van kijelölés, az első kattintás csak feloldja (különben
  minden „kattintsunk mellé” új beírómezőt nyitna);
- a **Kitakarás** az élő szöveget is viszi, ha a területébe esik;
- a Bekezdés eszközzel élő szövegre kattintva a Szöveg eszköz veszi át (az élő szöveg
  nem a lap bekezdése, a formázását a szövegpanel végzi).

**Visszavonás:** a verem eleme most `(PDF-bájtok | None, a szövegek másolata)`. Az élő
szöveg lépései nem másolják a PDF-et (`None`) — egy nagy szkennelt iratnál a nyilazás
különben minden lépésre megabájtokat másolna. Az **egymás utáni nyilazás egy lépés**, és
**egy kijelölés formázása is egy lépés** (kulcs: `("move", uid)` / `("style", uid)`).

### 21.3 Valós idejű formázás — Alkalmaz nélkül

**Élő szöveg:** a Szöveg eszköz panelje (betű, méret, félkövér, dőlt, aláhúzott, szín,
és maga a **szöveg**) kijelölt szövegnél azonnal arra hat; kijelölés nélkül a következő
új szöveg stílusa. A panel változását 120 ms-mal késleltetve rajzoljuk (`LIVE_MS`): a
méretmező gépelése közben ne minden billentyűre. A betűobjektumok gyorsítótárból jönnek
(`edit_font`): egy TTF megnyitása önmagában érezhető késés volna.

**Bekezdés:** a panel minden változása azonnal a lapra kerül; az **Alkalmaz gomb
megszűnt**, a helyén az **Eredeti bekezdés** visszaállítja a kijelöléskori állapotot.
A módszer: a kijelöléskor (az első változásnál) pillanatképet készítünk, és minden
változáskor **a pillanatképből indulva** a panel *teljes* eltérését alkalmazzuk. Így az
eredmény csak a panel mostani állapotától függ — a 10 → 8 → 10 pt ugyanazt a lapot
adja vissza, nem egy kétszer újratördelt változatot (a GUI-teszt méri). Minden
alkalmazás külön visszavonási lépés, mint eddig az Alkalmaz.

- Hibás állapot (hiányzó betű, félkövér család nélkül) nem dob ablakot gépelés közben: az
  állapotsor szól, a lap az utolsó jó állapotában marad.
- Vegyes formázású bekezdés újratördelése előtt egyszer kérdez (bekezdésenként).
- A „Bekezdés szövege…” párbeszéd ugyanebbe az élő menetbe ír.

### 21.4 Lapozás, nagyítás, görgetés

- **Görgetősáv:** a téma hibája volt (1×1 px, `kepek-pdf-terv.md` 19.1).
- **Lapozógombok** (első / előző / következő / utolsó) a beíró két oldalán, mellette
  „/ N”; a szélső lapon a gomb tiltott. **PageUp/PageDown** a vásznon. A lapozósor az
  eszköztár alatti sorba került, az állapottal együtt: az első sorban a gombok
  összenyomták a beírót, és az állapotból „nyi” maradt (felületfotón, 1280 px).
- **Shift+görgő** vízszintesen, **középső gombbal húzva** szabadon; a **Ctrl+görgő a
  kurzor alatti pontot** tartja helyben, a +/− gomb a nézet közepét.
- **Csak a látható sáv rajzolódik**, ha a lap képe 6 megapixelnél nagyobb lenne
  (`RENDER_MAX_PX`; 6× nagyításon egy A4 50 MP — másodpercekig tartott volna): fél
  képernyőnyi ráhagyással, és görgetéskor, ha kiér belőle, késleltetve újrarajzol.

### 21.5 A közben talált hiba: a saját mentett iratunk betűneve

A mentés `subset_fonts()`-szal részhalmazol, és a PyMuPDF ezután a betűt **„Calibri
Regular”**, „Calibri Bold Italic” néven adja vissza. A `span_style` ezt nem ismerte fel
családnak, így egy **mentett és újranyitott** iratban a szerkesztő saját bekezdését sem
lehetett újraformázni („A bekezdés betűje nincs meg a gépen: Calibri Regular”). A
szóközzel írt stílusszó (`STYLE_WORDS`) most leválik a névről; a családnév része
(„Times New *Roman*”) marad. Az új GUI-teszt épp a mentett iraton formáz.

### 21.6 Szándékos egyszerűsítések

- Az élő szöveg **egy sor** (mint eddig). A többsoros, tördelt szövegdoboz a 22.2 első
  javaslata.
- A **lap eredeti szövegének átírása** (kattintás meglévő szövegre) továbbra is azonnal a
  lapra kerül, nem élő objektum: különben a bekezdés-formázás nem látná, és a bekezdés
  közepéből „kilógna” egy mozgatható szó.
- Az élő szöveg az újranyitás után a lap tartalma — mozgatni már nem lehet (a kérés is
  ugyanabban a futásban kérte).
- Forgatott lapra továbbra sem írunk.

### 21.7 Ellenőrzés

Önteszt: új „ÉLŐ SZÖVEG” szakasz (13 ellenőrzés: befoglaló, előnézet, kiírás helye,
stílusa, színe, aláhúzás, hiányzó karakter, a mentés utáni betűnév, a betű-gyorsítótár).
GUI: új „SZERKESZTŐ: GÖRGETŐSÁV, NAGYÍTÁS, LAPOZÁS” (13), „SZERKESZTŐ: ÉLŐ SZÖVEG —
HÚZÁS, NYILAK, VALÓS IDEJŰ FORMÁZÁS” (25, köztük a gyors kijelölésváltás: a függő
formázás nem vész el), „SZERKESZTŐ: VALÓS IDEJŰ BEKEZDÉS-FORMÁZÁS” (5) — valódi egér- és billentyűeseményekkel; a régi „üres cellába új szöveg” és
„eszközváltás” ellenőrzés az új viselkedéshez igazítva. Felületfotó: `python
tools/ui-kep.py 6 bekezdes.png`.

---

## 22. Bővítési lehetőségek (2026-10-14): pdfrw és más projektek áttekintése

A kérés: tekintsük át a [pdfrw](https://github.com/pmaupin/pdfrw)-t és más repókat, hogy
a Műhely **elsősorban szöveges** PDF-szerkesztési modulokkal bővülhessen.

### 22.1 pdfrw — függőségnek nem, ötletnek igen

| | |
|---|---|
| mi | tiszta Python PDF olvasó/író: összefűzés, részhalmaz, forgatás, metaadat, lap mint Form XObject (vízjel, 4-up, füzet, poszter), reportlab-híd |
| állapot | utolsó kiadás **0.4, 2017. szeptember**; Python 2.6–3.6-ra tesztelve |
| nem tud | **szöveget kinyerni vagy szerkeszteni** (a tartalomfolyamot nem értelmezi), renderelni, titkosítást; kevés tömörítő szűrőt ismer |

**Döntés:** új függőségként **nem** javasolt. Amit tud, azt a már használt PyMuPDF is
tudja (`show_pdf_page` = lap mint XObject, `insert_pdf` = összefűzés, `select` =
részhalmaz, `set_metadata`), a szöveghez pedig épp az hiányzik belőle, amit a Műhely
már ma is használ. Ami **átvehető**: a példaprogramjai mint funkciólista (vízjel minden
lapra, N-up, füzetnyomtatás), és két rá épülő projekt ötlete (lent: pdf-redactor).

### 22.2 Javasolt szöveges modulok — a már meglévő PyMuPDF-re építve

Sorrend: érték a napi munkában / ráfordítás. Mind **új függőség nélkül** megy; a
PyMuPDF-funkciókat ezen a gépen (1.28.2) kipróbáltam.

1. **Többsoros szövegdoboz, gazdag szöveggel** — `Page.insert_htmlbox`: téglalapba
   tördelt szöveg HTML/CSS-ből, félkövér/dőlt **szavanként**, sorkizárás, és ha nem fér
   ki, arányos kicsinyítés (`scale_low`). Mérve: a magyar ékezetek (ő, ű, Ő, Ű) hibátlanok,
   a sorkizárás működik. Az élő szöveg (21.2) természetes folytatása: a `PlacedText` kap
   egy szélességet, a vásznon a doboz széle húzható. Ezzel jönne a hiányzó
   **megjegyzés-, záradék-, „Kelt:” blokk** is.
2. **Keresés és csere** (egy iratban, vagy a dolgozó összes iratában) — `search_for` +
   a meglévő `rewrite_span` útja (redakció 15%-kal beljebb húzott téglalappal, a span
   saját betűjével). **Előnézetes lista**, mint a Rendezésnél, és a csere csak
   jóváhagyásra. Mérve, miért kell a mi utunk: a PyMuPDF beépített cserés redakciója
   (`add_redact_annot(text=…)`) a szomszéd sor betűit is vitte. Ötlet a
   [pdfedit](https://github.com/sachinpandey22/pdfedit)-ből (MIT): ha az új szöveg
   szélesebb, a betű legfeljebb 60%-ig kicsinyül, utána figyelmeztet; kötegnél előbb
   mindent ellenőriz, és csak hiba nélkül ír.
3. **Mintás kitakarás (személyes adat)** — szabályos kifejezésekkel: TAJ (`\d{3} ?\d{3}
   ?\d{3}`), útlevélszám, adóazonosító, születési dátum; találatonként jóváhagyás, majd a
   meglévő `erase_area`. A [pdf-redactor](https://github.com/JoshData/pdf-redactor)
   (CC0, pdfrw-alapú) tanulsága: a **metaadatot és az XMP-t is** tisztítani kell, és a
   megjegyzések szövegét is — különben a kitakarás csak látszat.
4. **Fejléc, lábléc, oldalszám, bélyegszöveg, vízjel** — „1/3. oldal”, „MÁSOLAT”,
   „Iktatva: 2026-10-14 — Kiss Anna” minden lapra; `insert_htmlbox` elforgatással és
   átlátszósággal, vagy egy egyszer megrajzolt lap `show_pdf_page`-dzsel (a pdfrw
   `watermark.py` mintája). A [Stirling-PDF](https://github.com/Stirling-Tools/Stirling-PDF)
   funkciólistája (oldalszám, bélyeg, vízjel, automatikus kitakarás, OCR, összevetés)
   jó ellenőrzőlista ehhez a körhöz.
5. **Űrlap kitöltése és lapítása** — a Műhely már készít mezőt (DocGen-sablon); egy
   „Kitöltés” nézet a meglévő mezőkhöz, és a feltöltés előtti **lapítás**
   (`Document.bake()`): a portálok egy része a kitölthető űrlapot nem fogadja. Minta: a
   [PyPDFForm](https://github.com/chinapandaman/PyPDFForm) (MIT) kitöltő/mezőkészítő API-ja.
6. **Megjegyzések belső egyeztetéshez** — kiemelés és cetli (`add_highlight_annot`,
   `add_freetext_annot`), mentés előtt `bake()`-kel beégetve vagy törölve. Kisebb érték.

### 22.3 Külső eszközt igénylő, nagyobb lépés

- **OCR a szkennelt iratokra** — a Műhely iratainak nagy része szkennelt kép: ezeken ma
  semmilyen szöveges művelet (címke a szövegből, keresés, csere, mintás kitakarás) nem
  működik. Kétféle út: a PyMuPDF `get_textpage_ocr`-je, vagy az
  [OCRmyPDF](https://github.com/ocrmypdf/OCRmyPDF) (MPL-2.0; Windowson is fut, PDF/A-t ír,
  kiegyenesít, forgat). Mindkettőhöz **Tesseract** kell a magyar nyelvi csomaggal, az
  OCRmyPDF-hez Ghostscript is — vagyis telepítés a céges gépeken. Ezért külön döntés:
  opcionális modulként, ami csak akkor jelenik meg, ha a Tesseract megvan.

### 22.4 Amit nem javaslok

- **borb** — a funkciókészlete (elrendezés, bekezdés, táblázat) vonzó, de AGPL/kereskedelmi
  kettős licenc, egyszemélyes projekt, és a PyMuPDF mellett második PDF-motor volna.
- **pypdf / pikepdf** — jó, karbantartott könyvtárak, de a szöveghez (renderelés,
  betűmetrika, redakció) nem adnak többet a PyMuPDF-nél; csak akkor, ha egyszer
  alacsony szintű tartalomfolyam-szerkesztés (qpdf) kellene.
- **N-up, füzet, poszter** (a pdfrw példái) — a feltöltési munkafolyamatban nincs rájuk
  szükség.

### 22.5 Javasolt sorrend

1. Többsoros szövegdoboz (22.2/1) — a 21-es élő szöveg kiterjesztése, kis kockázat.
2. Keresés és csere előnézettel (22.2/2), utána mintás kitakarás (22.2/3) — ugyanaz a
   keresőmag, más művelet.
3. Fejléc/lábléc/oldalszám/bélyeg (22.2/4).
4. OCR (22.3) — külön döntés a telepítésről.

Ezekhez a felhasználó döntése kell (melyik, milyen sorrendben); a kód ehhez a körhöz
nem változott.

---

## 23. Hatodik kör (2026-10-14): szövegdoboz, keresés-csere, személyes adat, fejléc-bélyeg, űrlap, OCR

A 22.5 sorrendje, egy körben. A kérés külön hangsúlya: **a felület legyen könnyen
használható** — „hiába jók a fejlesztések, ha nehezen használható a UI”. Ezért a
fejezet a felülettel kezdődik.

### 23.1 A felület: tíz eszköz egy panelen

Az eszközök száma ötről tízre nőtt. A régi rádiógomb-lista ezzel a bal panel felét
vitte volna el, és alacsony ablakban az eszköz saját panelje a látható részen kívülre
csúszott (felületfotón). A megoldás:

- **Csempék, két sorban, öt oszlopban** (`EDIT_TOOLS`): fölül a **lapon** dolgozók
  (Szöveg, Doboz, Bekezdés, Mező, Kitakarás — kattintás, húzás a lapon), alul az
  **egész iratra** hatók (Keresés, Személyes, Fejléc, Űrlap, Felismerés — panel és
  előnézet). Ikon fölül, rövid felirat alul; a teljes név és egy mondatos magyarázat a
  **súgóbuborékban** (`Tip`) és a panel címében. A csempe nem kap fókuszt
  (`takefocus=0`): a nyilak a vásznon maradnak.
- **A fájllista egy sorra csukódik**, ha irat van nyitva: a fájl neve (félkövér, hosszú
  névnél „…”-tal, a teljes út a buborékban) és egy **Másik irat…** gomb. Mentetlen
  változásnál a név előtt ●, piros színnel.
- **Fix alsó műveletsáv eszközönként** (`_abar`): a fő gomb (Csere a kijelöltekre,
  Kitakarás, Beégetés, Felismerés indítása) a görgethető részen kívül van, mindig
  látszik (a 20.3 elve, most minden eszközre).
- **A súgó két sor** eszközönként; a részlet a buborékokban van.
- **Az üzenetek az alkalmazás alsó állapotsorába** kerültek; a lapozósorban így elfér a
  lapozás mellett a **nagyítás** (Illeszt, +, −) — 960 px-es ablakban az eszköztáron a
  nagyítógombok összenyomódtak, és az állapotból csak töredék látszott.
- **Gyorsbillentyűk:** Ctrl+F (Keresés), F3 / Shift+F3 (következő / előző találat),
  Ctrl+S (mentés), Ctrl+Z; a szövegdobozban Ctrl+B / Ctrl+I / Ctrl+U. Csak akkor élnek,
  ha a Szerkesztés fül látszik (`_guard`).
- **Gyors második kattintás** a lapon nem lesz „dupla kattintás”, ha alatta nincs
  objektum — különben a gyorsan egymás után letett két szövegből az egyik elveszett.

A panel szélessége 370 px (eddig 340): a csempefeliratok és a gombsorok 150%-os
skálán is elférnek (`PDF_MUHELY_SKALA=1.5`, GUI-teszt és felületfotó).

**Közös elv az egész iratra ható eszközöknél:** semmi nem íródik a lapra jóváhagyás
nélkül. A panel listában mutatja, mi fog történni (találatonként, jelölőnégyzettel),
a lapon **kiemelve** látszik ugyanez, a listában kattintva a lap odaugrik; a művelet a
műveletsáv gombjával indul, és **Ctrl+Z visszavonja** a mentésig.

### 23.2 Szövegdoboz (Doboz)

A 21-es élő szöveg többsoros párja: `PlacedBox` — lap, téglalap, bekezdések
futamokra bontva (`(szöveg, félkövér, dőlt, aláhúzott)`), betű, méret, szín,
igazítás (balra / középre / jobbra / **sorkizárt**), sortáv, „kicsinyít, ha nem fér”.

- **A lapon:** téglalapot húzol — ott lesz a doboz; a doboz húzható, a sarkainál és
  az oldalain átméretezhető, nyilakkal mozgatható (1 pt, Shift-tel 10 pt), Delete
  törli. A szöveg a panel formázott beírójába
  kerül (`tk.Text`): a kijelölt szavak **Ctrl+B / I / U**-val vagy a gombokkal
  formázhatók, a lapon azonnal látszik (mint a 21.3-ban).
- **Saját tördelő, nem az `insert_htmlbox`.** A 22.2 terve a HTML-motor volt, de a
  megvalósításkor két hibát mért: (1) a betű **ligatúráit** („tt”, „ti”) alkalmazza, és a
  szövegrétegből `\x82` jön vissza — a keresés, a csere és a „Címke a szövegből”
  elromlana rajta, CSS-sel nem kapcsolható ki; (2) ha a szöveg nem fér a dobozba,
  `scale_low=1` mellett **semmit nem ír**. A `TextWriter`-út (`wrap_words`,
  `line_positions` — a bekezdés-formázásé) ligatúra nélkül ír, a túlcsordulás mérhető.
- **Ha nem fér ki:** felezéses kereséssel a legnagyobb méret, amin kifér, legfeljebb a
  fele (`BOX_FIT_MIN`), és a panel kiírja, mekkorára. Ha így sem fér, a túlcsorduló
  sorok a dobozon túl is látszanak, a kijelölt doboz alsó éle piros, a panel szól — az
  előnézet nem rejti el a hibát.
- Hiányzó karakter (a választott betűben nincs meg) az állapotsorban.
- A mentés égeti be (`_bytes`), a szerkesztett példány érintetlen; visszavonás mint
  a 21.2-ben (élő réteg: PDF-másolat nélkül).

### 23.3 Keresés és csere

- **Élő keresés:** gépelés közben a találatok a lapon kiemelve (a kijelölt erősebben),
  a listában oldal + szövegkörnyezet + „mi lesz belőle”. Kis-/nagybetű, egész szó,
  minta (reguláris kifejezés; hibás mintánál a panel szól). Enter / F3: következő,
  Shift+Enter / Shift+F3: előző találat; a lista „Mind” / „Egyiket se” gombokkal.
- **A szövegréteg karakterenként** (`page_text_lines`, `rawdict`): a találat téglalapja
  pontos, és a span-határon átnyúló szó (félkövér szótag) is megvan. A blokk sorait
  szóközzel fűzzük össze: a **sortörésen átnyúló** adat (tördelt telefonszám, név a sor
  végén) is megtalálható — ezt kitakarni lehet, cserélni nem (a sor vége nem csúszhat
  át a következő sorba; a listában „sortörésen átnyúlik”, nincs kijelölve).
- **A csere terve írás előtt** (`replace_plan`), és a lista ezt mutatja találatonként:
  „rendben”, „jobbra csúszik”, „betű 85%”, „más betű”, „nem fér el” (`plan_short`: a
  keskeny oszlopba rövid alak; a teljes megjegyzés a találatra lépve az állapotsorban).
  A „nem fér el” alapból nincs kijelölve, és a találatszám sorában is ott van („· 2 nem
  fér el”) — a lista alatti magyarázat alacsony ablakban görgetés mögé kerül.
- **Ha az új szöveg más szélességű, a sor többi része a helyére csúszik** — mint egy
  szövegszerkesztőben —, amíg a hasáb jobb szélén belül marad, és a sor betűi megvannak.
  Mérve, miért kell: a „Kiss Anna” → „Kovács-Nagy Erzsébet” a puszta helyben cserével
  „nem fér el” volt a mintairaton, pedig a sor végén bőven volt hely. Egy sor több
  cseréjénél az eltolások összeadódnak. Ha csúsztatni nem lehet, a betű legfeljebb
  60%-ig kicsinyül (`REPLACE_MIN`, a pdfedit ötlete).
- **Utóellenőrzés:** a csere után újrakeres, és kiírja, hány helyen maradt a keresett
  szöveg (a kivett találatok ott maradnak, ez így helyes — de látszik).
- **Az írás** (`apply_replace`): a régi szöveg redakcióval ténylegesen törlődik (15%-kal
  beljebb húzott téglalap, 16.4), az új ugyanarra az alapvonalra, a saját színével és —
  ha a beágyazott betűben minden karakter megvan — a saját betűjével. Laponként egy
  redakció; az egész csere egy visszavonási lépés.
- Szkennelt iratnál a panel szól, és egy gombbal a Felismerésre visz (23.7).

### 23.4 Személyes adatok kitakarása

Ugyanaz a keresőmag (`find_hits`), előre megírt mintákkal (`PII_PATTERNS`):
TAJ-szám, adóazonosító jel, útlevélszám, személyi igazolvány száma, bankszámla és
IBAN, telefonszám, e-mail, dátum (alapból ki: a legtöbb irat tele van dátummal), és
egy **saját szöveg** (név, cím).

- **Ellenőrzőszám:** a TAJ (3-7 súly, mod 10), az adóazonosító (helyiérték-súly,
  mod 11), a belföldi számlaszám (9-7-3-1) és az IBAN (mod 97) **csak hibátlanul**
  kerül a listába — így a „kilenc jegyű szám” nem fut be minden iktatószámra (a
  jelölőnégyzet buborékja ezt el is mondja).
- A típusok jelölőnégyzetei mellett a találatok száma („TAJ-szám (2)”); a lista
  „Mind” / „Egyiket se” gombokkal, a gombon a kijelöltek száma („Kitakarás (3)”).
- Átfedő találatokból egy marad, a hosszabbik (a dátum és a telefonszám ugyanazt a
  jegysort is megfoghatja). Az átfedést **soronkénti** téglalapokkal mérjük: a két sorra
  törő találat befoglalója a köztes szöveget is lefedné, és jó találatot dobna el
  (a GUI-teszt mérte).
- **Kitakarás** (`redact_hits`): a terület szövege és a kép képpontjai **végleg**
  törlődnek; a helye fekete vagy fehér sáv. A pdf-redactor tanulsága szerint a
  **metaadat** is törlődik (cím, szerző, tárgy, XMP) — de a Műhely bélyege (/Keywords)
  marad, abból ismeri fel az Áttekintő az iratot.
- **Utána újrakeres**, és megmondja: „egyik sem maradt az iratban” — vagy hány maradt.
- Szkennelt lapon (OCR után) ugyanígy működik: a felismert szó helyén a kép
  képpontjai törlődnek.

### 23.5 Fejléc, lábléc, oldalszám, bélyeg, vízjel

A Stirling-PDF listájából ami a feltöltési munkafolyamatban kell. Élő beállítás
(`Decor`), minden lapon azonnal látszik, a **Mentés égeti be**.

- **Gyors beállítás, egy kattintással:** „Oldalszám” (1/3 alul középen), „Másolat”
  (vízjel), „Iktatva” (bélyeg az első lapon) — a ritkán kellő részletek alatta.
- **Fejléc, lábléc, oldalszám:** szöveg, igazítás (bal / közép / jobb); az oldalszám
  kész formákból („1/3”, „1. oldal”, „– 1 –” …), „az első lapon nem”. Ha a lábléc és az
  oldalszám ugyanabba a sarokba kerülne, az oldalszám fölé lép.
- **Változók** (`{oldal}`, `{összes}`, `{dátum}`, `{dolgozó}`, `{doktípus}`,
  `{fájlnév}`), egy „Változó beszúrása” menüből — a dolgozó és a doktípus a Műhely
  bélyegéből, ha nincs, az alapértelmezett dolgozóból.
- **Bélyeg:** keretes szöveg („Iktatva: {dátum}”), piros / kék / fekete, csak az első
  lapon vagy mindegyiken; alapból a jobb felső sarokban, **a lapon húzással bárhová
  tehető**, a „Sarokba” gomb visszateszi.
- **Vízjel:** átlós, halvány szöveg („MÁSOLAT”), az átlátszóság csúszkával.
- **Ütközés:** ha egy díszítés a lap meglévő szövegére esne, a panel szól
  (`decor_overlaps`; a vízjel szándékosan átfed) — a margó állításával elkerülhető.
- A műveletsávon „Mind kikapcsolása”.
- **Előnézet:** a lap másolatára írjuk és azt rajzoljuk (`_vcache`, az irat
  változat-számlálójával) — pontosan az látszik, ami a mentéskor a lapra kerül.

### 23.6 Űrlap kitöltése és beégetése

- A panel a mezőket **olvasási sorrendben** listázza (lap, majd fentről lefelé), a
  típusuk szerint: beíró, legördülő, jelölőnégyzet. A lapon a mezőre kattintva a panel
  odagörget és a beíróba ugrik; a panelen a mezőre lépve a lap odalapoz és kiemeli.
  Hosszú űrlapnál szűrő (név vagy érték részlete, ékezetfüggetlenül); fölül „N mező ·
  M üres”.
- **Mérve: a PyMuPDF mező-megjelenítése (Helv, WinAnsi) az ő/ű-t tartalmazó értéket
  egyáltalán nem rajzolja ki** — a „Kőműves Győző” üres mezőnek látszott, és így égett
  volna be. Ezért:
  - a **beégetés** a szöveges mezőt magunk írjuk a lapra (`draw_field_value`,
    `TextWriter`, Unicode-betű, választható családdal): függőlegesen középen, a mező
    igazítása (/Q) szerint, ha nem fér, kicsinyítve; többsoros mezőnél a szövegdoboz
    tördelőjével, fésűs (comb) mezőnél betűnként a cellákba. A jelölőnégyzetet és a
    rádiógombot a saját megjelenése égeti be (`doc.bake`).
  - a **vásznon kitöltés közben is a beégetett kép** látszik (előnézeti másolat), nem a
    mező saját — hibás — megjelenése: amit látsz, az kerül a feltöltött fájlba.
  - a kitöltött, de be nem égetett mezőn a NeedAppearances jelző be: a külső olvasó
    maga rajzolja újra.
- A **Beégetés** egy visszavonható lépés; utána a mezők a lap tartalmai, nem
  szerkeszthetők. A panel szövege elmondja, miért kell feltöltés előtt: a portál a
  kitölthető mezőt gyakran üresnek látja.

### 23.7 Szövegfelismerés (OCR) — telepítés nélkül

**A döntés:** a Tesseract programot **nem** telepítjük a gépekre. A PyMuPDF
(`get_textpage_ocr`) a MuPDF-be épített Tesseract-motort hívja; ehhez csak a
**nyelvi adatfájl** kell, amit a programmal együtt szállítunk:
`tessdata/hun.traineddata` (tessdata_fast, Apache-2.0, 5,3 MB; forrás és
ellenőrzőösszeg: `tessdata/FORRAS.md`). A frissítő (`tools/frissit.vbs`) az
almappát is másolja, így a használat helyére a következő frissítéssel kijut.
Mérve ezen a gépen: a magyar szkennelt mintalap hibátlan („Kőműves Győző”,
TAJ-szám), kb. 1,5 s/oldal 300 dpi-n.

Miért nem az OCRmyPDF: Tesseract és Ghostscript telepítése kellene hozzá minden gépre,
és a mi célunkhoz (a szkennelt iraton keresni, kitakarni, címkét venni) a láthatatlan
szövegréteg elég; PDF/A, kiegyenesítés nem kell a feltöltéshez.

- **Mit ír:** láthatatlan szövegréteget (`render_mode=3`) a lap képe fölé, a szó
  szélességére méretezett betűvel — kereshető, kijelölhető, kitakarható; a kép
  érintetlen, a fájl alig nő.
- **Külön folyamatban fut** (`--ocr`, mint a tömörítés, 13.10): a felület közben él,
  folyamatjelző laponként, **Mégsem** megszakítja (a lap nem változik). Ha közben másik
  irat nyílt meg, az eredmény eldobódik.
- **Mire:** „Minden szöveg nélküli oldal” (alapból) vagy „Csak ez az oldal”. A panel
  előre megmondja, hány lap szkennelt; szöveges iratnál nincs mit tennie.
- „Felismert szavak mutatása a lapon”: zöld keret minden felismert szón — ellenőrzéshez.
  Csak a láthatatlan (`render_mode=3`) rétegen (`ocr_word_rects`, a `get_texttrace`
  `type == 3` jelzéséből): felületfotón látszott, hogy előbb a szöveges lap minden
  saját szavát is bekeretezte, mintha azt is a felismerés adta volna.
- A Keresés és a Személyes adat panelje szkennelt iratnál szól, és egy gombbal ide
  visz.
- A nyelvi fájlt a program a saját `tessdata` mappájában, a `TESSDATA_PREFIX`-ben, vagy
  egy telepített Tesseract mellett keresi; ha nincs, a panel megmondja, hová kell.
  Angolhoz az `eng.traineddata` is betehető (`hun+eng`), a repóba nem tesszük.
- **Ékezetes útvonal (2026-10-14, mérve):** a beépített Tesseract ANSI-fopen-nel nyit,
  így a `…\Dániel\…` alatti `tessdata` mappát nem találja („Tesseract language
  initialisation failed”) — a fájl ép, ékezet nélküli helyről betölt. A felhőben
  ezért nem bukott el a teszt. Javítás: az `ocr_words` a `tessdata` mappába lép, és
  `"."`-ot ad át; a relatív utat a Windows Unicode-ban oldja fel. Elvetve: a
  **8.3-as rövid név** (`GetShortPathNameW`) — kötetenként kikapcsolható, hálózati
  és OneDrive-mappán nincs; **ékezet nélküli helyre másolás** — 5 MB másolat, és a
  felhasználói mappa (`%LOCALAPPDATA%`) maga is lehet ékezetes. Az önteszt ékezetes
  nevű ideiglenes mappából is felismertet, így ékezet nélküli gépen is méri.

### 23.8 Szándékos egyszerűsítések

- A csere **egy iratban** megy; a dolgozó összes iratára (22.2/2) nem — a lista ott
  átláthatatlanul hosszú lenne, és az iratok külön mentése mást kíván.
- A sortörésen átnyúló találatot nem cseréljük (a sor vége nem tördelődik át).
- A szövegdoboz forgatott lapra nem ír (mint az élő szöveg).
- Az OCR nem egyenesít ki és nem forgat; ferde szkennél rosszabb az eredmény — a
  Rendezés forgatása előtte segít.
- Megjegyzés (kiemelés, cetli, 22.2/6) nincs: a feltöltési munkafolyamatban kis érték.

### 23.9 Ellenőrzés

Önteszt: hat új szakasz, 50 ellenőrzés — SZÖVEGDOBOZ (9: tördelés, sorkizárás,
szavankénti félkövér/dőlt, aláhúzás a szóközzel, üres bekezdés, illesztés, kiírás
ligatúra nélkül), KERESÉS ÉS CSERE (14: kis-/nagybetű, egész szó, hibás minta,
sortörésen átnyúló találat, gyorsítótár, rövidebb és hosszabb csere csúsztatással, a
régi szöveg tényleg törlődik, a többi sor érintetlen, a lista rövid megjegyzése), SZEMÉLYES ADATOK (11:
ellenőrzőszámok, minden mintatípus, az iktatószám kiszűrve, kitakarás után a
szövegrétegben sincs, metaadat), FEJLÉC… (7: változók, helyek, első lap, ütközés),
ŰRLAP (4: olvasási sorrend, ő/ű a beégetés után a lap tartalma, fésűs mező),
SZÖVEGFELISMERÉS (5: a beépített motor magyarul, a réteg láthatatlan és kereshető, a
keret csak a felismert szavakon).
GUI: hét új szakasz, 60 ellenőrzés, valódi egér- és billentyűeseményekkel —
ESZKÖZCSEMPÉK, SZÖVEGDOBOZ, KERESÉS ÉS CSERE, SZEMÉLYES ADAT, FEJLÉC/LÁBLÉC/BÉLYEG,
ŰRLAP KITÖLTÉSE, SZÖVEGFELISMERÉS (a külön folyamatos futás a végéig). 100% és 150%
skálán is. Felületfotók eszközönként (1280×740 és 960×650); az új `python
tools/ui-kep.py 7 kep.png <eszköz>` ugyanezt a mintairatot fényképezi.
