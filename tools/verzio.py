#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Verziókezelés: `fő.al` — a fő a kiadás, az al a commit sorszáma (a DocGen sémája).

  python tools/verzio.py --leptet      alverzió a commit-számból (a pre-commit hook hívja)
  python tools/verzio.py --kiadas      főverzió +1 (a kiadas.py hívja)
  python tools/verzio.py --tagel       annotált git tag a most született commitra (post-commit)
  python tools/verzio.py --ellenoriz   nem ír semmit, csak jelent

Miért a commit-szám és nem külön számláló: a számláló állapot, az állapot elcsúszik
és merge-nél ütközik. A `git rev-list --count HEAD` mindig kiszámolható, mindig nő,
és nincs mit karbantartani rajta.

A verzió a verzio.json-ban utazik a fájlokkal; az app ebből olvassa, gitet sosem
hív. A verzió → commit megfeleltetést a git tag adja (v1.4): a commit SHA-ja nem
írható a saját tartalmába (körkörös volna).
"""

import datetime
import json
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # hookból is: a git UTF-8-at vár

GYOKER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERZIO_FAJL = os.path.join(GYOKER, "verzio.json")


def git(*args) -> str:
    return subprocess.run(["git", *args], cwd=GYOKER, capture_output=True,
                          text=True, check=True).stdout.strip()


def commit_szam() -> int:
    """Hány commit van HEAD-ig? Üres repóban 0."""
    try:
        return int(git("rev-list", "--count", "HEAD"))
    except Exception:
        return 0


def fo_resz(v) -> int:
    """'1.27' -> 1 ; '1' -> 1"""
    try:
        return int(str(v).split(".")[0])
    except ValueError:
        return 0


def olvas():
    """A verzio.json verziója, vagy None."""
    try:
        with open(VERZIO_FAJL, encoding="utf-8") as f:
            return str(json.load(f)["verzio"])
    except Exception:
        return None


def ir(uj: str):
    with open(VERZIO_FAJL, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"verzio": uj, "datum": datetime.date.today().isoformat()}, f)
        f.write("\n")


def leptet(uj_fo=None) -> str:
    most = olvas() or "1.0"
    # A pre-commit hook FUTÁSAKOR a commit még nem létezik, ezért +1.
    al = commit_szam() + (1 if uj_fo is None else 0)
    uj = f"{fo_resz(most) if uj_fo is None else uj_fo}.{al}"
    if uj == most:
        print(f"A verzió változatlan: {uj}")
        return uj
    print(f"Verzió: {most} → {uj}")
    ir(uj)
    return uj


def tagel():
    v = olvas()
    if not v:
        print("✗ Nincs verzio.json – nincs mit tagelni.")
        sys.exit(1)
    tag = "v" + v
    if git("tag", "--list", tag):
        print(f"A {tag} tag már létezik – kihagyva.")
        return
    # Annotált tag kell (-a): a `git push --follow-tags` a könnyűsúlyú tageket
    # NEM viszi fel, tehát a verzió sosem érne el a GitHubra (DocGen, lemért eset).
    git("tag", "-a", tag, "-m", f"PDF Műhely {tag}")
    print(f"✓ {tag} – feltöltés: git push --follow-tags")


def ellenoriz():
    hiba = 0
    v = olvas()
    print(f"verzio.json: {v or '—'}")
    if not v:
        print("✗ Hiányzik vagy olvashatatlan a verzio.json.")
        hiba += 1
    try:
        hooks = git("config", "core.hooksPath")
    except Exception:
        hooks = ""
    if hooks != "tools/hooks":
        print("✗ Nincs beállítva a hook-mappa. Egyszeri lépés ezen a gépen:")
        print("    git config core.hooksPath tools/hooks")
        print("    git config push.followTags true")
        hiba += 1
    if hiba:
        sys.exit(1)
    print("✓ A verziókezelés rendben.")


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg == "--leptet":
        leptet()
    elif arg == "--kiadas":
        leptet(uj_fo=fo_resz(olvas() or "1.0") + 1)
    elif arg == "--tagel":
        tagel()
    elif arg == "--ellenoriz":
        ellenoriz()
    else:
        print("Használat: python tools/verzio.py --leptet | --kiadas | --tagel | --ellenoriz")
        sys.exit(1)
