#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Connexion durable a Crunchyroll et export de l'historique de visionnage.

Remplace le cookie etp_rt, qui expirait sans prevenir et a fige la page du 8 aout
au 4 octobre 2026. Crunchyroll se connecte ici comme une application TV : un code
saisi une fois sur crunchyroll.com/activate rend un jeton de renouvellement, que
la routine reutilise chaque semaine. Aucun mot de passe n'est stocke.

Le jeton vit dans .crunchyroll-session.json, a la racine, jamais versionne : il
vaut un acces au compte.

A la main, pour se (re)connecter :
    .venv/Scripts/python.exe outils/crunchyroll.py connexion
"""
import io
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone

import requests

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SESSION = os.path.join(REPO, ".crunchyroll-session.json")

API = "https://beta-api.crunchyroll.com"
# Identifiants du client Samsung TV, ceux que l'application TV envoie a chaque
# requete. Le client web (celui du cookie) refuse le renouvellement de jeton :
# mesure le 28/09, « unsupported_grant_type ».
CLIENT_AUTH = "Basic eHVuaWh2ZWRidDNtYmlzdWhldnQ6MWtJUzVkeVR2akUwX3JxYUEzWWVBaDBiVVhVbXhXMTE="
UA = ("Mozilla/5.0 (SMART-TV; LINUX; Tizen 5.0) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Version/5.0 TV Safari/537.36")
# Les titres servent a l'appariement AniList, qui a ete construit sur l'anglais.
LOCALE = "en-US"
PAGE = 1000
# Crunchyroll annonce "interval": 500, en millisecondes. Lu en secondes, la
# premiere verification tombait apres la mort du code (300 s).
ATTENTE = 3


class SessionExpiree(Exception):
    """Crunchyroll refuse le jeton : il faut une nouvelle activation par code."""


def _entetes(auth):
    return {"User-Agent": UA, "Authorization": auth, "Accept": "application/json"}


def _lire_session():
    try:
        with io.open(SESSION, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _ecrire_session(jeton, device_id):
    with io.open(SESSION, "w", encoding="utf-8") as fh:
        json.dump({"refresh_token": jeton["refresh_token"],
                   "account_id": jeton["account_id"],
                   "device_id": device_id}, fh)


def jeton():
    """Jeton d'acces frais et identifiant du compte.

    Leve SessionExpiree seulement quand Crunchyroll refuse le jeton
    (400 invalid_grant, mesure). Une panne reseau ou un blocage leve une autre
    erreur : ce n'est pas une raison de demander un nouveau code."""
    session = _lire_session()
    if not session or not session.get("refresh_token"):
        raise SessionExpiree("aucune session Crunchyroll enregistree")
    r = requests.post(f"{API}/auth/v1/token", headers=_entetes(CLIENT_AUTH), timeout=30, data={
        "refresh_token": session["refresh_token"],
        "grant_type": "refresh_token",
        "scope": "offline_access",
    })
    if r.status_code in (400, 401):
        try:
            erreur = r.json().get("error")
        except ValueError:
            erreur = None
        if erreur == "invalid_grant":
            raise SessionExpiree("Crunchyroll a refuse le jeton enregistre")
    if not r.ok:
        raise RuntimeError(f"renouvellement du jeton Crunchyroll : HTTP {r.status_code} {r.text[:200]}")
    frais = r.json()
    # Le jeton ne tournait pas au 04/10, mais s'il se met a tourner, l'ancien
    # mourrait avec la routine suivante : on garde toujours le dernier rendu.
    if frais.get("refresh_token") and frais["refresh_token"] != session["refresh_token"]:
        _ecrire_session(frais, session.get("device_id"))
    return frais["access_token"], frais.get("account_id") or session["account_id"]


