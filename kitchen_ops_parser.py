"""KitchenOps Batch Parser — fixes unparsed recipe ingredients via Mealie's NLP API."""

import concurrent.futures, json, logging, os, signal, sys, threading, time
from datetime import datetime
from typing import Any, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TimeRemainingColumn, TimeElapsedColumn
from rich.theme import Theme

# Rich Console Setup
custom_theme = Theme({
    "info": "cyan",
    "warning": "yellow",
    "error": "bold red",
    "success": "bold green"
})
console = Console(theme=custom_theme)

LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()
logging.basicConfig(level=LOG_LEVEL, format='%(message)s', handlers=[logging.NullHandler()])
logger = logging.getLogger("parser")

# File logging
os.makedirs("logs", exist_ok=True)
_fh = logging.FileHandler(f"logs/parser_{datetime.now().strftime('%Y-%m-%d')}.log")
_fh.setFormatter(logging.Formatter('%(asctime)s | %(message)s', datefmt='%H:%M:%S'))
logger.addHandler(_fh)
logger.setLevel(logging.INFO)

MEALIE_URL: str = os.getenv("MEALIE_URL", "http://localhost:9000").rstrip("/")
API_TOKEN: str = os.getenv("MEALIE_API_TOKEN", "")
MAX_WORKERS: int = int(os.getenv("PARSER_WORKERS", "8"))
DRY_RUN: bool = os.getenv("DRY_RUN", "true").lower() == "true"
CONFIDENCE_THRESHOLD: float = 0.85
HISTORY_FILE: str = "parse_history.json"
SAVE_INTERVAL: int = 20

# Database config (optional — enables fast startup)
DB_TYPE: str = os.getenv('DB_TYPE', '').lower().strip()
SQLITE_PATH: str = os.getenv('SQLITE_PATH', '/app/data/mealie.db')
PG_DB: str = os.getenv('POSTGRES_DB', 'mealie')
PG_USER: str = os.getenv('POSTGRES_USER', 'mealie')
PG_PASS: str = os.getenv('POSTGRES_PASSWORD', 'mealie')
PG_HOST: str = os.getenv('POSTGRES_HOST', 'postgres')
PG_PORT: str = os.getenv('POSTGRES_PORT', '5432')

FOOD_CACHE: dict[str, str] = {}
UNIT_CACHE: dict[str, str] = {}
HISTORY_SET: set[str] = set()
CACHE_LOCK = threading.Lock()
HISTORY_LOCK = threading.Lock()
thread_local = threading.local()


SHUTDOWN_REQUESTED = False

def signal_handler(sig: int, frame: Any) -> None:
    global SHUTDOWN_REQUESTED
    SHUTDOWN_REQUESTED = True
    console.print("\n[warning]Interrupt received. Stopping threads cleanly...[/warning]")
    save_history()

signal.signal(signal.SIGINT, signal_handler)


def get_session() -> requests.Session:
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
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r") as f:
                return set(json.load(f))
        except (json.JSONDecodeError, IOError) as e:
            console.print(f"[warning]Could not load history file: {e}[/warning]")
            return set()
    return set()


def save_history() -> None:
    with HISTORY_LOCK:
        try:
            with open(HISTORY_FILE, "w") as f:
                json.dump(list(HISTORY_SET), f)
        except IOError as e:
            console.print(f"[error]Could not save history: {e}[/error]")


