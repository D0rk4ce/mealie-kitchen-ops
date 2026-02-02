import os
import sys
import re
import uuid

# --- CONFIGURATION ---
DRY_RUN = os.getenv('DRY_RUN', 'true').lower() == 'true'
DB_TYPE = os.getenv('DB_TYPE', 'sqlite')
SQLITE_PATH = os.getenv('SQLITE_PATH', '/app/data/mealie.db')

# Postgres Credentials
PG_DB = os.getenv('POSTGRES_DB', 'mealie')
PG_USER = os.getenv('POSTGRES_USER', 'mealie')
PG_PASS = os.getenv('POSTGRES_PASSWORD', 'mealie')
PG_HOST = os.getenv('POSTGRES_HOST', 'postgres')
PG_PORT = os.getenv('POSTGRES_PORT', '5432')

# ==========================================
# CONFIGURATION: CHEESE
# ==========================================
CHEESE_TYPES = {
    "Blue & Funky": "gorgonzola|roquefort|stilton|blue cheese|taleggio|danablu",
    "Fresh & Curd": "paneer|chenna|khoya|feta|halloumi|cotija|queso fresco|cheese curds",
    "Melting Cheese": "provolone|fontina|monterey jack|muenster|gouda|swiss|raclette|havarti|edam|jarlsberg",
    "Sharp & Aged": "cheddar|parmesan|pecorino|manchego|asiago|gruyere|comte|aged gouda",
    "Soft & Creamy": "mozzarella|burrata|ricotta|brie|camembert|goat cheese|chèvre|cream cheese|mascarpone|neufchatel"
}