def connexion_par_code(annoncer, essais=3):
    """Activation par code d'appareil. annoncer(code, essai, essais) transmet le
    code a Quentin. Rend True des que l'activation est validee."""
    device_id = (_lire_session() or {}).get("device_id") or str(uuid.uuid4())
    for essai in range(1, essais + 1):
        r = requests.post(f"{API}/auth/v1/device/code", headers=_entetes(CLIENT_AUTH), timeout=30, data={
            "device_id": device_id,
            "device_type": "Crunchyroll for Linux",
            "device_name": "Veille animes",
        })
        if not r.ok:
            raise RuntimeError(f"demande de code Crunchyroll : HTTP {r.status_code} {r.text[:200]}")
        code = r.json()
        annoncer(code["user_code"].upper(), essai, essais)
        fin = time.time() + int(code.get("expires_in") or 300)
        while time.time() < fin:
            time.sleep(ATTENTE)
            # En attente, Crunchyroll rend 204 sans corps ; un code mort, 400.
            r = requests.post(f"{API}/auth/v1/device/token", headers=_entetes(CLIENT_AUTH), timeout=30,
                              json={"device_id": device_id, "device_code": code["device_code"]})
            if r.status_code == 200 and r.text:
                _ecrire_session(r.json(), device_id)
                return True
            if r.status_code == 400:
                break
    return False


def _episode(item):
    """Meme forme que l'ancien export (CrunchyExporter), que build_profile.py lit."""
    panel = item.get("panel") or {}
    if not panel:
        return None
    meta = panel.get("episode_metadata") or {}
    try:
        saison = int(meta.get("season_number") or 1)
    except (TypeError, ValueError):
        saison = 1
    try:
        numero = float(meta.get("episode_number") or 0)
    except (TypeError, ValueError):
        numero = 0.0
    return {
        "series_id": meta.get("series_id") or panel.get("id", ""),
        "series_title": meta.get("series_title") or panel.get("title", "unknown"),
        "season_number": saison,
        "episode_number": numero,
        "episode_title": panel.get("title", ""),
        "episode_id": panel.get("id", ""),
        "watched_at": item.get("date_played"),
        "fully_watched": item.get("fully_watched", False),
    }


def exporter_historique(cible):
    """Ajoute a cible les episodes vus absents. Rend (avant, apres)."""
    acces, compte = jeton()
    vus = []
    # La pagination suit le curseur meta.next_page : les numeros de page sont
    # refuses au-dela de 10 (HTTP 400, mesure le 04/10).
    url = f"{API}/content/v2/{compte}/watch-history?page_size={PAGE}&locale={LOCALE}"
    for page in range(1, 201):
        r = requests.get(url, headers=_entetes(f"Bearer {acces}"), timeout=60)
        if not r.ok:
            raise RuntimeError(f"lecture de l'historique, page {page} : HTTP {r.status_code} {r.text[:200]}")
        reponse = r.json()
        vus.extend(e for e in map(_episode, reponse.get("data") or []) if e)
        suivante = (reponse.get("meta") or {}).get("next_page")
        if not suivante or not reponse.get("data"):
            break
        url = API + suivante
    else:
        raise RuntimeError("historique sans fin : 200 pages lues, curseur toujours ouvert")

    try:
        with io.open(cible, encoding="utf-8") as fh:
            historique = json.load(fh)
    except (OSError, ValueError):
        historique = {"last_sync": None, "episodes": []}
    avant = len(historique["episodes"])
    connus = {e["episode_id"] for e in historique["episodes"]}
    historique["episodes"].extend(e for e in vus if e["episode_id"] not in connus)
    historique["last_sync"] = datetime.now(timezone.utc).isoformat()
    os.makedirs(os.path.dirname(cible), exist_ok=True)
    with io.open(cible, "w", encoding="utf-8") as fh:
        json.dump(historique, fh, ensure_ascii=False, indent=2)
    return avant, len(historique["episodes"])


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if sys.argv[1:] != ["connexion"]:
        print(__doc__)
        sys.exit(2)

    def _console(code, essai, essais):
        print(f"Saisis {code} sur https://www.crunchyroll.com/activate "
              f"(valable 5 minutes, essai {essai}/{essais})", flush=True)

    ok = connexion_par_code(_console)
    print("Connecte." if ok else "Aucun code valide a temps, relance la commande.")
    sys.exit(0 if ok else 1)
