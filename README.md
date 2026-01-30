# KitchenOps 🔪
**The Advanced Automation Suite for Mealie**

KitchenOps is a production-ready set of maintenance tools for [Mealie](https://mealie.io/). It automates the organization, standardization, and sanitation of large recipe libraries.

## 🚀 The Suite

### 1. Auto-Tagger (`kitchen_ops_tagger.py`)
**"The Organizer"**
A dual-engine tool that scans your database and applies intelligent tags. It supports both **SQLite** (Default) and **PostgreSQL**.
* **World Fingerprints:** Detects 30+ cuisines based on ingredient signatures (e.g., *Kerala/Coastal*, *Sichuan*, *Tex-Mex*).
* **Phase Analysis:** Sorts cheeses, proteins, and diets (Keto/Vegan).
* **Equipment Scan:** Finds Air Fryers, Sous Vides, etc., in instructions.

### 2. Batch Parser (`kitchen_ops_parser.py`)
**"The Fixer"**
A multi-threaded worker that fixes "unparsed" ingredients using Mealie's local NLP engine.
* **Smart Parsing:** Scans for raw strings and converts them to structured objects.
* **AI Fallback:** Gracefully handles OpenAI escalations (if configured), or skips if unavailable.
* **Performance:** Fully configurable worker threads to respect server load.

### 3. Library Cleaner (`kitchen_ops_cleaner.py`)
**"The Janitor"**
Scans for "junk" content and broken imports.
* **Pattern Matching:** Removes blog posts, listicles ("10 Best..."), and non-recipe URLs.
* **Integrity Check:** Verifies that recipes actually have instructions. Empty recipes are flagged or removed.
* **Safe Mode:** All deletions are simulated by default (`DRY_RUN=true`).

---

## ⚙️ Configuration

The suite is configured via a single `.env` file.

| Feature | Variable | Default | Description |
| :--- | :--- | :--- | :--- |
| **Safety** | `DRY_RUN` | `true` | Set to `false` to apply changes. |
| **Launcher** | `SCRIPT_TO_RUN` | `tagger` | Choose `tagger`, `parser`, `cleaner`, or `all`. |
| **Connection** | `MEALIE_URL` | - | Your Mealie address (e.g., `http://localhost:9000`). |
| **Connection** | `MEALIE_API_TOKEN` | - | Long-lived API token from User Profile. |
| **Performance** | `PARSER_WORKERS` | `2` | Threads for NLP parsing. Set higher (5+) for powerful servers. |
| **Performance** | `CLEANER_WORKERS` | `2` | Threads for integrity scanning. |
| **Database** | `DB_TYPE` | `sqlite` | Switch to `postgres` for advanced setups. |

---

## 📦 Installation & Usage

### Method 1: Docker Compose (Recommended)
The easiest way to run the suite without installing Python dependencies manually.

**1. Setup**
```yaml
# docker-compose.yml
services:
  kitchen-ops:
    image: python:3.11-alpine
    volumes:
      - ./data:/app/data  # Mount your Mealie data if using SQLite
      - .:/app            # Mount scripts
    env_file: .env
```

**2. Run Tasks**
```bash
# Run the tool specified in .env
docker-compose up

# Override manually
docker-compose run -e SCRIPT_TO_RUN=cleaner kitchen-ops
```

### Method 2: Manual / Bare Metal
If you prefer running scripts directly on your host.

**1. Install Dependencies**
```bash
git clone https://github.com/yourusername/kitchen-ops.git
cd kitchen-ops
pip install -r requirements.txt
```

**2. Configure**
Create your `.env` file:
```bash
MEALIE_URL=http://localhost:9000
MEALIE_API_TOKEN=your_token
DB_TYPE=sqlite
SQLITE_PATH=/path/to/mealie.db
DRY_RUN=true
```

**3. Run**
```bash
# Standard Run
python3 kitchen_ops_tagger.py

# High-Performance Run (Overriding defaults)
export PARSER_WORKERS=8
export DRY_RUN=false
python3 kitchen_ops_parser.py
```

## 🤝 Contributing
Issues and Pull Requests are welcome. Please ensure all new logic includes `DRY_RUN` checks.

## 📄 License
MIT License.
