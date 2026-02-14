"""KitchenOps Batch Parser — Fixes unparsed recipe ingredients via Mealie's API.

Uses Mealie's local NLP parser first, then escalates to OpenAI for
low-confidence results.  Multi-threaded for throughput.
"""

import concurrent.futures
import json
import logging
import os
import signal
import sys
import threading
from typing import Any, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# --- LOGGING ---
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()
logging.basicConfig(
    level=LOG_LEVEL,
    format='[%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("parser")

# --- CONFIGURATION ---
MEALIE_URL: str = os.getenv("MEALIE_URL", "http://localhost:9000").rstrip("/")
API_TOKEN: str = os.getenv("MEALIE_API_TOKEN", "")
MAX_WORKERS: int = int(os.getenv("PARSER_WORKERS", "2"))
DRY_RUN: bool = os.getenv("DRY_RUN", "true").lower() == "true"
CONFIDENCE_THRESHOLD: float = 0.85

HISTORY_FILE: str = "parse_history.json"
SAVE_INTERVAL: int = 20

# --- STATE ---
FOOD_CACHE: dict[str, str] = {}
UNIT_CACHE: dict[str, str] = {}
HISTORY_SET: set[str] = set()
CACHE_LOCK = threading.Lock()
HISTORY_LOCK = threading.Lock()
PRINT_LOCK = threading.Lock()
thread_local = threading.local()


def signal_handler(sig: int, frame: Any) -> None:
    """Handle SIGINT gracefully by saving history before exit."""
    logger.info("Interrupt received. Saving history...")
    save_history()
    sys.exit(0)


signal.signal(signal.SIGINT, signal_handler)


def get_session() -> requests.Session:
    """Return a thread-local HTTP session with retry logic."""
    if not hasattr(thread_local, "session"):
        thread_local.session = requests.Session()
        thread_local.session.headers.update({
            "Authorization": f"Bearer {API_TOKEN}",
            "Content-Type": "application/json"
        })
        retries = Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
        thread_local.session.mount("http://", HTTPAdapter(max_retries=retries))
        thread_local.session.mount("https://", HTTPAdapter(max_retries=retries))
    return thread_local.session


def load_history() -> set[str]:
    """Load previously parsed recipe slugs from the history file."""
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r") as f:
                return set(json.load(f))
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Could not load history file: {e}")
            return set()
    return set()


def save_history() -> None:
    """Persist the current history set to disk."""
    with HISTORY_LOCK:
        try:
            with open(HISTORY_FILE, "w") as f:
                json.dump(list(HISTORY_SET), f)
        except IOError as e:
            logger.error(f"Could not save history: {e}")


def prime_cache() -> None:
    """Pre-load the food and unit caches from the Mealie API."""
    logger.info("Initializing cache...")
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {API_TOKEN}"})

    # --- Units ---
    page = 1
    while True:
        try:
            r = session.get(f"{MEALIE_URL}/api/units?page={page}&perPage=2000", timeout=10)
            if r.status_code != 200:
                break
            items = r.json().get("items", [])
            if not items:
                break
            with CACHE_LOCK:
                for item in items:
                    UNIT_CACHE[item["name"].lower().strip()] = item["id"]
                    plural = item.get("pluralName")
                    if plural:
                        UNIT_CACHE[plural.lower().strip()] = item["id"]
            page += 1
        except requests.RequestException as e:
            logger.warning(f"Unit cache fetch failed on page {page}: {e}")
            break

    # --- Foods ---
    page = 1
    count = 0
    while True:
        try:
            r = session.get(f"{MEALIE_URL}/api/foods?page={page}&perPage=2000", timeout=10)
            if r.status_code != 200:
                break
            items = r.json().get("items", [])
            if not items:
                break
            with CACHE_LOCK:
                for item in items:
                    FOOD_CACHE[item["name"].lower().strip()] = item["id"]
            count += len(items)
            print(f"   ...loaded {count} foods", end="\r")
            page += 1
        except requests.RequestException as e:
            logger.warning(f"Food cache fetch failed on page {page}: {e}")
            break

    logger.info(f"Cache ready ({len(FOOD_CACHE)} foods, {len(UNIT_CACHE)} units).")


def get_all_recipes() -> list[dict]:
    """Fetch the full recipe index from the Mealie API."""
    logger.info("Fetching recipe index...")
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {API_TOKEN}"})
    recipes: list[dict] = []
    page = 1
    while True:
        try:
            r = session.get(f"{MEALIE_URL}/api/recipes?page={page}&perPage=2000", timeout=15)
            if r.status_code != 200:
                break
            items = r.json().get("items", [])
            if not items:
                break
            recipes.extend(items)
            print(f"   ...scanned page {page}", end="\r")
            page += 1
        except requests.RequestException as e:
            logger.warning(f"Recipe index fetch failed on page {page}: {e}")
            break
    logger.info(f"Index complete. Total recipes: {len(recipes)}")
    return recipes


def get_id_for_food(name: str) -> Optional[str]:
    """Look up a food ID from the cache. Returns ``None`` on miss."""
    if not name:
        return None
    key = name.lower().strip()
    with CACHE_LOCK:
        return FOOD_CACHE.get(key)


def process_recipe(slug: str) -> bool:
    """Parse a single recipe's ingredients via NLP (with AI fallback).

    Returns ``True`` on success, ``False`` on failure.
    """
    session = get_session()
    try:
        r = session.get(f"{MEALIE_URL}/api/recipes/{slug}", timeout=15)
        if r.status_code != 200:
            return False
        full_recipe = r.json()
    except requests.RequestException:
        return False

    raw_ingredients = full_recipe.get("recipeIngredient", [])
    to_parse: list[str] = []
    to_parse_indices: list[int] = []
    clean_ingredients: list[Optional[dict]] = []

    for i, item in enumerate(raw_ingredients):
        if isinstance(item, str):
            to_parse.append(item)
            to_parse_indices.append(i)
            clean_ingredients.append(None)
        elif isinstance(item, dict) and item.get("note") and not item.get("unit") and not item.get("food"):
            to_parse.append(item["note"])
            to_parse_indices.append(i)
            clean_ingredients.append(None)
        else:
            clean_ingredients.append(item)

    if not to_parse:
        return True

    # 1. Attempt Local NLP
    try:
        r_nlp = session.post(
            f"{MEALIE_URL}/api/parser/ingredients",
            json={"ingredients": to_parse, "parser": "nlp", "language": "en"},
            timeout=30
        )
        nlp_results = r_nlp.json() if r_nlp.status_code == 200 else []
        retry_sub_indices: list[int] = []
        retry_texts: list[str] = []

        for idx, res in enumerate(nlp_results):
            score = res.get("confidence", {}).get("average", 0)
            actual_index = to_parse_indices[idx]
            if score < CONFIDENCE_THRESHOLD:
                retry_sub_indices.append(actual_index)
                retry_texts.append(to_parse[idx])
            else:
                clean_ingredients[actual_index] = res

        # 2. Attempt AI Escalation (if configured)
        if retry_texts:
            try:
                r_ai = session.post(
                    f"{MEALIE_URL}/api/parser/ingredients",
                    json={"ingredients": retry_texts, "parser": "openai", "language": "en"},
                    timeout=45
                )
                if r_ai.status_code == 200:
                    ai_results = r_ai.json()
                    for ai_idx, ai_res in enumerate(ai_results):
                        clean_ingredients[retry_sub_indices[ai_idx]] = ai_res
                # Silent failure: User likely doesn't have AI configured.
            except requests.RequestException:
                pass

    except requests.RequestException:
        return False

    # Reconstruct the ingredient list
    final_list: list[Any] = []
    for i, item in enumerate(clean_ingredients):
        if item is None:
            # Keep the original raw ingredient
            final_list.append(raw_ingredients[i])
        else:
            target = item.get("ingredient", item)
            for bad_key in ("referenceId", "id", "recipeId", "stepId", "labelId"):
                target.pop(bad_key, None)

            # Link food IDs from cache
            food = target.get("food")
            if food and food.get("name"):
                fid = get_id_for_food(food["name"])
                if fid:
                    food["id"] = fid

            final_list.append(target)

    full_recipe["recipeIngredient"] = final_list

    if DRY_RUN:
        with PRINT_LOCK:
            logger.info(f"[DRY RUN] Would update: {slug}")
        return True

    try:
        r_update = session.put(f"{MEALIE_URL}/api/recipes/{slug}", json=full_recipe, timeout=15)
        if r_update.status_code == 200:
            with PRINT_LOCK:
                logger.info(f"[OK] Parsed: {slug}")
            return True
    except requests.RequestException:
        return False
    return False


if __name__ == "__main__":
    logger.info("=" * 50)
    logger.info("  KITCHENOPS BATCH PARSER")
    logger.info("=" * 50)
    logger.info(f"  Mealie   : {MEALIE_URL}")
    logger.info(f"  Workers  : {MAX_WORKERS}")
    logger.info(f"  Dry Run  : {DRY_RUN}")
    logger.info("=" * 50)

    if DRY_RUN:
        logger.info("[INFO] DRY RUN ENABLED: No changes will be made.")

    if not API_TOKEN:
        logger.error("MEALIE_API_TOKEN is not set. Cannot proceed.")
        sys.exit(1)

    prime_cache()
    HISTORY_SET = load_history()
    candidates = get_all_recipes()
    todo = [r for r in candidates if r["slug"] not in HISTORY_SET]
    logger.info(f"Queue: {len(todo)} recipes to parse ({len(candidates) - len(todo)} already done)")

    count = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_slug = {executor.submit(process_recipe, r["slug"]): r["slug"] for r in todo}
        for future in concurrent.futures.as_completed(future_to_slug):
            slug = future_to_slug[future]
            try:
                if future.result():
                    with HISTORY_LOCK:
                        HISTORY_SET.add(slug)
                    count += 1
                    if count % SAVE_INTERVAL == 0:
                        save_history()
            except Exception as e:
                logger.warning(f"Worker error for {slug}: {e}")

    save_history()
    logger.info(f"\nBatch Parse Complete. Processed {count}/{len(todo)} recipes.")
