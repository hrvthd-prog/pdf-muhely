#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Minden teszt egyben.   Futtatás: python test/run-all.py

  önteszt   python pdf-muhely.py --test   szabályillesztés, tömörítés, képfeldolgozás
  verzió    python test/verzio.py         hookok, tagek egy ideiglenes repóban
  frissítő  python test/frissit.py        ZIP-ből frissítés egy hamis „céges gépen”
  GUI       python test/gui.py            valódi ablak és események (pár mp-re ablakok nyílnak)
"""

import os
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
GYOKER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KESZLETEK = [("önteszt", ["pdf-muhely.py", "--test"]),
             ("verzió", ["test/verzio.py"]),
             ("frissítő", ["test/frissit.py"]),
             ("GUI", ["test/gui.py"])]

eredmeny = []
for nev, args in KESZLETEK:
    print(f"\n{'─' * 60}\n{nev}\n{'─' * 60}", flush=True)
    t = time.time()
    r = subprocess.run([sys.executable, *args], cwd=GYOKER,
                       env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    eredmeny.append((nev, r.returncode == 0, time.time() - t))

print(f"\n{'═' * 60}")
for nev, ok, mp in eredmeny:
    print(f"  {'✓' if ok else '✗'} {nev:10} {mp:5.1f} s")
bukott = [n for n, ok, _ in eredmeny if not ok]
print("Mind sikeres ✓" if not bukott else f"ELBUKOTT: {', '.join(bukott)}")
sys.exit(1 if bukott else 0)
