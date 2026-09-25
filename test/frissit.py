#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A ZIP-ből frissítő tools/frissit.vbs tesztje.   Futtatás: python test/frissit.py

A tét nem a másolás, hanem az, hogy MI MARAD MEG. A használat helyén a kód
mellett élhetnek a dolgozói mappák (ha a munkamappa a szkript mappája), a napló
és a felhasználó saját szabályai. Egy „tükröző” frissítő ezt csendben letörölné
vagy felülírná. Ezért itt egy valódi frissítés fut: felépítünk egy hamis
„céges gépet”, ráengedjük a szkriptet egy GitHub-szerű ZIP-pel, és megnézzük,
mi lett. (A DocGen test/frissit.test.js átvétele.)
"""

import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
GYOKER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VBS = os.path.join(GYOKER, "tools", "frissit.vbs")
res = []


def ck(label, ok, info=""):
    res.append(bool(ok))
    print(("  PASS  " if ok else "  FAIL  ") + label + (f"   -> {info}" if info != "" else ""))


def ir(gyoker, rel, tartalom):
    ut = os.path.join(gyoker, rel)
    os.makedirs(os.path.dirname(ut), exist_ok=True)
    with open(ut, "w", encoding="utf-8") as f:
        f.write(tartalom)


def olvas(gyoker, rel):
    with open(os.path.join(gyoker, rel), encoding="utf-8") as f:
        return f.read()


def futtat(cel, zip_):
    r = subprocess.run(["cscript", "//nologo", os.path.join(cel, "tools", "frissit.vbs"),
                        zip_, "/csendes"], capture_output=True)
    return r.returncode, r.stdout.decode("cp852", errors="replace")


if sys.platform != "win32":
    print("(nem Windows – a .vbs nem futtatható, a készlet kimarad)")
    sys.exit(0)

tmp = tempfile.mkdtemp(prefix="pdf-muhely-frissit-")
try:
    forras = os.path.join(tmp, "forras", "pdf-muhely-main")
    cel = os.path.join(tmp, "cegesgep")
    zip_ = os.path.join(tmp, "pdf-muhely-main.zip")

    # ── A forrás: ez jön a GitHubról ────────────────────────────────────────
    ir(forras, "pdf-muhely.py", "print('ÚJ verzió')")
    ir(forras, "verzio.json", '{"verzio": "1.99", "datum": "2026-09-25"}\n')
    ir(forras, "README.md", "# új fájl")
    ir(forras, "attekinto-szabalyok.json", '{"rules": "a repó ALAP szabályai"}')
    ir(forras, "iktato-doktipusok.json", '["Útlevél"]')
    ir(forras, ".eredeti/csapda.pdf", "ez a ZIP-ben van, de a védett mappába SOHA nem írhat")

    # ── A „céges gép”: régi kód + éles adat + saját beállítás + elárvult fájl ──
    ir(cel, "pdf-muhely.py", "print('RÉGI verzió')")                   # frissülnie kell
    ir(cel, "verzio.json", '{"verzio": "1.5", "datum": "2026-09-01"}\n')
    ir(cel, "attekinto-szabalyok.json", '{"rules": "SAJÁT, kézzel hangolt"}')  # SOHA nem írható felül
    ir(cel, "Kiss Anna/Kiss Anna Útlevél.pdf", "éles irat")             # SOHA nem törölhető
    ir(cel, "iktato-naplo.csv", "időbélyeg;forrás")                     # SOHA nem törölhető
    ir(cel, "regi-segedfajl.txt", "ez már nincs a repóban")             # nem törölhető
    os.makedirs(os.path.join(cel, "tools"))
    shutil.copy(VBS, os.path.join(cel, "tools", "frissit.vbs"))

    # ── ZIP, ahogy a GitHub adja: egyetlen gyökérmappával ───────────────────
    with zipfile.ZipFile(zip_, "w") as z:
        for d, _, fs in os.walk(os.path.dirname(forras)):
            for f in fs:
                p = os.path.join(d, f)
                z.write(p, os.path.relpath(p, os.path.dirname(forras)))

    print("[Lefutás]")
    code, out = futtat(cel, zip_)
    ck("a szkript hibátlanul lefut", code == 0, (code, out.strip()[:200]))

    print("[Frissítés]")
    ck("a megváltozott kód frissült", "ÚJ" in olvas(cel, "pdf-muhely.py"))
    ck("a verzió frissült", "1.99" in olvas(cel, "verzio.json"))
    ck("az új fájl megérkezett", os.path.exists(os.path.join(cel, "README.md")))
    ck("a hiányzó beállításfájl létrejött", os.path.exists(os.path.join(cel, "iktato-doktipusok.json")))

    print("[Amihez nem szabad nyúlni]")
    ck("a SAJÁT szabályfájl megmaradt — a ZIP-beli alap NEM írta felül",
       "SAJÁT" in olvas(cel, "attekinto-szabalyok.json"), olvas(cel, "attekinto-szabalyok.json"))
    ck("a dolgozói mappa és irata megvan",
       olvas(cel, "Kiss Anna/Kiss Anna Útlevél.pdf") == "éles irat")
    ck("a napló megvan", os.path.exists(os.path.join(cel, "iktato-naplo.csv")))
    ck("a repóból kikerült fájlt nem törli", os.path.exists(os.path.join(cel, "regi-segedfajl.txt")))
    ck("a védett .eredeti mappába nem írt", not os.path.exists(os.path.join(cel, ".eredeti")))

    print("[Másodszori futás]")
    code2, out2 = futtat(cel, zip_)
    ck("a második futás már nem talál változást", code2 == 0 and "naprak" in out2, out2.strip()[:120])
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print(f"\n=== frissítő: {sum(res)}/{len(res)} sikeres ===")
sys.exit(0 if all(res) else 1)
