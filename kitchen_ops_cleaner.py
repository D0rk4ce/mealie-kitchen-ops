"""KitchenOps Library Cleaner — Removes junk content and broken recipes.

Scans the Mealie library for non-recipe content (product pages, listicles,
beauty tips) and recipes with empty/broken instructions, then deletes them.
"""

import concurrent.futures
import json
import logging
import os
import re
import sys
from typing import Optional
from urllib.parse import urlparse

import requests

# --- LOGGING ---
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()
logging.basicConfig(
    level=LOG_LEVEL,
    format='[%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("cleaner")

# --- CONFIGURATION ---
DRY_RUN: bool = os.getenv('DRY_RUN', 'true').lower() == 'true'
MEALIE_URL: str = os.getenv('MEALIE_URL', 'http://localhost:9000').rstrip('/')
MEALIE_API_TOKEN: str = os.getenv('MEALIE_API_TOKEN', '')
MAX_WORKERS: int = int(os.getenv('CLEANER_WORKERS', '2'))

REJECT_FILE: str = "data/rejects.json"
VERIFIED_FILE: str = "data/verified.json"

# --- FILTERS ---
HIGH_RISK_KEYWORDS: list[str] = [
    "cleaning", "storing", "freezing", "pantry", "kitchen tools",
    "review", "giveaway", "shop", "store", "product", "gift", "unboxing",
    "news", "travel", "podcast", "interview", "night cream", "face mask",
    "skin care", "beauty", "diy", "weekly plan", "menu", "holiday guide",
    "foods to try", "things to eat", "detox water", "lose weight"
]

LISTICLE_REGEX = re.compile(
    r'^(\d+)\s+(best|top|must|favorite|easy|healthy|quick|ways|things)',
    re.IGNORECASE
)


# --- STATE ---
def load_json_set(filename: str) -> set[str]:
    """Load a set of strings from a JSON file, or return an empty set on failure."""
    if os.path.exists(filename):
        try:
            with open(filename, 'r') as f:
                return set(json.load(f))
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Could not load {filename}: {e}")
            return set()
    return set()


def save_json_set(filename: str, data_set: set[str]) -> None:
    """Persist a set of strings to a JSON file."""
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    try:
        with open(filename, 'w') as f:
            json.dump(list(data_set), f)
    except IOError as e:
        logger.error(f"Could not save {filename}: {e}")


REJECTS: set[str] = load_json_set(REJECT_FILE)
VERIFIED: set[str] = load_json_set(VERIFIED_FILE)


# --- API ---
def get_recipes() -> list[dict]:
    """Fetch the full recipe index from the Mealie API."""
    headers = {"Authorization": f"Bearer {MEALIE_API_TOKEN}"}
    recipes: list[dict] = []
    page = 1
    logger.info(f"Scanning library at {MEALIE_URL}...")
    while True:
        try:
            r = requests.get(
                f"{MEALIE_URL}/api/recipes?page={page}&perPage=1000",
                headers=headers, timeout=10
            )
            if r.status_code != 200:
                break
            items = r.json().get('items', [])
            if not items:
                break
            recipes.extend(items)
            page += 1
            print(f"   ...fetched page {page - 1}", end="\r")
        except requests.RequestException as e:
            logger.warning(f"Recipe fetch failed on page {page}: {e}")
            break
    print("")
    logger.info(f"Total recipes: {len(recipes)}")
    return recipes


def delete_recipe(slug: str, name: str, reason: str, url: Optional[str] = None) -> None:
    """Delete a recipe by slug. In dry-run mode, only logs intent."""
    if DRY_RUN:
        logger.info(f"[DRY RUN] Would delete: '{name}' (Reason: {reason})")
        return

    headers = {"Authorization": f"Bearer {MEALIE_API_TOKEN}"}
    logger.info(f"[DELETE] '{name}' (Reason: {reason})")
    try:
        requests.delete(f"{MEALIE_URL}/api/recipes/{slug}", headers=headers, timeout=10)
    except requests.RequestException as e:
        logger.error(f"Error deleting {slug}: {e}")

    if url:
        REJECTS.add(url)
    VERIFIED.discard(slug)


# --- LOGIC ---
def is_junk_content(name: str, url: Optional[str]) -> bool:
    """Determine whether a recipe is likely non-recipe content (junk).

    Checks the recipe name and source URL against known junk keywords,
    listicle patterns, and non-recipe URL paths.
    """
    if not url:
        return False
    try:
        slug = urlparse(url).path.strip("/").split("/")[-1].lower()
    except (ValueError, IndexError):
        slug = ""
    name_l = name.lower()
    for kw in HIGH_RISK_KEYWORDS:
        if kw.replace(" ", "-") in slug or kw in name_l:
            return True
    if LISTICLE_REGEX.match(slug) or LISTICLE_REGEX.match(name_l):
        return True
    if any(x in url.lower() for x in ["privacy-policy", "contact", "about-us", "login", "cart"]):
        return True
    return False


def validate_instructions(inst: object) -> bool:
    """Check whether recipe instructions are present and meaningful.

    Returns ``False`` for empty, None, or  "could not detect" instructions.
    """
    if not inst:
        return False
    if isinstance(inst, str):
        if len(inst.strip()) == 0:
            return False
        if "could not detect" in inst.lower():
            return False
        return True
    if isinstance(inst, list):
        if len(inst) == 0:
            return False
        for step in inst:
            text = step.get('text', '') if isinstance(step, dict) else str(step)
            if text and len(text.strip()) > 0:
                return True
    return False


def check_integrity(recipe: dict) -> Optional[tuple]:
    """Verify that a recipe has valid instructions.

    Returns a tuple for action, or ``None`` if already verified / on error.
    Result format:
    - ``(slug, "VERIFIED")`` — recipe passed inspection
    - ``(slug, name, reason, url)`` — recipe should be deleted
    """
    slug = recipe.get('slug')
    if slug in VERIFIED:
        return None
    name = recipe.get('name')
    url = recipe.get('orgURL') or recipe.get('originalURL') or recipe.get('source')

    try:
        headers = {"Authorization": f"Bearer {MEALIE_API_TOKEN}"}
        r = requests.get(f"{MEALIE_URL}/api/recipes/{slug}", headers=headers, timeout=10)
        if r.status_code == 200:
            inst = r.json().get('recipeInstructions')
            if not validate_instructions(inst):
                return (slug, name, "Empty/Broken Instructions", url)
        return (slug, "VERIFIED")
    except requests.RequestException as e:
        logger.warning(f"Integrity check failed for {slug}: {e}")
        return None


# --- MAIN ---
if __name__ == "__main__":
    logger.info("=" * 50)
    logger.info("  KITCHENOPS LIBRARY CLEANER")
    logger.info("=" * 50)
    logger.info(f"  Mealie   : {MEALIE_URL}")
    logger.info(f"  Workers  : {MAX_WORKERS}")
    logger.info(f"  Dry Run  : {DRY_RUN}")
    logger.info("=" * 50)

    if DRY_RUN:
        logger.info("[INFO] DRY RUN ENABLED")

    if not MEALIE_API_TOKEN:
        logger.error("MEALIE_API_TOKEN is not set. Cannot proceed.")
        sys.exit(1)

    all_recipes = get_recipes()
    if not all_recipes:
        logger.info("No recipes found. Nothing to do.")
        sys.exit(0)

    logger.info("[PHASE 1] Junk Content Scan")
    clean_candidates: list[dict] = []
    junk_count = 0
    for r in all_recipes:
        name = r.get('name', 'Unknown')
        url = r.get('orgURL') or r.get('originalURL') or r.get('source')
        slug = r.get('slug')
        if is_junk_content(name, url):
            delete_recipe(slug, name, "JUNK CONTENT", url)
            junk_count += 1
        else:
            clean_candidates.append(r)
    logger.info(f"   Junk detected: {junk_count}")

    logger.info(f"[PHASE 2] Integrity Scan ({len(clean_candidates)} recipes)")
    verified_count = 0
    broken_count = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(check_integrity, r) for r in clean_candidates]
        for f in concurrent.futures.as_completed(futures):
            try:
                res = f.result()
            except Exception as e:
                logger.warning(f"Worker error: {e}")
                continue
            if res:
                if res[1] == "VERIFIED":
                    VERIFIED.add(res[0])
                    verified_count += 1
                else:
                    delete_recipe(res[0], res[1], res[2], res[3])
                    broken_count += 1

    if not DRY_RUN:
        save_json_set(REJECT_FILE, REJECTS)
        save_json_set(VERIFIED_FILE, VERIFIED)
        logger.info("State saved.")

    logger.info(f"Cycle Complete. Verified: {verified_count}, Broken: {broken_count}, Junk: {junk_count}")
