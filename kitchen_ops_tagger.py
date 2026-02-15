"""KitchenOps Auto-Tagger — tags Mealie recipes by cuisine, protein, cheese, and tools."""

import logging, os, re, sys, time, uuid
from datetime import datetime
from typing import Any, Optional
import yaml
from rich.console import Console
from rich.table import Table
from rich.progress import track

# Rich Console Setup
from rich.theme import Theme
custom_theme = Theme({
    "info": "cyan",
    "warning": "yellow",
    "error": "bold red",
    "success": "bold green"
})
console = Console(theme=custom_theme)

LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()
logging.basicConfig(level=LOG_LEVEL, format='%(message)s', handlers=[logging.NullHandler()])
logger = logging.getLogger("tagger")

# File logging
os.makedirs("logs", exist_ok=True)
_fh = logging.FileHandler(f"logs/tagger_{datetime.now().strftime('%Y-%m-%d')}.log")
_fh.setFormatter(logging.Formatter('%(asctime)s | %(message)s', datefmt='%H:%M:%S'))
logger.addHandler(_fh)
logger.setLevel(logging.INFO)

DRY_RUN: bool = os.getenv('DRY_RUN', 'true').lower() == 'true'
DB_TYPE: str = os.getenv('DB_TYPE', 'sqlite').lower().strip()
SQLITE_PATH: str = os.getenv('SQLITE_PATH', '/app/data/mealie.db')
PG_DB: str = os.getenv('POSTGRES_DB', 'mealie')
PG_USER: str = os.getenv('POSTGRES_USER', 'mealie')
PG_PASS: str = os.getenv('POSTGRES_PASSWORD', 'mealie')
PG_HOST: str = os.getenv('POSTGRES_HOST', 'postgres')
PG_PORT: str = os.getenv('POSTGRES_PORT', '5432')

# Load Config
try:
    with open("config/tagging.yaml", "r") as f:
        config = yaml.safe_load(f)
        CHEESE_TYPES = config.get("cheese_types", {})
        SQL_INGREDIENT_TAGS = config.get("protein_tags", {})
        SQL_CUISINE_FINGERPRINTS = config.get("cuisine_fingerprints", {})
        TEXT_ONLY_TAGS = config.get("text_tags", {})
        TOOLS_MATCHES = config.get("tools_matches", {})
except Exception as e:
    console.print(f"[error]Failed to load config/tagging.yaml: {e}[/error]")
    sys.exit(1)

MIN_CUISINE_MATCHES: int = 2


class DBWrapper:
    def __init__(self) -> None:
        self.conn: Any = None
        self.cursor: Any = None
        self.type: str = DB_TYPE
        self._placeholder: str = "%s" if self.type == "postgres" else "?"

        try:
            if self.type == "postgres":
                import psycopg2
                self.conn = psycopg2.connect(dbname=PG_DB, user=PG_USER, password=PG_PASS, host=PG_HOST, port=PG_PORT)
                self.conn.autocommit = True
            else:
                import sqlite3
                self.conn = sqlite3.connect(SQLITE_PATH)
                self.conn.create_function("REGEXP", 2, self._regexp)
            self.cursor = self.conn.cursor()
        except Exception as e:
            console.print(f"[error]Database connection failed: {e}[/error]")
            self.conn = None

    @property
    def placeholder(self) -> str:
        return self._placeholder

    @staticmethod
    def _regexp(expr: Optional[str], item: Optional[str]) -> bool:
        if item is None or expr is None:
            return False
        try:
            return re.compile(expr.replace(r'\y', r'\b'), re.IGNORECASE).search(item) is not None
        except re.error:
            return False

    def execute(self, sql: str, params: Optional[tuple] = None) -> "DBWrapper":
        try:
            if self.type == "sqlite":
                sql = re.sub(r"(\w+)\s*~\*\s*('[^']+')", r"\1 REGEXP \2", sql)
                sql = re.sub(r"(\w+)\s*!~\*\s*('[^']+')", r"NOT (\1 REGEXP \2)", sql)
                sql = sql.replace("gen_random_uuid()", "lower(hex(randomblob(16)))")
                sql = sql.replace("::uuid", "")
            self.cursor.execute(sql, params or ())
        except Exception as e:
            console.print(f"[error]SQL failed: {e}[/error]")
        return self

    def fetch_one(self) -> Optional[tuple]:
        return self.cursor.fetchone() if self.cursor else None

    def fetch_all(self) -> list[tuple]:
        return self.cursor.fetchall() if self.cursor else []

    def close(self) -> None:
        if self.conn:
            try:
                self.conn.close()
            except Exception:
                pass


