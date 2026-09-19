#!/usr/bin/env python3
"""
check_tarkov.py
----------------
Surveille les quêtes du marchand Prapor via l'API publique tarkov.dev,
détecte les nouvelles entrées (ou celles jamais traduites), les fait
reformuler en français par l'API Claude, puis met à jour
data/tarkov-quests.json.

Usage :
    pip install -r requirements.txt   # aucune dépendance externe en fait
    export ANTHROPIC_API_KEY="votre-clé"
    python scripts/check_tarkov.py
"""

import json
import os
import re
import sys
import urllib.error
import urllib.request

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
QUESTS_FILE = os.path.join(DATA_DIR, "tarkov-quests.json")
STATE_FILE = os.path.join(DATA_DIR, "tarkov-state.json")

TARKOV_API_URL = "https://api.tarkov.dev/graphql"
TRADER_NAME = "Prapor"

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"

GRAPHQL_QUERY = """
{
  tasks {
    id
    name
    normalizedName
    trader { name }
    minPlayerLevel
    objectives { description }
  }
}
"""

SYSTEM_PROMPT = """Tu rédiges la base de quêtes en français du site ABI News, pour la
partie consacrée à Escape from Tarkov (Battlestate Games).

Règles impératives :
- Traduis le nom de la quête en français, dans un style naturel (pas mot à
  mot au point d'être maladroit).
- Reformule chaque objectif en français, une phrase courte et actionnable
  par objectif (\"Éliminer 5 Scavs sur Customs\", pas de traduction littérale
  bancale).
- Résume les récompenses en une seule ligne courte. Si les données fournies
  sont limitées (juste un niveau requis), dis-le honnêtement plutôt que
  d'inventer des objets ou montants — par exemple : "Niveau requis : 6 ·
  récompenses détaillées à confirmer en jeu".
- Ne garde PAS le texte anglais dans les objectifs ou récompenses.

Réponds UNIQUEMENT avec un objet JSON valide, sans texte autour :
{
  "name_fr": "...",
  "objectives": ["...", "..."],
  "reward": "..."
}
"""


def log(msg: str) -> None:
    print(f"[check_tarkov] {msg}", file=sys.stderr)


def fetch_prapor_tasks() -> list[dict]:
    payload = json.dumps({"query": GRAPHQL_QUERY}).encode("utf-8")
    req = urllib.request.Request(
        TARKOV_API_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "ABI-News-Tarkov-Bot/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        log(f"Erreur HTTP {exc.code} de l'API tarkov.dev. Réponse : {body}")
        raise

    if "errors" in data:
        log(f"L'API a renvoyé des erreurs GraphQL : {data['errors']}")

    tasks = data.get("data", {}).get("tasks", []) or []
    return [t for t in tasks if t.get("trader", {}).get("name") == TRADER_NAME]


def load_json(path: str, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: str, data) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def slugify(name: str) -> str:
    s = name.lower()
    s = re.sub(r"[''\".,:!?()\[\]]", "", s)
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def summarize_rewards_en(task: dict) -> str:
    level = task.get("minPlayerLevel")
    if level:
        return f"Requires player level {level}. Detailed rewards not fetched via API — verify in-game."
    return "Detailed rewards not fetched via API — verify in-game."


def call_claude(name_en: str, objectives_en: list[str], rewards_en: str) -> dict:
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY n'est pas défini.")

    user_content = (
        f"Quest name (English): {name_en}\n\n"
        f"Objectives (English): {'; '.join(objectives_en) if objectives_en else 'none listed'}\n\n"
        f"Rewards (raw data): {rewards_en}"
    )

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
    text = re.sub(r"^```json\s*|\s*```$", "", text.strip())
    return json.loads(text)


def main() -> None:
    log("Récupération des quêtes Prapor depuis api.tarkov.dev...")
    tasks = fetch_prapor_tasks()
    log(f"{len(tasks)} quêtes Prapor trouvées côté API.")

    state = load_json(STATE_FILE, {"seen_ids": []})
    seen = set(state.get("seen_ids", []))

    quests = load_json(QUESTS_FILE, [])
    existing_by_id = {q["id"]: q for q in quests}

    new_count = 0
    for task in tasks:
        task_id = task.get("id") or slugify(task.get("normalizedName", task["name"]))
        slug = slugify(task.get("normalizedName") or task["name"])

        if task_id in seen:
            continue

        # Si une quête du même nom existe déjà (nos 69 quêtes de départ),
        # on ne la retraduit pas — on marque juste son ID API comme vu.
        if slug in existing_by_id:
            seen.add(task_id)
            continue

        log(f"Nouvelle quête détectée : {task['name']}")

        objectives_en = [o.get("description", "") for o in task.get("objectives", []) if o.get("description")]
        rewards_en = summarize_rewards_en(task)

        try:
            translated = call_claude(task["name"], objectives_en, rewards_en)
        except Exception as exc:  # noqa: BLE001
            log(f"  Échec de traduction, ignorée pour l'instant : {exc}")
            continue

        new_quest = {
            "id": slug,
            "name_fr": translated.get("name_fr", task["name"]),
            "name_en": task["name"],
            "objectives": translated.get("objectives", []),
            "reward": translated.get("reward", ""),
        }

        quests.append(new_quest)
        existing_by_id[slug] = new_quest
        seen.add(task_id)
        new_count += 1

    if new_count == 0:
        log("Aucune nouvelle quête. Rien à publier.")
        return

    save_json(QUESTS_FILE, quests)
    save_json(STATE_FILE, {"seen_ids": sorted(seen)})
    log(f"{new_count} nouvelle(s) quête(s) ajoutée(s) à data/tarkov-quests.json.")


if __name__ == "__main__":
    main()
