"""
KitchenOps Auto-Tagger v12.7 (Public Release Hybrid)
Tags Mealie recipes by cuisine, protein, cheese, tools, and categories.
Uses the Mealie API for safety, with parallel processing and a Rich UI.
"""

import os
import re
import requests
import logging
import sys
import time
import yaml
from datetime import datetime
from typing import Dict
from concurrent.futures import ThreadPoolExecutor, as_completed

from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn
from rich.theme import Theme

# ==========================================
# 1. UI & LOGGING SETUP
# ==========================================
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

os.makedirs("logs", exist_ok=True)
_fh = logging.FileHandler(f"logs/tagger_{datetime.now().strftime('%Y-%m-%d')}.log")
_fh.setFormatter(logging.Formatter('%(asctime)s | %(message)s', datefmt='%H:%M:%S'))
logger.addHandler(_fh)
logger.setLevel(logging.INFO)

# ==========================================
# 2. DEFAULT DICTIONARIES (Failsafe)
# ==========================================
DEFAULT_CHEESE = {
    "Sharp & Aged": "cheddar|parmesan|pecorino|manchego|asiago|gruyere|comte|aged gouda",
    "Soft & Creamy": "mozzarella|burrata|ricotta|brie|camembert|goat cheese|chèvre|cream cheese|mascarpone|neufchatel",
    "Blue & Funky": "gorgonzola|roquefort|stilton|blue cheese|taleggio|danablu",
    "Fresh & Curd": "paneer|chenna|khoya|feta|halloumi|cotija|queso fresco|cheese curds",
    "Melting Cheese": "provolone|fontina|monterey jack|muenster|gouda|swiss|raclette|havarti|edam|jarlsberg",
}

DEFAULT_PROTEIN = {
    "Chicken": {"regex": "chicken|chicken wing|drumstick|chicken thigh|chicken breast|poultry|cornish hen", "exclude": "broth|stock|bouillon|chickpea"},
    "Beef": {"regex": "beef|steak|hamburger|ground beef|ribeye|sirloin|brisket|chuck roast|filet mignon|short rib|flank steak|ground meat", "exclude": "broth|stock|bouillon|beef leaf"},
    "Pork": {"regex": "pork|bacon|ham hock|ham steak|sausage|pork tenderloin|chorizo|prosciutto|pancetta|guanciale|salami|pork belly|pork chop|pork loin|spare rib|pork shoulder", "exclude": "turkey|chicken|hamburger"},
    "Seafood": {"regex": "shrimp|salmon|tuna|cod fish|cod fillet|lobster|scallop|mussel|clam|fish|prawn|crab|squid|octopus|anchovy|sardine|tilapia|mahi mahi|halibut|swordfish|trout", "exclude": "sauce|stock|fish sauce"},
    "Lamb/Goat": {"regex": "lamb|mutton|goat cheese|gyro|merguez", "exclude": "goat cheese|lettuce"},
    "Game Meat": {"regex": "venison|duck|bison|rabbit|quail|goose|elk|pheasant", "exclude": "sauce|duck sauce"},
    "Egg": {"regex": r"egg|eggs|huevos", "exclude": "plant|noodle"},
    "Vegetarian Protein": {"regex": "tofu|tempeh|seitan|lentil|chickpea|black bean|kidney bean|cannellini|edamame|soy curl", "exclude": "pork|beef|chicken"},
}

