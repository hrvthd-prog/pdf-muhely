# tessdata — a szövegfelismerés nyelvi adata

A Szerkesztés → Szövegfelismerés a PyMuPDF-be épített Tesseract-motort hívja;
külön program telepítése nem kell, csak ez a nyelvi adatfájl. A döntés
indoklása: `szerkeszto-terv.md`, 23.7.

| fájl | forrás | licenc |
|------|--------|--------|
| `hun.traineddata` | <https://github.com/tesseract-ocr/tessdata_fast> (`main` ág) | Apache-2.0 |

SHA-256: `35067e7cfe102dcdc953f9a758fdfaa6296b17a1ee6d874ee780fa306430b9fb`

A `fast` változat a kisebb és gyorsabb; a gépelt, szkennelt mintairatot
(önteszt: „Kőműves Győző”, TAJ-szám) hibátlanul olvassa.

Angol szöveghez az `eng.traineddata` is ide tehető — ha megvan, a program
magától `hun+eng` nyelvvel ismer fel. Nem tesszük a repóba: a magyar modell a
latin betűs angol szöveget is olvassa, a +4 MB nem éri meg.
