"""Fait correspondre les series de l'historique Crunchyroll avec AniList.

Sortie : data/profile.json, la matiere premiere de la page de veille.
"""
import json
import sys
import time
import collections
import requests

sys.stdout.reconfigure(encoding="utf-8")

API = "https://graphql.anilist.co"

# AniList repond 403 aux requetes sans Origin ni Referer, sous couvert d'une
# « API temporairement desactivee ». Le message trompe : c'est un filtre contre
# les scripts, et le navigateur passe sans rien faire. Voir build_page.py.
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"),
    "Origin": "https://malov-lab.github.io",
    "Referer": "https://malov-lab.github.io/veille-animes/",
    "Accept": "application/json",
}

QUERY = """
query ($s: String) {
  Media(search: $s, type: ANIME) {
    id
    title { romaji english native }
    status
    episodes
    season
    seasonYear
    genres
    averageScore
    siteUrl
    coverImage { large }
    nextAiringEpisode { episode airingAt timeUntilAiring }
    relations {
      edges {
        relationType
        node {
          id type status season seasonYear format
          title { romaji english }
          startDate { year month }
          siteUrl
        }
      }
    }
  }
}
"""


def load_history(path="data/history.json"):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)["episodes"]


def summarize_history(episodes):
    """Une entree par serie : nb d'episodes vus, dernier vu, episode max."""
    by_series = collections.defaultdict(list)
    for ep in episodes:
        by_series[ep["series_title"]].append(ep)

    out = []
    for title, eps in by_series.items():
        eps.sort(key=lambda e: e["watched_at"])
        out.append({
            "cr_title": title,
            "watched_episodes": len(eps),
            "last_watched": eps[-1]["watched_at"],
            "max_episode_seen": max((e.get("episode_number") or 0) for e in eps),
            "last_season_seen": eps[-1].get("season_number"),
        })
    out.sort(key=lambda s: s["last_watched"], reverse=True)
    return out


def query_anilist(title, retries=3):
    for attempt in range(retries):
        try:
            resp = requests.post(
                API, json={"query": QUERY, "variables": {"s": title}},
                headers=HEADERS, timeout=25,
            )
            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", 60))
                print(f"    [limite atteinte, pause {wait}s]")
                time.sleep(wait + 1)
                continue
            if resp.status_code == 403:
                print("    [403 : requete refusee, verifier Origin et Referer]")
                return None
            resp.raise_for_status()
            return resp.json().get("data", {}).get("Media")
        except requests.RequestException as exc:
            if attempt == retries - 1:
                print(f"    [echec reseau] {exc}")
                return None
            time.sleep(3)
    return None


def extract_sequels(media):
    """Suites et adaptations a venir, seulement ce qui n'est pas deja sorti."""
    sequels = []
    for edge in media.get("relations", {}).get("edges", []):
        node = edge["node"]
        if node.get("type") != "ANIME":
            continue
        if edge["relationType"] not in ("SEQUEL", "SIDE_STORY", "ALTERNATIVE"):
            continue
        sequels.append({
            "relation": edge["relationType"],
            "id": node["id"],
            "title": node["title"].get("english") or node["title"].get("romaji"),
            "status": node.get("status"),
            "format": node.get("format"),
            "season": node.get("season"),
            "year": (node.get("startDate") or {}).get("year") or node.get("seasonYear"),
            "url": node.get("siteUrl"),
        })
    return sequels


def charger_profil_existant(path="data/profile.json"):
    """Les appariements deja faits, indexes par titre Crunchyroll."""
    try:
        with open(path, encoding="utf-8") as fh:
            return {s["cr_title"]: s for s in json.load(fh).get("series", [])}
    except (OSError, ValueError, KeyError):
        return {}


def main():
    # --incremental : n'interroge AniList que pour les series jamais appariees.
    # Une serie deja trouvee ne change pas d'identite ; ses compteurs de
    # visionnage, eux, sont relus de l'historique a chaque passage. Ce qui est
    # volatil (prochain episode, statut) est de toute facon redemande en direct
    # par la page. Passe de ~100 requetes a quelques-unes.
    incremental = "--incremental" in sys.argv
    connus = charger_profil_existant() if incremental else {}

    series = summarize_history(load_history())
    if incremental:
        neuves = [s for s in series if s["cr_title"] not in connus]
        print(f"{len(series)} series, dont {len(neuves)} a interroger "
              f"({len(series) - len(neuves)} deja appariees).\n")
    else:
        print(f"{len(series)} series a faire correspondre.\n")

    matched, unmatched = [], []
    for i, entry in enumerate(series, 1):
        deja = connus.get(entry["cr_title"])
        if deja and deja.get("anilist_id"):
            # Les compteurs viennent de l'historique frais, le reste du cache.
            fusion = {**deja, **entry}
            matched.append(fusion)
            continue
        media = query_anilist(entry["cr_title"])
        if not media:
            unmatched.append(entry["cr_title"])
            print(f"{i:>3}/{len(series)}  NON TROUVE  {entry['cr_title']}")
        else:
            entry.update({
                "anilist_id": media["id"],
                "title_romaji": media["title"].get("romaji"),
                "title_english": media["title"].get("english"),
                "status": media.get("status"),
                "episodes_total": media.get("episodes"),
                "genres": media.get("genres", []),
                "score": media.get("averageScore"),
                "cover": (media.get("coverImage") or {}).get("large"),
                "url": media.get("siteUrl"),
                "next_airing": media.get("nextAiringEpisode"),
                "sequels": extract_sequels(media),
            })
            matched.append(entry)
            flag = "  <-- SUITE A VENIR" if any(
                s["status"] == "NOT_YET_RELEASED" for s in entry["sequels"]
            ) else ""
            print(f"{i:>3}/{len(series)}  ok  {entry['title_romaji'][:45]}{flag}")
        time.sleep(2.1)  # limite AniList : 30 requetes par minute

    profile = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "matched_count": len(matched),
        "unmatched": unmatched,
        "series": matched,
    }
    with open("data/profile.json", "w", encoding="utf-8") as fh:
        json.dump(profile, fh, ensure_ascii=False, indent=2)

    print(f"\n=== RESULTAT ===")
    print(f"Correspondances : {len(matched)}/{len(series)}")
    print(f"Non trouvees    : {len(unmatched)}")
    for title in unmatched:
        print(f"  - {title}")

    # Filet : en incremental, un profil qui maigrit signale un incident (fichier
    # d'historique tronque, export partiel). Mieux vaut le dire que l'ecrire.
    if incremental and connus and len(matched) < len(connus):
        print(f"\nATTENTION : {len(connus)} series appariees avant, "
              f"{len(matched)} apres. L'historique a-t-il ete tronque ?")


if __name__ == "__main__":
    main()
