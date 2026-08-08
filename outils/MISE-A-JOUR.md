# Mettre à jour la page

La page interroge AniList à chaque ouverture, donc **les horaires de diffusion, le
retard et les suites se mettent à jour tout seuls**. Rien à faire pour ça.

Une seule chose ne se met pas à jour seule : **la liste des séries elle-même**.
Quand tu commences une nouvelle série sur Crunchyroll, elle n'apparaît pas tant
que l'historique n'a pas été récupéré à nouveau.

Deux façons de la corriger :

- **Rapide, depuis la page** : onglet « Ma liste », la recherche en haut. Tu ajoutes
  la série à la main, elle compte immédiatement dans les suggestions.
- **Complète, en relançant la récupération** : la procédure ci-dessous.

## Relancer la récupération complète

Prérequis : Python 3.11 ou plus.

```bash
# 1. Récupérer l'outil d'export Crunchyroll
git clone https://github.com/ruflas/crunchyexporter-cli
cd crunchyexporter-cli
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements.txt

# Norton inspecte le HTTPS sur ce poste : sans ce paquet, toutes les
# requêtes échouent en « certificate verify failed ».
./.venv/Scripts/python.exe -m pip install pip-system-certs

# 2. Copier les outils et les données conservées
cp ../outils/*.py ../outils/page_template.html .
mkdir -p data && cp ../donnees-locales/*.json data/

# 3. Renseigner le cookie de session Crunchyroll dans config.yaml
#    (crunchyroll.com connecté, F12, Application, Cookies, valeur de 'etp_rt')
cp config.example.yaml config.yaml

# 4. Récupérer l'historique, puis régénérer la page
./.venv/Scripts/python.exe src/main.py -c config.yaml fetch
./.venv/Scripts/python.exe build_profile.py     # ~4 min, limite AniList
./.venv/Scripts/python.exe build_page.py        # ~2 min

# 5. Publier
cp anime.html ../index.html
cd .. && git add -A && git commit -m "Mise a jour de l'historique" && git push
```

Le cookie `etp_rt` vaut un accès au compte Crunchyroll : il reste dans
`config.yaml`, qui n'est jamais versionné. Se déconnecter de Crunchyroll depuis
le site l'invalide.

## Regénérer seulement la page

Si seul le gabarit change, sans retaper AniList :

```bash
./.venv/Scripts/python.exe build_page.py --render-only
```

## Ce qui vit où

| Donnée | Emplacement | Publié ? |
|---|---|---|
| Liste des séries, suites, suggestions de départ | `index.html` | oui |
| Notes, ajouts manuels, séries écartées | stockage local du navigateur | non |
| Historique Crunchyroll brut | `donnees-locales/` | non |
| Cookie de session | `config.yaml` | non |

Sauvegarde des notes : onglet « Ma liste », bouton
« Sauvegarder / restaurer mes notes ». C'est aussi le moyen de les transférer
d'un appareil à l'autre.
