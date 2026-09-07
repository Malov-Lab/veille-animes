# Mettre à jour la page

La page interroge AniList à chaque ouverture, donc **les horaires de diffusion, le
retard et les suites se mettent à jour tout seuls**. Rien à faire pour ça.

Une seule chose ne se met pas à jour seule : **la liste des séries elle-même**.
Quand tu commences une nouvelle série sur Crunchyroll, elle n'apparaît pas tant
que l'historique n'a pas été récupéré à nouveau.

## La routine hebdomadaire

**Depuis le 2026-09-07, c'est automatique.** La tâche planifiée Windows
« Veille animes » lance `outils/routine_hebdo.py` **chaque dimanche à 19h**, avec
rattrapage si le poste était éteint. Elle enchaîne l'export Crunchyroll,
l'appariement AniList des seules séries neuves, la régénération, les tests, puis
le commit et le push. Tu n'as rien à faire.

- **Le cookie `etp_rt` est le point qui cassera.** Quand il expire, la routine
  s'arrête et **t'envoie un message Telegram** disant quoi faire. Tant qu'il n'est
  pas renouvelé dans `.crunchyexporter/config.yaml`, la page reste figée.
- Elle refuse de publier une page cassée : `test_logique.js` et
  `test_rattachement.js` doivent passer, sinon rien n'est poussé.
- Trois garde-fous contre la publication d'un désastre silencieux : un historique
  vide, un historique qui a fondu de plus de 10 %, et un `anime.html`
  anormalement petit interrompent la routine.
- À la main : `.crunchyexporter/.venv/Scripts/python.exe outils/routine_hebdo.py`,
  avec `--dry-run` pour tout faire sauf publier, et `--complet` pour réinterroger
  AniList sur toutes les séries au lieu des seules nouveautés.
- Journal dans `.routine.log`, non versionné.

Pour ajouter une série tout de suite sans attendre dimanche : onglet « Ma liste »,
la recherche en haut. Elle compte immédiatement dans les suggestions.

## Relancer la récupération à la main

L'outil d'export est installé à demeure dans `.crunchyexporter/`, avec son venv.
Il n'y a plus rien à cloner : la routine s'en sert, et toi aussi.

```bash
# Tout, de l'export au push
.crunchyexporter/.venv/Scripts/python.exe outils/routine_hebdo.py

# Tout sauf le commit et le push
.crunchyexporter/.venv/Scripts/python.exe outils/routine_hebdo.py --dry-run

# En réinterrogeant AniList sur les 102 séries, et pas seulement les nouvelles
.crunchyexporter/.venv/Scripts/python.exe outils/routine_hebdo.py --complet
```

Le cookie se renouvelle dans `.crunchyexporter/config.yaml` : crunchyroll.com
connecté, F12, onglet Application, Cookies, valeur de `etp_rt`. Ce fichier n'est
jamais versionné, et se déconnecter de Crunchyroll depuis le site l'invalide.

Norton inspecte le HTTPS sur ce poste : le venv embarque `pip-system-certs`,
sans quoi toutes les requêtes échouent en « certificate verify failed ».

## Regénérer seulement la page

Si seul le gabarit change, sans retaper AniList :

```bash
.crunchyexporter/.venv/Scripts/python.exe outils/routine_hebdo.py --dry-run
```

La routine s'en charge et vérifie les tests au passage. Pour l'appel nu, il
faut un dossier de travail contenant `data/` et `page_template.html`, ce que
`routine_hebdo.py` monte pour toi dans `.crunchyexporter/`.

## Le regroupement par œuvre

AniList compte un média par saison. « Jujutsu Kaisen » et « Jujutsu Kaisen 2nd
Season » y sont deux séries distinctes, avec deux notes possibles et deux lignes
dans le top. La page ramène tout ça à une seule œuvre : la racine de la chaîne
des prequels.

- Le rattachement demande une requête AniList par série. Il est fait **une seule
  fois**, en tâche de fond après le premier affichage, puis mis en cache dans le
  navigateur (`anime_veille_roots`). Les ouvertures suivantes ne le refont pas.
- Quand deux saisons portaient chacune une note, **la meilleure est conservée** :
  le top classe des œuvres, sur le souvenir global.
