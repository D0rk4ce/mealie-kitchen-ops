import subprocess
import re
import os
import sys
import uuid
import sqlite3
import datetime

# --- CONFIGURATION ---
DB_TYPE = os.getenv("DB_TYPE", "sqlite") 
DB_NAME = os.getenv("DB_NAME", "mealie_db")
SQLITE_PATH = os.getenv("SQLITE_PATH", "/app/data/mealie.db")
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true" # Default: Safety On

TAG_LINK_TABLE = "recipes_to_tags"
TOOL_LINK_TABLE = "recipes_to_tools"

# --- ADAPTERS ---
def cast_uuid(val_str):
    return f"'{val_str}'::uuid" if DB_TYPE == "postgres" else f"'{val_str}'"

def get_regex_op():
    return "~*" if DB_TYPE == "postgres" else "REGEXP"

def get_not_op():
    return "!~*" if DB_TYPE == "postgres" else "NOT REGEXP"

def escape_sql(val):
    return val.replace("'", "''")

def generate_uuid():
    return str(uuid.uuid4())

def get_now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# --- DATA DICTIONARIES (Abbreviated for clarity, full list in repo) ---
CHEESE_TYPES = {
    "Blue & Funky": "gorgonzola|roquefort|stilton|blue cheese|taleggio|danablu",
    "Fresh & Curd": "paneer|chenna|khoya|feta|halloumi|cotija|queso fresco|cheese curds",
    "Melting Cheese": "provolone|fontina|monterey jack|muenster|gouda|swiss|raclette|havarti|edam|jarlsberg",
    "Sharp & Aged": "cheddar|parmesan|pecorino|manchego|asiago|gruyere|comte|aged gouda",
    "Soft & Creamy": "mozzarella|burrata|ricotta|brie|camembert|goat cheese|chèvre|cream cheese|mascarpone|neufchatel"
}

SQL_INGREDIENT_TAGS = {
    "Beef": { "regex": "beef|steak|hamburger|ground meat|ribeye|sirloin|brisket|chuck roast|filet|short rib", "exclude": "broth|stock|bouillon" },
    "Chicken": { "regex": "chicken|wing|drumstick|thigh|breast|poultry|cornish hen", "exclude": "broth|stock|bouillon" },
    "Game Meat": { "regex": "venison|duck|bison|rabbit|quail|goose|elk", "exclude": "sauce" },
    "Lamb/Goat": { "regex": "lamb|mutton|goat|gyro|merguez", "exclude": "lettuce" },
    "Pork": { "regex": "pork|bacon|ham|sausage|tenderloin|chorizo|prosciutto|pancetta|guanciale|salami|pork belly", "exclude": "turkey|chicken" },
    "Seafood": { "regex": "shrimp|salmon|tuna|cod|lobster|scallop|mussel|clam|fish|prawn|crab|squid|octopus|anchovy|sardine|tilapia|mahi", "exclude": "sauce|stock" },
    "Vegetarian Protein": { "regex": "tofu|tempeh|seitan|lentil|chickpea|black bean|kidney bean|cannellini|edamame", "exclude": "pork|beef|chicken" }
}

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
    "Indian (North)": "garam masala|paneer|ghee|fenugreek|heavy cream|makhani|tandoori|kashmiri chili|amchur",
    "Indian (South)": "curry leaf|mustard seed|coconut oil|tamarind|gunpowder|sambar|rasam|urad dal|asafoetida|hing",
    "Indonesian / Malaysian": "kecap manis|galangal|sambal|shrimp paste|tempeh|lemongrass|kaffir lime|turmeric leaf",
    "Italian (Northern)": "butter|heavy cream|parmesan|risotto|polenta|balsamic|prosciutto|sage|gorgonzola|truffle",
    "Italian (Southern)": "olive oil|basil|oregano|mozzarella|tomato|capers|anchovy|pecorino",
    "Japanese": "miso|mirin|dashi|sake|nori|wasabi|furikake|panko|bonito|kombu|shoyu",
    "Kerala / Coastal": "kerala|malabar|kochi|meen curry|appam|puttu|stew|coconut milk|pearl spot",
    "Korean": "gochujang|gochugaru|kimchi|doenjang|rice cake|sesame oil|perilla leaf",
    "Levantine (Middle Eastern)": "tahini|za''atar|sumac|chickpea|bulgur|pomegranate molasses|halva|feta",
    "Mexican (Authentic)": "corn tortilla|masa|tomatillo|poblano|jalapeno|cotija|cilantro|mole|epazote|pepita",
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
    "Substitute American Cheese": ["american cheese", "kraft singles", "processed cheese", "velveeta"],
    "Substitute Ketchup": ["ketchup", "catsup"],
    "Vegan": ["vegan", "plant based"]
}

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

