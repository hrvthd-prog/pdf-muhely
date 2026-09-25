# CLAUDE.md — PDF Műhely

Útmutató AI-asszisztensnek (Claude Code) ehhez a repóhoz.

## A projekt

Egyfájlos, offline tkinter + pymupdf eszköztár (`pdf-muhely.py`), a DocGen
testvére: a nyomtatás–aláírás–szkennelés utáni lépések (Képek → PDF, Iktató,
Áttekintő). Használat: `README.md`. A döntések indoklása: `kepek-pdf-terv.md`,
11. fejezet — **új döntést oda írj**.

## Tesztek

```bash
python test/run-all.py            # önteszt + verzió + frissítő + GUI
python pdf-muhely.py --test       # csak az önteszt (gyors, ablak nélkül)
```

Kódváltozás után mindig futtasd; GUI-t érintő változásnál a `test/gui.py`-t is
bővítsd. A GUI-teszt a `script_dir`-t ideiglenes mappára irányítja — a valódi
beállításfájlokhoz tesztből ne nyúlj.

## Kötelező tudnivalók

- **5 MB-os feltöltési korlát** (`UPLOAD_LIMIT = 5_000_000`, szándékosan tizedes).
- A **`.gitignore` engedélyező lista**: új projektfájlt fel kell venni rá, különben
  csendben kimarad (a `tools/klon-proba.py` ezt méri). Dolgozói irat soha nem
  kerülhet a repóba.
- **Verzió**: `fő.al`, a DocGen sémája. A `verzio.json`-t a pre-commit hook írja,
  kézzel ne szerkeszd. Friss klónban egyszer:
  `git config core.hooksPath tools/hooks` és `git config push.followTags true`.
- A `tools/frissit.vbs` **UTF-16 LE BOM, CRLF** — másként elromlanak az ékezetek.
  A hookok LF-esek (`.gitattributes`), CRLF-fel némán nem futnának.

## Git

Commit és push közvetlenül `main`-re, `git push --follow-tags`-szel (a tagek is
menjenek). Commit-üzenet magyarul, a DocGen stílusában: tárgysor, indoklás,
tesztsor.
