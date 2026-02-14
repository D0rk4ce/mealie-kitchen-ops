"""KitchenOps Auto-Tagger — Applies intelligent tags to Mealie recipes.

Directly queries the Mealie database (SQLite or Postgres) for raw speed,
using regex-based ingredient matching to classify recipes by cuisine,
protein, cheese type, and cooking equipment.
"""

import logging
import os
import re
import sys
import uuid
from typing import Any, Optional

# --- LOGGING ---
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()
logging.basicConfig(
    level=LOG_LEVEL,
    format='[%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("tagger")

# --- CONFIGURATION ---
DRY_RUN: bool = os.getenv('DRY_RUN', 'true').lower() == 'true'
DB_TYPE: str = os.getenv('DB_TYPE', 'sqlite').lower().strip()
SQLITE_PATH: str = os.getenv('SQLITE_PATH', '/app/data/mealie.db')

# Postgres Credentials
PG_DB: str = os.getenv('POSTGRES_DB', 'mealie')
PG_USER: str = os.getenv('POSTGRES_USER', 'mealie')
PG_PASS: str = os.getenv('POSTGRES_PASSWORD', 'mealie')
PG_HOST: str = os.getenv('POSTGRES_HOST', 'postgres')
PG_PORT: str = os.getenv('POSTGRES_PORT', '5432')

# ==========================================
# CONFIGURATION: CHEESE
# ==========================================
CHEESE_TYPES: dict[str, str] = {
    "Blue & Funky": "gorgonzola|roquefort|stilton|blue cheese|taleggio|danablu",
    "Fresh & Curd": "paneer|chenna|khoya|feta|halloumi|cotija|queso fresco|cheese curds",
    "Melting Cheese": "provolone|fontina|monterey jack|muenster|gouda|swiss|raclette|havarti|edam|jarlsberg",
    "Sharp & Aged": "cheddar|parmesan|pecorino|manchego|asiago|gruyere|comte|aged gouda",
    "Soft & Creamy": "mozzarella|burrata|ricotta|brie|camembert|goat cheese|chèvre|cream cheese|mascarpone|neufchatel"
}

# ==========================================
# CONFIGURATION: PROTEINS (SQL REGEX)
# ==========================================
SQL_INGREDIENT_TAGS: dict[str, dict[str, str]] = {
    "Beef": { "regex": "beef|steak|hamburger|ground meat|ribeye|sirloin|brisket|chuck roast|filet|short rib", "exclude": "broth|stock|bouillon" },
    "Chicken": { "regex": "chicken|wing|drumstick|thigh|breast|poultry|cornish hen", "exclude": "broth|stock|bouillon" },
    "Game Meat": { "regex": "venison|duck|bison|rabbit|quail|goose|elk", "exclude": "sauce" },
    "Lamb/Goat": { "regex": "lamb|mutton|goat|gyro|merguez", "exclude": "lettuce" },
    "Pork": { "regex": "pork|bacon|ham|sausage|tenderloin|chorizo|prosciutto|pancetta|guanciale|salami|pork belly", "exclude": "turkey|chicken" },
    "Seafood": { "regex": "shrimp|salmon|tuna|cod|lobster|scallop|mussel|clam|fish|prawn|crab|squid|octopus|anchovy|sardine|tilapia|mahi", "exclude": "sauce|stock" },
    "Vegetarian Protein": { "regex": "tofu|tempeh|seitan|lentil|chickpea|black bean|kidney bean|cannellini|edamame", "exclude": "pork|beef|chicken" }
}

# ==========================================
# CONFIGURATION: CUISINE FINGERPRINTS (SQL)
# ==========================================
SQL_CUISINE_FINGERPRINTS: dict[str, str] = {
    "Brazilian": "dende oil|cassava flour|farofa|cachaca|condensed milk",
    "British / Irish": "malt vinegar|english mustard|worcestershire|stilton|golden syrup|stout|guinness|lamb",
    "Caribbean": "allspice|scotch bonnet|jerk|plantain|coconut milk|curry powder|callaloo",
    "Chinese (Cantonese)": "oyster sauce|hoisin|shaoxing|char siu|lap cheong|wonton|white pepper",
    "Chinese (Sichuan)": "sichuan pepper|doubanjiang|chili oil|mala|dried chili|black vinegar",
    "East African (Ethiopian)": "berbere|niter kibbeh|injera|teff|mitmita",
    "Eastern European": "dill|sour cream|beets|cabbage|poppy seed|pierogi|kielbasa|sauerkraut",
    "Filipino": "calamansi|cane vinegar|banana ketchup|ube|bagoong|lumpia|soy sauce",
    "French": "butter|wine|shallot|tarragon|thyme|dijon|gruyere|herbes de provence|cognac",
    "German": "sauerkraut|bratwurst|caraway|mustard|schnitzel|spaetzle|pretzel",
    "Greek": "feta|kalamata|olive|oregano|yogurt|dill|phyllo|halloumi|tzatziki",
    "Indian": "garam masala|paneer|ghee|fenugreek|heavy cream|makhani|tandoori|kashmiri chili|amchur|curry leaf|mustard seed|coconut oil|tamarind|gunpowder|sambar|rasam|urad dal|asafoetida|hing|kerala|malabar|kochi|meen curry|appam|puttu|stew|coconut milk|pearl spot",
    "Indonesian / Malaysian": "kecap manis|galangal|sambal|shrimp paste|tempeh|lemongrass|kaffir lime|turmeric leaf",
    "Italian": "olive oil|basil|oregano|mozzarella|tomato|capers|anchovy|pecorino|butter|heavy cream|parmesan|risotto|polenta|balsamic|prosciutto|sage|gorgonzola|truffle",
    "Japanese": "miso|mirin|dashi|sake|nori|wasabi|furikake|panko|bonito|kombu|shoyu",
    "Korean": "gochujang|gochugaru|kimchi|doenjang|rice cake|sesame oil|perilla leaf",
    "Levantine (Middle Eastern)": "tahini|za''atar|sumac|chickpea|bulgur|pomegranate molasses|halva|feta",
    "Mexican": "corn tortilla|masa|tomatillo|poblano|jalapeno|cotija|cilantro|mole|epazote|pepita",
    "North African (Maghreb)": "preserved lemon|ras el hanout|couscous|tagine|harissa|saffron|date",
    "Pakistani": "nihari|karahi|shan masala|chapli|haleem|ghee",
    "Persian (Iranian)": "saffron|rose water|barberry|dried lime|pomegranate molasses|walnut|sumac|tahdig",
    "Peruvian": "aji amarillo|aji panca|quinoa|ceviche|pisco|potato",
    "Spanish": "saffron|chorizo|paprika|manchego|sherry|paella|iberico",
    "Tex-Mex": "flour tortilla|cheddar|cumin|ground beef|sour cream|fajita|nacho",
    "Thai": "fish sauce|coconut milk|curry paste|lemongrass|galangal|thai basil|kaffir lime|bird''s eye chili|tamarind",
    "US Southern": "buttermilk|collard greens|cornmeal|grits|pecan|okra|bacon grease|cajun|creole|andouille",
    "Vietnamese": "fish sauce|star anise|pho|lemongrass|rice paper|vermicelli|nuoc cham",
    "West African": "scotch bonnet|yam|egusi|plantain|fufu|jollof|red palm oil"
}

# ==========================================
# CONFIGURATION: TEXT-BASED TAGS
# ==========================================
TEXT_ONLY_TAGS: dict[str, list[str]] = {
    "Breakfast": ["breakfast", "pancake", "waffle", "omelet", "benedict"],
    "Comfort Food": ["mac and cheese", "casserole", "meatloaf", "gravy", "pot pie", "stew", "grilled cheese"],
    "Dessert": ["dessert", "cake", "cookie", "brownie", "ice cream", "pie"],
    "Extra Spicy": ["extra spicy", "insane heat", "ghost pepper", "habanero", "thai chili", "bird's eye"],
    "Gluten Free": ["gluten free", "gluten-free", "gf"],
    "Keto": ["keto", "ketogenic", "low carb"],
    "One Pot": ["one pot", "sheet pan", "skillet dinner", "dutch oven"],
    "Project Meal": ["sourdough", "ferment", "cure", "smoke", "braise", "confit", "mole"],
    "Soup": ["soup", "stew", "chowder", "chili"],
    "Spicy": ["spicy", "jalapeno", "hot sauce", "sriracha", "chili flakes", "serrano", "cayenne", "gochujang"],
    "Vegan": ["vegan", "plant based"]
}

# ==========================================
# CONFIGURATION: TOOLS
# ==========================================
TOOLS_MATCHES: dict[str, list[str]] = {
    "Air Fryer": ["air fryer", "air-fryer"],
    "Cast Iron": ["cast iron", "skillet"],
    "Dutch Oven": ["dutch oven", "le creuset"],
    "Instant Pot": ["instant pot", "pressure cooker", "multicooker"],
    "Slow Cooker": ["slow cooker", "crock pot"],
    "Smoker / Grill": ["smoker", "traeger", "charcoal", "grill", "big green egg"],
    "Sous Vide": ["sous vide", "immersion circulator"],
    "Wok": ["wok"]
}

# ==========================================
# DATABASE ENGINE (Universal Adapter)
# ==========================================
class DBWrapper:
    """Database abstraction layer supporting both SQLite and Postgres.

    Translates Postgres-dialect SQL (regex operators, UUID functions) to
    SQLite equivalents on-the-fly so a single set of queries works on both
    backends.
    """

    def __init__(self) -> None:
        self.conn: Any = None
        self.cursor: Any = None
        self.type: str = DB_TYPE
        self._placeholder: str = "%s" if self.type == "postgres" else "?"

        try:
            if self.type == "postgres":
                import psycopg2
                self.conn = psycopg2.connect(
                    dbname=PG_DB, user=PG_USER, password=PG_PASS,
                    host=PG_HOST, port=PG_PORT
                )
                self.conn.autocommit = True
            else:
                import sqlite3
                self.conn = sqlite3.connect(SQLITE_PATH)
                # Inject REGEXP function for SQLite
                self.conn.create_function("REGEXP", 2, self._regexp)

            self.cursor = self.conn.cursor()
        except Exception as e:
            logger.error(f"Database connection failed: {e}")
            self.conn = None

    @property
    def placeholder(self) -> str:
        """Return the parameter placeholder for the active DB dialect."""
        return self._placeholder

    @staticmethod
    def _regexp(expr: Optional[str], item: Optional[str]) -> bool:
        """SQLite user-defined REGEXP function.

        Converts Postgres word-boundary markers (``\\y``) to Python ``\\b``
        before compiling the pattern.
        """
        if item is None or expr is None:
            return False
        try:
            clean_expr = expr.replace(r'\y', r'\b')
            reg = re.compile(clean_expr, re.IGNORECASE)
            return reg.search(item) is not None
        except re.error:
            return False

    def execute(self, sql: str, params: Optional[tuple] = None) -> "DBWrapper":
        """Execute a SQL statement with automatic dialect translation.

        Always returns ``self`` so that ``.fetch_all()`` / ``.fetch_one()``
        can be chained safely even after an error (they will return empty
        results).
        """
        try:
            # Dialect translation for SQLite
            if self.type == "sqlite":
                sql = re.sub(r"(\w+)\s*~\*\s*('[^']+')", r"\1 REGEXP \2", sql)
                sql = re.sub(r"(\w+)\s*!~\*\s*('[^']+')", r"NOT (\1 REGEXP \2)", sql)
                sql = sql.replace("gen_random_uuid()", "lower(hex(randomblob(16)))")
                sql = sql.replace("::uuid", "")

            self.cursor.execute(sql, params or ())
        except Exception as e:
            logger.error(f"SQL failed: {e}\n  Statement: {sql[:200]}")
        return self

    def fetch_one(self) -> Optional[tuple]:
        """Fetch a single row, or ``None`` if the previous query failed."""
        try:
            return self.cursor.fetchone()
        except Exception:
            return None

    def fetch_all(self) -> list[tuple]:
        """Fetch all rows, or an empty list if the previous query failed."""
        try:
            return self.cursor.fetchall()
        except Exception:
            return []

    def close(self) -> None:
        """Close the database connection."""
        if self.conn:
            try:
                self.conn.close()
            except Exception:
                pass


# ==========================================
# LOGIC PROCESSORS
# ==========================================

def get_group_id(db: DBWrapper) -> Optional[str]:
    """Retrieve the first group ID from the database."""
    row = db.execute("SELECT id FROM groups LIMIT 1").fetch_one()
    return row[0] if row else None


def _make_slug(name: str) -> str:
    """Convert a human-readable name to a URL-safe slug."""
    return name.lower().replace(" ", "-").replace("/", "-").replace("&", "and")


def ensure_tag(db: DBWrapper, name: str, group_id: str) -> Optional[str]:
    """Return the ID of an existing tag, or create it if it doesn't exist.

    Uses parameterized queries to prevent SQL injection.
    """
    slug = _make_slug(name)
    p = db.placeholder

    row = db.execute(f"SELECT id FROM tags WHERE slug = {p}", (slug,)).fetch_one()
    if row:
        return row[0]

    logger.info(f"   [+] Creating Tag: {name}")
    if not DRY_RUN:
        new_id = str(uuid.uuid4())
        db.execute(
            f"INSERT INTO tags (id, group_id, name, slug) VALUES ({p}, {p}, {p}, {p})",
            (new_id, group_id, name, slug)
        )
        return new_id
    return "dry-run-id"


def ensure_tool(db: DBWrapper, name: str, group_id: str) -> Optional[str]:
    """Return the ID of an existing tool, or create it if it doesn't exist.

    Uses parameterized queries to prevent SQL injection.
    """
    slug = name.lower().replace(" ", "-")
    p = db.placeholder

    row = db.execute(f"SELECT id FROM tools WHERE slug = {p}", (slug,)).fetch_one()
    if row:
        return row[0]

    logger.info(f"   [+] Creating Tool: {name}")
    if not DRY_RUN:
        new_id = str(uuid.uuid4())
        db.execute(
            f"INSERT INTO tools (id, group_id, name, slug, on_hand) VALUES ({p}, {p}, {p}, {p}, 0)",
            (new_id, group_id, name, slug)
        )
        return new_id
    return "dry-run-id"


def link_tag(db: DBWrapper, recipe_id: str, tag_id: str) -> None:
    """Link a tag to a recipe (idempotent — skips if already linked)."""
    if DRY_RUN:
        logger.debug(f"   [DRY RUN] Would link Tag {tag_id} → Recipe {recipe_id}")
        return
    p = db.placeholder
    check = db.execute(
        f"SELECT 1 FROM recipes_to_tags WHERE recipe_id = {p} AND tag_id = {p}",
        (recipe_id, tag_id)
    ).fetch_one()
    if not check:
        db.execute(
            f"INSERT INTO recipes_to_tags (recipe_id, tag_id) VALUES ({p}, {p})",
            (recipe_id, tag_id)
        )


def link_tool(db: DBWrapper, recipe_id: str, tool_id: str) -> None:
    """Link a tool to a recipe (idempotent — skips if already linked)."""
    if DRY_RUN:
        logger.debug(f"   [DRY RUN] Would link Tool {tool_id} → Recipe {recipe_id}")
        return
    p = db.placeholder
    check = db.execute(
        f"SELECT 1 FROM recipes_to_tools WHERE recipe_id = {p} AND tool_id = {p}",
        (recipe_id, tool_id)
    ).fetch_one()
    if not check:
        db.execute(
            f"INSERT INTO recipes_to_tools (recipe_id, tool_id) VALUES ({p}, {p})",
            (recipe_id, tool_id)
        )


# --- PHASES ---

def phase_1_cheese(db: DBWrapper, group_id: str) -> None:
    """Tag recipes by cheese category based on ingredient names."""
    logger.info("[PHASE 1] Category: Cheese")
    for cat, regex in CHEESE_TYPES.items():
        logger.info(f"   [SCAN] {cat}...")
        tag_id = ensure_tag(db, cat, group_id)
        sql = f"SELECT DISTINCT recipe_id FROM recipes_ingredients WHERE food_id IN (SELECT id FROM ingredient_foods WHERE name ~* '{regex}')"
        recipes = db.execute(sql).fetch_all()
        for (rid,) in recipes:
            link_tag(db, rid, tag_id)


def phase_2_protein(db: DBWrapper, group_id: str) -> None:
    """Tag recipes by protein type based on ingredient names (with exclusions)."""
    logger.info("[PHASE 2] Category: Protein")
    for cat, rules in SQL_INGREDIENT_TAGS.items():
        logger.info(f"   [SCAN] {cat}...")
        tag_id = ensure_tag(db, cat, group_id)
        sql = (
            f"SELECT DISTINCT recipe_id FROM recipes_ingredients "
            f"WHERE food_id IN ("
            f"  SELECT id FROM ingredient_foods "
            f"  WHERE name ~* '{rules['regex']}' AND name !~* '{rules['exclude']}'"
            f")"
        )
        recipes = db.execute(sql).fetch_all()
        for (rid,) in recipes:
            link_tag(db, rid, tag_id)


def phase_3_cuisine(db: DBWrapper, group_id: str) -> None:
    """Tag recipes by cuisine, requiring at least 2 matching fingerprint ingredients."""
    logger.info("[PHASE 3] Category: Cuisine")
    for cuisine, regex in SQL_CUISINE_FINGERPRINTS.items():
        logger.info(f"   [SCAN] {cuisine}...")
        tag_id = ensure_tag(db, cuisine, group_id)
        sql = (
            f"SELECT recipe_id FROM recipes_ingredients "
            f"WHERE food_id IN ("
            f"  SELECT id FROM ingredient_foods WHERE name ~* '{regex}'"
            f") GROUP BY recipe_id HAVING COUNT(DISTINCT food_id) >= 2"
        )
        recipes = db.execute(sql).fetch_all()
        for (rid,) in recipes:
            link_tag(db, rid, tag_id)


def phase_4_text(db: DBWrapper, group_id: str) -> None:
    """Tag recipes by keyword matches in recipe name or description."""
    logger.info("[PHASE 4] Category: Text & Metadata")
    for tag, keywords in TEXT_ONLY_TAGS.items():
        logger.info(f"   [SCAN] {tag}...")
        tag_id = ensure_tag(db, tag, group_id)
        safe_kws = [k.replace("'", "''") for k in keywords]
        regex_chain = "|".join([r"\y" + k + r"\y" for k in safe_kws])

        sql = f"SELECT id FROM recipes WHERE name ~* '{regex_chain}' OR description ~* '{regex_chain}'"
        recipes = db.execute(sql).fetch_all()
        for (rid,) in recipes:
            link_tag(db, rid, tag_id)


def phase_5_tools(db: DBWrapper, group_id: str) -> None:
    """Tag recipes with cooking tools based on instruction text."""
    logger.info("[PHASE 5] Category: Tools")
    for tool, keywords in TOOLS_MATCHES.items():
        logger.info(f"   [SCAN] {tool}...")
        tool_id = ensure_tool(db, tool, group_id)
        regex_chain = "|".join([r"\y" + k + r"\y" for k in keywords])
        sql = (
            f"SELECT DISTINCT r.id FROM recipes r "
            f"JOIN recipe_instructions ri ON r.id = ri.recipe_id "
            f"WHERE ri.text ~* '{regex_chain}'"
        )
        recipes = db.execute(sql).fetch_all()
        for (rid,) in recipes:
            link_tool(db, rid, tool_id)


def phase_6_report(db: DBWrapper) -> None:
    """Print a summary report of cuisine tag distribution and untagged recipes."""
    logger.info("")
    logger.info("=" * 40)
    logger.info("[REPORT] SUMMARY")
    logger.info("=" * 40)
    p = db.placeholder

    logger.info("\n[MARKET SHARE]")
    for cuisine in SQL_CUISINE_FINGERPRINTS:
        slug = _make_slug(cuisine)
        count_row = db.execute(
            f"SELECT COUNT(*) FROM recipes_to_tags WHERE tag_id IN (SELECT id FROM tags WHERE slug = {p})",
            (slug,)
        ).fetch_one()
        count = count_row[0] if count_row else 0
        if count > 0:
            logger.info(f" - {cuisine}: {count}")

    ghosts_row = db.execute(
        "SELECT COUNT(*) FROM recipes WHERE id NOT IN (SELECT recipe_id FROM recipes_to_tags)"
    ).fetch_one()
    ghosts = ghosts_row[0] if ghosts_row else "?"
    logger.info(f"\n[AUDIT] Untagged Recipes: {ghosts}")


def main() -> None:
    """Entry point for the KitchenOps Auto-Tagger."""
    logger.info("=" * 50)
    logger.info("  KITCHENOPS AUTO-TAGGER")
    logger.info("=" * 50)
    logger.info(f"  Database : {DB_TYPE.upper()}")
    if DB_TYPE == "sqlite":
        logger.info(f"  DB Path  : {SQLITE_PATH}")
    else:
        logger.info(f"  DB Host  : {PG_HOST}:{PG_PORT}/{PG_DB}")
    logger.info(f"  Dry Run  : {DRY_RUN}")
    logger.info("=" * 50)

    if DRY_RUN:
        logger.info("[INFO] DRY RUN ENABLED: No database changes will be made.")

    db = DBWrapper()
    if not db.conn:
        logger.error("Cannot proceed without a database connection.")
        sys.exit(1)

    try:
        gid = get_group_id(db)
        if not gid:
            logger.error("[FATAL] Group ID not found. Connection failed or DB empty.")
            return

        phase_1_cheese(db, gid)
        phase_2_protein(db, gid)
        phase_3_cuisine(db, gid)
        phase_4_text(db, gid)
        phase_5_tools(db, gid)
        phase_6_report(db)

    except Exception as e:
        logger.error(f"Runtime failure: {e}", exc_info=True)
    finally:
        db.close()
        logger.info("\n--- Operation Complete. Container Exiting. ---")


if __name__ == "__main__":
    main()
