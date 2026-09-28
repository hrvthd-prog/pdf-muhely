# Terv — Szétvágás kötegelt kiosztással (és visszavezetés a Képek → PDF-be)

**Státusz:** megvalósítva (F0–F6, 2026-09-28) — lásd 14.4 · **Készült:** 2026-09-28
**Fontos:** a 14. fejezet (döntések) felülírja a korábbi fejezeteket, ahol eltérnek — megvalósításkor az a mérvadó.
**Érintett fájlok:** `pdf-muhely.py`, `test/gui.py`, `README.md`
**Előzmény:** `kepek-pdf-terv.md` — a rács, a vonszolás, a nagyító és az 5 MB-os lépcsőzetes tömörítés onnan jön.

---

## 0. Kiindulás — mi van ma

### 0.1 Szétvágás fül (`SplitTab`)

- Fájllista, a kijelölt PDF-ek **minden oldala külön fájlba** kerül: `{forrásnév}\{forrásnév}_001.pdf`, …
- Próbafutás és felülírás kapcsoló van. Előnézet, sorrend, névképzés, Iktató-kapcsolat **nincs**.
- A kimenet 40 oldalnál 40 számozott fájl, amit utána egyenként kell az Iktatóban elnevezni és összefűzni. Kötegelt szkennelésre ez nem használható.

### 0.2 Képek → PDF fül (`ImagesToPdfTab`) — és miért nehézkes

Megvan: bélyegképrács, vonszolásos sorrend, Ctrl/Shift kijelölés, ↺/↻, nagyító, 5 MB fölött automatikus tömörítés.

Egy iratnyi kép feldolgozása ma így megy:

| # | Lépés | Hol |
|---|-------|-----|
| 1 | képek kijelölése | Képek → PDF |
| 2 | „Kijelöltekből PDF → Iktató…” | Képek → PDF |
| 3 | **mentés-párbeszéd** (ideiglenes név és hely) | párbeszéd |
| 4 | (automatikus fülváltás) doktípus választása | Iktató |
| 5 | a dolgozó megkeresése, húzás a csempéjére | Iktató |
| 6 | vissza a Képek → PDF fülre, a következő irat | fülváltás |

**N iratnál ez N párbeszéd és 2N fülváltás.** Mellékhatás: a 3. lépés köztes PDF-je a képek mappájában marad, mert az Iktató másol, nem mozgat.

---

## 1. Cél

