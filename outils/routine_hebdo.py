#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Met a jour la page de veille animes, du dernier episode vu jusqu'a GitHub.

Enchaine : export Crunchyroll, appariement AniList des seules series neuves,
recommandations et grille, rendu, commit et push. Prevenu par Telegram quand
ca casse, ce qui arrivera le jour ou le cookie Crunchyroll expirera.

Lance par la tache planifiee « Veille animes » le dimanche a 19h.
A la main :  .crunchyexporter/.venv/Scripts/python.exe outils/routine_hebdo.py
Options   :  --dry-run  tout sauf le commit et le push
             --complet  reinterroge AniList pour toutes les series
"""
import io
import json
import os
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTILS = os.path.join(REPO, "outils")
EXPORT = os.path.join(REPO, ".crunchyexporter")
PY_EXPORT = os.path.join(EXPORT, ".venv", "Scripts", "python.exe")
DONNEES = os.path.join(REPO, "donnees-locales")
LOG = os.path.join(REPO, ".routine.log")
ENV_TELEGRAM = os.path.join(REPO, ".telegram.env")

DRY = "--dry-run" in sys.argv
COMPLET = "--complet" in sys.argv


def log(msg):
    ligne = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(ligne)
    with io.open(LOG, "a", encoding="utf-8") as fh:
        fh.write(ligne + "\n")


def telegram(texte):
    """Previent Quentin. Ne leve jamais : l'alerte ne doit pas masquer la panne."""
    try:
        conf = {}
        for ligne in io.open(ENV_TELEGRAM, encoding="utf-8"):
            if "=" in ligne:
                cle, val = ligne.strip().split("=", 1)
                conf[cle] = val
        token, chat = conf.get("TELEGRAM_BOT_TOKEN"), conf.get("TELEGRAM_ALLOWED_USER_ID")
        if not token or not chat:
            log("  telegram : identifiants absents, pas d'alerte envoyee")
            return
        import requests
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat, "text": texte, "parse_mode": "HTML"},
            timeout=30, verify=False)
        log(f"  telegram : HTTP {r.status_code}")
    except Exception as exc:                                  # noqa: BLE001
        log(f"  telegram : echec de l'alerte ({type(exc).__name__})")


def lancer(cmd, cwd, etape, timeout=1800):
    """Sous-processus dont chaque ligne part au log. Leve si le code n'est pas 0."""
    log(f"  $ {' '.join(str(c) for c in cmd[:3])} ...")
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, timeout=timeout,
                       encoding="utf-8", errors="replace")
    for ligne in (p.stdout or "").splitlines()[-25:]:
        log("    " + ligne)
    if p.returncode != 0:
        for ligne in (p.stderr or "").splitlines()[-15:]:
            log("    err: " + ligne)
        raise RuntimeError(f"{etape} a echoue (code {p.returncode})")
    return p.stdout or ""


def compter_episodes(chemin):
    try:
        with io.open(chemin, encoding="utf-8") as fh:
            return len(json.load(fh).get("episodes", []))
    except (OSError, ValueError):
        return 0


def etape_export():
    """Recupere l'historique Crunchyroll. C'est ici que le cookie expire."""
    if not os.path.exists(PY_EXPORT):
        raise RuntimeError(
            "l'outil d'export est absent, relancer son installation "
            "(voir outils/MISE-A-JOUR.md)")
    config = os.path.join(EXPORT, "config.yaml")
    if not os.path.exists(config):
        raise RuntimeError("config.yaml absent : le cookie etp_rt n'est pas renseigne")

    data = os.path.join(EXPORT, "data")
    os.makedirs(data, exist_ok=True)
    cible = os.path.join(data, "history.json")
    avant = compter_episodes(cible)

    lancer([PY_EXPORT, os.path.join("src", "main.py"), "-c", "config.yaml", "fetch"],
           EXPORT, "l'export Crunchyroll")

    apres = compter_episodes(cible)
    if apres == 0:
        raise RuntimeError("l'export a rendu un historique vide, cookie expire ?")
    # Un historique qui retrecit est un incident, pas une mise a jour.
    if avant and apres < avant * 0.9:
        raise RuntimeError(f"l'historique a fondu, {avant} episodes avant, {apres} apres")
    log(f"  historique : {avant} -> {apres} episodes ({apres - avant:+d})")
    return apres - avant


