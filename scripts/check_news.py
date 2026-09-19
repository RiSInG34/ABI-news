#!/usr/bin/env python3
"""
check_news.py
--------------
Surveille le flux RSS officiel Steam d'Arena Breakout: Infinite, détecte les
nouvelles entrées, les fait reformuler/traduire en français par l'API Claude
dans le ton du site, puis les ajoute à data/news.json.

Ce script est fait pour tourner automatiquement via GitHub Actions
(voir .github/workflows/check-news.yml), mais peut aussi être lancé à la main :

    pip install -r requirements.txt
    export ANTHROPIC_API_KEY="votre-clé"
    python scripts/check_news.py
"""

import json
import os
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

STEAM_APP_ID = "2073620"  # Arena Breakout: Infinite
STEAM_RSS_URL = f"https://store.steampowered.com/feeds/news/app/{STEAM_APP_ID}/?cc=US&l=english"

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
NEWS_FILE = os.path.join(DATA_DIR, "news.json")
STATE_FILE = os.path.join(DATA_DIR, "state.json")

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"

SYSTEM_PROMPT = """Tu rédiges les actualités du site ABI News, un site de fans francophone
qui couvre Arena Breakout: Infinite (jeu développé par MoreFun Studios).

Règles impératives :
- Reformule entièrement dans tes propres mots, en français. Ne traduis jamais
  mot à mot le texte source, résume-le comme le ferait un journaliste.
- Ton neutre, factuel, précis, sans emphase promotionnelle ("incroyable",
  "épique", etc.). Phrases courtes et concrètes.
- 2 à 4 phrases pour le résumé (summary), pas plus.
- Choisis une catégorie parmi : "saison" (nouvelle saison), "maj" (mise à
  jour / patch / annonce), "lancement" (accès anticipé, sortie, gros
  relancement), "evenement" (événement temporaire, collab, Twitch drops).
- Le "tag" est un court libellé affiché en majuscules sur le site, par
  exemple "SAISON 8", "PATCH", "ÉVÉNEMENT", "ANNONCE".

Réponds UNIQUEMENT avec un objet JSON valide, sans texte autour, au format :
{
  "category": "saison|maj|lancement|evenement",
  "tag": "...",
  "title": "titre court en français, sans le nom du jeu répété inutilement",
  "summary": "résumé en français, 2 à 4 phrases"
}
"""


def log(msg: str) -> None:
    print(f"[check_news] {msg}", file=sys.stderr)


def fetch_steam_rss() -> list[dict]:
    """Récupère et parse le flux RSS officiel Steam pour ce jeu."""
    req = urllib.request.Request(STEAM_RSS_URL, headers={"User-Agent": "ABI-News-Bot/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()

    root = ET.fromstring(raw)
    items = []
    for item in root.findall(".//item"):
        guid = (item.findtext("guid") or item.findtext("link") or "").strip()
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub_date = (item.findtext("pubDate") or "").strip()
        description = (item.findtext("description") or "").strip()
        # Strip any HTML tags from the description for a cleaner prompt.
        description = re.sub(r"<[^>]+>", " ", description)
        description = re.sub(r"\s+", " ", description).strip()

        if not guid or not title:
            continue

        items.append({
            "guid": guid,
            "title": title,
            "link": link or STEAM_RSS_URL,
            "pub_date": pub_date,
            "description": description,
        })
    return items


def load_json(path: str, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: str, data) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def parse_pub_date(pub_date: str) -> str:
    """Convertit une date RFC822 (RSS) en date ISO (YYYY-MM-DD). Retombe sur
    aujourd'hui si le format est inattendu."""
    try:
        # Ex: "Wed, 16 Sep 2026 10:00:00 +0000"
        dt = datetime.strptime(pub_date[:25].strip(), "%a, %d %b %Y %H:%M:%S")
        return dt.date().isoformat()
    except Exception:
        return datetime.now(timezone.utc).date().isoformat()


def french_date_label(iso_date: str) -> str:
    months = ["JANV.", "FÉVR.", "MARS", "AVRIL", "MAI", "JUIN",
              "JUIL.", "AOÛT", "SEPT.", "OCT.", "NOV.", "DÉC."]
    try:
        dt = datetime.fromisoformat(iso_date)
        return f"{dt.day} {months[dt.month - 1]}\n{dt.year}"
    except Exception:
        return iso_date


def call_claude(title: str, description: str) -> dict:
    """Appelle l'API Claude pour reformuler l'actu en français."""
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY n'est pas défini.")

    user_content = f"Titre source (anglais) : {title}\n\nContenu source (anglais) : {description}"

    payload = {
        "model": ANTHROPIC_MODEL,
        "max_tokens": 600,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_content}],
    }

    req = urllib.request.Request(
        ANTHROPIC_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read())

    text_blocks = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
    text = "\n".join(text_blocks).strip()

    # Le modèle peut parfois entourer le JSON de ```json ... ``` — on nettoie.
    text = re.sub(r"^```json\s*|\s*```$", "", text.strip())

    return json.loads(text)


def main() -> None:
    log(f"Vérification du flux Steam : {STEAM_RSS_URL}")
    rss_items = fetch_steam_rss()
    log(f"{len(rss_items)} entrées trouvées dans le flux Steam.")

    state = load_json(STATE_FILE, {"seen_guids": []})
    seen = set(state.get("seen_guids", []))

    news = load_json(NEWS_FILE, [])
    existing_ids = {item["id"] for item in news}

    new_count = 0
    for entry in rss_items:
        if entry["guid"] in seen:
            continue

        log(f"Nouvelle entrée détectée : {entry['title']}")

        try:
            translated = call_claude(entry["title"], entry["description"])
        except Exception as exc:  # noqa: BLE001
            log(f"  Échec de la traduction, entrée ignorée pour l'instant : {exc}")
            continue

        iso_date = parse_pub_date(entry["pub_date"])
        slug = re.sub(r"[^a-z0-9]+", "-", entry["title"].lower()).strip("-")[:40]
        item_id = f"{iso_date}-{slug}" or entry["guid"]

        if item_id in existing_ids:
            item_id = f"{item_id}-{entry['guid'][-6:]}"

        news_item = {
            "id": item_id,
            "date": iso_date,
            "date_label": french_date_label(iso_date),
            "category": translated.get("category", "maj"),
            "tag": translated.get("tag", "MISE À JOUR"),
            "title": translated.get("title", entry["title"]),
            "summary": translated.get("summary", ""),
            "source_label": "annonce officielle Steam",
            "source_url": entry["link"],
        }

        news.insert(0, news_item)
        existing_ids.add(item_id)
        seen.add(entry["guid"])
        new_count += 1

    if new_count == 0:
        log("Aucune nouveauté. Rien à publier.")
        return

    news.sort(key=lambda x: x["date"], reverse=True)
    save_json(NEWS_FILE, news)
    save_json(STATE_FILE, {"seen_guids": sorted(seen)})
    log(f"{new_count} nouvelle(s) actu(s) ajoutée(s) à data/news.json.")


if __name__ == "__main__":
    main()