def connect_db() -> Optional[object]:
    """Try to connect to the database (Postgres or SQLite). Returns connection or None."""
    if not DB_TYPE:
        return None

    try:
        if DB_TYPE == "postgres":
            import psycopg2
            conn = psycopg2.connect(dbname=PG_DB, user=PG_USER, password=PG_PASS, host=PG_HOST, port=PG_PORT)
            conn.autocommit = True
            return conn
            
        elif DB_TYPE == "sqlite":
            import sqlite3
            if not os.path.exists(SQLITE_PATH):
                console.print(f"[warning]SQLite DB not found at {SQLITE_PATH}[/warning]")
                console.print(f"  ❌ File not found. Check your volume mount in docker-compose.yml.")
                console.print(f"     Expected: /app/data/mealie.db (inside container)")
                return None
            
            # Diagnostic permissions check
            if not os.access(SQLITE_PATH, os.R_OK):
                console.print(f"  ❌ File is not readable. Check permissions.")
                # SELinux / Ownership Hint
                console.print(f"  💡 Hint: If you use Podman/Fedora, you may need the ':z' suffix on your volume.")
            
            # Connect in Read-Only mode if possible (URI) specific to sqlite3
            # But standard connect is fine as we only SELECT.
            conn = sqlite3.connect(f"file:{SQLITE_PATH}?mode=ro", uri=True)
            return conn
            
    except Exception as e:
        console.print(f"[warning]DB connection failed ({DB_TYPE}), falling back to API: {e}[/warning]")
    return None


def prime_cache_db(conn) -> bool:
    """Prime the cache using direct SQL queries (Fast). Returns True on success."""
    try:
        cursor = conn.cursor()
        with CACHE_LOCK:
            # Fetch Foods - Verified table name from tagger is 'ingredient_foods'
            # We skip 'units' here because table name is uncertain (maybe 'ingredient_units'?) 
            # and it's small enough (~700 items) to fetch via API quickly.
            cursor.execute("SELECT id, name FROM ingredient_foods")
            for fid, name in cursor.fetchall():
                FOOD_CACHE[name.lower().strip()] = fid
        
        console.print(f"[info]DB Cache ready: {len(FOOD_CACHE)} foods loaded from SQL.[/info]")
        return True
    except Exception as e:
        console.print(f"[warning]DB Cache Prime failed ({e}), falling back to API...[/warning]")
        return False


def prime_cache() -> None:
    with console.status("[bold green]Prime Cache: Fetching foods & units...[/bold green]", spinner="dots"):
        session = requests.Session()
        session.headers.update({"Authorization": f"Bearer {API_TOKEN}"})

        # Units
        page = 1
        while True:
            try:
                r = session.get(f"{MEALIE_URL}/api/units?page={page}&perPage=2000", timeout=10)
                if r.status_code != 200:
                    break
                data = r.json()
                items = data.get("items", [])
                if not items:
                    break
                with CACHE_LOCK:
                    for item in items:
                        UNIT_CACHE[item["name"].lower().strip()] = item["id"]
                        if item.get("pluralName"):
                            UNIT_CACHE[item["pluralName"].lower().strip()] = item["id"]
                page += 1
            except requests.RequestException:
                break

        # Foods
        page = 1
        while True:
            try:
                r = session.get(f"{MEALIE_URL}/api/foods?page={page}&perPage=2000", timeout=10)
                if r.status_code != 200:
                    break
                data = r.json()
                items = data.get("items", [])
                if not items:
                    break
                with CACHE_LOCK:
                    for item in items:
                        FOOD_CACHE[item["name"].lower().strip()] = item["id"]
                page += 1
            except requests.RequestException:
                break

    console.print(f"[info]Cache ready: {len(FOOD_CACHE)} foods, {len(UNIT_CACHE)} units.[/info]")


