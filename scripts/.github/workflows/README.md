ABI News
Site de fans, non officiel, qui recense en français les actualités d'Arena
Breakout: Infinite (MoreFun Studios).
Structure
`index.html` — le site. Charge les actus depuis `data/news.json`.
`data/news.json` — les actualités affichées sur le site.
`data/state.json` — mémoire interne du robot (ne pas modifier à la main).
`scripts/check_news.py` — surveille le flux RSS Steam du jeu, traduit et
résume les nouveautés en français via l'API Claude, et met à jour
`data/news.json`.
`.github/workflows/check-news.yml` — fait tourner le script automatiquement
toutes les heures via GitHub Actions.
Mise en route
Sur console.anthropic.com, créez une clé API.
Dans ce dépôt GitHub : Settings → Secrets and variables → Actions → New
repository secret. Nom : `ANTHROPIC_API_KEY`. Valeur : la clé obtenue.
Reliez ce dépôt à Vercel ou Netlify
(import depuis GitHub, aucune configuration nécessaire pour un site
statique). Chaque mise à jour de `data/news.json` redéploiera le site
automatiquement.
Une fois le domaine acheté, reliez-le au projet Vercel/Netlify dans ses
réglages.
Pour tester le robot sans attendre une heure : onglet Actions du
dépôt → Vérifier les news ABI → Run workflow.
À savoir
Le premier passage du robot peut retomber sur des actus déjà couvertes
manuellement dans `data/news.json` (avec une formulation légèrement
différente). Si ça arrive, supprimez simplement le doublon dans
`data/news.json`.
Le robot ne source que le flux Steam officiel. C'est volontaire : c'est la
source la plus stable et la moins susceptible de casser avec le temps.
