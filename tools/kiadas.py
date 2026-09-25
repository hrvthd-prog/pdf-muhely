#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kiadás: tesztek, klón-próba, főverzió-lépés — egyetlen paranccsal.

  python tools/kiadas.py                    teljes kiadás
  python tools/kiadas.py --csak-ellenoriz   nem ír semmit, csak jelent

Kiadás = ami a használat helyére megy (ZIP-ből frissítés). Az alverziót minden
commitnál a pre-commit hook lépteti; itt a FŐ verzió nő, hogy a használat
helyén a címsorból egyértelmű legyen, melyik kiadás fut. Ha bármi bukik,
MEGÁLL — hibás kódot nem adunk ki. (A DocGen tools/kiadas.js átvétele.)
"""

import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
GYOKER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSAK_ELLENORIZ = "--csak-ellenoriz" in sys.argv


def fejlec(szoveg):
    print("\n" + "═" * 60 + "\n" + szoveg + "\n" + "═" * 60, flush=True)


def futtat(cimke, *args):
    r = subprocess.run([sys.executable, *args], cwd=GYOKER,
                       env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    if r.returncode != 0:
        print(f"\n✗ {cimke} — a kiadás MEGÁLL.\n  Hibás kódot nem adunk ki.")
        sys.exit(1)


fejlec("1/3  Tesztek")
futtat("A tesztek elbuktak", "test/run-all.py")

fejlec("2/3  Klón-próba — a repó önmagában is teljes?")
futtat("A klón-próba elbukott", "tools/klon-proba.py")

fejlec("3/3  Verzió")
if CSAK_ELLENORIZ:
    futtat("A verzió-ellenőrzés elbukott", "tools/verzio.py", "--ellenoriz")
    print("\n(--csak-ellenoriz: nem írtam semmit)")
    sys.exit(0)
futtat("A verziólépés elbukott", "tools/verzio.py", "--kiadas")

print("\n" + "═" * 60)
print("✓ Kiadásra kész.\n")
print("Hátralévő lépések:")
print("  1. git add -A && git commit   (a hook lépteti az alverziót és tagel)")
print("  2. git push --follow-tags")
print("  3. a használat helyén: GitHub → Code → Download ZIP, majd a ZIP-et")
print("     rá kell húzni a tools\\frissit.vbs fájlra")
