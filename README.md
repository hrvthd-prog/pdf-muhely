# PDF Műhely

Offline asztali eszköztár idegenrendészeti iratok előkészítéséhez: PDF-ek
összefűzése, arckép elhelyezése, szkennelt kötegek és képek szétosztása iratokra,
iktatás a dolgozók mappáiba, és áttekintés arról, ki adható be. Hálózatot nem
használ.
A dokumentumokat a [DocGen](https://github.com/hrvthd-prog/DocGen) generálja,
ez az eszköz a nyomtatás–aláírás–szkennelés utáni lépéseket segíti.

A felső sáv a munka sorrendje; az eseti műveletek az **Eszközök** fül
alfülein vannak (döntés: `kepek-pdf-terv.md` 13.2).

| Fül | Mire való |
|---|---|
| **1 · Összeállító** | szkennelt kötegből és képekből iratok: az oldalak számbillentyűvel doktípust kapnak, egyetlen Iktatással mind a dolgozó mappájába kerül |
| **2 · Iktató** | a PDF-et ráejted a dolgozó nevére: szabványos nevet kap, a mappájába kerül, naplózva. **Oldalanként** módban egy többoldalas köteget oldalanként osztasz szét több dolgozó között |
| **3 · Áttekintő** | mátrix: dolgozónként melyik irat van kész, ki adható be, mi hiányzik |
| Eszközök → Arckép elhelyezés | fénykép **körülvágása** és ráhelyezése egy PDF-nyomtatványra, majd iktatás a feltölthetőbe |
| Eszközök → Szerkesztés | kész PDF **szerkesztése**: szöveg átírása, **húzható, élőben formázható új szöveg**, **többsoros szövegdoboz**, X, **bekezdés-formázás**, **űrlapmezők** (DocGen-sablon), kitakarás — és az egész iratra: **keresés és csere** előnézettel, **személyes adatok kitakarása** (TAJ, adóazonosító, útlevél…), **fejléc, lábléc, oldalszám, bélyeg, vízjel**, **űrlap kitöltése és beégetése**, **szövegfelismerés** (OCR) a szkennelt iratokra |
| Eszközök → Összefűzés, Raszterizálás | eseti PDF-műveletek |
| Eszközök → MD → DOCX | **Markdown-fájlból szerkeszthető Word-irat** (.md → .docx) |
| Eszközök → DOCX-tisztítás | Word-dokumentumokból a **szerző, az utolsó módosító és minden eredet-nyom törlése** (lásd lent) |

A program **megjegyzi** az utoljára használt munkamappát, az alapértelmezett
dolgozót, a mellékletek mappáját és az Iktatóban választott doktípust
(`emlekezet.json`).

## Alapértelmezett dolgozó

A munkamappa sora alatt, a fülsor jobb végén: **ALAPÉRTELMEZETT DOLGOZÓ**. Ha itt
kiválasztod (elég a név egy részlete), nem kell fülenként újra:

- az **Összeállító** és az **Arckép** dolgozóválasztója ezt veszi át;
- az **Arckép**, a **Szerkesztés**, az **Összefűzés** és a **Raszterizálás** fájllistája a
  dolgozó mappáját mutatja, mindkét alkönyvtárával (`01_Elokeszitett\…`,
  `02_Feltoltheto\…`);
- az **Iktató nem** — annak épp az a dolga, hogy a köteget több dolgozó között ossza szét.

Váltáskor minden fül követi; a fülön kézzel választott dolgozót a Frissítés nem írja
felül. A „— nincs —” elem törli: a listák újra a munkamappát mutatják. Döntés:
`kepek-pdf-terv.md` 19.3.

## Arckép: körülvágás, fényerő

Az arckép szegélyét nem kell Paintben leszedni: **Körülvágás, fényerő…** → húzz
téglalapot a megtartandó rész köré → **Körülvág**. Ugyanitt két csúszka a
**fényerőre** és a **kontrasztra**, élő előnézettel (vágás nélkül is
alkalmazható). A **Teljes kép, alaphelyzet** mindkettőt visszavonja.

A kép fájlja soha nem változik. A vágás veszteségmentes (a lap cropboxa);
a fényerő/kontraszt viszont újrakódolja a képet (JPEG Q92, a beágyazott kép
valódi felbontásán), ezért csak akkor fut le, ha tényleg állítottál rajta.

## DOCX-tisztítás: metaadat és eredet-nyom törlése

*Eszközök → DOCX-tisztítás*: jelöld ki a `.docx`-eket → **Metaadatok törlése…**. A
fájl **helyben, az eredeti felülírásával** tisztul (előbb rákérdez; a megnyitott Word-fájl
nem írható — azt zárd be). Törli:

- a szerzőt, az utolsó módosítót, a címet, a megjegyzést, a létrehozó programot
  (`python-docx`, „Microsoft Word” stb.), a cég- és sablonadatot, a bélyegképet (`docProps\`);
- a követett módosítások és megjegyzések szerzőjét, kezdőbetűit, dátumát (a szöveg marad);
- a sablon útvonalát (abban a gép felhasználóneve szokott lenni);
- a beágyazott JPEG/PNG képek EXIF/XMP/IPTC/szöveges adatát (GPS, fényképező, szerző) —
  a képpontok azonosak, a fotó tájolása megmarad;
- a ZIP-csomag és az XML-fejlécek Python-ra valló nyomát (időbélyeg, jogok, idézőjelek).

A szöveg, a formázás, a stílusok, a képek képpontjai és minden más rész **bájtra
azonos**. Amit tartalomnak is vehetünk (`customXml\`, beágyazott fájl, helyi útvonalra
mutató hivatkozás), azt nem törli, hanem figyelmeztet rá.

Szkriptből (pl. a generáló Python-program végén) is hívható; kiírás nélkül helyben tisztít:

```bash
python pdf-muhely.py --docx-tisztit be.docx [ki.docx]
```

Fájlrendszer-szintű adatot (az NTFS „tulajdonos”-át, a fájl módosítási idejét) nem érint.
Ha a megtisztított fájlt utána Wordben megnyitod és mented, a Word a saját felhasználónevedet
újra beírja — ezt a Word *Fájl → Beállítások → Adatkezelési központ → Személyes adatok
eltávolítása mentéskor* jelölőnégyzete tiltja le. Döntések: `szerkeszto-terv.md` 24.

## Szerkesztés: kész PDF javítása, DocGen-sablon készítése

*Eszközök → Szerkesztés*, vagy az Áttekintőben jobb klikk egy cellán →
**✎ Szerkesztés: <fájl>**. Megnyitott iratnál a fájllista egy sorra csukódik (a
fájl nevével, mentetlen változásnál ● jellel); a **Másik irat…** kinyitja.

Tíz eszköz, csempéken, két sorban. Az ikon fölött megállva a súgóbuborék elmondja,
mire való; az eszköz fő gombja (Csere, Kitakarás, Beégetés…) mindig a panel alján
van, nem kell érte görgetni. Az üzenetek az ablak alsó állapotsorában jelennek meg.

**Fölső sor — a lapon dolgozók** (kattintás, húzás a lapon):

- **Szöveg és X** — kattints egy szövegre: a beírómezőben átírhatod, a régi szöveg
  *ténylegesen* törlődik (nem csak letakarva), az új ugyanoda, ugyanakkora betűvel
  kerül. Jelölőnégyzetbe: X be/ki. Üres helyre kattintva **új szöveg** (a cellához
  igazítva), ami a mentésig **élő objektum**:
  - egérrel **húzható**, a **nyilakkal** 1 pt-onként, **Shift+nyíllal** 10 pt-onként
    mozgatható; **dupla kattintással** átírható, **Delete**-tel törölhető;
  - a panelen a **betű, méret, félkövér, dőlt, aláhúzás, szín** — és maga a szöveg is —
    **azonnal** látszik rajta, Alkalmaz nélkül (kijelölés nélkül a panel a következő új
    szövegre szól);
  - a lapra a **Mentés** írja, pontosan úgy, ahogy a vásznon látszik; ugyanabban a
    futásban a mentés után is mozgatható marad.
- **Szövegdoboz** — húzz egy téglalapot a lapon: abba kerül a **többsoros** szöveg. A
  panel beírójában gépelsz; a kijelölt szavak **Ctrl+B / Ctrl+I / Ctrl+U**-val (vagy a
  gombokkal) félkövérek, dőltek, aláhúzottak lesznek — szavanként is. Igazítás (balra /
  középre / jobbra / **sorkizárt**), sortáv, betű, méret, szín; minden azonnal látszik.
  Ha a szöveg nem fér a dobozba, a betű magától kisebb lesz (legfeljebb a felére), és a
  panel szól. A doboz húzható, a sarkainál és oldalainál átméretezhető, nyilakkal
  mozgatható; a mentésig élő, mint az új szöveg. Jó záradékra, „Kelt:” blokkra,
  megjegyzésre.
- **Bekezdés formázása** — vektoros (nem szkennelt) PDF-en. Kattints egy bekezdésre:
  szaggatott keret jelzi, mire fog hatni, a panel pedig a bekezdés mai értékeivel
  töltődik ki. Beállítható az **igazítás** (balra / középre / jobbra / **sorkizárt**),
  a **sortávolság** (kézzel vagy 1,15× / 1,5× / 2× gombbal), a **térköz előtte**, a
  **betű** (család, méret, félkövér, dőlt, aláhúzott, szín), a **behúzás**
  (bal / jobb / első sor), és a *Bekezdés szövege…* gombbal az egész bekezdés
  szövege átírható. Minden beállítás **azonnal** a lapra kerül (Alkalmaz gomb nincs);
  az **Eredeti bekezdés** gomb visszaállítja a kijelöléskori állapotot.

  Alapból a **sortörések nem változnak** — a sorkizárás csak a szóközöket nyújtja, így
  a lap tördelése biztosan nem csúszik el, és a bekezdésen belüli félkövér/dőlt szavak
  is megmaradnak. Az *Újratördelés* jelölővel a program újratördeli a bekezdést
  (szebb, egyenletesebb szóközök, de a sortörések és a kiemelések változhatnak —
  vegyes formázású bekezdésnél ezért rákérdez).

  Ha a bekezdés betűje nincs meg a gépen, vagy a választott betűből hiányzik egy
  karakter (az Arial Bold például nem ismeri a magyar iratokban használt nem-törő
  kötőjelet), a program **nem formáz át**, hanem megmondja, mi a baj — a csendes
  betűcsere láthatóan elrontaná a lapot.
- **Űrlapmező** — ezzel készül a **DocGen PDF-sablonja**: kattints a cellába, és add
  meg a mező nevét, ami a DocGen-jelölő (pl. `surname`, `Neme=male`,
  `{postal_code} {locality}`). Több kis cellán át húzva betűnkénti mezők lesznek
  (`date_of_birth_year#1…#4`). Mezőre kattintva átnevezhető, Delete-tel törölhető.
  Ha a nyomtatvány nagybetűs kitöltést kér, kapcsold be „A DocGen nagybetűvel töltse
  ki” jelölőt (az egész sablonra szól).
  A jelölők leírása: a DocGen README „Kitölthető PDF-sablon” szakasza.
- **Kitakarás** — húzd körbe a területet: a tartalma végleg törlődik, a helye fehér.

**Alsó sor — az egész iratra hatók.** Közös bennük: semmi nem kerül a lapra
jóváhagyás nélkül. A panel listában mutatja, mi fog történni (soronként
jelölőnégyzettel), a lapon ugyanez kiemelve látszik, a listában kattintva a lap
odaugrik; a művelet a panel alján lévő gombbal indul, és Ctrl+Z visszavonja.

- **Keresés és csere** (Ctrl+F) — gépelés közben keres; kis-/nagybetű, egész szó,
  minta (reguláris kifejezés). Enter / F3 a következő, Shift+F3 az előző találat. A
  listában minden találat mellett ott van, **mi lesz belőle**: „rendben”, „jobbra
  csúszik” (a sor többi része a helyére csúszik, mint egy szövegszerkesztőben), „betű
  85%” (kicsit kisebb betűvel fér csak el), „nem fér el” (ez nincs kijelölve — ott a
  Bekezdés eszköz *Bekezdés szövege…* gombja segít). A régi szöveg ténylegesen
  törlődik; utána a program újra keres, és kiírja, maradt-e még.
- **Személyes adatok** — megkeresi a **TAJ-számot, adóazonosító jelet, útlevélszámot,
  személyi igazolvány számát, bankszámlaszámot / IBAN-t, telefonszámot, e-mailt**
  (és kérésre a dátumokat, meg egy saját szöveget, pl. nevet). Ahol van
  ellenőrzőszám (TAJ, adóazonosító, számlaszám, IBAN), csak a hibátlan számot jelöli —
  az iktatószámok nem kerülnek a listába. A **Kitakarás** végleg törli a szöveget és a
  kép képpontjait (fekete vagy fehér sáv), és a metaadatot is (a Műhely bélyege
  marad); utána ellenőrzi, hogy egyik sem maradt.
- **Fejléc** — fejléc, lábléc, **oldalszám** („1/3”, „1. oldal” …), keretes **bélyeg**
  („Iktatva: 2026. 10. 14.”, piros/kék/fekete, a lapon húzással áthelyezhető) és átlós
  **vízjel** („MÁSOLAT”). Egy kattintásos gyors beállítás: *Oldalszám*, *Másolat*,
  *Iktatva*. A szövegben változók: `{oldal}`, `{összes}`, `{dátum}`, `{dolgozó}`,
  `{doktípus}`, `{fájlnév}`. Élőben látszik minden lapon, a **Mentés** égeti be; ha
  valami a lap szövegére esne, a panel szól.
- **Űrlap** — a kitölthető mezők listája a panelen (olvasási sorrendben, szűrővel);
  a lapon a mezőre kattintva a beírójába ugrik. **Beégetés** feltöltés előtt: a
  mezők a lap tartalmává válnak — a portál a kitölthető mezőt gyakran üresnek látja,
  az ékezetes értéket (ő, ű) pedig sok olvasó nem is mutatja. Kitöltés közben is a
  beégetett kép látszik: amit látsz, az kerül a fájlba.
- **Felismerés** (OCR) — a szkennelt lapok szövegét ismeri fel, és láthatatlan
  rétegként a lapra teszi: utána a lap **kereshető, kijelölhető és kitakarható** (a
  Személyes adatok így a szkennelt iraton is működik), a kép nem változik. Külön
  folyamatban fut, haladásjelzővel, megszakítható. **Telepíteni semmit nem kell:** a
  program beépített motort használ, a magyar nyelvi fájl a `tessdata` mappában jön
  vele (`tessdata/FORRAS.md`).

**Lapozás és nagyítás:** a vászon fölött lapozógombok (első / előző / következő /
utolsó, mellette „/ N”), PageUp/PageDown; nagyítva **görgetősávok**, Shift+görgővel
vízszintes görgetés, középső gombbal húzva szabad mozgatás, Ctrl+görgővel nagyítás a
kurzor körül.

Minden lépés visszavonható (Ctrl+Z) a mentésig. A **Mentés** helyben ír; az előző
példány a dolgozó `01_Elokeszitett` mappájába kerül „(előző példány …)” jelölővel, a
bélyeg megmarad, és az Áttekintőből nyitott fájlnál naplósor is készül. Forgatott
lapot a szerkesztő nem kezel.
Gyorsbillentyűk: Ctrl+F keresés, F3 / Shift+F3 találatok, Ctrl+S mentés, Ctrl+Z
visszavonás.
Döntések és buktatók: `szerkeszto-terv.md`, 16. fejezet; a bekezdés-formázásé a 19.,
az élő szövegé és a valós idejű formázásé a 21., a pdfrw és más projektek áttekintése
a 22., a szövegdoboz, a keresés-csere, a személyes adat, a fejléc-bélyeg, az űrlap és
a szövegfelismerés a 23.

## MD → DOCX: Markdownból Word-irat

Az **Eszközök → MD → DOCX** alfülön egy `.md` fájlból szerkeszthető `.docx` lesz
(pl. egy AI-val írt vagy tervdokumentum-szöveg kollégának, beadásra). A lista a
munkamappát (vagy az alapértelmezett dolgozó mappáját) mutatja; másik mappából a
**Tallózás…** hozza. Az **Átalakítás és mentés…** a forrás mellé, azonos néven ajánlja
fel a mentést; a kész iratot megnyitja (kikapcsolható).

Átkerül: címsorok (`#` és aláhúzásos), bekezdések, **félkövér**, *dőlt*, ~~áthúzott~~,
`kód` és kódblokk, felsorolás és számozott lista (beágyazva is, a számozás listánként
újraindul), feladatlista (☐ / ☒), táblázat (oszlopigazítással, kiemelt fejléccel),
idézet, vízszintes vonal, kattintható link. A Word **saját stílusait** kapja
(Címsor 1…, Felsorolás…, Idézet), így a kész irat a Wordben tovább formázható; A4,
2,5 cm-es margó, Calibri 11, magyar helyesírás-ellenőrzés. Kép **nem** kerül át: a
helyén `[kép: …]` jelölő áll. Az YAML-előfej és a `<!-- megjegyzés -->` kimarad.

Kell hozzá a **python-docx** (`pip install python-docx`); nélküle a program elindul,
csak ez az alfül szól. Döntések: `szerkeszto-terv.md` 24.

## A felület

Világos, levegős felület: fejléc (név, verzió, munkamappa) akcentuscsíkkal,
alatta a fülsáv, középen a munkaterület, alul állapotsor. A gombok, mezők, fülek, jelölők és
csúszkák grafikája **kódból készül** futásidőben (élsimított, lekerekített,
lágy árnyékkal), az ikonokkal együtt — nincs hozzá képfájl és nincs új
függőség. Részletek és indoklás: `kepek-pdf-terv.md` 13.7.

Az ablak mérete a képernyőhöz igazodik. **Nagyított kijelzőn** (Windows 125–200%)
a feliratok arányos ráhagyást kapnak, hogy a végük ne vágódjon le (`kepek-pdf-terv.md`
19.2). A megjelenés ellenőrzése fejlesztéskor:

```bash
python tools/ui-kep.py 0 kep.png      # 0–2: fő fülek · 3: Eszközök · 4: Ellenőrzés
                                      # 5–6: Szerkesztés (mező, bekezdés)
python tools/ui-kep.py 7 k.png search # 7: Szerkesztés egy eszközzel (box, search,
                                      #    pii, decor, form, ocr)
```

## A dolgozói mappa szerkezete

Minden dolgozónak **két alkönyvtára** van — így ránézésre látszik, mi van kész:

```
<munkamappa>\
  <Dolgozó Név>\
    01_Elokeszitett\   ← a DocGen kimenete: nyomtatásra / aláírásra vár.
                         Ide tartozik az arckép (jpg) és az aláírt
                         formanyomtatvány is, amin még nincs fotó.
    02_Feltoltheto\    ← szkennelt, aláírt, 5 MB alatti végleges PDF:
                         ez megy a portálra.
    .eredeti\          ← felülírt iratok előző példánya (közös)
  iktato-naplo.csv
```

Az **Iktató** és az **Összeállító** alapból a `02_Feltoltheto`-be ír. Egyetlen
kivétel a **formanyomtatvány**, amire arcképet is kell helyezni: ott van egy
jelölő („Az arckép már rajta van"). Ha nincs bepipálva, az irat a
`01_Elokeszitett`-be kerül — aláírva sem feltölthető, míg nincs rajta a fotó.
Az **Arckép elhelyezés** fül eredménye mindig a `02_Feltoltheto`-be megy: a fotó
épp akkor kerül rá. Ezzel zárul a kör: `01` → fotó → `02`.

A mappák a **Rendezés…** gombbal hozhatók létre minden dolgozónál egyszerre
(Áttekintő), és iktatáskor magukból is létrejönnek.

### Rendezés: a régi, lapos szerkezet besorolása

Ugyanaz a **Rendezés…** párbeszéd sorolja be a gyökérben hagyott fájlokat.
Előnézetet ad, és csak jóváhagyás után mozgat:

| forrás | cél |
|---|---|
| PDF DocGen-bélyeggel | `01_Elokeszitett` (generált, még nem aláírt) |
| PDF `aláírt` utótaggal, bélyeg nélkül | `02_Feltoltheto` |
| PDF bélyeg és utótag nélkül | `01_Elokeszitett` — **tippként jelölve** |
| kép, `.docx` | `01_Elokeszitett` |
| amit egyik szabály sem ismer fel | marad a gyökérben, felsorolva |

A bizonytalan eset szándékosan `01` felé téved: ha `02`-be tennénk, a mátrix
aláírás nélküli iratot mondana beadhatónak. **A mozgatás nem visszavonható** —
ezért mutat az előnézet minden sort.

### A munkamappa-kapu

Mivel a mozgatás nem visszavonható, a Rendezés **csak bizonyítottan dolgozói
mappában** dolgozik. Egy almappa akkor számít annak, ha

- már van benne `01_Elokeszitett` vagy `02_Feltoltheto`, **vagy**
- van benne legalább egy felismert irat, **vagy**
- teljesen üres (frissen létrehozott dolgozói mappa — nincs is mit mozgatni).

Minden más almappát **kihagy**, és a párbeszéd tetején felsorolja. Ha egyik
almappa sem felel meg, a Rendezés nem is engedi a továbblépést, csak figyelmeztet
és megmutatja a kiválasztott útvonalat.

Erre azért van szükség, mert a képeket a Rendezés szabály-illesztés **nélkül**
sorolja be (az arckép jellemzően nem illeszkedik irattípusra). Kapu nélkül egy
tévesen kiválasztott munkamappában — mondjuk a Letöltésekben vagy egy képmappában
— az összes kép elmozdulna.

## Telepítés és indítás

Python 3.10+, PyMuPDF és python-docx kell (a tkinter a Python része):

```bash
pip install pymupdf python-docx
```

(A python-docx csak az MD → DOCX alfülhöz kell.)

```bash
python pdf-muhely.py
```

A szövegfelismeréshez külön program nem kell: a nyelvi adat a `tessdata` mappában
van, a program mellett (a frissítő ezt is másolja).

A címsorban látszik a verzió (pl. `v1.4 (2026-09-25)`). Ha a PyMuPDF túl régi a
tömörítéshez vagy a JPEG-minőség állításához, az app induláskor szól
(1.26.7-tel tesztelve); a többi funkció ilyenkor is működik.

## Bélyeg: a dolgozó és a típus a PDF-ben

Minden iktatott irat kap egy **bélyeget** a PDF metaadatában (`/Keywords`):

```
pdf-muhely=1;dolgozo=Kiss Anna;tipus=Útlevél;szabaly=utlevel;hely=02_Feltoltheto;datum=2026-10-01
```

Ez **átnevezést és áthelyezést túlél** (a tömörítést is), ezért:

- az **Áttekintő** akkor is a típusához számítja az iratot, ha a nevét átírták
  (`IMG_20260101_0001.pdf`) — a hiánylista jelzi: „átnevezve";
- a **Rendezés** a bélyeg szerint viszi vissza a helyére (tipp helyett
  bizonyíték);
- ha egy iraton **más dolgozó** bélyege van, a hiánylista `IDEGEN` sorral szól.

**A fájlnév marad az elsődleges igazság:** a bélyeget csak ott nézzük meg, ahol
a nevet egyik szabály sem ismeri fel. A sima iktatás másolása a bélyeget
**növekményes** függelékként kapja, tehát a forrás bájtjai a célban is
megvannak; ha a bélyegzés nem sikerül, az irat bélyeg nélkül, de hibátlanul
kerül a helyére. A szkennelt lapon az iktatás **előtt** nincs bélyeg (a
nyomtatás–aláírás–szkennelés kör mindent elveszít), és visszamenőleg sem
keletkezik. Döntés és korlátok: `kepek-pdf-terv.md` 13.5.

## Az 5 MB-os feltöltési korlát

A portálra egy fájl legfeljebb 5 MB lehet. A korlát szándékosan a szigorúbb
értelmezés: **5 000 000 bájt** (`UPLOAD_LIMIT`). Minden fül jelez, ha egy kész
fájl fölötte van; az **Iktató** iktatáskor felajánlja a tömörítést (a forrás
érintetlen marad), az **Összeállító** magától tömörít, az **Áttekintő** `P!`
jellel mutatja, és a csak túlméretes PDF-fel rendelkező iratot nem számítja
beadhatónak. A tömörítés csak a beágyazott képeket kódolja újra, lépcsőnként
(200 → 150 → 120 → 100 DPI), és megáll, amint befért.

## Egy köteg, több dolgozó — oldalankénti szétosztás (Iktató)

Ha egy PDF-ben **több dolgozó ugyanolyan típusú irata** van (például 18 oldal =
18 útlevélmásolat), kapcsold be az Iktató felső sávjában az **Oldalanként
(szétosztás)** jelölőt:

1. a várólistába tedd be a köteget (**Tallózás…** vagy ráejtés),
2. válaszd ki a doktípust (mindenkinél ugyanaz),
3. az oldalt ráejted a dolgozó nevére — **csak az az egy oldal** kerül át,
   önálló egyoldalas PDF-ként, a szokásos névvel és naplóval,
4. a program magától a következő oldalra lép; az utolsó után a köteg kikerül a
   sorból.

A kihagyott oldalhoz az **Oldal ◀ ▶** gombokkal visszaléphetsz, a
**Visszavonás** pedig az oldalt is visszaadja a készletbe. Az oldal tartalma
bitre változatlan (nincs újrarajzolás). Vegyes kötegnél (egy dolgozó több
iratával) továbbra is az **Összeállító** a jó eszköz.

## Az Összeállító röviden

Egy köteg = egy dolgozó iratai (szkenneléskor így kell összerakni).

1. **PDF / kép hozzáadása…** — a köteg oldalai bélyegképként jelennek meg
   (képek és PDF-ek vegyesen is jöhetnek). Az Iktatóból a többoldalas PDF alatti
   **✂ Szétosztás…** gomb ugyanide küldi.
2. **Dolgozó:** elég a név egy részlete (ékezet nélkül is), a mező alatt látszik,
   melyik mappát találta meg.
3. **Címkézés:** jelöld ki az oldalakat (kattintás, Shift/Ctrl+kattintás), és
   nyomj számot: az a doktípus (a jobb oldali lista sorszáma, az Áttekintő
   oszlopsorrendjében). Utána a kijelölés a következő oldalra lép, így a köteg
   billentyűzetről is végigmehető. `0` / Backspace: címke le. A nagyítóban (dupla
   kattintás) ugyanígy működik. Címke nélküli oldal kimarad.
4. **Címke a szövegből (ahol van)** — ha az oldalnak van szövegrétege
   (DocGen-PDF vagy OCR-es szkenner), a doktípus a tartalomból is megállapítható;
   tiszta szkennelt kötegen nem tud dönteni, ott marad a számbillentyű.
5. Egy irat = az azonos címkéjű oldalak, a rács sorrendjében (vonszolással
   átrendezhető). A **Kimenet** listában egy irat kijelölésével az oldalai is
   kijelölődnek, és az utótagja átírható.
6. **Iktatás (N irat)** — egy összegzés után mind a dolgozó mappájába kerül, az
   Iktató szabályai szerint (szabványos név, ütközésnél új név vagy felülírás
   `.eredeti\` mentéssel, napló, 5 MB fölött tömörítés). A **Visszavonás** az egész
   utolsó iktatást visszacsinálja, az oldalak visszakerülnek a rácsba.

A PDF-oldalak veszteségmentesen kerülnek az iratba (a forgatás csak `/Rotate`);
a képoldalakra a „Képoldalak” minőség, a szürkeárnyalat és az A4-illesztés hat.
A forrás köteg-PDF változatlan marad.

## Adatfájlok — mi hol él

| Fájl / mappa | Hol | Verziókezelésben? |
|---|---|---|
| `attekinto-szabalyok.json` — az Áttekintő irattípusai, kulcsszavai | a program mappájában | igen (alapértelmezés) |
| `iktato-doktipusok.json` — az Iktató doktípus-listája | a program mappájában | igen, ha létrejön |
| `verzio.json` — a verziószám | a program mappájában | igen, **gép írja** |
| `emlekezet.json` — utolsó útvonalak, doktípus | a program mappájában | **nem** (gépenként más) |
| `iktato-naplo.csv` — az iktatás naplója | a munkamappában | **nem** |
| `.eredeti\` — felülírt iratok előző példánya | a dolgozó mappájában | **nem** |

A `.gitignore` **engedélyező lista**: csak a név szerint felsorolt fájlok
kerülhetnek a repóba, mert a munkamappa alapból a program mappája, és oda
dolgozói iratok is kerülhetnek. **Új projektfájlt a `.gitignore`-ba is fel kell
venni** — a klón-próba (lásd lent) szól, ha kimaradt.

Felülírásnál (Iktató, Összeállító, Arckép) az előző példány a dolgozó mappájának
**gyökerében** a `.eredeti\` almappába kerül — egy helyen, nem a 01/02 alatt
szétszórva —, és a **Visszavonás** visszahozza. A ponttal kezdődő mappát az
Áttekintő és az Iktató is kihagyja.

## Az Áttekintő cellái

A jel azt mondja meg, **hol van** a fájl — vagyis mi van kész:

| jel | jelentés |
|---|---|
| `F` | van a `02_Feltoltheto`-ban → **kész** |
| `EF` | mindkét mappában van (az előkészített és az aláírt példány is) |
| `E` | csak az előkészítettben → még nem aláírt/szkennelt |
| `~` | se 01-ben, se 02-ben → **besorolatlan, nem beadható** (Rendezés…) |
| `?` | kétértelmű illeszkedés — nézd meg |
| `·` | nincs semmi |

A `!` utótag (pl. `F!`) továbbra is az 5 MB fölötti, nem feltölthető PDF-et
jelenti, az `×2` pedig azt, hogy a feltölthetőben **több** PDF is van ugyanahhoz
a típushoz (melyik a jó?). Az előkészített + aláírt példány együtt **nem**
ütközés, az a normális állapot.

## Ellenőrzés és kötegelt tömörítés (Áttekintő)

Két gomb a mátrix alatt:

- **Ellenőrzés…** — egyszer átnézi az összes dolgozói PDF-et, és felsorolja:
  mi bélyegezhető **utólag** (a névből és a helyből), hol nincs se bélyeg, se
  felismerhető név (kézi munka), hol van **idegen** dolgozó bélyege, hol tér el
  a bélyeg a névtől, és mely fájlok **tartalom szerint azonosak** (két néven
  ugyanaz). Egy gombbal megbélyegzi a bélyegezhetőket — ez hozza be a
  visszamenőleges bélyeget.
- **Tömörítés…** — minden 5 MB feletti PDF egy körben, előnézettel. Az előző
  példány a dolgozó `.eredeti\` mappájába kerül, és naplósort is kap. Ami a
  legerősebb lépcső után is a korlát fölött marad, név szerint felsorolva a
  végén (ott kevesebb oldalra kell bontani).

**Beadható** csak az, aminek minden kötelező iratához van korlát alatti PDF a
`02_Feltoltheto`-ban. A gyökérben talált PDF-ről nem tudjuk, hogy aláírt-e,
ezért nem számít.

## Tesztek

```bash
python test/run-all.py
```

| Készlet | Parancs | Mit mér |
|---|---|---|
| önteszt | `python pdf-muhely.py --test` | szabályillesztés, 5 MB, tömörítés, képfeldolgozás |
| verzió | `python test/verzio.py` | hookok és tagek egy ideiglenes repóban, valódi commitokkal |
| frissítő | `python test/frissit.py` | ZIP-ből frissítés egy hamis „céges gépen”: mi marad meg |
| GUI | `python test/gui.py` | valódi ablak és események — pár másodpercre ablakok nyílnak |

A **megjelenést** a tesztek nem mérik (csak azt, hogy a téma elemei és az ikonok
felkerültek): ahhoz a `tools/ui-kep.py` felületfotó való.

A GUI-teszt a valódi beállításfájlokhoz nem nyúl (ideiglenes mappában dolgozik).

## Kiadás

```bash
python tools/kiadas.py
```

Lefuttatja az összes tesztet, a klón-próbát (a repó önmagában is teljes-e), majd
lépteti a főverziót. Ha bármi bukik, **megáll** — hibás kódot nem ad ki.
Csak nézni, változtatás nélkül: `python tools/kiadas.py --csak-ellenoriz`

## Verziószámok

A verzió `fő.al` alakú, például **1.27** — ugyanaz a séma, mint a DocGen-ben:

| rész | mit jelent | ki lépteti |
|---|---|---|
| fő | kiadás | `python tools/kiadas.py` |
| al | a commit sorszáma (`git rev-list --count HEAD`) | a `pre-commit` hook, minden commitnál |

Az alverziót nem tárolja külön számláló, a commit-számból számoljuk — így nem
tud elcsúszni, és merge-nél sincs mit ütköztetni. A verzió látszik a program
**címsorában**, és a repóban **git tagként** (`v1.27`, a `post-commit` hook
készíti) — a GitHub *Tags* oldaláról egy kattintással a pontos commitra lehet
jutni. A program maga soha nem hív gitet: a `verzio.json` a fájlokkal utazik.

**A fejlesztői gépen** egyszer be kell állítani (a git a configot szándékosan
nem klónozza):

```bash
git config core.hooksPath tools/hooks
git config push.followTags true
```

Az állapot ellenőrzése: `python tools/verzio.py --ellenoriz`

## Frissítés a használat helyén (ZIP-ből)

Ahol nincs git, a kód GitHubról letöltött ZIP-ben érkezik (*Code → Download
ZIP*). Kicsomagolni nem kell:

1. Húzd rá a letöltött ZIP-et a `tools\frissit.vbs` fájlra.
   (Vagy kattints rá duplán: magától megkeresi a legfrissebb *pdf-muhely* ZIP-et
   a Letöltések és az Asztal mappában.)
2. A szkript megmutatja, mi változna — **utána kérdez rá**, hogy csinálja-e.
3. Indítsd újra a programot: a címsorban az új verzió látszik.

**Amit garantál:** soha nem töröl semmit. Csak azokat a fájlokat írja felül,
amelyek a ZIP-ben is szerepelnek és tényleg különböznek (bájtra hasonlít
össze). A dolgozói mappák, a napló és a `.eredeti\` mentések nincsenek a
ZIP-ben, tehát hozzájuk sem nyúlhat; a **beállításfájlokat**
(`attekinto-szabalyok.json`, `iktato-doktipusok.json`, `emlekezet.json`) csak akkor hozza létre,
ha még nincsenek — a helyben testreszabott szabályok megmaradnak.

Ez nem ígéret, hanem mért tulajdonság: a `test/frissit.py` felépít egy hamis
„céges gépet” éles adattal és saját szabályfájllal, ráengedi a szkriptet egy
GitHub-szerű ZIP-pel, és ellenőrzi, hogy minden megmaradt.

> **VBScript**, mert a DocGen mérése szerint a Windows Script Host ezen a
> munkaállomáson fut, a PowerShell futtatási házirendjéről nincs mérés.
> Kérdés nélküli (rendszergazdai) futtatás:
> `cscript //nologo tools\frissit.vbs <zip> /csendes`
>
> A `.vbs` UTF-16 LE kódolású, BOM-mal — másként a Windows Script Host
> elrontja az ékezeteket. Szerkesztés után így kell menteni.

## Döntések

A tervezés és a döntések indoklása: [`kepek-pdf-terv.md`](kepek-pdf-terv.md)
(11. fejezet: mi készült el és miért), az Összeállítóé:
[`szetvago-terv.md`](szetvago-terv.md) (14. fejezet).
