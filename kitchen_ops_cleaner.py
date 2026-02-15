"""KitchenOps Library Cleaner — removes junk content and broken recipes from Mealie."""

import concurrent.futures, json, logging, os, re, sys, time
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse
import yaml
import requests
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table
from rich.theme import Theme

# Rich Console Setup
custom_theme = Theme({
    "info": "cyan",
    "warning": "yellow",
    "error": "bold red",
    "success": "bold green"
})
console = Console(theme=custom_theme)

# Load Config
try:
    with open("config/cleaning.yaml", "r") as f:
        config = yaml.safe_load(f)
        HIGH_RISK_KEYWORDS = config.get("junk_keywords", [])
except Exception as e:
    console.print(f"[error]Failed to load config/cleaning.yaml: {e}[/error]")
    sys.exit(1)

LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()
logging.basicConfig(level=LOG_LEVEL, format='%(message)s', handlers=[logging.NullHandler()])
logger = logging.getLogger("cleaner")

# File logging
os.makedirs("logs", exist_ok=True)
_fh = logging.FileHandler(f"logs/cleaner_{datetime.now().strftime('%Y-%m-%d')}.log")
_fh.setFormatter(logging.Formatter('%(asctime)s | %(message)s', datefmt='%H:%M:%S'))
logger.addHandler(_fh)
logger.setLevel(logging.INFO)

DRY_RUN: bool = os.getenv('DRY_RUN', 'true').lower() == 'true'
MEALIE_URL: str = os.getenv('MEALIE_URL', 'http://localhost:9000').rstrip('/')
MEALIE_API_TOKEN: str = os.getenv('MEALIE_API_TOKEN', '')
MAX_WORKERS: int = int(os.getenv('CLEANER_WORKERS', '8'))

# Database config (optional — enables fast Phase 2)
DB_TYPE: str = os.getenv('DB_TYPE', '').lower().strip()
SQLITE_PATH: str = os.getenv('SQLITE_PATH', '/app/data/mealie.db')
PG_DB: str = os.getenv('POSTGRES_DB', 'mealie')
PG_USER: str = os.getenv('POSTGRES_USER', 'mealie')
PG_PASS: str = os.getenv('POSTGRES_PASSWORD', 'mealie')
PG_HOST: str = os.getenv('POSTGRES_HOST', 'postgres')
PG_PORT: str = os.getenv('POSTGRES_PORT', '5432')

REJECT_FILE: str = "data/rejects.json"
VERIFIED_FILE: str = "data/verified.json"

LISTICLE_REGEX = re.compile(
    r'^(\d+)\s+(best|top|must|favorite|easy|healthy|quick|ways|things)',
    re.IGNORECASE
)


def load_json_set(filename: str) -> set[str]:
    if os.path.exists(filename):
        try:
            with open(filename, 'r') as f:
                return set(json.load(f))
        except (json.JSONDecodeError, IOError) as e:
            console.print(f"[warning]Could not load {filename}: {e}[/warning]")
            return set()
    return set()


def save_json_set(filename: str, data_set: set[str]) -> None:
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    try:
        with open(filename, 'w') as f:
            json.dump(list(data_set), f)
    except IOError as e:
        console.print(f"[error]Could not save {filename}: {e}[/error]")


REJECTS: set[str] = load_json_set(REJECT_FILE)
VERIFIED: set[str] = load_json_set(VERIFIED_FILE)


def get_recipes() -> list[dict]:
    headers = {"Authorization": f"Bearer {MEALIE_API_TOKEN}"}
    recipes: list[dict] = []
    page = 1
    
    console.print(f"[info]Scanning library at {MEALIE_URL}...[/info]")
    while True:
        try:
            r = requests.get(f"{MEALIE_URL}/api/recipes?page={page}&perPage=1000", headers=headers, timeout=30)
            if r.status_code != 200:
                break
            items = r.json().get('items', [])
            if not items:
                break
            recipes.extend(items)
            console.print(f"[dim]  Page {page}: {len(recipes)} recipes loaded...[/dim]")
            page += 1
        except requests.RequestException as e:
            console.print(f"[warning]Fetch failed on page {page}: {e} — retrying...[/warning]")
            # Retry up to 3 times
            retried = False
            for attempt in range(3):
                time.sleep(2 * (attempt + 1))
                try:
                    r = requests.get(f"{MEALIE_URL}/api/recipes?page={page}&perPage=1000", headers=headers, timeout=30)
                    if r.status_code == 200:
                        items = r.json().get('items', [])
                        if items:
                            recipes.extend(items)
                            page += 1
                            retried = True
                            break
                except requests.RequestException:
                    pass
            if not retried:
                console.print(f"[error]Failed to fetch page {page} after 3 retries. Proceeding with {len(recipes)} recipes.[/error]")
                break
                
    console.print(f"[info]Total recipes found: {len(recipes)}[/info]")
    return recipes