DEFAULT_CUISINE = {
    "Chinese (Cantonese)": "oyster sauce|hoisin|shaoxing|char siu|lap cheong|wonton|five spice",
    "Chinese (Sichuan)": "sichuan pepper|doubanjiang|chili oil|mala|dried chili|black vinegar|facing heaven pepper",
    "Japanese": "miso|mirin|dashi|sake|nori|wasabi|furikake|panko|bonito|kombu|shoyu|katsu",
    "Korean": "gochujang|gochugaru|kimchi|doenjang|rice cake|perilla leaf|bulgogi|japchae",
    "Thai": "fish sauce|curry paste|thai basil|kaffir lime|bird's eye chili|nam pla|pad thai",
    "Vietnamese": "fish sauce|star anise|pho|rice paper|vermicelli|nuoc cham|banh mi",
    "Indonesian / Malaysian": "kecap manis|galangal|sambal|shrimp paste|kaffir lime|turmeric leaf|rendang|nasi",
    "Filipino": "calamansi|cane vinegar|banana ketchup|ube|bagoong|lumpia|adobo",
    "Indian": "garam masala|paneer|ghee|fenugreek|makhani|tandoori|kashmiri chili|amchur|curry leaf|mustard seed|asafoetida|hing|sambar|rasam|urad dal|appam|puttu",
    "Pakistani": "nihari|karahi|shan masala|chapli|haleem|biryani masala",
    "Mexican": "corn tortilla|masa|tomatillo|poblano|cotija|epazote|pepita|mole|queso fresco|guajillo|ancho chili",
    "Tex-Mex": "flour tortilla|fajita seasoning|fajita|nacho|queso|taco seasoning|refried beans",
    "Peruvian": "aji amarillo|aji panca|quinoa|ceviche|pisco|huacatay|rocoto",
    "Brazilian": "dende oil|cassava flour|farofa|cachaca|guarana|tucupi|pao de queijo",
    "US Southern": "buttermilk|collard greens|cornmeal|grits|okra|bacon grease|cajun|creole|andouille|remoulade",
    "Caribbean": "scotch bonnet|jerk seasoning|jerk|plantain|callaloo|allspice|ackee|sorrel",
    "Italian": "pecorino|parmesan|risotto|polenta|balsamic|prosciutto|gorgonzola|truffle|pancetta|nduja|focaccia|pesto",
    "French": "herbes de provence|dijon|tarragon|cognac|gruyere|creme fraiche|bouquet garni|fleur de sel",
    "Spanish": "saffron|chorizo|manchego|sherry|paella|iberico|pimenton|romesco",
    "Greek": "feta|kalamata|phyllo|halloumi|tzatziki|oregano|greek yogurt",
    "German": "sauerkraut|bratwurst|caraway|schnitzel|spaetzle|pretzel|juniper berry",
    "British / Irish": "malt vinegar|english mustard|worcestershire|stilton|golden syrup|stout|guinness|clotted cream|marmite",
    "Eastern European": "pierogi|kielbasa|sauerkraut|poppy seed|borscht|kvass",
    "Levantine (Middle Eastern)": "tahini|za'atar|sumac|bulgur|pomegranate molasses|halva|labneh|freekeh",
    "Persian (Iranian)": "rose water|barberry|dried lime|pomegranate molasses|tahdig|saffron|zereshk",
    "North African (Maghreb)": "preserved lemon|ras el hanout|tagine|harissa|merguez|chermoula",
    "East African (Ethiopian)": "berbere|niter kibbeh|injera|teff|mitmita|awaze",
    "West African": "scotch bonnet|egusi|fufu|jollof|red palm oil|suya|dawadawa",
}

DEFAULT_TEXT = {
    "Extra Spicy": ["extra spicy", "insane heat", "ghost pepper", "habanero", "thai chili", "bird's eye", "scotch bonnet", "carolina reaper", "vindaloo", "phaal"],
    "Spicy": ["spicy", "jalapeno", "hot sauce", "sriracha", "chili flakes", "serrano", "cayenne", "gochujang", "harissa", "sambal", "peri peri"],
    "Comfort Food": ["mac and cheese", "casserole", "meatloaf", "gravy", "pot pie", "stew", "grilled cheese"],
    "One Pot": ["one pot", "sheet pan", "skillet dinner", "dutch oven"],
    "Project Meal": ["sourdough", "ferment", "cure", "smoke", "braise", "confit", "mole"],
    "Vegan": ["vegan", "plant based", "plant-based"],
    "Keto": ["keto", "ketogenic", "low carb", "low-carb"],
    "Gluten Free": ["gluten free", "gluten-free", "gf"],
    "Paleo": ["paleo", "whole30"]
}

