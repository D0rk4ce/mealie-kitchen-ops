# KitchenOps 🔪
**The Advanced Automation Suite for Mealie**

KitchenOps is a production-ready set of maintenance tools for [Mealie](https://mealie.io/). It automates the organization, standardization, and sanitation of large recipe libraries while prioritizing "Wife Approval Factor" (WAF) by minimizing downtime.

## 🚀 The Suite

### 1. Auto-Tagger (kitchen_ops_tagger.py)
**"The Organizer"**
A dual-engine tool that scans your database and applies intelligent tags. It supports both **SQLite** (Default) and **PostgreSQL**.
* **World Fingerprints:** Detects 30+ cuisines based on ingredient signatures (e.g., East Asian, Mediterranean, Tex-Mex).
* **Phase Analysis:** Sorts cheeses, proteins, and diets (Keto/Vegan).
* **Equipment Scan:** Finds Air Fryers, Sous Vides, etc., in instructions.

### 2. Batch Parser (kitchen_ops_parser.py)
**"The Fixer"**
A multi-threaded worker that fixes "unparsed" ingredients using Mealie's local NLP engine. [cite: 2026-01-22]
* **Smart Parsing:** Scans for raw strings and converts them to structured objects.
* **API Driven:** Runs via the Mealie API, meaning **zero downtime** for your users.

### 3. Library Cleaner (kitchen_ops_cleaner.py)
**"The Janitor"**
Scans for "junk" content and broken imports.
* **Pattern Matching:** Removes blog posts, listicles, and non-recipe URLs.
* **Integrity Check:** Verifies that recipes have instructions. Empty recipes are flagged or removed.
* **Safe Mode:** All deletions are simulated by default (DRY_RUN=true). [cite: 2025-12-16]

---

## 🗄️ Database & API Instructions

KitchenOps uses two different methods to interact with your data. The **Parser** and **Cleaner** use the Mealie API and can run while Mealie is active. However, the **Tagger** interacts directly with the database for speed and precision.

### 📂 SQLite Instructions (The "Sandwich" Command)

> [!CAUTION]
> **CRITICAL: Only the Tagger requires this downtime.**
> Because SQLite locks the database file, running the **Tagger** while Mealie is active **will result in database corruption.** Always ensure the Mealie container is fully stopped before proceeding with tagging.

The safest way to run a tagger pass is to "sandwich" the command:

>```bash
> # Replace 'mealie' with your actual container name if different
>docker stop mealie && docker run --rm kitchen-ops && docker start mealie
> ```
---

### 🐘 Postgres Credentials

> [!TIP] 
> **Where are my passwords?**
> * **Standard Install:** Check your `docker-compose.yml` or `.env` file for `POSTGRES_PASSWORD` or `DB_PASSWORD`.
> * **Community Script Install:** Look for a `mealie.creds` file. In many production environments, this is located at:
>    * `/root/mealie.creds` (Root-level script installs)
>    * `~/mealie/mealie.creds` (Standard home directory)

**Note:** The Tagger needs these to "handshake" with your database while Mealie is running. Unlike SQLite, you **do not** need to stop your containers for Postgres! 🚀

---

## ⚙️ Configuration

The suite is configured via a single .env file.

| Variable | Default | Description |
| :--- | :--- | :--- |
| DRY_RUN | true | Set to false to apply changes. |
| SCRIPT_TO_RUN | tagger | Choose tagger, parser, cleaner, or all. |
| MEALIE_URL | - | Your Mealie address (e.g., http://192.168.1.50:9000). |
| MEALIE_API_TOKEN | - | API token from Mealie (Settings -> API Tokens). |
| DB_TYPE | sqlite | Switch to postgres for advanced setups. |
| **Postgres Settings** | | (Only required if DB_TYPE=postgres) |
| POSTGRES_HOST | postgres | IP or Hostname of DB server. |
| POSTGRES_USER | mealie | Database Username. |
| POSTGRES_PASSWORD | mealie | Database Password. |
| POSTGRES_DB | mealie | Database Name. |

---

## 📦 Installation & Usage

You can run KitchenOps directly via Docker without needing to clone the repository. [cite: 2025-12-30]

1. **Prepare your environment:** Create a .env file in your local directory (see Configuration above).
2. **Pull the latest image:** docker pull ghcr.io/d0rk4ce/kitchen-ops:latest
3. **Run the suite:** docker run --rm --env-file .env ghcr.io/d0rk4ce/kitchen-ops:latest

> [!IMPORTANT]
> **WAF Optimization (SQLite Only):** If running SCRIPT_TO_RUN=all, the Parser and Cleaner will execute while the Mealie UI is down. For maximum "Wife Approval Factor," use the **Sandwich Command** to run the tagger individually, then restart Mealie and run the parser and cleaner while the UI is live.

## 📄 License
MIT License.