def get_group_id(db: DBWrapper) -> Optional[str]:
    row = db.execute("SELECT id FROM groups LIMIT 1").fetch_one()
    return row[0] if row else None


def _make_slug(name: str) -> str:
    return name.lower().replace(" ", "-").replace("/", "-").replace("&", "and")


def ensure_tag(db: DBWrapper, name: str, group_id: str) -> Optional[str]:
    slug, p = _make_slug(name), db.placeholder
    row = db.execute(f"SELECT id FROM tags WHERE slug = {p}", (slug,)).fetch_one()
    if row:
        return row[0]
    if not DRY_RUN:
        new_id = str(uuid.uuid4())
        db.execute(f"INSERT INTO tags (id, group_id, name, slug) VALUES ({p}, {p}, {p}, {p})", (new_id, group_id, name, slug))
        return new_id
    return "dry-run-id"


def ensure_tool(db: DBWrapper, name: str, group_id: str) -> Optional[str]:
    slug, p = name.lower().replace(" ", "-"), db.placeholder
    row = db.execute(f"SELECT id FROM tools WHERE slug = {p}", (slug,)).fetch_one()
    if row:
        return row[0]
    if not DRY_RUN:
        new_id = str(uuid.uuid4())
        db.execute(f"INSERT INTO tools (id, group_id, name, slug, on_hand) VALUES ({p}, {p}, {p}, {p}, 0)", (new_id, group_id, name, slug))
        return new_id
    return "dry-run-id"


def link_tag(db: DBWrapper, recipe_id: str, tag_id: str) -> None:
    if DRY_RUN:
        return
    p = db.placeholder
    if not db.execute(f"SELECT 1 FROM recipes_to_tags WHERE recipe_id = {p} AND tag_id = {p}", (recipe_id, tag_id)).fetch_one():
        db.execute(f"INSERT INTO recipes_to_tags (recipe_id, tag_id) VALUES ({p}, {p})", (recipe_id, tag_id))


def link_tool(db: DBWrapper, recipe_id: str, tool_id: str) -> None:
    if DRY_RUN:
        return
    p = db.placeholder
    if not db.execute(f"SELECT 1 FROM recipes_to_tools WHERE recipe_id = {p} AND tool_id = {p}", (recipe_id, tool_id)).fetch_one():
        db.execute(f"INSERT INTO recipes_to_tools (recipe_id, tool_id) VALUES ({p}, {p})", (recipe_id, tool_id))


def _wrap_word_boundaries(pattern: str) -> str:
    terms = [t.strip() for t in pattern.split("|") if t.strip()]
    return "|".join(r"\y" + t + r"\y" for t in terms)


def phase_1_cheese(db: DBWrapper, group_id: str) -> None:
    console.print("[bold]Phase 1: Cheese Tags[/bold]")
    for cat, regex in track(CHEESE_TYPES.items(), description="Scanning cheese types..."):
        tag_id = ensure_tag(db, cat, group_id)
        safe = _wrap_word_boundaries(regex)
        for (rid,) in db.execute(f"SELECT DISTINCT recipe_id FROM recipes_ingredients WHERE food_id IN (SELECT id FROM ingredient_foods WHERE name ~* '{safe}')").fetch_all():
            link_tag(db, rid, tag_id)


def phase_2_protein(db: DBWrapper, group_id: str) -> None:
    console.print("[bold]Phase 2: Protein Tags[/bold]")
    for cat, rules in track(SQL_INGREDIENT_TAGS.items(), description="Scanning proteins..."):
        tag_id = ensure_tag(db, cat, group_id)
        inc, exc = _wrap_word_boundaries(rules["regex"]), _wrap_word_boundaries(rules.get("exclude", ""))
        sql = f"SELECT DISTINCT recipe_id FROM recipes_ingredients WHERE food_id IN (SELECT id FROM ingredient_foods WHERE name ~* '{inc}' AND name !~* '{exc}')"
        for (rid,) in db.execute(sql).fetch_all():
            link_tag(db, rid, tag_id)


def phase_3_cuisine(db: DBWrapper, group_id: str) -> None:
    console.print(f"[bold]Phase 3: Cuisine Tags (Threshold: {MIN_CUISINE_MATCHES})[/bold]")
    for cuisine, regex in track(SQL_CUISINE_FINGERPRINTS.items(), description="Scanning cuisines..."):
        tag_id = ensure_tag(db, cuisine, group_id)
        safe = _wrap_word_boundaries(regex)
        sql = f"SELECT recipe_id FROM recipes_ingredients WHERE food_id IN (SELECT id FROM ingredient_foods WHERE name ~* '{safe}') GROUP BY recipe_id HAVING COUNT(DISTINCT food_id) >= {MIN_CUISINE_MATCHES}"
        for (rid,) in db.execute(sql).fetch_all():
            link_tag(db, rid, tag_id)


