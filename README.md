# PDF Műhely

Offline asztali eszköztár idegenrendészeti iratok előkészítéséhez: PDF-ek
összefűzése, szétvágása, arckép elhelyezése, képekből tömörített PDF, iktatás a
dolgozók mappáiba, és áttekintés arról, ki adható be. Hálózatot nem használ.
A dokumentumokat a [DocGen](https://github.com/hrvthd-prog/DocGen) generálja,
ez az eszköz a nyomtatás–aláírás–szkennelés utáni lépéseket segíti.

| Fül | Mire való |
|---|---|
| Arckép elhelyezés | fénykép ráhelyezése egy PDF-nyomtatványra |
| Összefűzés / Szétvágás / Raszterizálás | PDF-műveletek |
| Képek → PDF | fotókból, szkennelt képekből egy tömörített PDF (vonszolásos sorrend, nagyító, kijelöltekből külön PDF) |
| Iktató | a PDF-et ráejted a dolgozó nevére: szabványos nevet kap, a mappájába kerül, naplózva |
| Áttekintő | mátrix: dolgozónként melyik irat van meg, ki adható be, mi hiányzik |

## Telepítés és indítás

Python 3.10+ és PyMuPDF kell (a tkinter a Python része):

```bash
pip install pymupdf
```

```bash
python pdf-muhely.py
```

A címsorban látszik a verzió (pl. `v1.4 (2026-09-25)`). Ha a PyMuPDF túl régi a
tömörítéshez vagy a JPEG-minőség állításához, az app induláskor szól
(1.26.7-tel tesztelve); a többi funkció ilyenkor is működik.

## Az 5 MB-os feltöltési korlát

A portálra egy fájl legfeljebb 5 MB lehet. A korlát szándékosan a szigorúbb
értelmezés: **5 000 000 bájt** (`UPLOAD_LIMIT`). Minden fül jelez, ha egy kész
fájl fölötte van; az **Iktató** iktatáskor felajánlja a tömörítést (a forrás
érintetlen marad), a **Képek → PDF** magától tömörít, az **Áttekintő** `P!`
jellel mutatja, és a csak túlméretes PDF-fel rendelkező iratot nem számítja
beadhatónak. A tömörítés csak a beágyazott képeket kódolja újra, lépcsőnként
(200 → 150 → 120 → 100 DPI), és megáll, amint befért.

## Adatfájlok — mi hol él

| Fájl / mappa | Hol | Verziókezelésben? |
|---|---|---|
| `attekinto-szabalyok.json` — az Áttekintő irattípusai, kulcsszavai | a program mappájában | igen (alapértelmezés) |
| `iktato-doktipusok.json` — az Iktató doktípus-listája | a program mappájában | igen, ha létrejön |
| `verzio.json` — a verziószám | a program mappájában | igen, **gép írja** |
| `iktato-naplo.csv` — az iktatás naplója | a munkamappában | **nem** |
| `.eredeti\` — felülírt iratok előző példánya | a dolgozó mappájában | **nem** |

A `.gitignore` **engedélyező lista**: csak a név szerint felsorolt fájlok
kerülhetnek a repóba, mert a munkamappa alapból a program mappája, és oda
dolgozói iratok is kerülhetnek. **Új projektfájlt a `.gitignore`-ba is fel kell
venni** — a klón-próba (lásd lent) szól, ha kimaradt.

Felülírásnál (Iktató) az előző példány a dolgozó mappájában a `.eredeti\`
almappába kerül, és a **Visszavonás** visszahozza. A ponttal kezdődő mappát az
Áttekintő és az Iktató is kihagyja.

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
(`attekinto-szabalyok.json`, `iktato-doktipusok.json`) csak akkor hozza létre,
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
(11. fejezet: mi készült el és miért).