def etape_construction():
    """Appariement, recommandations, grille, rendu. Depuis un dossier de travail
       ou build_page.py trouve ses data/ et son gabarit, comme il s'y attend."""
    travail = os.path.join(EXPORT)
    for nom in ("build_profile.py", "build_page.py", "page_template.html"):
        _copier(os.path.join(OUTILS, nom), os.path.join(travail, nom))
    for nom in ("profile.json", "recos.json", "popular.json"):
        src = os.path.join(DONNEES, nom)
        if os.path.exists(src):
            _copier(src, os.path.join(travail, "data", nom))

    args = [] if COMPLET else ["--incremental"]
    lancer([PY_EXPORT, "build_profile.py"] + args, travail, "l'appariement AniList")
    lancer([PY_EXPORT, "build_page.py"], travail, "la generation de la page")

    # Les donnees regenerees reviennent au depot, la page devient index.html.
    for nom in ("profile.json", "recos.json", "popular.json", "history.json"):
        src = os.path.join(travail, "data", nom)
        if os.path.exists(src):
            _copier(src, os.path.join(DONNEES, nom))
    page = os.path.join(travail, "anime.html")
    if not os.path.exists(page) or os.path.getsize(page) < 50_000:
        raise RuntimeError("anime.html absent ou anormalement petit")
    _copier(page, os.path.join(REPO, "index.html"))


def _copier(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with io.open(src, "rb") as a, io.open(dst, "wb") as b:
        b.write(a.read())


def etape_verification():
    """Refuse de publier une page cassee. Les tests du depot font foi."""
    for test in ("test_logique.js", "test_rattachement.js"):
        _copier(os.path.join(OUTILS, test), os.path.join(EXPORT, test))
    sortie = lancer(["node", "test_logique.js"], EXPORT, "les tests de logique", timeout=300)
    sortie += lancer(["node", "test_rattachement.js"], EXPORT, "les tests de rattachement", timeout=300)
    if "0 echecs" not in sortie:
        raise RuntimeError("des tests ont echoue, la page n'est pas publiee")


def etape_publication(delta):
    etat = lancer(["git", "status", "--porcelain"], REPO, "la lecture de l'etat git")
    if not etat.strip():
        log("  rien n'a change, pas de commit")
        return False
    if DRY:
        log("  --dry-run : commit et push sautes")
        return False
    sujet = (f"Mise a jour hebdomadaire, {delta} episodes de plus"
             if delta > 0 else "Mise a jour hebdomadaire")
    lancer(["git", "add", "-A"], REPO, "git add")
    lancer(["git", "commit", "-m", sujet], REPO, "le commit")
    lancer(["git", "push", "origin", "main"], REPO, "le push", timeout=300)
    return True


def main():
    log("=== Routine hebdomadaire de la veille animes ===")
    if DRY:
        log("  mode --dry-run")
    try:
        delta = etape_export()
        etape_construction()
        etape_verification()
        publie = etape_publication(delta)
    except Exception as exc:                                  # noqa: BLE001
        log(f"ECHEC : {exc}")
        telegram(
            "<b>Veille animés : la mise à jour a échoué</b>\n\n"
            f"{exc}\n\n"
            "Si c'est le cookie Crunchyroll : connecte-toi sur crunchyroll.com, "
            "F12 puis Application, Cookies, copie la valeur de <code>etp_rt</code> "
            "dans <code>.crunchyexporter/config.yaml</code>.\n\n"
            f"Journal : <code>{LOG}</code>")
        return 1

    log(f"=== Termine, {'publie' if publie else 'rien a publier'} ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