DEFAULT_TOOLS = {
    "Air Fryer": ["air fryer", "air-fryer", "airfryer"],
    "Instant Pot": ["instant pot", "pressure cooker", "multicooker"],
    "Slow Cooker": ["slow cooker", "crock pot"],
    "Dutch Oven": ["dutch oven", "le creuset"],
    "Wok": ["wok"],
    "Cast Iron": ["cast iron", "skillet"],
    "Smoker / Grill": ["smoker", "traeger", "charcoal", "grill", "big green egg"],
    "Sous Vide": ["sous vide", "immersion circulator"],
}

DEFAULT_CATEGORIES = [
    ("Beverage", ["smoothie", "shake", "latte", "lemonade", "lassi", "punch", "tea", "coffee", "cider", "cocoa", "soda", "limeade", "agua fresca", "julius", "frappe", "chai", "milkshake", "mocha", "cold brew", "cappuccino", "espresso", "macchiato", "cocktail", "mocktail", "margarita", "martini", "mojito", "sangria", "piña colada", "mimosa", "shot", "julep", "bellini", "irish cream", "drunken", "slushie", "spritzer", "fizz", "sour", "collins", "toddy", "old fashioned", "negroni", "daiquiri", "buttermilk", "sambaram"]),
    ("Condiment", ["sauce", "rub", "marinade", "pesto", "dressing", "dip", "hummus", "salsa", "jam", "jelly", "pickle", "syrup", "chutney", "relish", "vinaigrette", "glaze", "reduction", "compote", "curd", "butter", "oil", "spice mix", "seasoning", "paste", "spread", "mayonnaise", "ketchup", "mustard", "bbq sauce", "aioli", "remoulade", "sriracha", "gochujang", "harissa"]),
    ("Dessert", ["dessert", "cake", "cookie", "brownie", "fudge", "ice cream", "pudding", "pie", "tart", "sorbet", "gelato", "candy", "chocolate", "truffle", "donut", "doughnut", "shortcake", "cheesecake", "pastry", "postre", "dulce", "galleta", "helado", "paleta", "cinnabunny", "cinnamon roll", "toffee", "pop", "popsicle", "burfi", "jalebi", "sandesh", "sondesh", "panjeeri", "panjiri", "sheera", "caramel", "gummies", "apple dumpling", "crisp", "bunuelos", "tamales dulces", "gelatina", "pay de calabaza", "creamsicle", "mousse", "parfait", "scone", "biscotti", "cobbler", "buckeye", "blondie", "cupcake", "macaron", "meringue", "pavlova", "trifle", "turnover", "strudel", "ambrosia", "kheer", "halwa", "ladoo", "gulab jamun"]),
    ("Breakfast", ["pancake", "waffle", "oats", "oatmeal", "breakfast", "omelet", "scramble", "french toast", "granola", "cereal", "crepe", "hot cake", "muesli", "bagel", "benedict", "hash", "frittata", "quiche", "huevos rancheros", "shakshuka", "idli", "dosa", "vada", "uttapam", "appam", "puttu", "idi appam", "upma"]),
    ("Snack", ["snack", "bite", "energy bite", "energy ball", "pecan", "nut", "mix", "chestnut", "cottage cheese", "bistro box", "popcorn", "chips", "cracker", "dip", "chex mix", "trail mix", "granola bar", "jerky", "deviled egg", "nacho", "finger food", "appetizer", "murukku", "samosa", "pakora"]),
    ("Bread", ["bread", "loaf", "roll", "bun", "baguette", "ciabatta", "focaccia", "sourdough", "flatbread", "pita", "toast", "muffin", "pretzel", "breadstick", "mollete", "naan", "tortilla", "biscuit", "roti", "chapati", "paratha", "kulcha", "pav"]),
    ("Soup", ["soup", "stew", "chowder", "chili", "bisque", "pozole", "ramen", "pho", "stock", "broth", "gazpacho", "consumme", "minestrone", "gumbo", "bouillabaisse", "vysusuoise"]),
    ("Salad", ["salad", "slaw", "coleslaw", "caesar", "caprese", "waldorf", "wedge", "cobb", "niçoise", "tabbouleh"]),
    ("Side Dish", ["side dish", "side", "fries", "wedges", "tots", "rice", "vegetable", "veggie", "corn", "bean", "succotash", "asparagus", "broccoli", "carrot", "cauliflower", "zucchini", "mushroom", "onion", "parsnip", "plantain", "grits", "stuffing", "borlotti", "eggplant", "potato", "yam", "gnocchi", "au gratin", "mash", "puree", "pilaf", "couscous", "quinoa", "thoran", "poriyal", "dal", "sambal"]),
    ("Main Course", ["chicken", "beef", "pork", "steak", "burger", "roast", "stew", "curry", "pizza", "pasta", "lasagna", "spaghetti", "fettuccine", "risotto", "casserole", "enchilada", "burrito", "taco", "fajita", "quesadilla", "meatball", "meatloaf", "ribs", "brisket", "pulled pork", "carnitas", "chop", "tenderloin", "salmon", "tuna", "cod", "halibut", "shrimp", "lobster", "crab", "fish", "tofu", "tempeh", "seitan", "stir fry", "pad thai", "lo mein", "soup", "chili", "chowder", "bisque", "pozole", "ramen", "pho", "udon", "sandwich", "wrap", "gyro", "shawarma", "kebab", "falafel", "biryani", "paella", "jambalaya", "gumbo", "etouffee", "shepherd's pie", "pot pie", "london broil", "empanada", "tamale", "sushi", "sashimi", "poke bowl", "bibimbap", "bulgogi", "macaroni", "ziti", "alfredo", "carbonara", "bolognese", "stroganoff", "vindaloo", "korma", "tikka"])
]