def get_recipes_needing_parsing_db(conn) -> Optional[list[dict]]:
    """
    Fetch only recipes that actually have unparsed ingredients.
    This replaces downloading 100k recipes just to filter them in Python.
    Returns list of dicts with 'slug' key, or None if failed.
    """
    try:
        cursor = conn.cursor()
        console.print("[bold green]DB Scan: Finding recipes with unparsed ingredients...[/bold green]")
        
        # We need recipes where at least one ingredient is loose text (no food_id AND no unit_id AND not a note)
        # Note checking is tricky in SQL across dialects, but generally if it has no food_id it's a candidate.
        # However, purely note ingredients effectively have no food_id too.
        # A safer bet for "unparsed" is usually just missing food_id, as standard lines get parsed into food/unit.
        
        # Tries 'recipes_ingredients' (standard per tagger code)
        query = """
            SELECT DISTINCT r.slug 
            FROM recipes r
            JOIN recipes_ingredients ri ON r.id = ri.recipe_id
            WHERE ri.food_id IS NULL
        """
        cursor.execute(query)
        rows = cursor.fetchall()
        
        # We return a list of dicts to match what get_all_recipes returns (conceptually)
        # though process_recipe only needs the slug.
        return [{"slug": r[0]} for r in rows]
        
    except Exception as e:
        console.print(f"[warning]DB Candidate Scan failed ({e}), falling back to API...[/warning]")
        return None


def get_all_recipes() -> list[dict]:
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {API_TOKEN}"})
    recipes: list[dict] = []
    page = 1
    
    with console.status("[bold green]Fetching recipe index...[/bold green]", spinner="dots"):
        while True:
            try:
                r = session.get(f"{MEALIE_URL}/api/recipes?page={page}&perPage=2000", timeout=15)
                if r.status_code != 200:
                    break
                items = r.json().get("items", [])
                if not items:
                    break
                recipes.extend(items)
                page += 1
            except requests.RequestException as e:
                console.print(f"[warning]Index fetch failed page {page}: {e}[/warning]")
                break
    return recipes


def get_id_for_food(name: str) -> Optional[str]:
    if not name:
        return None
    with CACHE_LOCK:
        return FOOD_CACHE.get(name.lower().strip())


def process_recipe(slug: str) -> bool:
    if SHUTDOWN_REQUESTED:
        return False
        
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

    # NLP pass
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

        # AI escalation
        if retry_texts:
            try:
                r_ai = session.post(
                    f"{MEALIE_URL}/api/parser/ingredients",
                    json={"ingredients": retry_texts, "parser": "openai", "language": "en"},
                    timeout=45
                )
                if r_ai.status_code == 200:
                    for ai_idx, ai_res in enumerate(r_ai.json()):
                        clean_ingredients[retry_sub_indices[ai_idx]] = ai_res
            except requests.RequestException:
                pass

    except requests.RequestException:
        return False

    # Reconstruct
    final_list: list[Any] = []
    for i, item in enumerate(clean_ingredients):
        if item is None:
            final_list.append(raw_ingredients[i])
        else:
            target = item.get("ingredient", item)
            for bad_key in ("referenceId", "id", "recipeId", "stepId", "labelId"):
                target.pop(bad_key, None)
            food = target.get("food")
            if food and food.get("name"):
                fid = get_id_for_food(food["name"])
                if fid:
                    food["id"] = fid
            final_list.append(target)

    full_recipe["recipeIngredient"] = final_list

    if DRY_RUN:
        return True

    try:
        r_update = session.put(f"{MEALIE_URL}/api/recipes/{slug}", json=full_recipe, timeout=15)
        return r_update.status_code == 200
    except requests.RequestException:
        return False


def format_elapsed(seconds: float) -> str:
    s = int(seconds)
    if s >= 86400:
        return f"{s // 86400}d {(s % 86400) // 3600}h {(s % 3600) // 60}m"
    if s >= 3600:
        return f"{s // 3600}h {(s % 3600) // 60}m"
    if s >= 60:
        return f"{s // 60}m {s % 60}s"
    return f"{s}s"