- Avant la toute première fusion, l'état complet est sauvegardé dans
  `anime_veille_backup_premerge`. C'est le filet si le résultat déplaît.
- La sauvegarde manuelle passe en `v3` et emporte le rattachement, pour que
  l'autre appareil n'ait pas à refaire les requêtes. Une sauvegarde `v2` reste
  lisible.
- Seuls les liens `PREQUEL` vers un format de série (TV, TV court, ONA) sont
  suivis. `PARENT` rattacherait les spin-offs et fusionnerait des œuvres
  distinctes.
- **Le cache porte un numéro de version** (`ROOTS_VERSION`). Il est mis en cache
  pour toujours, donc une erreur s'y installait définitivement : une requête
  perdue était enregistrée comme un verdict « pas de prequel », et la série
  restait séparée de son œuvre à jamais. Un échec n'est désormais plus écrit, et
  monter le numéro fait repartir le rattachement à zéro. **À monter à chaque
  changement de règle de rattachement.**
- `outils/test_rattachement.js` couvre ces deux points, réseau simulé. Il se
  lance comme `test_logique.js`, depuis un dossier contenant `anime.html`.

Conséquence voulue : une suite non vue d'une série que tu suis **n'apparaît plus
dans « Pour toi »**, puisque ce n'est pas une découverte. Elle remonte en tête de
l'onglet « Cette saison » avec la mention « Tu suis déjà ».

### La grille de calibrage, elle, est regroupée au build

L'écran « j'ai déjà vu » ne passait pas par ce rattachement : il affichait les
300 séries les plus populaires d'AniList telles quelles, donc **sept vignettes
pour Attack on Titan et six pour My Hero Academia**. Le rattachement du
navigateur ne pouvait rien y faire, il ne connaît que les séries de ta liste.

`fetch_popular` remonte donc les chaînes côté Python avant d'écrire la grille,
avec la même règle. Résultat mesuré : **300 saisons, 215 œuvres**.

- L'identifiant de la vignette reste la racine, pour rester d'accord avec le
  `rootOf` de la page. Mais **le titre et le visuel viennent du membre le plus
  populaire de la chaîne**, et c'est indispensable : AniList déclare
  « MONSTERS: 103 Mercies Dragon Damnation », un ONA de 1999, prequel de
  ONE PIECE. Nommer par la racine faisait disparaître One Piece de la grille.
- Le verrouillage d'une vignette se teste sur la racine, sinon
  « Attack on Titan » resterait décochable alors que la Final Season est dans
  ton historique.
- **Cas résiduel connu** : « That Time I Got Reincarnated as a Slime » garde
  deux vignettes. Sa saison 2 remonte à un OVA, format que la règle ne suit pas.
  Un cas sur 300, laissé tel quel plutôt que d'élargir la règle aux OVA.

## Le piège du 403 : « API temporarily disabled »

Si un script rend `The AniList API has been temporarily disabled due to severe
stability issues`, **ce n'est pas une panne**. AniList refuse les requêtes sans
`Origin` ni `Referer`, c'est-à-dire celles qui ne viennent pas d'un navigateur.
Le message est trompeur : au même moment, l'API répond normalement au site et à
la page de veille.

Les deux scripts envoient donc ces en-têtes (`HEADERS` dans `build_page.py` et
`build_profile.py`), et traitent le 403 par un message explicite. Le `Referer`
annonce la vraie page appelante, il n'usurpe pas anilist.co.

L'API a par ailleurs de vrais trous : environ une requête sur trois part en
timeout par moments. Les retries existants absorbent ça.


## Ce qui vit où

| Donnée | Emplacement | Publié ? |
|---|---|---|
| Liste des séries, suites, suggestions de départ | `index.html` | oui |
| Notes, ajouts manuels, séries écartées | stockage local du navigateur | non |
| Historique Crunchyroll brut | `donnees-locales/` | non |
| Cookie de session | `.crunchyexporter/config.yaml` | non |
| Jeton Telegram des alertes | `.telegram.env` | non |
| Journal de la routine | `.routine.log` | non |

Sauvegarde des notes : onglet « Ma liste », bouton
« Sauvegarder / restaurer mes notes ». C'est aussi le moyen de les transférer
d'un appareil à l'autre.
