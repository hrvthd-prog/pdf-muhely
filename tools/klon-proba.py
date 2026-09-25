#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Klón-próba: friss klónban is teljes-e a repó?   python tools/klon-proba.py

Miért kell itt különösen: a .gitignore ENGEDÉLYEZŐ LISTA (`*` + név szerinti
kivételek), hogy dolgozói irat soha ne kerüljön a repóba. Ennek az ára, hogy egy
új projektfájl csendben kimarad, ha nem vesszük fel a listára — nálunk működik,
egy friss klónban (és a GitHub-ZIP-ben, amiből a használat helyén frissítünk)
viszont hiányzik. Ez a szkript az egész hibaosztályt kizárja. (A DocGen
tools/klon-proba.js átvétele, ott egy .gitignore-szabály okozott ilyet.)

A nem commitolt változtatásokat NEM viszi át — pont az a lényeg, hogy azt mérje,
ami tényleg a repóban van.
"""

import os
import shutil
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
GYOKER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KELL = ["pdf-muhely.py", "verzio.json", "attekinto-szabalyok.json", "README.md",
        "tools/verzio.py", "tools/kiadas.py", "tools/frissit.vbs",
        "tools/hooks/pre-commit", "tools/hooks/post-commit",
        "test/run-all.py", "test/gui.py", "test/verzio.py", "test/frissit.py"]


def git(*args, cwd=GYOKER):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


piszkos = git("status", "--porcelain").stdout.strip()
if piszkos:
    print("FIGYELEM: van nem commitolt változás. A klón-próba csak azt méri, ami már")
    print("a repóban van, tehát ezek NEM lesznek benne:\n")
    print("\n".join("  " + s for s in piszkos.splitlines()) + "\n")

tmp = tempfile.mkdtemp(prefix="pdf-muhely-klon-")
hiba = 0
try:
    klon = os.path.join(tmp, "klon")
    git("clone", "--quiet", GYOKER, klon)
    hianyzik = [f for f in KELL if not os.path.exists(os.path.join(klon, f))]
    print(f"Fájlok a klónban: {len(KELL) - len(hianyzik)}/{len(KELL)}")
    for f in hianyzik:
        print(f"  ✗ hiányzik: {f}   (felvetted a .gitignore engedélyező listájára?)")
    hiba += len(hianyzik)

    # CRLF-es hook: a `#!/bin/sh` sor használhatatlan, és a hook NÉMÁN nem fut le.
    for h in ("pre-commit", "post-commit"):
        p = os.path.join(klon, "tools", "hooks", h)
        if os.path.exists(p) and b"\r\n" in open(p, "rb").read():
            print(f"  ✗ tools/hooks/{h}: CRLF sorvég — a hook nem futna (.gitattributes!)")
            hiba += 1

    print("\nÖnteszt a klónban:")
    r = subprocess.run([sys.executable, "pdf-muhely.py", "--test"], cwd=klon,
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    print("  " + (r.stdout.strip().splitlines() or ["(nincs kimenet)"])[-1])
    if r.returncode != 0:
        print("  ✗ A KLÓNBAN NEM FUT LE AZ ÖNTESZT.")
        hiba += 1
finally:
    shutil.rmtree(tmp, ignore_errors=True)

if hiba:
    print("\n✗ A friss klón NEM teljes.")
    sys.exit(1)
print("\nEmlékeztető: friss klónban egyszer le kell futtatni:")
print("  git config core.hooksPath tools/hooks")
print("  git config push.followTags true")
print("\n✓ A friss klón önmagában is teljes.")
