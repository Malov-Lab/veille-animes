"""Rattrape les series manquantes, calcule les recommandations, genere la page.

Sortie : anime.html, page autonome a ouvrir dans un navigateur.
"""
import json
import re
import sys
import time
import collections
import requests

sys.stdout.reconfigure(encoding="utf-8")

API = "https://graphql.anilist.co"

# Titres que la recherche automatique ne retrouve pas : le libelle Crunchyroll
# est un titre francais ou porte un suffixe de version.
ALIASES = {
    "Moi, quand je me réincarne en Slime": "Tensei shitara Slime Datta Ken",
    "Tsugai - Daemons of the Shadow Realm": "Yomi no Tsugai",
    "Villageois LVL 999": "Level 999 Villager",
}

Q_MEDIA = """
query ($s: String) {
  Media(search: $s, type: ANIME) {
    id title { romaji english } status episodes genres averageScore siteUrl
    coverImage { large }
    nextAiringEpisode { episode airingAt timeUntilAiring }
    relations { edges { relationType node {
      id type status season seasonYear format
      title { romaji english } startDate { year } siteUrl
    } } }
  }
}
"""

Q_RECO = """
query ($id: Int) {
  Media(id: $id) {
    title { romaji english }
    recommendations(sort: RATING_DESC, perPage: 15) {
      nodes { rating mediaRecommendation {
        id title { romaji english } genres averageScore episodes format status
        popularity siteUrl coverImage { large } startDate { year }
      } }
    }
  }
}
"""

# Grille de calibrage : les series les plus connues, celles qu'il a le plus de
# chances d'avoir deja vues ailleurs que sur Crunchyroll.
Q_POPULAR = """
query ($page: Int) {
  Page(page: $page, perPage: 50) {
    media(type: ANIME, sort: POPULARITY_DESC, isAdult: false) {
      id popularity
      title { romaji english }
      coverImage { medium }
    }
  }
}
"""


def gql(query, variables, retries=3):
    for attempt in range(retries):
        try:
            r = requests.post(API, json={"query": query, "variables": variables}, timeout=25)
            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After", 60))
                print(f"    [limite, pause {wait}s]")
                time.sleep(wait + 1)
                continue
            r.raise_for_status()
            return r.json().get("data")
        except requests.RequestException as exc:
            if attempt == retries - 1:
                print(f"    [echec] {exc}")
                return None
            time.sleep(3)
    return None


def clean_title(title):
    """Retire les suffixes de version qui parasitent la recherche."""
    return re.sub(r"\s*\((VOSTA|VOSTFR|VF|Dub|Sub)\)\s*$", "", title, flags=re.I).strip()


def extract_sequels(media):
    out = []
    for edge in media.get("relations", {}).get("edges", []):
        node = edge["node"]
        if node.get("type") != "ANIME":
            continue
        if edge["relationType"] not in ("SEQUEL", "SIDE_STORY", "ALTERNATIVE"):
            continue
        out.append({
            "relation": edge["relationType"],
            "id": node["id"],
            "title": node["title"].get("english") or node["title"].get("romaji"),
            "status": node.get("status"),
            "format": node.get("format"),
            "year": (node.get("startDate") or {}).get("year") or node.get("seasonYear"),
            "url": node.get("siteUrl"),
        })
    return out


def rescue_unmatched(profile, history_summary):
    """Deuxieme passage sur les series non retrouvees."""
    if not profile["unmatched"]:
        return
    print(f"=== RATTRAPAGE DE {len(profile['unmatched'])} SERIES ===")
    still_missing = []
    for cr_title in profile["unmatched"]:
        search = ALIASES.get(cr_title) or clean_title(cr_title)
        data = gql(Q_MEDIA, {"s": search})
        media = (data or {}).get("Media")
        if not media:
            still_missing.append(cr_title)
            print(f"  toujours introuvable : {cr_title}")
            time.sleep(2.1)
            continue
        entry = dict(history_summary[cr_title])
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
        profile["series"].append(entry)
        print(f"  retrouve : {cr_title}  ->  {entry['title_romaji']}")
        time.sleep(2.1)

    profile["unmatched"] = still_missing
    profile["matched_count"] = len(profile["series"])


def fetch_popular(pages=6):
    """Les series les plus connues, pour la grille de calibrage 'deja vu'."""
    print(f"\n=== GRILLE DE CALIBRAGE ===")
    out = []
    for page in range(1, pages + 1):
        data = gql(Q_POPULAR, {"page": page})
        time.sleep(2.1)
        if not data:
            break
        for m in data["Page"]["media"]:
            out.append({
                "id": m["id"],
                "title": m["title"].get("english") or m["title"].get("romaji"),
                "cover": (m.get("coverImage") or {}).get("medium"),
            })
        print(f"  page {page} : {len(out)} series cumulees")
    return out