if __name__ == "__main__":
    console.rule("[bold cyan]KitchenOps Batch Parser[/bold cyan]")
    console.print(f"Mealie: [underline]{MEALIE_URL}[/underline] | Workers: {MAX_WORKERS} | Dry Run: {DRY_RUN}")
    logger.info(f"Started | Mealie: {MEALIE_URL} | Workers: {MAX_WORKERS} | Dry Run: {DRY_RUN}")

    if not API_TOKEN:
        console.print("[error]MEALIE_API_TOKEN is not set. Cannot proceed.[/error]")
        sys.exit(1)

    start_time = time.time()
    
    # DB Acceleration Strategy
    db_conn = connect_db()
    candidates = None
    
    if db_conn:
        console.print(f"[info]DB Connection established ({DB_TYPE}). Accelerated mode active.[/info]")
        
        # 1. Prime Cache via DB (Foods only)
        if prime_cache_db(db_conn):
            # Manually fetch units via API since we skipped them in DB
            with console.status("[bold green]Fetching units via API...[/bold green]", spinner="dots"):
                 # Mini-routine to just fetch units
                session = requests.Session()
                session.headers.update({"Authorization": f"Bearer {API_TOKEN}"})
                page = 1
                while True:
                    try:
                        r = session.get(f"{MEALIE_URL}/api/units?page={page}&perPage=2000", timeout=10)
                        if r.status_code != 200: break
                        items = r.json().get("items", [])
                        if not items: break
                        with CACHE_LOCK:
                            for item in items:
                                UNIT_CACHE[item["name"].lower().strip()] = item["id"]
                                if item.get("pluralName"):
                                    UNIT_CACHE[item["pluralName"].lower().strip()] = item["id"]
                        page += 1
                    except requests.RequestException:
                        break
        else:
            prime_cache() # Full API fallback if food fetch failed
            
        # 2. Get Candidates via DB
        candidates = get_recipes_needing_parsing_db(db_conn)
        db_conn.close()
    
    # Fallback if DB failed or not configured
    if candidates is None:
        if not db_conn:
            prime_cache()
            
        candidates = get_all_recipes()

    HISTORY_SET = load_history()
    todo = [r for r in candidates if r["slug"] not in HISTORY_SET]
    
    console.print(f"[info]Recipes: {len(candidates)} total, {len(HISTORY_SET)} already done, {len(todo)} remaining[/info]")
    logger.info(f"Recipes: {len(candidates)} total, {len(HISTORY_SET)} done, {len(todo)} remaining")

    if not todo:
        console.print("[success]All recipes parsed! Nothing to do.[/success]")
        sys.exit(0)

    count = 0
    failed = 0
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        TextColumn("•"),
        TimeRemainingColumn(),
        console=console
    ) as progress:
        task = progress.add_task(f"Parsing {len(todo)} recipes...", total=len(todo))
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_to_slug = {executor.submit(process_recipe, r["slug"]): r["slug"] for r in todo}
            for future in concurrent.futures.as_completed(future_to_slug):
                if SHUTDOWN_REQUESTED:
                    for f in future_to_slug:
                        f.cancel()
                    break
                    
                slug = future_to_slug[future]
                try:
                    if future.result():
                        with HISTORY_LOCK:
                            HISTORY_SET.add(slug)
                        count += 1
                        logger.info(f"OK: {slug}")
                        if count % SAVE_INTERVAL == 0:
                            save_history()
                    else:
                        failed += 1
                        logger.info(f"FAIL: {slug}")
                except Exception as e:
                    failed += 1
                    logger.info(f"ERROR: {slug} — {e}")
                progress.advance(task)

    elapsed = time.time() - start_time
    save_history()
    console.rule("[bold green]Batch Parse Complete[/bold green]")
    console.print(f"Processed: [green]{count}[/green] | Failed: [red]{failed}[/red] | Total: [cyan]{len(todo)}[/cyan]")
    console.print(f"⏱️  Elapsed: {format_elapsed(elapsed)}")
    if count > 0:
        rate = count / (elapsed / 60) if elapsed > 0 else 0
        console.print(f"📊 Rate: {rate:.1f} recipes/min")
    logger.info(f"Complete | OK: {count} | Failed: {failed} | Elapsed: {format_elapsed(elapsed)}")