def phase_4_text(db: DBWrapper, group_id: str) -> None:
    console.print("[bold]Phase 4: Text-Based Tags[/bold]")
    for tag, keywords in track(TEXT_ONLY_TAGS.items(), description="Scanning text..."):
        tag_id = ensure_tag(db, tag, group_id)
        chain = "|".join(r"\y" + k.replace("'", "''") + r"\y" for k in keywords)
        for (rid,) in db.execute(f"SELECT id FROM recipes WHERE name ~* '{chain}' OR description ~* '{chain}'").fetch_all():
            link_tag(db, rid, tag_id)


def phase_5_tools(db: DBWrapper, group_id: str) -> None:
    console.print("[bold]Phase 5: Tool Tagging[/bold]")
    for tool, keywords in track(TOOLS_MATCHES.items(), description="Scanning tools..."):
        tool_id = ensure_tool(db, tool, group_id)
        chain = "|".join(r"\y" + k + r"\y" for k in keywords)
        sql = f"SELECT DISTINCT r.id FROM recipes r JOIN recipe_instructions ri ON r.id = ri.recipe_id WHERE ri.text ~* '{chain}'"
        for (rid,) in db.execute(sql).fetch_all():
            link_tool(db, rid, tool_id)


def phase_6_report(db: DBWrapper) -> None:
    table = Table(title="Cuisine Market Share")
    table.add_column("Cuisine", style="cyan")
    table.add_column("Count", style="green", justify="right")

    # Single query instead of N+1
    cuisine_slugs = {_make_slug(c): c for c in SQL_CUISINE_FINGERPRINTS}
    placeholders = ", ".join([db.placeholder] * len(cuisine_slugs))
    rows = db.execute(
        f"SELECT t.slug, COUNT(*) FROM recipes_to_tags rt "
        f"JOIN tags t ON rt.tag_id = t.id "
        f"WHERE t.slug IN ({placeholders}) "
        f"GROUP BY t.slug ORDER BY t.slug",
        tuple(cuisine_slugs.keys())
    ).fetch_all()

    for slug, count in (rows or []):
        name = cuisine_slugs.get(slug, slug)
        if count > 0:
            table.add_row(name, str(count))

    console.print(table)
    
    row = db.execute(
        "SELECT COUNT(*) FROM recipes r "
        "LEFT JOIN recipes_to_tags rt ON r.id = rt.recipe_id "
        "WHERE rt.recipe_id IS NULL"
    ).fetch_one()
    untagged = row[0] if row else "?"
    console.print(f"\n[bold red]Untagged Recipes Left:[/bold red] {untagged}")


def format_elapsed(seconds: float) -> str:
    s = int(seconds)
    if s >= 86400:
        return f"{s // 86400}d {(s % 86400) // 3600}h {(s % 3600) // 60}m"
    if s >= 3600:
        return f"{s // 3600}h {(s % 3600) // 60}m"
    if s >= 60:
        return f"{s // 60}m {s % 60}s"
    return f"{s}s"


def main() -> None:
    console.rule("[bold cyan]KitchenOps Auto-Tagger[/bold cyan]")
    console.print(f"DB: {DB_TYPE.upper()} | Dry Run: {DRY_RUN}")
    logger.info(f"Started | DB: {DB_TYPE.upper()} | Dry Run: {DRY_RUN}")

    db = DBWrapper()
    if not db.conn:
        console.print("[error]Cannot proceed without a database connection.[/error]")
        sys.exit(1)

    try:
        start_time = time.time()
        gid = get_group_id(db)
        if not gid:
            console.print("[error]Group ID not found. DB empty or connection failed.[/error]")
            return
        

        phase_1_cheese(db, gid)
        phase_2_protein(db, gid)
        phase_3_cuisine(db, gid)
        phase_4_text(db, gid)
        phase_5_tools(db, gid)
        phase_6_report(db)

        elapsed = time.time() - start_time
        console.print(f"\n⏱️  Elapsed: {format_elapsed(elapsed)}")
        logger.info(f"Complete | Elapsed: {format_elapsed(elapsed)}")

    except KeyboardInterrupt:
        console.print("\n[warning]Interrupted by user. Closing database connection...[/warning]")
    except Exception as e:
        console.print_exception(show_locals=True)
    finally:
        db.close()
        console.rule("[bold green]Complete[/bold green]")


if __name__ == "__main__":
    main()