1. **Grafikus előnézet:** a köteg-PDF oldalai bélyegképként látszanak, kijelölhetők és vonszolással sorrendezhetők.
2. **Egy helyen kiosztás:** egy felületen dől el, melyik oldalból milyen típusú és nevű PDF lesz. **Egyetlen „Iktatás” gomb** írja ki az összeset.
3. **Az Iktató metodikája:** ugyanaz a névképzés (`target_name`), ütközéskezelés, `.eredeti\` mentés, ellenőrzött írás, `iktato-naplo.csv`, 5 MB-os tömörítés és visszavonás — **közös kódból, nem másolatból**.
4. **Visszavezetés:** ha a megoldás bevált, a Képek → PDF is így működjön.

---

## 2. Az alapötlet: a kiosztás címke az oldalon

Nincs külön „iratszerkesztő”: **a rács maga a szerkesztő.**

- Minden oldal (bélyegkép) kaphat egy **címkét**: *(dolgozó, doktípus)*.
- **Egy kimeneti irat = az azonos címkéjű oldalak, a rácsban látott sorrendben.** Az irat oldallistáját sehol nem tároljuk, mindig a rácsból számoljuk, így nem csúszhat el a képtől.
- A címke **színes sávként** látszik a bélyegkép alján, az Áttekintő rövid kódjával (`Forma`, `Előz`, `Útl` …). Minden irat saját színt kap.
- **Címke nélküli oldal = kimarad** (elválasztó lap, üres hátoldal). Iktatáskor az összegzés megmondja, hány ilyen van.

### 2.1 A leggyorsabb mozdulat: címkézés és továbblépés

Ha egy oldal van kijelölve, a **számbillentyű felcímkézi, és a kijelölés a következő oldalra lép.** Egy 12 oldalas köteg így billentyűzetről is végigmehető (`1 1 1 2 2 3 3 3 0 4 …`), a szem közben a képen marad. Többes kijelölésnél mind megkapja a címkét, a kijelölés pedig az utolsó utáni oldalra ugrik.

A **nagyítóban** (dupla kattintás) ugyanezek a billentyűk működnek: nagyban látod az oldalt, számmal címkézed, és lapoz a következőre. Szkennelt iratnál ez akkor is felismerhetővé teszi a típust, ha a bélyegképen nem olvasható.

### 2.2 Egy tipikus köteg

12 oldalas szkennelés, Kiss Anna aláírt iratai:

1. **PDF megnyitása…** (vagy az Iktatóból: „Szétosztás…”, lásd F6)
2. Dolgozó mező: `kis` ↵ → Kiss Anna
3. 1. oldalra kattintás, Shift+kattintás a 3.-ra → `1` (formanyomtatvány)
4. 4.–5. oldal → `2` (előzetes megállapodás) … és így tovább
5. **Iktatás (4 irat)** → összegző párbeszéd → Igen

Iratonként **2 mozdulat** (kijelölés, szám), kötegenként 3 fix lépés. Ma iratonként 6 lépés és egy párbeszéd.

---

## 3. Képernyőterv

```
┌─ Összeállító ─────────────────────────────────────────────────────────────────────┐
│ [PDF megnyitása…] [+ PDF / kép…]  [↺] [↻]  [Törlés]   42 oldal · 3 kijelölve      │
├──────────────────────────────────────────────────────┬────────────────────────────┤
│ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐         │ Dolgozó: [kis          ▼]  │
│ │      │ │      │ │      │ │      │ │      │         │          Kiss Anna         │
│ │  1   │ │  2   │ │  3   │ │  4   │ │  5   │         ├────────────────────────────┤
│ │      │ │      │ │      │ │      │ │      │         │ Típus (kattintás / szám):  │
│ ├──────┤ ├──────┤ ├──────┤ ├──────┤ ├──────┤         │ [1] Tart_eng_formanyomt.   │
│ │Forma │ │Forma │ │Forma │ │ Előz │ │  —   │         │ [2] Előzetes megállapodás  │
│ └──────┘ └──────┘ └──────┘ └──────┘ └──────┘         │ [3] Elfogadó nyilatkozat   │
│ ┌──────┐ ┌──────┐                                    │ [4] …                      │
│ │  6   │ │  7   │  …                                 │ [0] címke törlése          │
│                                                      │ [Típusok…]                 │
│                                                      ├────────────────────────────┤
│                                                      │ Kimenet — 3 irat           │
│                                                      │ ■ Kiss Anna Tart_eng_fo…   │
│                                                      │     3 old. · 0,4 MB        │
│                                                      │ ■ Kiss Anna Előzetes me…   │
│                                                      │     1 old. · ⚠ már létezik │
│                                                      │ ■ Kiss Anna Útlevél        │
│                                                      │     1 old. · 6,1 MB ⚠ 5 MB+│
│                                                      │ Utótag: [aláírt]           │
│                                                      │ 1 oldal címke nélkül       │
│                                                      │ [   Iktatás (3 irat)   ]   │
│                                                      │ [Visszavonás]              │
├──────────────────────────────────────────────────────┴────────────────────────────┤
│ napló                                                                             │
└───────────────────────────────────────────────────────────────────────────────────┘
```

- **Bal:** a Képek → PDF rácsa, változatlan mozdulatokkal (kattintás, Ctrl, Shift, vonszolás, Delete, dupla kattintás = nagyító).
- **Dolgozó:** szűrős legördülő a munkamappa almappáiból (ugyanaz a forrás és ékezetfüggetlen szűrés, mint az Iktató csempéinél). Csak létező mappa választható, a program mappát nem hoz létre (mint az Iktató). A címkézés a **pillanatnyi** dolgozót teszi az oldalra, így vegyes kötegnél dolgozót váltasz, és címkézel tovább.
- **Típuspaletta:** az Iktató doktípus-listája (`iktato-doktipusok.json`), ugyanazzal a „Típusok…” szerkesztővel. Az első kilenc típus kap számbillentyűt.
- **Kimenet:** iratonként egy sor, dolgozónként csoportosítva: teljes név, oldalszám, méret, figyelmeztetés. Egy sorra kattintva a rácsban kijelölődnek az irat oldalai. Az **Utótag** mező a kijelölt iratra vonatkozik, az alapértéke a típusból jön, ugyanúgy, mint az Iktatóban (DocGen-irat: „aláírt”, egyéb: üres).

---

## 4. Adatmodell

A Képek → PDF `ImgItem`-je két mezővel bővül, és `PageItem` lesz:

```python
@dataclass(eq=False)
class PageItem:
    path: str                    # PDF vagy kép
    page: int = 0                # PDF-oldal sorszáma (képnél 0)
    rot: int = 0                 # felhasználói forgatás
    thumb: object = None
    bad: str = ""
    doc: "OutDoc | None" = None  # a címke

