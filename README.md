# cpliege-data

Scraper quotidien du site du [Comité Provincial de Liège de basketball](https://www.cpliege.be)
(AWBB). Convertit les pages HTML (exports Excel, windows-1252) en JSON propres,
consommés par l'app iOS **CPLiege_App**.

## Fonctionnement

- `scraper/scrape.py` (Python 3, stdlib uniquement) télécharge les pages utiles
  et écrit les JSON dans `docs/api/`.
- Une GitHub Action ([.github/workflows/scrape.yml](.github/workflows/scrape.yml))
  l'exécute chaque matin après la régénération du site (~6h50 heure belge) et le
  dimanche soir, puis commite les changements.
- GitHub Pages sert `docs/` : chaque commit est donc automatiquement publié, et
  l'historique git fait office d'historique des données.

## Endpoints

| Fichier | Contenu | Source |
|---|---|---|
| `api/meta.json` | Horodatages de génération et des pages sources, erreurs | — |
| `api/clubs.json` | Les clubs (matricule, nom, couleurs, salle) | `caleclub.asp` + `lesclubs.asp` |
| `api/clubs/{matricule}.json` | Calendrier personnalisé : équipes du club et leurs matchs, matchs non programmés | `clubs/clubNNNN.asp` |
| `api/annuaire.json` | Annuaire complet (secrétaire, courriel, salle, équipes par niveau) | `lesclubs.asp` |
| `api/resultats/seniors.json` | Par division : résultats du week-end + classement | `resulsen.asp` |
| `api/resultats/jeunes.json` | Idem jeunes | `resuljeu.asp` |
| `api/resultats/natreg.json` | Idem nationale/régionale | `resulnat.asp` |
| `api/calendriers/seniors.json` | Calendrier complet par semaine et division | `calensen.asp` |
| `api/calendriers/jeunes.json` | Idem jeunes | `calenjeu.asp` |
| `api/infos.json` | Fil d'actualités | `infos.asp` |

## Formats

- Match de calendrier : `{no, modified, day, date, time, remisAu, home, away}` —
  `modified: true` = numéro affiché en rouge sur le site (calendrier modifié
  depuis la publication officielle) ; `remisAu` remplace l'heure pour un match remis.
- Résultat : `{home, away, scoreHome, scoreAway}` (scores `null` avant que le
  match soit joué).
- Classement : `{team, played, won, lost, for, against, points}`.

## Exécution locale

```bash
python3 scraper/scrape.py
```

## Limites connues

- En intersaison, les pages résultats affichent des classements à zéro et la
  « prochaine journée » est vide : c'est l'état réel du site.
- Le parsing repose sur la mise en page actuelle du site ; si elle change,
  l'Action échoue et un mail est envoyé au propriétaire du repo.
