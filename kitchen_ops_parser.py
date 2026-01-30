import concurrent.futures
import json
import os
import signal
import sys
import threading
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# --- CONFIGURATION ---
MEALIE_URL = os.getenv("MEALIE_URL", "http://localhost:9000")
API_TOKEN = os.getenv("MEALIE_API_TOKEN", "")
# Default: 2 Workers (Public Friendly)
MAX_WORKERS = int(os.getenv("PARSER_WORKERS", 2)) 
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"
CONFIDENCE_THRESHOLD = 0.85

HISTORY_FILE = "parse_history.json"
SAVE_INTERVAL = 20

# --- STATE ---
FOOD_CACHE = {}
UNIT_CACHE = {}
HISTORY_SET = set()
CACHE_LOCK = threading.Lock()
HISTORY_LOCK = threading.Lock()
PRINT_LOCK = threading.Lock()
thread_local = threading.local()

def signal_handler(sig, frame):
    with PRINT_LOCK: print("\n[INFO] Interrupt received. Saving history...")
    save_history()
    sys.exit(0)
signal.signal(signal.SIGINT, signal_handler)

def get_session():
    if not hasattr(thread_local, "session"):
        thread_local.session = requests.Session()
        thread_local.session.headers.update({
            "Authorization": f"Bearer {API_TOKEN}",
            "Content-Type": "application/json"
        })
        retries = Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
        thread_local.session.mount('http://', HTTPAdapter(max_retries=retries))
    return thread_local.session

def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r') as f: return set(json.load(f))
        except: return set()
    return set()

def save_history():
    with HISTORY_LOCK:
        try:
            with open(HISTORY_FILE, 'w') as f: json.dump(list(HISTORY_SET), f)
        except: pass

def prime_cache():
    print("[INFO] Initializing Cache...")
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {API_TOKEN}"})
    page = 1
    while True:
        try:
            r = session.get(f"{MEALIE_URL}/api/units?page={page}&perPage=2000", timeout=10)
            if r.status_code != 200: break
            items = r.json().get('items', [])
            if not items: break
            with CACHE_LOCK:
                for item in items:
                    UNIT_CACHE[item['name'].lower().strip()] = item['id']
                    if item.get('pluralName'): UNIT_CACHE[item['pluralName'].lower().strip()] = item['id']
            page += 1
        except: break
        
    page = 1
    count = 0
    while True:
        try:
            r = session.get(f"{MEALIE_URL}/api/foods?page={page}&perPage=2000", timeout=10)
            if r.status_code != 200: break
            items = r.json().get('items', [])
            if not items: break
            with CACHE_LOCK:
                for item in items: FOOD_CACHE[item['name'].lower().strip()] = item['id']
            count += len(items)
            print(f"   ...loaded {count} foods", end="\r")
            page += 1
        except: break
    print(f"\n[INFO] Cache Ready ({len(FOOD_CACHE)} foods, {len(UNIT_CACHE)} units).")

def get_all_recipes():
    print("[INFO] Fetching recipe index...")
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {API_TOKEN}"})
    recipes = []
    page = 1
    while True:
        try:
            r = session.get(f"{MEALIE_URL}/api/recipes?page={page}&perPage=2000", timeout=15)
            if r.status_code != 200: break
            items = r.json().get('items', [])
            if not items: break
            recipes.extend(items)
            print(f"   ...scanned page {page}", end="\r")
            page += 1
        except: break
    print(f"\n[INFO] Index complete. Total recipes: {len(recipes)}")
    return recipes

def get_id_for_food(name):
    if not name: return None
    key = name.lower().strip()
    with CACHE_LOCK:
        if key in FOOD_CACHE: return FOOD_CACHE[key]
    # No auto-create to prevent spamming DB with bad data
    return None

def process_recipe(slug):
    session = get_session()
    try:
        r = session.get(f"{MEALIE_URL}/api/recipes/{slug}", timeout=15)
        if r.status_code != 200: return False
        full_recipe = r.json()
    except: return False

    raw_ingredients = full_recipe.get("recipeIngredient", [])
    to_parse = []
    to_parse_indices = []
    clean_ingredients = []
    
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

    if not to_parse: return True

    # 1. Attempt Local NLP
    try:
        r_nlp = session.post(f"{MEALIE_URL}/api/parser/ingredients", 
                             json={"ingredients": to_parse, "parser": "nlp", "language": "en"}, timeout=30)
        
        nlp_results = r_nlp.json() if r_nlp.status_code == 200 else []
        retry_sub_indices = []
        retry_texts = []
        
        for idx, res in enumerate(nlp_results):
            score = res.get('confidence', {}).get('average', 0)
            actual_index = to_parse_indices[idx]
            if score < CONFIDENCE_THRESHOLD:
                retry_sub_indices.append(actual_index)
                retry_texts.append(to_parse[idx])
            else:
                clean_ingredients[actual_index] = res

        # 2. Attempt AI Escalation (If configured)
        if retry_texts:
            try:
                r_ai = session.post(f"{MEALIE_URL}/api/parser/ingredients", 
                                    json={"ingredients": retry_texts, "parser": "openai", "language": "en"}, timeout=45)
                if r_ai.status_code == 200:
                    ai_results = r_ai.json()
                    for ai_idx, ai_res in enumerate(ai_results):
                        clean_ingredients[retry_sub_indices[ai_idx]] = ai_res
                else:
                    # Silent failure: User likely doesn't have AI configured. Keep original text.
                    pass
            except: pass

    except: return False

    # Reconstruct
    final_list = []
    raw_idx = 0
    for item in clean_ingredients:
        if item is None:
            final_list.append(raw_ingredients[raw_idx])
        else:
            target = item.get("ingredient", item)
            for bad_key in ['referenceId', 'id', 'recipeId', 'stepId', 'labelId']:
                if bad_key in target: del target[bad_key]
            
            # Link IDs
            if target.get('food') and target['food'].get('name'):
                fid = get_id_for_food(target['food']['name'])
                if fid: target['food']['id'] = fid
            
            final_list.append(target)
        raw_idx += 1

    full_recipe["recipeIngredient"] = final_list
    
    if DRY_RUN:
        with PRINT_LOCK: print(f"[DRY RUN] Would update: {slug}")
        return True
        
    try:
        r_update = session.put(f"{MEALIE_URL}/api/recipes/{slug}", json=full_recipe, timeout=15)
        if r_update.status_code == 200:
            with PRINT_LOCK: print(f"[OK] Parsed: {slug}")
            return True
    except: return False
    return False

if __name__ == "__main__":
    print(f"--- BATCH PARSER (Workers: {MAX_WORKERS}) ---")
    if DRY_RUN: print("[INFO] DRY RUN ENABLED: No changes will be made.")
    prime_cache()
    HISTORY_SET = load_history()
    candidates = get_all_recipes()
    todo = [r for r in candidates if r['slug'] not in HISTORY_SET]
    print(f"[INFO] Queue: {len(todo)} recipes")
    
    count = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_slug = {executor.submit(process_recipe, r['slug']): r['slug'] for r in todo}
        for future in concurrent.futures.as_completed(future_to_slug):
            try:
                if future.result():
                    with HISTORY_LOCK: HISTORY_SET.add(future_to_slug[future])
                    count += 1
                    if count % SAVE_INTERVAL == 0: save_history()
            except: pass
            
    save_history()
    print("\nBatch Parse Complete.")
