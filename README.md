# KitchenOps 🔪
**The Advanced Automation Suite for Mealie**

KitchenOps is a production-ready set of maintenance tools for [Mealie](https://mealie.io/). It automates the organization and sanitation of large recipe libraries while prioritizing "Wife Approval Factor" (WAF).

## 🚀 Key Features

*   **Data-Driven Architecture**: All tagging rules (cuisines, ingredients, tools) and cleaning logic are externalized in **YAML configuration files**. Customize the behavior without touching a line of code.
*   **Beautiful CLI**: Built with `rich`, featuring real-time progress bars, status spinners, and formatted reports.
*   **Production Ready**: Includes robust error handling, automated retries, and comprehensive logging.

## 🛠️ The Suite

| Tool | Script | Method | Complexity | Speed | Notes |
| :--- | :--- | :--- | :--- | :--- | :--- |
- **🧹 Auto-Cleaner:** Removes junk recipes, broken content, and listicles.
- **🏷️ Auto-Tagger:** Tags recipes by cuisine, protein, cheese, etc. (Direct DB Access).
- **🔧 Batch Parser:** Fixes unparsed ingredients using Mealie's NLP engine.
- **⚡ DB Accelerator:** 
  - Massive speedup for finding unparsed recipes (~20m → <1s)
  - Instant library scanning for Cleaner (~7h → <1s)
  - **Works with configured Postgres OR SQLite (Read-Only)**
- **🛡️ Safety First:**
  - **Dry Run** by default.
  - **Tagger Safety:** Auto-stops/starts Mealie to prevent SQLite corruption.
  - **Liveness Check:** Ensures Mealie is offline before DB writes.
- **✨ Setup Wizard:** Interactive CLI guides you through first-run configuration.
- **🔄 Smart Workflow:** "Run All" command handles the entire pipeline in one go.

> [!TIP]
> **Performance Tip:** Configuring a Database (SQLite or Postgres) triggers **Accelerator Mode**, reducing startup times from hours to seconds (1000x faster).
> *Note: SQLite acceleration uses **Read-Only** mode to ensure safety.*

---

## ⚙️ Configuration

KitchenOps is configured via environment variables (for connection details) and YAML files (for logic rules).

### 1. Environment Variables (.env)

#### 🟢 Basic Settings (Parser, Cleaner, & Common)

| Variable | Default | Description |
| :--- | :--- | :--- |
| `MEALIE_URL` | - | Your Mealie instance URL (e.g. `http://PLACEHOLDER_MEALIE_IP:9000`). |
| `MEALIE_API_TOKEN` | - | API token from Mealie → User Profile → API Tokens. |
| `DRY_RUN` | `true` | Set to `false` to apply changes. |
| `SCRIPT_TO_RUN` | `parser` | Choose `tagger`, `parser`, `cleaner`, or `all`. |
| `LOG_LEVEL` | `INFO` | Logging verbosity: `DEBUG`, `INFO`, `WARNING`, `ERROR`. |
| `PARSER_WORKERS` | `2` | Number of concurrent parsing threads. |
| `CLEANER_WORKERS` | `2` | Number of concurrent integrity-check threads. |

#### 🔴 Database Settings (Accelerator & Tagger)

> **Required for Tagger**. Optional but recommended for Parser/Cleaner (Postgres only).

| Variable | Default | Description |
| :--- | :--- | :--- |
| `DB_TYPE` | `sqlite` | Database backend: `sqlite` or `postgres`. |
| `SQLITE_PATH` | `/app/data/mealie.db` | Path to SQLite database file. |
| `POSTGRES_HOST` | `postgres` | Postgres server hostname or IP. |
| `POSTGRES_PORT` | `5432` | Postgres server port. |
| `POSTGRES_DB` | `mealie` | Postgres database name. |
| `POSTGRES_USER` | `mealie` | Postgres username. |
| `POSTGRES_PASSWORD` | `mealie` | Postgres password. |

### 2. Logic Rules (YAML)

To customize how KitchenOps behaves, edit the files in the `config/` directory:

*   **`config/tagging.yaml`**: Define regex patterns for Proteins, Cuisines, Cheese categories, Text tags, and Tool detection.
    *   *Example:* Add "Air Fryer" detection by adding `air fryer` to the `tools_matches` list.
*   **`config/cleaning.yaml`**: Define the "blacklisted keywords" for the Library Cleaner.
    *   *Example:* Add "giveaway" or "review" to automatically flag those pages as junk.

---

## 📦 Quick Start (Docker)

```bash
# 1. Create your .env file
cp .env.example .env
# Edit .env with your settings (add your API token, Mealie URL, etc.)

# 2. Pull the image
docker pull ghcr.io/d0rk4ce/mealie-kitchen-ops:latest

# 3a. Run interactively — you'll get a selection menu!
docker run -it --rm \
  --env-file .env \
  -v $(pwd)/config:/app/config \
  ghcr.io/d0rk4ce/mealie-kitchen-ops:latest

# 3b. Or choose a specific tool directly:
docker run -it --rm \
  --env-file .env \
  -e SCRIPT_TO_RUN=parser \
  -v $(pwd)/config:/app/config \
  ghcr.io/d0rk4ce/mealie-kitchen-ops:latest
```

Run `--help` for a full usage guide:
```bash
docker run --rm ghcr.io/d0rk4ce/mealie-kitchen-ops:latest --help
```

```

### 📦 Quick Start (Podman)

Podman users (Fedora/Bazzite) often need the `:z` suffix for SELinux compatibility.

```bash
# 1. Create your .env file
cp .env.example .env
# Edit .env with your settings

# 2. Run interactively
podman run -it --rm \
  --env-file .env \
  -v $(pwd)/config:/app/config:z \
  ghcr.io/d0rk4ce/mealie-kitchen-ops:latest
```

---

## 🗄️ Database Setup (Accelerator & Tagger)

> [!TIP]
> **Skip this section** if you are only using the **Parser** or **Cleaner**. Those tools use the API and do not need direct database access.

KitchenOps uses **direct SQL** to achieve blazing speed.
> *   **Tagger:** Required (1000s recipes/min). Works with SQLite or Postgres.
> *   **Parser/Cleaner:** Optional (Enables "Accelerator Mode"). **Postgres Only**.

### 📂 SQLite (Default)

> [!IMPORTANT]
> **SQLite Safety:** The Tagger writes to the database file. To prevent corruption, Mealie must be stopped during tagging.
> 
> **KitchenOps handles this automatically!**
> When you run the Tagger (or "Run All"), the script will:
> 1. Detect if Mealie is running.
> 2. Offer to stop it automatically.
> 3. Run the tools safely.
> 4. Restart Mealie for you.
>
> You don't need to manually stop containers anymore. 🚀

### 🐘 Postgres (Advanced)

---

### 🐘 Postgres Connection Setup

> [!TIP]
> **Where are my passwords?**
> * **Standard Install:** Check your `docker-compose.yml` or `.env` file for `POSTGRES_PASSWORD`.
> * **Community Script Install:** Look for a `mealie.creds` file:
>    * `/root/mealie.creds` (Root-level script installs)
>    * `~/mealie/mealie.creds` (Standard home directory)

Unlike SQLite, Postgres users do **not** need to stop their containers! 🚀

#### 1. Environment Configuration

Your `.env` file needs the `POSTGRES_` prefixed variables:

```ini
DB_TYPE=postgres

POSTGRES_DB=mealie
POSTGRES_USER=mealie
POSTGRES_PASSWORD=PLACEHOLDER_DB_PASSWORD
POSTGRES_HOST=PLACEHOLDER_POSTGRES_IP
POSTGRES_PORT=5432
```

#### 2. Server-Side Permissions

By default, Postgres may block external connections from your machine. Verify these two files **on the database server**:

| File | Required Setting | Purpose |
| :--- | :--- | :--- |
| `postgresql.conf` | `listen_addresses = '*'` | Listen beyond localhost |
| `pg_hba.conf` | `host all all PLACEHOLDER_SUBNET/24 md5` | Allow your local network |

After editing, restart Postgres: `sudo systemctl restart postgresql`

#### 3. Running Locally (Dev / Manual)

To run scripts directly on your machine (outside Docker), install dependencies and load environment variables:

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Load .env and run
export $(grep -v '^#' .env | xargs) && python3 kitchen_ops_tagger.py
```

---

## 🔧 Troubleshooting

| Problem | Solution |
| :--- | :--- |
| `FATAL: Group ID not found` | Database is empty or connection failed. Verify credentials and that Mealie has been used at least once. |
| `MEALIE_API_TOKEN is not set` | The Parser and Cleaner require an API token. Generate one in Mealie → User Profile → API Tokens. |
| `connection refused` (Postgres) | Check `pg_hba.conf` and `postgresql.conf` on the DB server. Ensure the port is open in your firewall. |
| `database is locked` (SQLite) | Mealie is still running. Stop it first: `docker stop mealie` |
| `Failed to load config/tagging.yaml` | Ensure you are running the script from the project root or that the `config/` directory is mounted correctly in Docker. |
| `Permission denied` (Podman) | SELinux is blocking access. ensure you use the `:z` suffix on your volume mounts (e.g. `-v ./data:/app/data:z`). |

---

## 📄 License
MIT License.