# ==========================================
# 3. CONFIGURATION LOADING
# ==========================================
def load_environment():
    env_path = os.path.join(os.getcwd(), 'config.env')
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line.startswith('export '):
                    line = line.replace('export ', '', 1).split('#')[0].strip()
                    if '=' in line:
                        k, v = line.split('=', 1)
                        os.environ[k] = v.strip().strip('"').strip("'")

load_environment()

MEALIE_URL = os.getenv("MEALIE_URL", "http://localhost:9000").rstrip('/')
# API Token configuration
API_TOKEN = os.getenv("MEALIE_API_TOKEN")
DRY_RUN = os.getenv("DRY_RUN", "True").lower() == "true"
MIN_CUISINE_MATCHES = 3

try:
    MAX_WORKERS = int(os.getenv("MAX_WORKERS", "4")) 
except (ValueError, TypeError):
    MAX_WORKERS = 4

try:
    with open("config/tagging.yaml", "r") as f:
        CONFIG = yaml.safe_load(f) or {}
        console.print("[info]Loaded custom rules from config/tagging.yaml[/info]")
except FileNotFoundError:
    # Intentionally silent on FileNotFoundError so as not to clutter standard usage
    CONFIG = {}
except Exception as e:
    console.print(f"[warning]Error reading config/tagging.yaml ({e}). Falling back to built-in default tags...[/warning]")
    CONFIG = {}

CHEESE_TYPES = CONFIG.get("cheese_types", DEFAULT_CHEESE)
PROTEIN_TAGS = CONFIG.get("protein_tags", DEFAULT_PROTEIN)
CUISINE_FINGERPRINTS = CONFIG.get("cuisine_fingerprints", DEFAULT_CUISINE)
TEXT_ONLY_TAGS = CONFIG.get("text_tags", DEFAULT_TEXT)
TOOLS_MATCHES = CONFIG.get("tools_matches", DEFAULT_TOOLS)
CATEGORY_WATERFALL = CONFIG.get("categories", DEFAULT_CATEGORIES)