# --- DATABASE ENGINE ---
def run_query(sql, fetch=False):
    if DRY_RUN and not fetch and "INSERT" in sql.upper():
        return True

    if DB_TYPE == "postgres":
        try:
            sql_clean = sql.replace('\n', ' ')
            args = ["psql", "-d", DB_NAME, "-t", "-A", "-c", sql_clean]
            result = subprocess.run(args, capture_output=True, text=True, check=True)
            if fetch:
                raw = result.stdout.strip()
                return raw.split('\n') if raw else []
            return True
        except subprocess.CalledProcessError as e:
            print(f"[ERROR] Postgres: {e.stderr.strip()}")
            return None

    elif DB_TYPE == "sqlite":
        try:
            with sqlite3.connect(SQLITE_PATH) as conn:
                conn.create_function("REGEXP", 2, lambda x, y: 1 if y and x and re.search(y, x, re.IGNORECASE) else 0)
                cursor = conn.cursor()
                cursor.execute(sql)
                if fetch:
                    return [str(row[0]) if len(row) == 1 else '|'.join(map(str, row)) for row in cursor.fetchall()]
                conn.commit()
                return True
        except Exception as e:
            print(f"[ERROR] SQLite: {e}")
            return None

def ensure_tag_exists(tag_name, group_id):
    slug = tag_name.lower().replace(" ", "-").replace("/", "-").replace("&", "and")
    existing_id = run_query(f"SELECT id FROM tags WHERE slug = '{slug}' AND group_id = '{group_id}'", fetch=True)
    if existing_id: return existing_id[0]
    
    if DRY_RUN:
        print(f"[DRY RUN] Would Create Tag: {tag_name}")
        return "00000000-0000-0000-0000-000000000000"

    print(f"[INFO] Creating Tag: {tag_name}")
    new_id = generate_uuid()
    now = get_now()
    id_val = cast_uuid(new_id)
    sql = f"INSERT INTO tags (id, group_id, name, slug, created_at, update_at) VALUES ({id_val}, '{group_id}', '{tag_name}', '{slug}', '{now}', '{now}');"
    run_query(sql)
    return new_id

def ensure_tool_exists(tool_name, group_id):
    slug = tool_name.lower().replace(" ", "-")
    existing_id = run_query(f"SELECT id FROM tools WHERE slug = '{slug}' AND group_id = '{group_id}'", fetch=True)
    if existing_id: return existing_id[0]
    
    if DRY_RUN:
        print(f"[DRY RUN] Would Create Tool: {tool_name}")
        return "00000000-0000-0000-0000-000000000000"

    print(f"[INFO] Creating Tool: {tool_name}")
    new_id = generate_uuid()
    now = get_now()
    id_val = cast_uuid(new_id)
    sql = f"INSERT INTO tools (id, group_id, name, slug, on_hand, created_at, update_at) VALUES ({id_val}, '{group_id}', '{tool_name}', '{slug}', FALSE, '{now}', '{now}');"
    run_query(sql)
    return new_id

# --- LOGIC ---
def process_cheese_vault(group_id):
    print("\n[PHASE 1] Cheese Categorization")
    op = get_regex_op()
    for category in sorted(CHEESE_TYPES.keys()):
        regex = CHEESE_TYPES[category]
        tag_id = ensure_tag_exists(category, group_id)
        tag_val = cast_uuid(tag_id)
        if DRY_RUN: print(f"   [DRY RUN] Scanning for {category}...")
        else:
            sql = f"""
                INSERT INTO {TAG_LINK_TABLE} (recipe_id, tag_id)
                SELECT DISTINCT recipe_id, {tag_val}
                FROM recipes_ingredients
                WHERE food_id IN (SELECT id FROM ingredient_foods WHERE name {op} '{escape_sql(regex)}')
                AND recipe_id NOT IN (SELECT recipe_id FROM {TAG_LINK_TABLE} WHERE tag_id = {tag_val});
            """
            run_query(sql)
            print(f"   [OK] Processed: {category}")

def process_sql_ingredients(group_id):
    print("\n[PHASE 2] Protein Classification")
    op = get_regex_op()
    not_op = get_not_op()
    for tag_name in sorted(SQL_INGREDIENT_TAGS.keys()):
        rules = SQL_INGREDIENT_TAGS[tag_name]
        tag_id = ensure_tag_exists(tag_name, group_id)
        tag_val = cast_uuid(tag_id)
        if DRY_RUN: print(f"   [DRY RUN] Scanning for {tag_name}...")
        else:
            sql = f"""
                INSERT INTO {TAG_LINK_TABLE} (recipe_id, tag_id)
                SELECT DISTINCT recipe_id, {tag_val}
                FROM recipes_ingredients 
                WHERE food_id IN (SELECT id FROM ingredient_foods WHERE name {op} '{escape_sql(rules['regex'])}' AND name {not_op} '{escape_sql(rules['exclude'])}')
                AND recipe_id NOT IN (SELECT recipe_id FROM {TAG_LINK_TABLE} WHERE tag_id = {tag_val});
            """
            run_query(sql)
            print(f"   [OK] Processed: {tag_name}")