def delete_recipe(slug: str, name: str, reason: str, url: Optional[str] = None) -> None:
    logger.info(f"FLAGGED: {name} | {reason} | {url or 'N/A'}")
    FLAGGED_RECIPES.append({"name": name, "reason": reason, "url": url or ""})
    if DRY_RUN:
        console.print(f"[dim]  [DRY RUN] Would delete: '{name}' ({reason})[/dim]")
        return
    headers = {"Authorization": f"Bearer {MEALIE_API_TOKEN}"}
    for attempt in range(3):
        try:
            r = requests.delete(f"{MEALIE_URL}/api/recipes/{slug}", headers=headers, timeout=30)
            if r.status_code == 200:
                console.print(f"[success]  🗑️ Deleted: '{name}' ({reason})[/success]")
                logger.info(f"DELETED: {slug}")
                break
        except requests.RequestException as e:
            if attempt == 2:
                console.print(f"[error]Error deleting {slug} after 3 attempts: {e}[/error]")
        time.sleep(1)
    if url:
        REJECTS.add(url)
    VERIFIED.discard(slug)


def is_junk_content(name: str, url: Optional[str]) -> bool:
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
    slug = recipe.get('slug')
    if slug in VERIFIED:
        return None
    name = recipe.get('name')
    url = recipe.get('orgURL') or recipe.get('originalURL') or recipe.get('source')
    try:
        headers = {"Authorization": f"Bearer {MEALIE_API_TOKEN}"}
        r = requests.get(f"{MEALIE_URL}/api/recipes/{slug}", headers=headers, timeout=30)
        if r.status_code == 200:
            inst = r.json().get('recipeInstructions')
            if not validate_instructions(inst):
                return (slug, name, "Empty/Broken Instructions", url)
        return (slug, "VERIFIED")
    except requests.RequestException:
        return None


def connect_db() -> Optional[object]:
    """Try to connect to the database (Postgres or SQLite). Returns connection or None."""
    if not DB_TYPE:
        return None

    # SAFETY: SQLite is safe here because we open in READ-ONLY mode.
    # The entrypoint script also ensures Mealie is STOPPED if user runs 'Run All'.
    # Even if Mealie is running, read-only mode prevents corruption.

    try:
        if DB_TYPE == "postgres":
            import psycopg2
            conn = psycopg2.connect(dbname=PG_DB, user=PG_USER, password=PG_PASS, host=PG_HOST, port=PG_PORT)
            conn.autocommit = True
            console.print("[dim]  DB: Connected to Postgres (Accelerated Mode)[/dim]")
            return conn
            
        elif DB_TYPE == "sqlite":
            import sqlite3
            if not os.path.exists(SQLITE_PATH):
                console.print(f"[warning]SQLite DB not found at {SQLITE_PATH}[/warning]")
                return None
            
            # Connect in Read-Only mode (URI)
            # This is critical for safety if Mealie happens to be running.
            conn = sqlite3.connect(f"file:{SQLITE_PATH}?mode=ro", uri=True)
            console.print("[dim]  DB: Connected to SQLite (Read-Only Accelerated Mode)[/dim]")
            return conn
            
    except Exception as e:
        console.print(f"[warning]DB connection failed ({DB_TYPE}), falling back to API: {e}[/warning]")
    return None


def check_integrity_via_db(conn, all_slugs: set[str]) -> tuple[list[tuple], set[str]]:
    """Single SQL query to find recipes with no instructions. Returns (broken, verified)."""
    cursor = conn.cursor()
    
    # Find recipes that have NO instruction rows, or only empty instruction text
    cursor.execute(
        "SELECT r.slug, r.name "
        "FROM recipes r "
        "LEFT JOIN recipe_instructions ri ON r.id = ri.recipe_id "
        "GROUP BY r.id, r.slug, r.name "
        "HAVING COUNT(ri.id) = 0 "
        "   OR MAX(CASE WHEN ri.text IS NOT NULL AND ri.text != '' THEN 1 ELSE 0 END) = 0"
    )
    broken_rows = cursor.fetchall()
    
    broken_slugs = {row[0] for row in broken_rows}
    broken = []
    for slug, name in broken_rows:
        if slug in all_slugs and slug not in VERIFIED:
            broken.append((slug, name, "Empty/Broken Instructions", None))
    
    # Everything else is verified
    verified = all_slugs - broken_slugs
    
    return broken, verified


