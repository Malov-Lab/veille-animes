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
PAGE_URL = "https://malov-lab.github.io/veille-animes/"

# AniList refuse par 403 les requetes sans Origin ni Referer, avec le message
# « The AniList API has been temporarily disabled due to severe stability
# issues. » Le message trompe : l'API repond normalement des que la requete se
# presente comme une page web, ce que le navigateur fait tout seul. Seuls ces
# scripts avaient besoin d'etre corriges. Le Referer annonce la vraie page
# appelante, il n'usurpe pas anilist.co.
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"),
    "Origin": "https://malov-lab.github.io",
    "Referer": PAGE_URL,
    "Accept": "application/json",
}

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
#
# AniList compte un media par saison : le top 300 brut sort sept vignettes pour
# « Attack on Titan » et six pour « My Hero Academia ». On ramene chaque saison
# a son oeuvre avant d'ecrire la grille, avec la meme regle que la page : on ne
# suit que PREQUEL et seulement vers un format de serie. Les relations arrivent
# dans la requete existante, ce regroupement ne coute donc aucun appel de plus
# sur les 300, seulement le rattrapage des racines absentes du lot.
Q_POPULAR = """
query ($page: Int) {
  Page(page: $page, perPage: 50) {
    media(type: ANIME, sort: POPULARITY_DESC, isAdult: false) {
      id popularity
      title { romaji english }
      coverImage { medium }
      relations { edges { relationType node { id type format } } }
    }
  }
}
"""

# Alignes sur la page : voir SERIES_FORMATS et MAX_CHAIN dans page_template.html.
SERIES_FORMATS = {"TV", "TV_SHORT", "ONA"}
MAX_CHAIN = 8


def gql(query, variables, retries=3):
    for attempt in range(retries):
        try:
            r = requests.post(API, json={"query": query, "variables": variables},
                              headers=HEADERS, timeout=25)
            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After", 60))
                print(f"    [limite, pause {wait}s]")
                time.sleep(wait + 1)
                continue
            if r.status_code == 403:
                # Ne pas laisser ce cas se confondre avec une panne : c'est le
                # filtre anti-script d'AniList, donc HEADERS est en cause.
                print("    [403 : requete refusee, verifier Origin et Referer]")
                return None
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


def _relation_query(ids):
    """Plusieurs medias en une requete, par alias : meme principe que la page."""
    parts = "\n".join(
        f"""r{i}: Media(id: {mid}) {{
      id popularity
      title {{ romaji english }}
      coverImage {{ medium }}
      relations {{ edges {{ relationType node {{ id type format }} }} }}
    }}"""
        for i, mid in enumerate(ids)
    )
    return "query { %s }" % parts


def _absorb(media, known):
    """Retient le prequel serie d'un media, ou None s'il ouvre sa chaine."""
    edges = (media.get("relations") or {}).get("edges", [])
    prequel = next(
        (
            e["node"]["id"]
            for e in edges
            if e.get("relationType") == "PREQUEL"
            and (e.get("node") or {}).get("type") == "ANIME"
            and (e.get("node") or {}).get("format") in SERIES_FORMATS
        ),
        None,
    )
    known[media["id"]] = {
        "prequel": prequel,
        "title": media["title"].get("english") or media["title"].get("romaji"),
        "cover": (media.get("coverImage") or {}).get("medium"),
        "popularity": media.get("popularity") or 0,
    }


def _resolve_roots(known):
    """Complete `known` jusqu'aux racines, couche par couche.

    La saison 1 d'une oeuvre est presque toujours plus populaire que ses suites
    et se trouve deja dans le lot, mais pas toujours : ce rattrapage va chercher
    les racines qui manquent, par paquets de 8 comme le fait le navigateur.
    """
    for _ in range(MAX_CHAIN):
        missing = sorted({
            k["prequel"] for k in known.values()
            if k["prequel"] and k["prequel"] not in known
        })
        if not missing:
            return
        print(f"  rattrapage de {len(missing)} racine(s) hors du lot")
        for i in range(0, len(missing), 8):
            chunk = missing[i:i + 8]
            data = gql(_relation_query(chunk), {}) or {}
            time.sleep(2.1)
            for k, mid in enumerate(chunk):
                media = data.get(f"r{k}")
                if media:
                    _absorb(media, known)
                else:
                    # Marquer l'echec plutot que de le laisser manquant : sans
                    # ca, la boucle redemanderait le meme id a chaque couche.
                    known[mid] = {"prequel": None, "title": None,
                                  "cover": None, "popularity": 0}


def _chain_root(start, known):
    """Remonte la chaine des prequels. Le garde-fou est le cycle, pas la longueur."""
    seen = {start}
    cur = start
    while True:
        prequel = (known.get(cur) or {}).get("prequel")
        if not prequel or prequel in seen:
            return cur
        cur = prequel
        seen.add(cur)


def fetch_popular(pages=6):
    """Les oeuvres les plus connues, pour la grille de calibrage 'deja vu'."""
    print(f"\n=== GRILLE DE CALIBRAGE ===")
    known, order = {}, []
    for page in range(1, pages + 1):
        data = gql(Q_POPULAR, {"page": page})
        time.sleep(2.1)
        if not data:
            break
        for m in data["Page"]["media"]:
            _absorb(m, known)
            order.append(m["id"])
        print(f"  page {page} : {len(order)} saisons cumulees")

    _resolve_roots(known)

    # Une vignette par oeuvre. L'identifiant reste la racine, pour rester
    # d'accord avec le rootOf de la page, mais le titre et le visuel viennent
    # du membre le plus populaire de la chaine.
    #
    # Sans ca la grille perdrait ses reperes : AniList declare « MONSTERS: 103
    # Mercies Dragon Damnation », un ONA de 1999, prequel de ONE PIECE, et
    # « Nekomonogatari Black » prequel de Bakemonogatari. Remonter jusqu'au bout
    # de la chaine est bon pour regrouper, mauvais pour nommer.
    groups = collections.defaultdict(list)
    for mid in known:
        groups[_chain_root(mid, known)].append(mid)

    wanted = {_chain_root(mid, known) for mid in order}
    out = []
    for root, members in groups.items():
        if root not in wanted:
            continue  # racine ramenee par le rattrapage d'une autre chaine
        nommables = [m for m in members if known[m].get("title")]
        if not nommables:
            continue
        face = max(nommables, key=lambda m: known[m]["popularity"])
        out.append({
            "id": root,
            "title": known[face]["title"],
            "cover": known[face]["cover"],
            "_pop": known[face]["popularity"],
        })

    out.sort(key=lambda o: -o["_pop"])
    for o in out:
        del o["_pop"]

    print(f"  {len(order)} saisons -> {len(out)} oeuvres "
          f"({len(order) - len(out)} regroupees)")
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