# ==========================================
# CONFIGURATION: PROTEINS (SQL REGEX)
# ==========================================
SQL_INGREDIENT_TAGS = {
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
SQL_CUISINE_FINGERPRINTS = {
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
TEXT_ONLY_TAGS = {
    "Breakfast": ["breakfast", "pancake", "waffle", "omelet", "benedict"],
    "Comfort Food": ["mac and cheese", "casserole", "meatloaf", "gravy", "pot pie", "stew", "grilled cheese"],
    "Dessert": ["dessert", "cake", "cookie", "brownie", "ice cream", "pie"],
    "Extra Spicy": ["extra spicy", "insane heat", "ghost pepper", "habanero", "thai chili", "bird''s eye"],
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
TOOLS_MATCHES = {
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
    def __init__(self):
        self.conn = None
        self.cursor = None
        self.type = DB_TYPE
        
        if self.type == 'postgres':
            import psycopg2
            self.conn = psycopg2.connect(dbname=PG_DB, user=PG_USER, password=PG_PASS, host=PG_HOST, port=PG_PORT)
            self.conn.autocommit = True
        else:
            import sqlite3
            self.conn = sqlite3.connect(SQLITE_PATH)
            # Inject REGEXP function for SQLite
            self.conn.create_function("REGEXP", 2, self._regexp)
        
        self.cursor = self.conn.cursor()

    def _regexp(self, expr, item):
        if item is None: return False
        try:
            # Convert Postgres word boundary \y to Python \b
            clean_expr = expr.replace(r'\y', r'\b')
            reg = re.compile(clean_expr, re.IGNORECASE)
            return reg.search(item) is not None
        except Exception:
            return False

    def execute(self, sql, params=None):
        try:
            # Dialect translation
            if self.type == 'sqlite':
                # Convert Postgres '~*' regex operator to SQLite 'REGEXP'
                sql = re.sub(r"(\w+)\s*~\*\s*('[^']+')", r"\1 REGEXP \2", sql)
                sql = re.sub(r"(\w+)\s*!~\*\s*('[^']+')", r"NOT (\1 REGEXP \2)", sql)
                # Convert gen_random_uuid() to HEX(RANDOMBLOB(16))
                sql = sql.replace("gen_random_uuid()", "lower(hex(randomblob(16)))")
                # Remove Postgres casting '::uuid'
                sql = sql.replace("::uuid", "")
                
            self.cursor.execute(sql, params or [])
            return self # Return self to allow chaining .fetch_all()
        except Exception as e:
            print(f"[ERROR] SQL Failed: {e}")
            return None

    def fetch_one(self):
        return self.cursor.fetchone()

    def fetch_all(self):
        return self.cursor.fetchall()

    def close(self):
        if self.conn: self.conn.close()

# ==========================================
# LOGIC PROCESSORS
# ==========================================

def get_group_id(db):
    db.execute("SELECT id FROM groups LIMIT 1")
    row = db.fetch_one()
    return row[0] if row else None

def ensure_tag(db, name, group_id):
    slug = name.lower().replace(" ", "-").replace("/", "-").replace("&", "and")
    db.execute(f"SELECT id FROM tags WHERE slug = '{slug}'")
    row = db.fetch_one()
    if row: return row[0]

    print(f"   [+] Creating Tag: {name}")
    if not DRY_RUN:
        new_id = str(uuid.uuid4())
        sql = f"INSERT INTO tags (id, group_id, name, slug) VALUES ('{new_id}', '{group_id}', '{name}', '{slug}')"
        db.execute(sql)
        return new_id
    return "dry-run-id"

def ensure_tool(db, name, group_id):
    slug = name.lower().replace(" ", "-")
    db.execute(f"SELECT id FROM tools WHERE slug = '{slug}'")
    row = db.fetch_one()
    if row: return row[0]

    print(f"   [+] Creating Tool: {name}")
    if not DRY_RUN:
        new_id = str(uuid.uuid4())
        sql = f"INSERT INTO tools (id, group_id, name, slug, on_hand) VALUES ('{new_id}', '{group_id}', '{name}', '{slug}', 0)"
        db.execute(sql)
        return new_id
    return "dry-run-id"

def link_tag(db, recipe_id, tag_id):
    if DRY_RUN:
        print(f"   [DRY RUN] Would link Tag ID {tag_id} to Recipe {recipe_id}")
        return
    sql = f"INSERT INTO recipes_to_tags (recipe_id, tag_id) VALUES ('{recipe_id}', '{tag_id}')"
    # Manual Conflict Check to avoid 'ON CONFLICT' syntax diffs
    check = f"SELECT 1 FROM recipes_to_tags WHERE recipe_id='{recipe_id}' AND tag_id='{tag_id}'"
    if not db.execute(check).fetch_one():
        db.execute(sql)

def link_tool(db, recipe_id, tool_id):
    if DRY_RUN:
        print(f"   [DRY RUN] Would link Tool ID {tool_id} to Recipe {recipe_id}")
        return
    sql = f"INSERT INTO recipes_to_tools (recipe_id, tool_id) VALUES ('{recipe_id}', '{tool_id}')"
    check = f"SELECT 1 FROM recipes_to_tools WHERE recipe_id='{recipe_id}' AND tool_id='{tool_id}'"
    if not db.execute(check).fetch_one():
        db.execute(sql)

# --- PHASES ---

def phase_1_cheese(db, group_id):
    print("\n[PHASE 1] Category: Cheese")
    for cat, regex in CHEESE_TYPES.items():
        print(f"   [SCAN] {cat}...")
        tag_id = ensure_tag(db, cat, group_id)
        sql = f"SELECT DISTINCT recipe_id FROM recipes_ingredients WHERE food_id IN (SELECT id FROM ingredient_foods WHERE name ~* '{regex}')"
        recipes = db.execute(sql).fetch_all()
        for (rid,) in recipes:
            link_tag(db, rid, tag_id)

def phase_2_protein(db, group_id):
    print("\n[PHASE 2] Category: Protein")
    for cat, rules in SQL_INGREDIENT_TAGS.items():
        print(f"   [SCAN] {cat}...")
        tag_id = ensure_tag(db, cat, group_id)
        sql = f"SELECT DISTINCT recipe_id FROM recipes_ingredients WHERE food_id IN (SELECT id FROM ingredient_foods WHERE name ~* '{rules['regex']}' AND name !~* '{rules['exclude']}')"
        recipes = db.execute(sql).fetch_all()
        for (rid,) in recipes:
            link_tag(db, rid, tag_id)

def phase_3_cuisine(db, group_id):
    print("\n[PHASE 3] Category: Cuisine")
    for cuisine, regex in SQL_CUISINE_FINGERPRINTS.items():
        print(f"   [SCAN] {cuisine}...")
        tag_id = ensure_tag(db, cuisine, group_id)
        # Must have at least 2 matching ingredients
        sql = f"SELECT recipe_id FROM recipes_ingredients WHERE food_id IN (SELECT id FROM ingredient_foods WHERE name ~* '{regex}') GROUP BY recipe_id HAVING COUNT(DISTINCT food_id) >= 2"
        recipes = db.execute(sql).fetch_all()
        for (rid,) in recipes:
            link_tag(db, rid, tag_id)

def phase_4_text(db, group_id):
    print("\n[PHASE 4] Category: Text & Metadata")
    for tag, keywords in TEXT_ONLY_TAGS.items():
        print(f"   [SCAN] {tag}...")
        tag_id = ensure_tag(db, tag, group_id)
        safe_kws = [k.replace("'", "''") for k in keywords]
        regex_chain = "|".join([r"\y" + k + r"\y" for k in safe_kws])
        
        sql = f"SELECT id FROM recipes WHERE name ~* '{regex_chain}' OR description ~* '{regex_chain}'"
        recipes = db.execute(sql).fetch_all()
        for (rid,) in recipes:
            link_tag(db, rid, tag_id)

def phase_5_tools(db, group_id):
    print("\n[PHASE 5] Category: Tools")
    for tool, keywords in TOOLS_MATCHES.items():
        print(f"   [SCAN] {tool}...")
        tool_id = ensure_tool(db, tool, group_id)
        regex_chain = "|".join([r"\y" + k + r"\y" for k in keywords])
        sql = f"SELECT DISTINCT r.id FROM recipes r JOIN recipe_instructions ri ON r.id = ri.recipe_id WHERE ri.text ~* '{regex_chain}'"
        recipes = db.execute(sql).fetch_all()
        for (rid,) in recipes:
            link_tool(db, rid, tool_id)

def phase_6_report(db):
    print("\n" + "="*40)
    print("[REPORT] SUMMARY")
    print("="*40)
    
    print("\n[MARKET SHARE]")
    for cuisine in SQL_CUISINE_FINGERPRINTS.keys():
        slug = cuisine.lower().replace(" ", "-").replace("/", "-")
        sql = f"SELECT COUNT(*) FROM recipes_to_tags WHERE tag_id IN (SELECT id FROM tags WHERE slug = '{slug}')"
        count = db.execute(sql).fetch_one()[0]
        if count > 0:
            print(f" - {cuisine}: {count}")

    sql = "SELECT COUNT(*) FROM recipes WHERE id NOT IN (SELECT recipe_id FROM recipes_to_tags)"
    ghosts = db.execute(sql).fetch_one()[0]
    print(f"\n[AUDIT] Untagged Recipes: {ghosts}")

def main():
    print(f"--- KITCHENOPS TAGGER (Mode: {DB_TYPE.upper()}) ---")
    if DRY_RUN:
        print("[INFO] DRY RUN ENABLED: No database changes will be made.")
    
    db = DBWrapper()
    if not db.conn:
        sys.exit(1)

    try:
        gid = get_group_id(db)
        if not gid:
            print("[FATAL] Group ID not found. Connection failed or DB empty.")
            return

        phase_1_cheese(db, gid)
        phase_2_protein(db, gid)
        phase_3_cuisine(db, gid)
        phase_4_text(db, gid)
        phase_5_tools(db, gid)
        phase_6_report(db)

    except Exception as e:
        print(f"[ERROR] Runtime Failure: {e}")
    finally:
        db.close()
        print("\n--- Operation Complete. Container Exiting. ---")

if __name__ == "__main__":
    main()
