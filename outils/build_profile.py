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
                API, json={"query": QUERY, "variables": {"s": title}}, timeout=25
            )
            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", 60))
                print(f"    [limite atteinte, pause {wait}s]")
                time.sleep(wait + 1)
                continue
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


def main():
    series = summarize_history(load_history())
    print(f"{len(series)} series a faire correspondre.\n")

    matched, unmatched = [], []
    for i, entry in enumerate(series, 1):
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


if __name__ == "__main__":
    main()
