# KitchenOps 🔪
**The Advanced Automation Suite for Mealie**

KitchenOps is a production-ready set of maintenance tools for [Mealie](https://mealie.io/). It automates the organization, standardization, and sanitation of large recipe libraries.

## 🚀 The Suite

### 1. Auto-Tagger (`kitchen_ops_tagger.py`)
**"The Organizer"**
A dual-engine tool that scans your database and applies intelligent tags. It supports both **SQLite** (Default) and **PostgreSQL**.
* **World Fingerprints:** Detects 30+ cuisines based on ingredient signatures (e.g., *Italian*, *Chinese (Sichuan)*, *Tex-Mex*).
* **Phase Analysis:** Sorts cheeses, proteins, and diets (Keto/Vegan).
* **Equipment Scan:** Finds Air Fryers, Sous Vides, etc., in instructions.

### 2. Batch Parser (`kitchen_ops_parser.py`)
**"The Fixer"**
A multi-threaded worker that fixes "unparsed" ingredients using Mealie's local NLP engine.
* **Smart Parsing:** Scans for raw strings and converts them to structured objects.
* **AI Fallback:** Gracefully handles OpenAI escalations (if configured), or skips if unavailable.

### 3. Library Cleaner (`kitchen_ops_cleaner.py`)
**"The Janitor"**
Scans for "junk" content and broken imports.
* **Pattern Matching:** Removes blog posts, listicles ("10 Best..."), and non-recipe URLs.
* **Integrity Check:** Verifies that recipes actually have instructions. Empty recipes are flagged or removed.
* **Safe Mode:** All deletions are simulated by default (`DRY_RUN=true`).

---

## ⚠️ SQLite vs Postgres

| Feature | PostgreSQL | SQLite (Default) |
| :--- | :--- | :--- |
| **Parser / Cleaner** | Works while Mealie runs | Works while Mealie runs |
| **Auto-Tagger** | Works while Mealie runs | **REQUIRES DOWNTIME** |

### 📂 SQLite Instructions (The "Sandwich" Command)
Because SQLite locks the database file, you cannot run the Tagger while Mealie is writing to it. Use this one-liner to briefly stop Mealie, tag your library, and restart it:

```bash
# Replace 'mealie' with your actual container name
docker compose stop mealie && docker compose run --rm kitchen-ops && docker compose start mealie
```

### 📂 Postgres Password
💡 **Tip:** If you forgot your Postgres credentials, check the `docker-compose.yml` or `.env` file where you originally installed Mealie. Look for `POSTGRES_PASSWORD` or `DB_PASSWORD`.

---

## ⚙️ Configuration

The suite is configured via a single `.env` file.

| Variable | Default | Description |
| :--- | :--- | :--- |
| `DRY_RUN` | `true` | Set to `false` to apply changes. |
| `SCRIPT_TO_RUN` | `tagger` | Choose `tagger`, `parser`, `cleaner`, or `all`. |
| `MEALIE_URL` | - | Your Mealie address (e.g., `http://192.168.1.50:9000`). |
| `MEALIE_API_TOKEN` | - | Long-lived API token from User Profile. |
| `DB_TYPE` | `sqlite` | Switch to `postgres` for advanced setups. |
| **Postgres Settings** | | *(Only required if DB_TYPE=postgres)* |
| `POSTGRES_HOST` | `postgres` | IP or Hostname of DB server. |
| `POSTGRES_PORT` | `5432` | Database Port. |
| `POSTGRES_USER` | `mealie` | Database Username. |
| `POSTGRES_PASSWORD` | `mealie` | Database Password. |
| `POSTGRES_DB` | `mealie` | Database Name (check `docker-compose` if unsure). |

---

## 📦 Installation

1. **Clone the repo:**
   ```bash
   git clone https://github.com/d0rk4ce/kitchen-ops.git
   cd kitchen-ops
   ```

2. **Configure:**
   ```bash
   cp .env.example .env
   nano .env
   ```

3. **Run:**
   ```bash
   docker compose run --rm kitchen-ops
   ```

## 📄 License
MIT License.
