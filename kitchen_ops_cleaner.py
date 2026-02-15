"""KitchenOps Library Cleaner — removes junk content and broken recipes from Mealie."""

import concurrent.futures, json, logging, os, re, sys
from typing import Optional
from urllib.parse import urlparse
import yaml
import requests
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
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
# Suppress standard logging in favor of Rich, unless debugging
logging.basicConfig(level=LOG_LEVEL, format='%(message)s', handlers=[logging.NullHandler()])
logger = logging.getLogger("cleaner")

DRY_RUN: bool = os.getenv('DRY_RUN', 'true').lower() == 'true'
MEALIE_URL: str = os.getenv('MEALIE_URL', 'http://localhost:9000').rstrip('/')
MEALIE_API_TOKEN: str = os.getenv('MEALIE_API_TOKEN', '')
MAX_WORKERS: int = int(os.getenv('CLEANER_WORKERS', '2'))

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
    
    with console.status("[bold green]Scanning library...[/bold green]", spinner="dots"):
        while True:
            try:
                r = requests.get(f"{MEALIE_URL}/api/recipes?page={page}&perPage=1000", headers=headers, timeout=10)
                if r.status_code != 200:
                    break
                items = r.json().get('items', [])
                if not items:
                    break
                recipes.extend(items)
                page += 1
            except requests.RequestException as e:
                console.print(f"[warning]Recipe fetch failed on page {page}: {e}[/warning]")
                break
                
    console.print(f"[info]Total recipes found: {len(recipes)}[/info]")
    return recipes


def delete_recipe(slug: str, name: str, reason: str, url: Optional[str] = None) -> None:
    if DRY_RUN:
        return
    headers = {"Authorization": f"Bearer {MEALIE_API_TOKEN}"}
    try:
        requests.delete(f"{MEALIE_URL}/api/recipes/{slug}", headers=headers, timeout=10)
        console.print(f"[success]Deleted: {name} ({reason})[/success]")
    except requests.RequestException as e:
        console.print(f"[error]Error deleting {slug}: {e}[/error]")
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
        r = requests.get(f"{MEALIE_URL}/api/recipes/{slug}", headers=headers, timeout=10)
        if r.status_code == 200:
            inst = r.json().get('recipeInstructions')
            if not validate_instructions(inst):
                return (slug, name, "Empty/Broken Instructions", url)
        return (slug, "VERIFIED")
    except requests.RequestException:
        return None


if __name__ == "__main__":
    console.rule("[bold cyan]KitchenOps Library Cleaner[/bold cyan]")
    console.print(f"Mealie: [underline]{MEALIE_URL}[/underline] | Workers: {MAX_WORKERS} | Dry Run: {DRY_RUN}")

    if not MEALIE_API_TOKEN:
        console.print("[error]MEALIE_API_TOKEN is not set. Cannot proceed.[/error]")
        sys.exit(1)

    try:
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
        console.print(f"\n[bold]Phase 2: Integrity Scan ({len(clean_candidates)} recipes)[/bold]")
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

        console.rule("[bold green]Cycle Complete[/bold green]")
        console.print(f"Verified: [green]{verified_count}[/green] | Broken: [red]{broken_count}[/red] | Junk: [yellow]{junk_count}[/yellow]")

    except KeyboardInterrupt:
        console.print("\n[warning]Interrupted by user. Saving progress...[/warning]")
        if not DRY_RUN:
            save_json_set(REJECT_FILE, REJECTS)
            save_json_set(VERIFIED_FILE, VERIFIED)
            console.print("[success]State saved.[/success]")
        console.rule("[bold yellow]Interrupted[/bold yellow]")
        sys.exit(130)