# Track flagged recipes for summary table
FLAGGED_RECIPES: list[dict] = []


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
    console.rule("[bold cyan]KitchenOps Library Cleaner[/bold cyan]")
    console.print(f"Mealie: [underline]{MEALIE_URL}[/underline] | Workers: {MAX_WORKERS} | Dry Run: {DRY_RUN}")
    logger.info(f"Started | Mealie: {MEALIE_URL} | Workers: {MAX_WORKERS} | Dry Run: {DRY_RUN}")

    if not MEALIE_API_TOKEN:
        console.print("[error]MEALIE_API_TOKEN is not set. Cannot proceed.[/error]")
        sys.exit(1)

    try:
        start_time = time.time()
        all_recipes = get_recipes()
        if not all_recipes:
            console.print("[warning]No recipes found. Nothing to do.[/warning]")
            sys.exit(0)

        # Phase 1: Junk scan
        console.print("\n[bold]Phase 1: Junk Content Scan[/bold]")
        clean_candidates: list[dict] = []
        junk_count = 0
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console
        ) as progress:
            task1 = progress.add_task("Scanning metadata...", total=len(all_recipes))
            for r in all_recipes:
                name = r.get('name', 'Unknown')
                url = r.get('orgURL') or r.get('originalURL') or r.get('source')
                slug = r.get('slug')
                if is_junk_content(name, url):
                    delete_recipe(slug, name, "JUNK CONTENT", url)
                    junk_count += 1
                else:
                    clean_candidates.append(r)
                progress.advance(task1)
        
        console.print(f"[info]  -> Junk detected: {junk_count}[/info]")

        # Phase 2: Integrity scan
        db_conn = connect_db()
        
        if db_conn:
            # DB-ACCELERATED PATH — single SQL query
            console.print(f"\n[bold]Phase 2: Integrity Scan (DB-Accelerated ⚡)[/bold]")
            all_slugs = {r.get('slug') for r in clean_candidates}
            
            broken_list, verified_set = check_integrity_via_db(db_conn, all_slugs)
            db_conn.close()
            
            verified_count = len(verified_set)
            broken_count = 0
            VERIFIED.update(verified_set)
            
            for slug, name, reason, url in broken_list:
                delete_recipe(slug, name, reason, url)
                broken_count += 1
            
            console.print(f"[info]  -> Verified: {verified_count} | Broken: {broken_count}[/info]")
        else:
            # API FALLBACK — one request per recipe (slow)
            console.print(f"\n[bold]Phase 2: Integrity Scan ({len(clean_candidates)} recipes, API mode)[/bold]")
            console.print("[dim]  Tip: Set DB_TYPE=postgres for instant results[/dim]")
            verified_count = 0
            broken_count = 0
            
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                console=console
            ) as progress:
                task2 = progress.add_task("Verifying instructions...", total=len(clean_candidates))
                with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                    future_to_recipe = {executor.submit(check_integrity, r): r for r in clean_candidates}
                    for future in concurrent.futures.as_completed(future_to_recipe):
                        try:
                            res = future.result()
                            if res:
                                if res[1] == "VERIFIED":
                                    VERIFIED.add(res[0])
                                    verified_count += 1
                                else:
                                    delete_recipe(res[0], res[1], res[2], res[3])
                                    broken_count += 1
                        except Exception:
                            pass
                        progress.advance(task2)

        if not DRY_RUN:
            save_json_set(REJECT_FILE, REJECTS)
            save_json_set(VERIFIED_FILE, VERIFIED)
            console.print("[success]State saved.[/success]")

        elapsed = time.time() - start_time

        # Deletion summary table (item 8)
        if FLAGGED_RECIPES:
            console.print("")
            table = Table(title="Flagged Recipes", show_lines=True, title_style="bold yellow")
            table.add_column("#", style="dim", width=4)
            table.add_column("Recipe Name", style="cyan", max_width=45)
            table.add_column("Reason", style="red")
            table.add_column("Source URL", style="dim", max_width=50)
            for i, entry in enumerate(FLAGGED_RECIPES, 1):
                table.add_row(str(i), entry["name"], entry["reason"], entry["url"][:50] if entry["url"] else "")
            console.print(table)

        console.rule("[bold green]Cycle Complete[/bold green]")
        console.print(f"Verified: [green]{verified_count}[/green] | Broken: [red]{broken_count}[/red] | Junk: [yellow]{junk_count}[/yellow]")
        console.print(f"⏱️  Elapsed: {format_elapsed(elapsed)}")
        logger.info(f"Complete | Verified: {verified_count} | Broken: {broken_count} | Junk: {junk_count} | Elapsed: {format_elapsed(elapsed)}")

    except KeyboardInterrupt:
        console.print("\n[warning]Interrupted by user. Saving progress...[/warning]")
        if not DRY_RUN:
            save_json_set(REJECT_FILE, REJECTS)
            save_json_set(VERIFIED_FILE, VERIFIED)
            console.print("[success]State saved.[/success]")
        console.rule("[bold yellow]Interrupted[/bold yellow]")
        sys.exit(130)