# ==========================================
# 4. CORE LOGIC & UTILITIES
# ==========================================
def fetch_all_summaries(headers):
    all_items = []
    page, per_page = 1, 500
    try:
        with console.status("[bold green]Fetching recipe list from Mealie...") as status:
            while True:
                try:
                    url = f"{MEALIE_URL}/api/recipes?page={page}&perPage={per_page}"
                    r = requests.get(url, headers=headers, timeout=30)
                    r.raise_for_status()
                    items = r.json().get('items', [])
                    if not items: break
                    all_items.extend(items)
                    status.update(f"[bold green]Fetched {len(all_items)} summaries...")
                    if len(items) < per_page: break
                    page += 1
                except Exception as e:
                    console.print(f"[error]Fetch error on page {page}: {e}[/error]")
                    sys.exit(1)
    except KeyboardInterrupt:
        console.print("\n[warning]🛑 Interrupted by user during fetch. Exiting cleanly...[/warning]")
        sys.exit(1)
        
    return all_items

def check_match(text: str, include_regex: str, exclude_regex: str = None) -> bool:
    include_regex = include_regex.replace(r'\y', r'\b')
    if not re.search(fr"\b({include_regex})\b", text, re.I):
        return False
    if exclude_regex:
        exclude_regex = exclude_regex.replace(r'\y', r'\b')
        if re.search(fr"\b({exclude_regex})\b", text, re.I):
            return False
    return True

def process_single_recipe(summary: Dict, headers: Dict):
    slug = summary['slug']
    result = {"slug": slug, "tags_added": [], "cats_added": [], "tools_added": [], "error": False}
    
    try:
        resp = requests.get(f"{MEALIE_URL}/api/recipes/{slug}", headers=headers, timeout=15)
        recipe = resp.json()
        
        # Text Blobs
        ing_text = " ".join([(i.get('food') or {}).get('name', '') + " " + i.get('note', '') for i in recipe.get('recipeIngredients', [])])
        inst_text = " ".join([step.get('text', '') for step in recipe.get('recipeInstructions', [])])
        cat_text = f"{recipe.get('name', '')} {slug}"
        
        current_tags = {t['name'] for t in recipe.get('tags', [])}
        original_tags = set(current_tags)
        
        current_cats = {c['name'] for c in recipe.get('categories', [])}
        original_cats = set(current_cats)
        
        current_tools = {t['name'] for t in recipe.get('tools', [])}
        original_tools = set(current_tools)

        # 1. Proteins
        for tag, rules in PROTEIN_TAGS.items():
            if check_match(ing_text, rules.get('regex', ''), rules.get('exclude')):
                current_tags.add(tag)

        # 2. Cheese
        for tag, regex in CHEESE_TYPES.items():
            if check_match(ing_text, regex):
                current_tags.add(tag)

        # 3. Cuisine
        for cuisine, regex in CUISINE_FINGERPRINTS.items():
            matches = len(re.findall(fr"\b({regex})\b", ing_text, re.I))
            if matches >= MIN_CUISINE_MATCHES:
                current_tags.add(cuisine)
                
        # 4. Text Tags
        for tag, keywords in TEXT_ONLY_TAGS.items():
            chain = "|".join(keywords).replace("'", "''")
            if check_match(cat_text, chain): 
                current_tags.add(tag)

        # 5. Tools
        for tool, keywords in TOOLS_MATCHES.items():
            chain = "|".join(keywords)
            if check_match(inst_text, chain):
                current_tools.add(tool)

        # 6. Categories (Waterfall)
        if not current_cats:
            for cat in CATEGORY_WATERFALL:
                cat_name = cat[0] if isinstance(cat, (list, tuple)) else list(cat.keys())[0]
                keywords = cat[1] if isinstance(cat, (list, tuple)) else list(cat.values())[0]
                
                pattern = "|".join(keywords).replace("'", "''")
                if check_match(cat_text, pattern):
                    current_cats.add(cat_name)
                    break 

        updates = {}
        if current_tags != original_tags:
            updates["tags"] = [{"name": t} for t in current_tags]
            result["tags_added"] = list(current_tags - original_tags)
            
        if current_cats != original_cats:
            updates["categories"] = [{"name": c} for c in current_cats]
            result["cats_added"] = list(current_cats - original_cats)
            
        if current_tools != original_tools:
            updates["tools"] = [{"name": t} for t in current_tools]
            result["tools_added"] = list(current_tools - original_tools)

        if updates and not DRY_RUN:
            requests.patch(f"{MEALIE_URL}/api/recipes/{slug}", json=updates, headers=headers, timeout=15)
            
        return result
    except Exception as e:
        logger.error(f"Error processing {slug}: {e}")
        result["error"] = True
        return result

