"""KitchenOps Batch Parser — fixes unparsed recipe ingredients via Mealie's NLP API."""

import concurrent.futures, json, logging, os, signal, sys, threading
from typing import Any, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
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

LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()
logging.basicConfig(level=LOG_LEVEL, format='%(message)s', handlers=[logging.NullHandler()])
logger = logging.getLogger("parser")

MEALIE_URL: str = os.getenv("MEALIE_URL", "http://localhost:9000").rstrip("/")
API_TOKEN: str = os.getenv("MEALIE_API_TOKEN", "")
MAX_WORKERS: int = int(os.getenv("PARSER_WORKERS", "2"))
DRY_RUN: bool = os.getenv("DRY_RUN", "true").lower() == "true"
CONFIDENCE_THRESHOLD: float = 0.85
HISTORY_FILE: str = "parse_history.json"
SAVE_INTERVAL: int = 20

FOOD_CACHE: dict[str, str] = {}
UNIT_CACHE: dict[str, str] = {}
HISTORY_SET: set[str] = set()
CACHE_LOCK = threading.Lock()
HISTORY_LOCK = threading.Lock()
thread_local = threading.local()


def signal_handler(sig: int, frame: Any) -> None:
    console.print("\n[warning]Interrupt received. Saving history...[/warning]")
    save_history()
    sys.exit(0)

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


def prime_cache() -> None:
    with console.status("[bold green]Prime Cache: Fetching foods & units...[/bold green]", spinner="dots"):
        session = requests.Session()
        session.headers.update({"Authorization": f"Bearer {API_TOKEN}"})

        # Units
        page = 1
        while True:
            try:
                r = session.get(f"{MEALIE_URL}/api/units?page={page}&perPage=2000", timeout=10)
                if r.status_code != 200 or not r.json().get("items"):
                    break
                with CACHE_LOCK:
                    for item in r.json().get("items", []):
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
                if r.status_code != 200 or not r.json().get("items"):
                    break
                with CACHE_LOCK:
                    for item in r.json().get("items", []):
                        FOOD_CACHE[item["name"].lower().strip()] = item["id"]
                page += 1
            except requests.RequestException:
                break

    console.print(f"[info]Cache ready: {len(FOOD_CACHE)} foods, {len(UNIT_CACHE)} units.[/info]")


def get_all_recipes() -> list[dict]:
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {API_TOKEN}"})
    recipes: list[dict] = []
    page = 1
    
    with console.status("[bold green]Fetching recipe index...[/bold green]", spinner="dots"):
        while True:
            try:
                r = session.get(f"{MEALIE_URL}/api/recipes?page={page}&perPage=2000", timeout=15)
                if r.status_code != 200 or not r.json().get("items"):
                    break
                recipes.extend(r.json().get("items", []))
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


if __name__ == "__main__":
    console.rule("[bold cyan]KitchenOps Batch Parser[/bold cyan]")
    console.print(f"Mealie: [underline]{MEALIE_URL}[/underline] | Workers: {MAX_WORKERS} | Dry Run: {DRY_RUN}")

    if not API_TOKEN:
        console.print("[error]MEALIE_API_TOKEN is not set. Cannot proceed.[/error]")
        sys.exit(1)

    prime_cache()
    HISTORY_SET = load_history()
    candidates = get_all_recipes()
    todo = [r for r in candidates if r["slug"] not in HISTORY_SET]
    
    if not todo:
        console.print("[success]All recipes parsed! Nothing to do.[/success]")
        sys.exit(0)

    count = 0
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console
    ) as progress:
        task = progress.add_task(f"Parsing {len(todo)} recipes...", total=len(todo))
        
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
                except Exception:
                    pass
                progress.advance(task)

    save_history()
    console.rule("[bold green]Batch Parse Complete[/bold green]")
    console.print(f"Processed: [green]{count}[/green]/[cyan]{len(todo)}[/cyan]")
