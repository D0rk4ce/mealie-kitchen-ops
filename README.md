# KitchenOps 🔪
**The Advanced Automation Suite for Mealie**

KitchenOps is a production-ready set of maintenance tools for [Mealie](https://mealie.io/). It automates the organization and sanitation of large recipe libraries while prioritizing "Wife Approval Factor" (WAF).

## 🚀 The Suite

| Tool | Script | Method | Downtime? |
| :--- | :--- | :--- | :--- |
| **Auto-Tagger** "The Organizer" | `kitchen_ops_tagger.py` | Direct SQL | SQLite: Yes · Postgres: No |
| **Batch Parser** "The Fixer" | `kitchen_ops_parser.py` | Mealie API | No |
| **Library Cleaner** "The Janitor" | `kitchen_ops_cleaner.py` | Mealie API | No |

### 1. Auto-Tagger
Applies intelligent tags based on "World Fingerprints" (30+ cuisines), proteins, cheese categories, and cooking equipment. Directly queries the database for raw speed using regex-based ingredient matching.

### 2. Batch Parser
A multi-threaded worker that fixes "unparsed" ingredients using Mealie's local NLP engine, with automatic AI escalation for low-confidence results.

### 3. Library Cleaner
Scans for "junk" content (product pages, listicles, beauty tips) and recipes with empty/broken instructions. All deletions are simulated by default (`DRY_RUN=true`).

---

## ⚙️ Configuration (.env)

| Variable | Default | Used By | Description |
| :--- | :--- | :--- | :--- |
| `DRY_RUN` | `true` | All | Set to `false` to apply changes. |
| `SCRIPT_TO_RUN` | `tagger` | Entrypoint | Choose `tagger`, `parser`, `cleaner`, or `all`. |
| `LOG_LEVEL` | `INFO` | All | Logging verbosity: `DEBUG`, `INFO`, `WARNING`, `ERROR`. |
| `DB_TYPE` | `sqlite` | Tagger | Database backend: `sqlite` or `postgres`. |
| `SQLITE_PATH` | `/app/data/mealie.db` | Tagger | Path to SQLite database file. |
| `POSTGRES_HOST` | `postgres` | Tagger | Postgres server hostname or IP. |
| `POSTGRES_PORT` | `5432` | Tagger | Postgres server port. |
| `POSTGRES_DB` | `mealie` | Tagger | Postgres database name. |
| `POSTGRES_USER` | `mealie` | Tagger | Postgres username. |
| `POSTGRES_PASSWORD` | `mealie` | Tagger | Postgres password. |
| `MEALIE_URL` | - | Parser, Cleaner | Your Mealie instance URL (e.g. `http://192.168.1.50:9000`). |
| `MEALIE_API_TOKEN` | - | Parser, Cleaner | API token from Mealie → User Profile → API Tokens. |
| `PARSER_WORKERS` | `2` | Parser | Number of concurrent parsing threads. |
| `CLEANER_WORKERS` | `2` | Cleaner | Number of concurrent integrity-check threads. |

---

## 📦 Quick Start (Docker)

```bash
# 1. Create your .env file
cp .env.example .env
# Edit .env with your settings

# 2. Pull the image
docker pull ghcr.io/d0rk4ce/kitchen-ops:latest

# 3. Run (interactive mode for safety prompts)
docker run -it --rm --env-file .env ghcr.io/d0rk4ce/kitchen-ops:latest
```

> [!IMPORTANT]
> **Safety Lock:** When running on SQLite, the container will pause and ask for confirmation that Mealie is stopped. Use the `-it` flag to ensure you can see and answer this prompt!

Run `--help` for a full usage guide:
```bash
docker run --rm ghcr.io/d0rk4ce/kitchen-ops:latest --help
```

---

## 🗄️ Database & API Setup

KitchenOps uses **two different methods** to interact with your data. The **Tagger** uses direct SQL for speed. The **Parser** and **Cleaner** use the Mealie REST API for zero-downtime operation.

### 📂 SQLite (The "Sandwich" Command)

> [!CAUTION]
> **CRITICAL: SQLite corruption risk.**
> Because SQLite locks the database file, running the **Tagger** while Mealie is active **will result in database corruption.** The KitchenOps launcher includes a safety prompt, but you should always manually stop your container first.

**The Sandwich** — stop Mealie, run KitchenOps, restart Mealie:
```bash
docker stop mealie && \
  docker run -it --rm --env-file .env -v /path/to/mealie/data:/app/data ghcr.io/d0rk4ce/kitchen-ops:latest && \
  docker start mealie
```

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

POSTGRES_DB=mealie_db
POSTGRES_USER=mealie_user
POSTGRES_PASSWORD=YOUR_DB_PASSWORD
POSTGRES_HOST=192.168.14.55
POSTGRES_PORT=5432
```

#### 2. Server-Side Permissions

By default, Postgres may block external connections from your machine. Verify these two files **on the database server**:

| File | Required Setting | Purpose |
| :--- | :--- | :--- |
| `postgresql.conf` | `listen_addresses = '*'` | Listen beyond localhost |
| `pg_hba.conf` | `host all all 192.168.14.0/24 md5` | Allow your local network |

After editing, restart Postgres: `sudo systemctl restart postgresql`

#### 3. Running Locally (Dev / Manual)

To run scripts directly on your machine (outside Docker), load the `.env` variables into your shell:

```bash
# Load .env and run the Tagger in dry-run mode
export $(grep -v '^#' .env | xargs) && DRY_RUN=true SCRIPT_TO_RUN=tagger ./entrypoint.sh
```

Or run a specific script directly:
```bash
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
| Container exits immediately | Check `DRY_RUN` is set. Run with `-it` flag for interactive prompts. |

---

## 📄 License
MIT License.