def build_recommendations(profile, top_n=40, keep=60):
    """Agrege les recommandations AniList, en penalisant les evidences.

    Quentin a vu beaucoup d'animes hors Crunchyroll : les blockbusters qui
    remontent naturellement sont donc presque tous des faux positifs. On
    divise le score par la popularite et on favorise les series recentes.
    """
    import math

    seen_ids = {s["anilist_id"] for s in profile["series"]}
    this_year = time.gmtime().tm_year

    # Base elargie : les series ou il a le plus investi ET les plus recentes,
    # pour ne pas ne tirer que sur ses cinq gros shonen.
    by_volume = sorted(profile["series"], key=lambda s: s["watched_episodes"], reverse=True)[:25]
    by_recency = sorted(profile["series"], key=lambda s: s["last_watched"], reverse=True)[:25]
    ranked, seen_src = [], set()
    for s in by_volume + by_recency:
        if s["anilist_id"] not in seen_src:
            seen_src.add(s["anilist_id"])
            ranked.append(s)
    ranked = ranked[:top_n]

    scores = collections.defaultdict(float)
    info, because = {}, {}

    print(f"\n=== RECOMMANDATIONS (base sur {len(ranked)} series) ===")
    for source in ranked:
        data = gql(Q_RECO, {"id": source["anilist_id"]})
        time.sleep(2.1)
        if not data or not data.get("Media"):
            continue
        src_title = source["title_english"] or source["title_romaji"]
        for node in data["Media"]["recommendations"]["nodes"]:
            rec = node.get("mediaRecommendation")
            if not rec or rec["id"] in seen_ids:
                continue
            if rec.get("format") in ("MUSIC", "SPECIAL"):
                continue

            raw = max(node.get("rating") or 0, 0) + 1
            # Penalite de notoriete : plus c'est massivement populaire, plus il
            # est probable qu'il l'ait deja vu ailleurs.
            popularity = rec.get("popularity") or 1000
            damp = math.log10(max(popularity, 100))
            # Bonus de fraicheur : ce qui est sorti recemment, il a pu le rater.
            year = (rec.get("startDate") or {}).get("year") or 2000
            freshness = 1.6 if year >= this_year - 2 else (1.2 if year >= this_year - 5 else 1.0)

            scores[rec["id"]] += (raw / damp) * freshness
            info[rec["id"]] = rec
            because.setdefault(rec["id"], src_title)
        print(f"  lu : {src_title}")

    top = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:keep]
    recos = []
    for rec_id, _ in top:
        rec = info[rec_id]
        recos.append({
            "id": rec_id,
            "title": rec["title"].get("english") or rec["title"].get("romaji"),
            "genres": rec.get("genres", []),
            "score": rec.get("averageScore"),
            "episodes": rec.get("episodes"),
            "popularity": rec.get("popularity"),
            "year": (rec.get("startDate") or {}).get("year"),
            "cover": (rec.get("coverImage") or {}).get("large"),
            "url": rec.get("siteUrl"),
            "because": because[rec_id],
        })
    print(f"  -> {len(recos)} recommandations retenues")
    return recos


def render_page(profile, recos, popular):
    with open("page_template.html", encoding="utf-8") as fh:
        tpl = fh.read()

    slim = {
        "generated_at": profile["generated_at"],
        "series": [
            {
                "anilist_id": s["anilist_id"],
                "title_romaji": s.get("title_romaji"),
                "title_english": s.get("title_english"),
                "cover": s.get("cover"),
                "genres": s.get("genres", []),
                "max_episode_seen": s.get("max_episode_seen"),
                "watched_episodes": s.get("watched_episodes"),
                "last_watched": s.get("last_watched"),
                "sequels": s.get("sequels", []),
            }
            for s in profile["series"]
        ],
    }

    html = tpl.replace("/*__PROFILE__*/", json.dumps(slim, ensure_ascii=False))
    html = html.replace("/*__RECOS__*/", json.dumps(recos, ensure_ascii=False))
    html = html.replace("/*__POPULAR__*/", json.dumps(popular, ensure_ascii=False))
    with open("anime.html", "w", encoding="utf-8") as fh:
        fh.write(html)
    return len(html)


def main():
    # --render-only : regenere la page a partir des donnees deja collectees,
    # sans retaper AniList. Utile quand seul le gabarit change.
    if "--render-only" in sys.argv:
        with open("data/profile.json", encoding="utf-8") as fh:
            profile = json.load(fh)
        with open("data/recos.json", encoding="utf-8") as fh:
            recos = json.load(fh)
        with open("data/popular.json", encoding="utf-8") as fh:
            popular = json.load(fh)
        size = render_page(profile, recos, popular)
        print(f"Page regeneree : anime.html ({size // 1024} ko)")
        print(f"  {len(profile['series'])} series, {len(recos)} recos, {len(popular)} au calibrage")
        return

    with open("data/profile.json", encoding="utf-8") as fh:
        profile = json.load(fh)
    with open("data/history.json", encoding="utf-8") as fh:
        episodes = json.load(fh)["episodes"]

    by_series = collections.defaultdict(list)
    for ep in episodes:
        by_series[ep["series_title"]].append(ep)
    summary = {}
    for title, eps in by_series.items():
        eps.sort(key=lambda e: e["watched_at"])
        summary[title] = {
            "cr_title": title,
            "watched_episodes": len(eps),
            "last_watched": eps[-1]["watched_at"],
            "max_episode_seen": max((e.get("episode_number") or 0) for e in eps),
            "last_season_seen": eps[-1].get("season_number"),
        }

    rescue_unmatched(profile, summary)
    recos = build_recommendations(profile)
    popular = fetch_popular()

    with open("data/profile.json", "w", encoding="utf-8") as fh:
        json.dump(profile, fh, ensure_ascii=False, indent=2)
    with open("data/recos.json", "w", encoding="utf-8") as fh:
        json.dump(recos, fh, ensure_ascii=False, indent=2)
    with open("data/popular.json", "w", encoding="utf-8") as fh:
        json.dump(popular, fh, ensure_ascii=False, indent=2)

    size = render_page(profile, recos, popular)
    print(f"\n=== PAGE GENEREE ===")
    print(f"anime.html  ({size // 1024} ko)")
    print(f"Series      : {len(profile['series'])}")
    print(f"Recos       : {len(recos)}")
    print(f"Calibrage   : {len(popular)} series a cocher")
    print(f"Introuvables: {profile['unmatched'] or 'aucune'}")


if __name__ == "__main__":
    main()
