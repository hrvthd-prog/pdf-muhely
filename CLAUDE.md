# CLAUDE.md — PDF Műhely

Útmutató AI-asszisztensnek (Claude Code) ehhez a repóhoz.

## A projekt

Egyfájlos, offline tkinter + pymupdf eszköztár (`pdf-muhely.py`), a DocGen
testvére: a nyomtatás–aláírás–szkennelés utáni lépések (Összeállító, Iktató,
Áttekintő). Használat: `README.md`. A döntések indoklása: `kepek-pdf-terv.md`,
11. fejezet (a dolgozónkénti két alkönyvtár: 12. fejezet), az Összeállítóé (a volt
Szétvágás és Képek → PDF) `szetvago-terv.md`, 14–15. fejezet, a PDF-szerkesztőé
és a TAJ-szabályoké `szerkeszto-terv.md`, 14–21. és 23. (a bővítési javaslatok: 22.), a
közös felületi döntéseké `kepek-pdf-terv.md` 13.7 és 19. — **új döntést a
témához tartozó fájlba írj**. A két alkönyvtár DocGen-oldali párja:
`DocGen/TERV-mappaszerkezet.md`.

## Hol fut?

- **Élesben a felhasználó céges Windows-gépén**, a dolgozói iratok is ott
  vannak. Fejlesztőgépen (otthoni Windows, VPS `/root/pdf-muhely`, felhős
  session) ne keress iratot.
- **VPS (Ubuntu):** a `python3` ott 3.13, tkinter nélkül — a repó `.venv`-je
  kell (Python 3.12 + tkinter + pymupdf): `source .venv/bin/activate`, majd
  `xvfb-run -a python test/run-all.py`. Újraépítés:
  `python3.12 -m venv --without-pip .venv && python3.13 -m pip --python .venv/bin/python install pymupdf==1.26.7`.
- **Linuxon ismert, platformfüggő bukások** (2026-10-15, alapállapot): nincs
  Calibri (önteszt 1, GUI 1), `ctypes.windll` (GUI 1), időzítésérzékeny
  tömörítés-alatti akadás (GUI 1). A `frissítő` kihagyja magát; a
  `tools/ui-kep.py` Windows-only, a megjelenést ott nem lehet lefényképezni.

## Tesztek

```bash
python test/run-all.py            # önteszt + verzió + frissítő + GUI
python pdf-muhely.py --test       # csak az önteszt (gyors, ablak nélkül)
```

Kódváltozás után mindig futtasd; GUI-t érintő változásnál a `test/gui.py`-t is
bővítsd. Nagyított (125–200%-os) Windows-kijelző utánzása:
`PDF_MUHELY_SKALA=1.5 python test/gui.py` (`kepek-pdf-terv.md` 19.2). A GUI-teszt
a `script_dir`-t ideiglenes mappára irányítja — a valódi beállításfájlokhoz
tesztből ne nyúlj.

**A megjelenést egyik teszt sem méri.** Ha a felülethez nyúlsz, nézd meg:

```bash
python tools/ui-kep.py 0 kep.png   # 0–2: fő fülek · 3: Eszközök · 4: Ellenőrzés
                                   # 5: Szerkesztés (mező) · 6: Bekezdés formázása
python tools/ui-kep.py 7 kep.png search   # 7: Szerkesztés egy eszközzel: box, search,
                                          #    pii, decor, form, ocr
```

A szövegfelismerés nyelvi adata (`tessdata/hun.traineddata`) a repóban van: a
PyMuPDF beépített motorja használja, Tesseractot nem telepítünk
(`szerkeszto-terv.md` 23.7).

A téma (gombok, mezők, fülek, ikonok) kódból rajzolt grafika — a döntés és a
buktatók: `kepek-pdf-terv.md` 13.7.

## Kötelező tudnivalók

- **5 MB-os feltöltési korlát** (`UPLOAD_LIMIT = 5_000_000`, szándékosan tizedes).
- A **`.gitignore` engedélyező lista**: új projektfájlt fel kell venni rá, különben
  csendben kimarad (a `tools/klon-proba.py` ezt méri). Dolgozói irat soha nem
  kerülhet a repóba.
- **Verzió**: `fő.al`, a DocGen sémája. A `verzio.json`-t a pre-commit hook írja,
  kézzel ne szerkeszd. Friss klónban egyszer:
  `git config core.hooksPath tools/hooks` és `git config push.followTags true`.
- A `tools/frissit.vbs` **UTF-16 LE BOM, CRLF** — másként elromlanak az ékezetek.
  A hookok LF-esek (`.gitattributes`), CRLF-fel némán nem futnának; és
  futtathatók (`100755`) — `644`-gyel Linuxon némán kimaradnak.

## Git

Commit és push közvetlenül `main`-re, `git push --follow-tags`-szel (a tagek is
menjenek). Commit-üzenet magyarul, a DocGen stílusában: tárgysor, indoklás,
tesztsor.
