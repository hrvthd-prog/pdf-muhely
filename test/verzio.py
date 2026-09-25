#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A verziókezelés tesztje: valódi commitok egy ideiglenes repóban, a valódi hookokkal.
Futtatás: python test/verzio.py

A tét: ha a hook nem fut vagy nem tagel, a használat helyén látott verziószámból
nem lehet visszatalálni a commitra — és a frissítés nem ellenőrizhető.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
GYOKER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
res = []


def ck(label, ok, info=""):
    res.append(bool(ok))
    print(("  PASS  " if ok else "  FAIL  ") + label + (f"   -> {info}" if info != "" else ""))


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def verzio(repo):
    with open(os.path.join(repo, "verzio.json"), encoding="utf-8") as f:
        return json.load(f)["verzio"]


def commit(repo, fajl, uzenet):
    with open(os.path.join(repo, fajl), "a", encoding="utf-8") as f:
        f.write(uzenet + "\n")
    git(repo, "add", fajl)
    return git(repo, "commit", "-q", "-m", uzenet)


tmp = tempfile.mkdtemp(prefix="pdf-muhely-verzio-")
try:
    repo = os.path.join(tmp, "repo")
    shutil.copytree(os.path.join(GYOKER, "tools"), os.path.join(repo, "tools"),
                    ignore=shutil.ignore_patterns("__pycache__"))
    git(repo, "init", "-q", "-b", "main")
    for k, v in (("user.name", "teszt"), ("user.email", "teszt@example.invalid"),
                 ("core.hooksPath", "tools/hooks"), ("commit.gpgsign", "false"),
                 ("tag.gpgsign", "false")):
        git(repo, "config", k, v)
    git(repo, "add", "tools")

    print("[Alverzió minden commitnál]")
    r = commit(repo, "a.txt", "első")
    ck("az első commit lefut (a hook nem akasztja meg)", r.returncode == 0, r.stderr.strip()[:200])
    ck("verzio.json = 1.1, és a commitban van",
       verzio(repo) == "1.1" and "verzio.json" in git(repo, "show", "--name-only", "HEAD").stdout,
       verzio(repo))
    commit(repo, "a.txt", "második")
    ck("második commit -> 1.2", verzio(repo) == "1.2", verzio(repo))
    tags = git(repo, "tag", "--list").stdout.split()
    ck("minden commit tagelve: v1.1, v1.2", tags == ["v1.1", "v1.2"], tags)
    ck("a tag annotált (a push --follow-tags csak ezt viszi fel)",
       git(repo, "cat-file", "-t", "v1.2").stdout.strip() == "tag")
    ck("a v1.2 a HEAD-re mutat",
       git(repo, "rev-parse", "v1.2^{commit}").stdout == git(repo, "rev-parse", "HEAD").stdout)
    ck("munka közben tiszta marad a fa (a hook a verziót is commitolja)",
       git(repo, "status", "--porcelain").stdout.strip() == "")

    print("[Kiadás: főverzió +1]")
    subprocess.run([sys.executable, os.path.join(repo, "tools", "verzio.py"), "--kiadas"],
                   cwd=repo, capture_output=True)
    ck("--kiadas -> 2.2 (a commit előtt)", verzio(repo) == "2.2", verzio(repo))
    git(repo, "add", "verzio.json")
    commit(repo, "a.txt", "kiadás")
    ck("a kiadás commitja -> 2.3 és v2.3 tag",
       verzio(repo) == "2.3" and "v2.3" in git(repo, "tag", "--list").stdout, verzio(repo))

    print("[Ellenőrzés]")
    e = subprocess.run([sys.executable, os.path.join(repo, "tools", "verzio.py"), "--ellenoriz"],
                       cwd=repo, capture_output=True, text=True, encoding="utf-8")
    ck("--ellenoriz rendben (hook-mappa beállítva)", e.returncode == 0, e.stdout.strip())
    git(repo, "config", "--unset", "core.hooksPath")
    e = subprocess.run([sys.executable, os.path.join(repo, "tools", "verzio.py"), "--ellenoriz"],
                       cwd=repo, capture_output=True, text=True, encoding="utf-8")
    ck("--ellenoriz szól, ha nincs hook-mappa", e.returncode == 1 and "hooksPath" in e.stdout)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print(f"\n=== verziókezelés: {sum(res)}/{len(res)} sikeres ===")
sys.exit(0 if all(res) else 1)
