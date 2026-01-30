import requests
import time
import re
import json
import os
import sys
import concurrent.futures
import logging
from urllib.parse import urlparse

# --- CONFIGURATION ---
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()
DRY_RUN = os.getenv('DRY_RUN', 'true').lower() == 'true'
MEALIE_URL = os.getenv('MEALIE_URL', 'http://localhost:9000').rstrip('/')
MEALIE_API_TOKEN = os.getenv('MEALIE_API_TOKEN', '')
MAX_WORKERS = int(os.getenv('CLEANER_WORKERS', 2)) # Safe Default

REJECT_FILE = "data/rejects.json"
VERIFIED_FILE = "data/verified.json"

logging.basicConfig(level=LOG_LEVEL, format='[%(levelname)s] %(message)s', handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger("cleaner")

# --- FILTERS ---
HIGH_RISK_KEYWORDS = [
    "cleaning", "storing", "freezing", "pantry", "kitchen tools",
    "review", "giveaway", "shop", "store", "product", "gift", "unboxing",
    "news", "travel", "podcast", "interview", "night cream", "face mask", 
    "skin care", "beauty", "diy", "weekly plan", "menu", "holiday guide",
    "foods to try", "things to eat", "detox water", "lose weight"
]

LISTICLE_REGEX = re.compile(r'^(\d+)\s+(best|top|must|favorite|easy|healthy|quick|ways|things)', re.IGNORECASE)

# --- STATE ---
def load_json_set(filename):
    if os.path.exists(filename):
        try:
            with open(filename, 'r') as f: return set(json.load(f))
        except: return set()
    return set()

def save_json_set(filename, data_set):
    os.makedirs(os.path.dirname(filename), exist_ok=True) # SAFETY: Auto-create dir
    with open(filename, 'w') as f: json.dump(list(data_set), f)

REJECTS = load_json_set(REJECT_FILE)
VERIFIED = load_json_set(VERIFIED_FILE)

# --- API ---
def get_recipes():
    headers = {"Authorization": f"Bearer {MEALIE_API_TOKEN}"}
    recipes, page = [], 1
    logger.info(f"Scanning library at {MEALIE_URL}...")
    while True:
        try:
            r = requests.get(f"{MEALIE_URL}/api/recipes?page={page}&perPage=1000", headers=headers, timeout=10)
            if r.status_code != 200: break
            items = r.json().get('items', [])
            if not items: break
            recipes.extend(items)
            page += 1
            print(f"   ...fetched page {page-1}", end="\r")
        except: break
    print("")
    logger.info(f"Total recipes: {len(recipes)}")
    return recipes

def delete_recipe(slug, name, reason, url=None):
    if DRY_RUN:
        logger.info(f"[DRY RUN] Would delete: '{name}' (Reason: {reason})")
        return
    
    headers = {"Authorization": f"Bearer {MEALIE_API_TOKEN}"}
    logger.info(f"[DELETE] '{name}' (Reason: {reason})")
    try:
        requests.delete(f"{MEALIE_URL}/api/recipes/{slug}", headers=headers, timeout=10)
    except Exception as e:
        logger.error(f"Error deleting {slug}: {e}")

    if url: REJECTS.add(url)
    if slug in VERIFIED: VERIFIED.remove(slug)

# --- LOGIC ---
def is_junk_content(name, url):
    if not url: return False
    try: slug = urlparse(url).path.strip("/").split("/")[-1].lower()
    except: slug = ""
    name_l = name.lower()
    for kw in HIGH_RISK_KEYWORDS:
        if kw.replace(" ", "-") in slug or kw in name_l: return True
    if LISTICLE_REGEX.match(slug) or LISTICLE_REGEX.match(name_l): return True
    if any(x in url.lower() for x in ["privacy-policy", "contact", "about-us", "login", "cart"]): return True
    return False

def validate_instructions(inst):
    if not inst: return False
    if isinstance(inst, str):
        if len(inst.strip()) == 0: return False
        if "could not detect" in inst.lower(): return False
        return True
    if isinstance(inst, list):
        if len(inst) == 0: return False
        for step in inst:
            text = step.get('text', '') if isinstance(step, dict) else str(step)
            if text and len(text.strip()) > 0: return True
    return False

def check_integrity(recipe):
    slug = recipe.get('slug')
    if slug in VERIFIED: return None
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
    except: return None

# --- MAIN ---
if __name__ == "__main__":
    logger.info("--- LIBRARY CLEANER ---")
    if DRY_RUN: logger.info("[INFO] DRY RUN ENABLED")
    
    all_recipes = get_recipes()
    if not all_recipes: sys.exit(0)

    logger.info("[PHASE 1] Junk Content Scan")
    clean_candidates = []
    for r in all_recipes:
        name = r.get('name', 'Unknown')
        url = r.get('orgURL') or r.get('originalURL') or r.get('source')
        slug = r.get('slug')
        if is_junk_content(name, url): delete_recipe(slug, name, "JUNK CONTENT", url)
        else: clean_candidates.append(r)

    logger.info(f"[PHASE 2] Integrity Scan ({len(clean_candidates)} recipes)")
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(check_integrity, r) for r in clean_candidates]
        for f in concurrent.futures.as_completed(futures):
            res = f.result()
            if res:
                if res[1] == "VERIFIED": VERIFIED.add(res[0])
                else: delete_recipe(res[0], res[1], res[2], res[3])

    if not DRY_RUN:
        save_json_set(REJECT_FILE, REJECTS)
        save_json_set(VERIFIED_FILE, VERIFIED)
        logger.info("State saved.")
    logger.info("Cycle Complete.")