def process_cuisine_fingerprinting(group_id):
    print("\n[PHASE 3] World Cuisine Fingerprinting")
    op = get_regex_op()
    for cuisine in sorted(SQL_CUISINE_FINGERPRINTS.keys()):
        regex = SQL_CUISINE_FINGERPRINTS[cuisine]
        tag_id = ensure_tag_exists(cuisine, group_id)
        tag_val = cast_uuid(tag_id)
        if DRY_RUN: print(f"   [DRY RUN] Scanning for {cuisine}...")
        else:
            sql = f"""
                INSERT INTO {TAG_LINK_TABLE} (recipe_id, tag_id)
                SELECT recipe_id, {tag_val}
                FROM recipes_ingredients
                WHERE food_id IN (SELECT id FROM ingredient_foods WHERE name {op} '{escape_sql(regex)}')
                GROUP BY recipe_id
                HAVING COUNT(DISTINCT food_id) >= 2
            """
            if DB_TYPE == "postgres": sql += " ON CONFLICT DO NOTHING;"
            else: sql = f"INSERT OR IGNORE {sql[7:]};"
            run_query(sql)
            print(f"   [OK] Fingerprinted: {cuisine}")

def process_text_tags(group_id):
    print("\n[PHASE 4] Flavor & Diet Profiles")
    op = get_regex_op()
    for tag_name in sorted(TEXT_ONLY_TAGS.keys()):
        keywords = TEXT_ONLY_TAGS[tag_name]
        tag_id = ensure_tag_exists(tag_name, group_id)
        tag_val = cast_uuid(tag_id)
        if DRY_RUN: print(f"   [DRY RUN] Scanning for {tag_name}...")
        else:
            safe_kw = [escape_sql(kw) for kw in keywords]
            fmt = "'\\y{kw}\\y'" if DB_TYPE == 'postgres' else "'{kw}'"
            conditions = [f"name {op} {fmt.format(kw=kw)} OR slug {op} {fmt.format(kw=kw)}" for kw in safe_kw]
            sql = f"""
                INSERT INTO {TAG_LINK_TABLE} (recipe_id, tag_id)
                SELECT id, {tag_val} FROM recipes WHERE ({' OR '.join(conditions)})
                AND id NOT IN (SELECT recipe_id FROM {TAG_LINK_TABLE} WHERE tag_id = {tag_val});
            """
            run_query(sql)
            print(f"   [OK] Tagged: {tag_name}")

def process_tools(group_id):
    print("\n[PHASE 5] Equipment Detection")
    op = get_regex_op()
    for tool_name in sorted(TOOLS_MATCHES.keys()):
        keywords = TOOLS_MATCHES[tool_name]
        tool_id = ensure_tool_exists(tool_name, group_id)
        tool_val = cast_uuid(tool_id)
        if DRY_RUN: print(f"   [DRY RUN] Scanning for {tool_name}...")
        else:
            safe_kw = [escape_sql(kw) for kw in keywords]
            conditions = [f"text {op} '{kw}'" for kw in safe_kw]
            sql = f"""
                INSERT INTO {TOOL_LINK_TABLE} (recipe_id, tool_id)
                SELECT DISTINCT recipe_id, {tool_val} FROM recipe_instructions 
                WHERE ({' OR '.join(conditions)})
                AND recipe_id NOT IN (SELECT recipe_id FROM {TOOL_LINK_TABLE} WHERE tool_id = {tool_val});
            """
            run_query(sql)
            print(f"   [OK] Linked: {tool_name}")

def main():
    print(f"--- KITCHENOPS UNIVERSAL TAGGER 6.1 (Mode: {DB_TYPE.upper()}) ---")
    if DRY_RUN: print("[INFO] DRY RUN ENABLED: No database changes will be made.")
    
    gid_row = run_query("SELECT id FROM groups LIMIT 1", fetch=True)
    if not gid_row:
        print("[FATAL] Group ID not found. Connection failed or DB empty.")
        return
    group_id = gid_row[0]

    process_cheese_vault(group_id)
    process_sql_ingredients(group_id)
    process_cuisine_fingerprinting(group_id)
    process_text_tags(group_id)
    process_tools(group_id)

    if not DRY_RUN:
        print("\n[REPORT] Cuisine Market Share:")
        stats = []
        for cuisine in SQL_CUISINE_FINGERPRINTS.keys():
            slug = cuisine.lower().replace(" ", "-").replace("/", "-")
            res = run_query(f"SELECT COUNT(*) FROM {TAG_LINK_TABLE} WHERE tag_id IN (SELECT id FROM tags WHERE slug = '{slug}')", fetch=True)
            count = int(res[0].split('|')[0]) if res and res[0] else 0
            if count > 0: stats.append((cuisine, count))
        for c, count in sorted(stats, key=lambda x: x[1], reverse=True):
            print(f"   - {c}: {count}")

        untagged_res = run_query(f"SELECT COUNT(*) FROM recipes WHERE id NOT IN (SELECT recipe_id FROM {TAG_LINK_TABLE})", fetch=True)
        print(f"\n[WARN] {untagged_res[0] if untagged_res else 0} recipes have ZERO tags.")

    print("-" * 40 + "\nCycle Complete.")

if __name__ == "__main__":
    main()