@dataclass(eq=False)
class OutDoc:
    who: str                     # a dolgozó mappája
    doc_type: str
    suffix: str
    color: str
```

- **A kép és a PDF-oldal ugyanaz a dolog:** a MuPDF a képet egyoldalas dokumentumként nyitja meg (`pymupdf.open(kep)[0]`), így a bélyegkép, a nagyító és a forgatás kódja közös, csak `d[0]` helyett `d[it.page]` áll. **Csak a kiírás különbözik:**
  - PDF-oldal: `insert_pdf` + `set_rotation` — **veszteségmentes**, a kép bájtra azonos marad (lemérve, 1.26.7);
  - kép: a mai `image_page_jpeg` + `add_image_page` (minőség-előbeállítás, szürkeárnyalat, A4).
- Az irat oldalai: `[it for it in items if it.doc is d]`, ami a rácssorrendet adja. Tárolt oldallista nincs.
- Ugyanarra a *(dolgozó, típus)* párra címkézve a meglévő irat bővül, nem keletkezik új.

---

## 5. Iktatás (kiírás)

### 5.1 Előellenőrzés — a gomb megnyomásakor, írás előtt

Iratonként: név (`target_name`), cél (`munkamappa\dolgozó\név`), útvonalhossz (`check_path_len`), **létezik-e már**, és a tényleges méret. Az irat memóriában áll össze; ez 3 oldalnál ~13 ms (lemérve), tehát a kimeneti lista mérete címkézés közben is élőben frissülhet.

**Egyetlen összegző párbeszéd:**

> 4 irat, 1 dolgozó · 1 már létezik · 1 tömörítendő (5 MB fölött) · 2 oldal címke nélkül (kimarad)
> Ütközésnél: **Új néven (2)** · Felülírás (az előző a `.eredeti\`-be kerül) · Mégsem

Az ütközés módját tehát **kötegenként egyszer** kell eldönteni, nem fájlonként. Hogy melyik ütközik, a kimeneti listában látszik.

### 5.2 Kiírás

- `after()`-láncban, iratonként (a Képek → PDF mintájára): a felület él, van folyamatjelző és „Mégsem”.
- 5 MB fölött automatikus lépcsőzetes tömörítés (`shrink_later`), ugyanúgy, mint a Képek → PDF-ben.
- `write_pdf_verified` (.part → oldalszám-ellenőrzés → `os.replace`), felülírásnál előbb `.eredeti\` mentés.
- **Napló:** iratonként egy sor az `iktato-naplo.csv`-be, az Iktatóéval azonos oszlopokkal. A „forrás” mezőben a köteg és az oldalak szerepelnek: `...\koteg.pdf [1-3]`.
- **A sikeresen iktatott oldalak kikerülnek a rácsból**, ahogy az Iktató várólistájáról is. Ami bent marad, az a teendő: a címke nélküli és a hibás oldalak.
- **Visszavonás:** az **egész utolsó köteget** vonja vissza (a fájlok törlődnek, felülírásnál az előző példány visszakerül), és az oldalak visszakerülnek a rácsba.
- A forrás köteg-PDF érintetlen marad (→ 5. kérdés).

---

## 6. Közös mag — refaktor, viselkedésváltozás nélkül

A követelmény („az Iktató metodikája szerint”) csak akkor tartható hosszú távon, ha **ugyanaz a kód** fut mindkét helyen.

| Mit | Honnan | Hová |
|-----|--------|------|
| `.eredeti\` mentés | `IktatoTab._backup_existing` | modulszintű `backup_existing(dst)` |
| naplósor | `IktatoTab._log` | `log_row(parent, src, folder, name, doc_type, result)` |
| visszavonás egy fájlra | `IktatoTab._undo` törzse | `undo_copy(src, dst, backup)` → az Iktató egyet hív, a köteg sokat |
| bélyegkép, rács, kijelölés, vonszolás, nagyító | `ImagesToPdfTab`, `ImageViewer` | közös ősosztály (`PageGridTab`), az elem `PageItem` |

Az Iktató a kiemelt függvényeket hívja, a viselkedése nem változik. Ezt a meglévő GUI-teszt (iktatás, tömörítés, `.eredeti\`, visszavonás) őrzi.

---

## 7. Visszavezetés a Képek → PDF-be

- A „Mindből PDF → Iktató…” és a „Kijelöltekből PDF → Iktató…” gomb helyére a **típuspaletta + kimeneti lista + Iktatás** kerül, ugyanaz, mint a Szétvágásban.
- **Megszűnik** a mentés-párbeszéd, a köztes PDF a képek mappájában és a fülváltás.
- A minőség, a szürkeárnyalat és az A4-illesztés marad; ezek a képoldalakra hatnak.
- Mivel az elem- és a rácskód közös, ez a fázis főleg **törlés**: a két régi gomb, a `_run` mentés-párbeszéde és az Iktatóba küldés.

**Egy fül vagy kettő?** A közös elemmodell miatt egyetlen fül („Összeállító”) is fogadhat vegyesen PDF-et és képet: szkennelt köteg + egy telefonos fotó az útlevélről, egy iratba. Kódban ez a kisebb változat. A döntés az F5-ig ráér (→ 3. kérdés).

---

## 8. Hibakezelés

| Eset | Viselkedés |
|------|-----------|
| Jelszavas / sérült PDF | `open_checked` üzenete, a rács nem változik |
| A forrás időközben eltűnt vagy megváltozott | az adott irat hibás (⚠ a listában, naplósor), a többi megy tovább |
| Címkézés dolgozó nélkül | a Dolgozó mező kivillan (`_flash_combo` mintája), nincs címke |
| Részleges hiba a kötegben | a sikeresek kiírva és naplózva, a hibás oldalai a rácsban maradnak |
| 5 MB a legerősebb lépcsővel sem fér be | figyelmeztetés, mint az Iktatóban: „bontsd kevesebb oldalra” — itt ez helyben megtehető |
| Útvonal > 255 karakter | az előellenőrzés jelzi, írás előtt |

---

## 9. Tesztterv

**Önteszt (`--test`, ablak nélkül):**
1. Címkék → iratok: a csoportosítás a rácssorrendet követi, a címke nélküli oldal kimarad.
2. PDF-oldal kiírása veszteségmentes: a kép-xref bájtra azonos, a forgatás `/Rotate`.
3. Vegyes irat (PDF-oldal + kép) helyes oldalszámmal.
4. Előellenőrzés: ütközés, útvonalhossz, 5 MB-jelzés.

**GUI-teszt (`test/gui.py`):**
1. 6 oldalas, oldalanként „oldal N” szövegű PDF megnyitása → 6 bélyegkép.
2. Kijelölés + `1`, majd `2 2` billentyűvel továbblépve → a kimeneti lista 2 iratot mutat.
3. Vonszolás után az iraton belüli sorrend is változik (`get_text`-tel ellenőrizve).
4. Iktatás ütközéssel → `(2)` név; a dolgozó mappájában a helyes oldalszám és sorrend; naplósorok.
5. Kötegvisszavonás → a fájlok eltűnnek, a felülírt visszaáll, az oldalak visszakerülnek a rácsba.
6. 5 MB fölötti irat → tömörítve, a korlát alatt.
7. Képek → PDF (F5 után): ugyanez a folyamat képekkel.

---

## 10. Megvalósítási fázisok

| Fázis | Tartalom | Becslés |
|-------|----------|---------|
| **F0** | Közös iktatómag kiemelése az `IktatoTab`-ból (6. fejezet), viselkedésváltozás nélkül | ~±40 sor |
| **F1** | `PageItem` + közös rács/nagyító ősosztály; a Képek → PDF ráköltözik, a viselkedése nem változik | ~±80 sor |
| **F2** | Új Szétvágás fül a rácson: PDF-ek betöltése, oldal-bélyegképek, forgatás, törlés, sorrend | ~120 sor |
| **F3** | Címkézés: dolgozó, típuspaletta, számbillentyűk (a nagyítóban is), színes sávok, kimeneti lista | ~220 sor |
| **F4** | Kötegelt iktatás: előellenőrzés, összegzés, kiírás, tömörítés, napló, kötegvisszavonás | ~180 sor |
| **F5** | Visszavezetés a Képek → PDF-be (vagy összevonás egy fülbe) | ~−90 / +40 sor |
| **F6** | *(opcionális)* Iktató: többoldalas PDF-nél „Szétosztás…” gomb, ami az új fülön nyitja meg | ~15 sor |

Nettó ~+550 sor. Minden fázis után zöld `test/run-all.py`; az F1 és az F5 előtt és után ugyanazok a Képek → PDF-tesztek futnak.

### 10.1 Szándékos egyszerűsítések (később bővíthető)

- Egy oldalnak egy címkéje van. Ha ugyanaz az oldal két iratba kell, az „oldal duplikálása” később hozzáadható (→ 9. kérdés).
- Ugyanahhoz a *(dolgozó, típus)* párhoz egy irat tartozik. A szándékos második példány (`(2)`) ma csak ütközésből keletkezik.
- A munka nem mentődik: ha bezárod a programot, a címkék elvesznek (a forrás megmarad).
- Üres oldal automatikus felismerése nincs benne, mert a szkenner üresoldal-kihagyással dolgozik (→ 14.2). Ha mégis rendszeresen átcsúszik üres oldal: ~15 sor a bélyegképből, a küszöböt valódi mintán kell kalibrálni.

---

## 11. Mellékhatás, nem része a tervnek

A közös rács több PDF-et is fogad, ezért az **Összefűzés** fül funkciója (több PDF → egy irat, egy címkével) is lefedhető vele. Az Összefűzés kivezetése akkor lehet napirenden, ha az új fül bevált.

---

## 12. Nyitott kérdések

### A) A munkafolyamatról

1. **Egy köteg jellemzően egy dolgozó iratait tartalmazza, vagy vegyesen többét?** A modell mindkettőt kezeli, de ettől függ, hogy a Dolgozó mező egyszeri beállítás legyen-e, vagy a paletta mellett, szem előtt.
2. **A típuspaletta forrása:** az Iktató listája ma a 6 DocGen-irat. Bekerüljenek alapból az Áttekintő többi típusai is (Útlevél, Szálláshely-igazolás, Végzettséget igazoló okirat, NAV jövedelemigazolás, Munkáltatói jövedelemigazolás)? **Javaslat: igen**, mert a szkennelt kötegekben ezek is előfordulnak, és a „Típusok…” szerkesztővel utána is alakítható.
3. **Egy fül vagy kettő?** Külön Szétvágás és Képek → PDF, közös alappal, vagy egyetlen „Összeállító” fül vegyes forrással? **Javaslat: egy fül.** Kevesebb kód, és a vegyes irat (szkennelt köteg + fotó) is megoldódik. Ráér az F5-ig.
4. Kell még a mai **„minden oldal külön fájlba”** funkció? Ha igen, az új fülön egy gomb lesz (~20 sor); ha nem, megszűnik.
5. Iktatás után a **forrás köteg-PDF**: maradjon a helyén (javaslat), kerüljön egy „feldolgozott” almappába, vagy törlődjön?
6. Képek → PDF: maradjon meg a régi **„→ Iktató várólistára”** út is? **Javaslat: nem.** Két út ugyanarra zavaró, és az Iktató az egyedi fájlokra továbbra is ott van.

### B) Méretezés és kényelem

7. **Hány oldalas** egy köteg jellemzően (10? 100?) — ettől függ, kell-e oldalankénti gyorsítótár. A bélyegkép ~4 ms/oldal (lemérve), így 100 oldal is bőven belefér.
8. Van a szkennelésben **elválasztólap vagy üres hátoldal** (duplex)? Ha igen, az üres oldalak automatikusan „kimarad” jelölést kaphatnak (egyszerű pixelszórás-vizsgálat, ~15 sor).
9. Előfordul, hogy **ugyanaz az oldal két iratba** kell?
10. **Bélyegméret:** elég a 160 px, ha a nagyítóban is lehet címkézni, vagy legyen nagyobb (pl. 220 px, kevesebb fér ki)?

---

## 13. Mire várok választ, mielőtt kódolok

Minden kérdés eldőlt (14. fejezet), nincs függő tétel.

---

## 14. Döntések (2026-09-28)

### 14.1 A felhasználó döntései

| Kérdés | Döntés |
|--------|--------|
| 1. Egy vagy több dolgozó egy kötegben | **egy köteg = egy dolgozó** — szándékosan így szkennel |
| 2. Típuspaletta | az Iktató listája **+ az Áttekintő nem DocGen-típusai** (Útlevél, Szálláshely-igazolás, Végzettséget igazoló okirat, NAV jövedelemigazolás, Munkáltatói jövedelemigazolás) |
| 3. Egy fül vagy kettő | **egy fül**, vegyes forrással (PDF + kép) |
| 4. „Minden oldal külön fájlba” | megszűnik |
| 5. A forrás köteg-PDF iktatás után | marad a helyén |
| 6. Régi „→ Iktató várólistára” út | megszűnik |
| 7. Oldalszám kötegenként | 20–60 |
| 8. Üres oldalak | ~~automatikus jelölés~~ → **kimarad a tervből**: a szkenner rendszerint üresoldal-kihagyással dolgozik (utólagos pontosítás, 2026-09-28) |
| 9. Ugyanaz az oldal két iratba | nem fordul elő |
| 10. Bélyegméret | 160 px marad |

### 14.2 Ami ebből következik

**Egy dolgozó kötegenként → a címke csak a doktípus.**
- A dolgozó a fül egyetlen mezője, és a köteg minden iratára vonatkozik. Az `OutDoc.who` megszűnik, a címke kulcsa a doktípus. Ha dolgozót váltasz, az összes kimeneti név élőben átíródik.
- A kimeneti lista nem csoportosít dolgozónként.
- Címkézni dolgozó nélkül is lehet (a sorrend szabad: előbb címkézel, utána választasz). **Az Iktatás** nem indul dolgozó nélkül: a mező kivillan. Ez felülírja a 8. fejezet „Címkézés dolgozó nélkül” sorát.

**Típuspaletta.**
- Futásidőben áll össze, nincs külön tárolva: az Iktató listája, plusz az Áttekintő azon `generated=False` szabályai, amelyekre még egyik Iktató-típus sem illeszkedik (`match_rule`). Így a fájlnevet az Áttekintő mindig felismeri (a „minden szabálynév önmagára illeszkedik” önteszt ezt már most garantálja).
- **Sorrend: az Áttekintő oszlopsorrendje**, a kötelezők elöl. `1` Forma · `2` Előz · `3` Elism · `4` Hozzá · `5` Megh · `6` Útl · `7` SzVált · `8` SzIg · `9` Végz; a NAV és a Munk csak kattintással érhető el. Az egyik szabályra sem illeszkedő saját típusok a végére kerülnek.
- A „Típusok…” az Iktató listáját szerkeszti, az Áttekintőből jövő típusokat az Áttekintő Beállításai. Az Iktató saját legördülője nem változik.

**Egy fül: „Összeállító”.**
- A Képek → PDF helyére kerül, és kiváltja a Szétvágás fület is. A `SplitTab` törlődik (4. döntés). Az `ImagesToPdfTab` **átnevezve és bővítve** lesz az Összeállító.
- Mivel a rácsot csak egy fül használja, **nem kell közös ősosztály** (6. fejezet utolsó sora): elég, ha az `ImgItem` `PageItem` lesz (`page` és `doc` mezővel), és a nagyító oldalt nyit, nem csak képet.
- Hozzáadás: „PDF / kép hozzáadása…” és „Mappa hozzáadása…” (képek és PDF-ek). Egy PDF az oldalaival, sorrendben kerül a rács végére.
- A minőség-előbeállítás, a szürkeárnyalat és az A4-illesztés **csak a képoldalakra** hat (a sor felirata „Képoldalak:”); a PDF-oldalak veszteségmentesen mennek át.
- Az Összefűzés fül marad (11. fejezet).

**Üres oldalak: nincs automatikus felismerés.** Az első válasz még automatikus jelölést kért, de a szkenner rendszerint maga kihagyja az üres oldalakat. Ha mégis átcsúszik egy, címke nélkül marad, és így kimarad az iktatásból. Így nem kell kalibrálni, és a címkézés-továbblépés is egyszerű marad: mindig a következő oldalra lép. Utólagos bővítés: 10.1.

**20–60 oldal:** gyorsítótár nem kell, a bélyegképek a mai `after()`-láncban készülnek (~4 ms/oldal, 60 oldal ~0,25 s). Ma elemenként nyílik meg a forrás. Ha ez egy 60 oldalas PDF-nél lassúnak mérődik, a megnyitott dokumentumokat útvonalanként meg kell tartani.

**Az 5., 6., 9. és 10. döntés** nem módosít a terven: az 5.2, a 7. és a 10.1 fejezet így marad.

### 14.3 Módosult fázisok

| Fázis | Tartalom | Becslés |
|-------|----------|---------|
| **F0** | Közös iktatómag kiemelése az `IktatoTab`-ból, viselkedésváltozás nélkül | ~±40 sor |
| **F1** | `ImgItem` → `PageItem` (`page`, `doc`), a nagyító oldalt nyit; a Képek → PDF viselkedése nem változik | ~+20 sor |
| **F2** | PDF-ek fogadása a rácsban, veszteségmentes oldalkiírás | ~100 sor |
| **F3** | Címkézés: dolgozó, típuspaletta (Áttekintő-sorrend), számbillentyűk (a nagyítóban is), sávok, kimeneti lista | ~200 sor |
| **F4** | Kötegelt iktatás: előellenőrzés, összegzés, kiírás, tömörítés, napló, kötegvisszavonás | ~180 sor |
| **F5** | Átnevezés „Összeállító”-ra; a régi kimeneti gombok, a mentés-párbeszéd, az Iktatóba küldés és a `SplitTab` törlése; README | ~−230 sor |
| **F6** | *(opcionális)* Iktató: többoldalas PDF-nél „Szétosztás…” gomb, ami az Összeállítóban nyitja meg, a dolgozóval együtt | ~15 sor |

Nettó ~+280 sor, kevesebb az eredeti ~550-nél, mert a régi Szétvágás és a régi kimeneti út törlődik.

### 14.4 Megvalósítás

**F0 — kész (2026-09-28).** Modulszintű iktatómag a `check_path_len` mellett: `backup_existing(dst)`, `undo_copy(dst, backup)`, `log_row(parent, src, folder, name, doc_type, result)`. Az Iktató ezeket hívja; a `_log` vékony burok maradt, mert a doktípus alapértéke (a legördülő aktuális értéke) Iktató-specifikus. Eltérés a 6. fejezettől: az `undo_copy` nem kapja meg a forrást. A „helyben felülírt fájl nem vonható vissza” szabály csak az Iktatóban fordulhat elő (ott lehet a forrás maga a cél), ezért ott maradt. Önteszt: +5 (IKTATÓMAG), a GUI-teszt Iktató-része változatlanul zöld.

**F1 — kész (2026-09-28).** Az `ImgItem` neve `PageItem` lett, `page` mezővel (képnél 0); a bélyegkép és a nagyító a `page`-edik oldalt rendereli. A Képek → PDF viselkedése nem változott. Eltérés a 14.3-tól: a `doc` (címke) mező az F3-ban jön, amikor használni is kezdjük. GUI-teszt: +2 („OLDAL MINT ELEM”: egy kétoldalas PDF 2. oldala a bélyegképen és a nagyítóban is).

**Az F2-re átvitt megfigyelés:** a nagyító felső nagyítási határa a lapon lévő első kép natív felbontása. Képet nem tartalmazó (vektoros, pl. DocGen-ből nyomtatott) PDF-oldalnál ez most az illesztésre korlátozna, ott más felső határ kell (pl. `ZOOM_MAX`).

**F2–F6 — kész (2026-09-28).** Az Összeállító a Képek → PDF helyén; a Szétvágás fül törölve. Önteszt: +13 (ÖSSZEÁLLÍTÓ), GUI: a régi Képek → PDF-kimenet tesztjei helyett a teljes kötegfolyamat (54 teszt).

- **F2 — források:** hozzáadáskor minden fájl megnyílik (kép ~5 ms), és oldalanként kerül a rácsba. Így a **többoldalas TIFF is oldalanként** jön, megszűnt a korábbi „csak az 1. oldal” egyszerűsítés (kepek-pdf-terv.md, 11.4). A bélyegkép oldalanként újranyitja a forrást (60 oldalas kötegen mérve 13 ms/oldal, nyitva tartva 7 ms): a különbség az `after()`-láncban nem érezhető, gyorsítótár nincs. A PDF-oldal `insert_pdf`-fel, veszteségmentesen megy át, a forgatás `/Rotate` (az irány az önteszt szerint egyezik a bélyegképével). A nagyító PDF-oldalon `ZOOM_MAX`-ig nagyít.
- **F3 — címkézés:** a paletta színes lista (nem gombsor): kicsi, és a színei megegyeznek a csempék sávjaival. A Kimenet oszlopos lista behúzás nélkül (a fanézet levágta a neveket). **Eltérés az 5.1-től:** a kimeneti lista nem mutat élő méretet. Az 5 MB fölötti iratot az iktatás úgyis automatikusan tömöríti, a méret a naplóban látszik, a képoldalak élő újrakódolása pedig lassú lenne (~0,5 s/kép).
- **F4 — iktatás:** előellenőrzés (név, útvonalhossz, ütközés), egyetlen összegző párbeszéd (ütközésnél kötegenként egy döntés), iratonként `after()`-lánc, 5 MB fölött `shrink_later`, `write_pdf_verified`, felülírásnál `backup_existing`, iratonként `log_row` (a forrás oldalakkal: `koteg.pdf [2,1]`). Hibás irat után a többi megy tovább. A sikeresen iktatott oldalak kikerülnek a rácsból; a Visszavonás az egész köteget `undo_copy`-val vonja vissza, és az oldalakat az eredeti helyükre teszi.
- **F5 — takarítás:** `ImagesToPdfTab` → `ComposerTab`, `ImageViewer` → `PageViewer`; a régi kimeneti gombok, a mentés-párbeszéd, az Iktatóba küldés, a `SplitTab` és a csak általa használt `FileList`-részek (`multi`, `all_paths`, `select_all`, `extra`) törölve. A dolgozói mappák listája közös (`worker_dirs`), az Iktató is ezt hívja. A minőség-előbeállítás rádiógombok helyett legördülő lett, mert 960 px szélességnél a sor levágódott.
- **F6 — Iktató:** többoldalas PDF-nél az előnézet alatt „✂ Szétosztás…” gomb: a köteg az Összeállítóba kerül (a várólistáról ki), a dolgozó az Iktató szűrőjéből jön, ha az Összeállítóban még nincs megadva.
- **Egy teszt által talált hiba:** a `_name` metódusnév ütközött a tkinter widgetek belső `_name` attribútumával; `_doc_name` lett.