def format_elapsed(seconds: float) -> str:
    s = int(seconds)
    if s >= 3600: return f"{s // 3600}h {(s % 3600) // 60}m"
    if s >= 60: return f"{s // 60}m {s % 60}s"
    return f"{s}s"

# ==========================================
# 5. ORCHESTRATOR & REPORT
# ==========================================
def main():
    console.rule("[bold cyan]KitchenOps Auto-Tagger (API Edition)[/bold cyan]")
    
    if not API_TOKEN:
        console.print("[error]No API_TOKEN found in config.env! Cannot proceed.[/error]")
        sys.exit(1)

    headers = {"Authorization": f"Bearer {API_TOKEN}"}
    start_time = time.time()
    
    summaries = fetch_all_summaries(headers)
    total = len(summaries)
    if total == 0:
        console.print("[warning]No recipes found on the server.[/warning]")
        sys.exit(0)

    updated_count = 0
    cuisine_counts = {c: 0 for c in CUISINE_FINGERPRINTS.keys()}
    untagged_count = 0
    
    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            console=console
        ) as progress:
            task = progress.add_task(f"Tagging {total} recipes...", total=total)
            
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                futures = {executor.submit(process_single_recipe, s, headers): s for s in summaries}
                
                for future in as_completed(futures):
                    res = future.result()
                    
                    if res["tags_added"] or res["cats_added"] or res["tools_added"]:
                        updated_count += 1
                        
                    if not res["tags_added"] and not futures[future].get('tags'):
                        untagged_count += 1

                    for tag in res["tags_added"]:
                        if tag in cuisine_counts:
                            cuisine_counts[tag] += 1
                            
                    progress.update(task, advance=1, description=f"Updated: {updated_count} | Total: {total}")
    except KeyboardInterrupt:
        executor.shutdown(wait=False, cancel_futures=True)
        console.print("\n[warning]🛑 Interrupted by user during tagging. Shutting down cleanly...[/warning]")
        sys.exit(1)

    # Final Report Output
    console.print("\n")
    table = Table(title="Cuisine Market Share (New Additions)")
    table.add_column("Cuisine", style="cyan")
    table.add_column("Added", style="green", justify="right")
    
    for cuisine, count in sorted(cuisine_counts.items(), key=lambda x: x[1], reverse=True):
        if count > 0:
            table.add_row(cuisine, str(count))
            
    if table.row_count > 0:
        console.print(table)
        
    console.print(f"\n[bold red]Untagged Recipes Left (Approx):[/bold red] {untagged_count}")

    elapsed = time.time() - start_time
    console.print(f"\n⏱️  Elapsed: {format_elapsed(elapsed)}")
    logger.info(f"Complete | Updated: {updated_count} | Elapsed: {format_elapsed(elapsed)}")
    console.rule("[bold green]Complete[/bold green]")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[warning]🛑 Script interrupted by user. Exiting cleanly...[/warning]")
        sys.exit(1)