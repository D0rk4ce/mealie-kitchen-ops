# KitchenOps 🔪
**The Advanced Automation Suite for Mealie**

KitchenOps is a production-ready set of maintenance tools for [Mealie](https://mealie.io/). It automates the organization and sanitation of large recipe libraries while prioritizing "Wife Approval Factor" (WAF).

## 🚀 The Suite

### 1. Auto-Tagger (kitchen_ops_tagger.py)
**"The Organizer"**
A dual-engine tool that applies intelligent tags based on "World Fingerprints" (30+ cuisines), proteins, and equipment.
* **Note:** Directly interacts with the database for speed.

### 2. Batch Parser (kitchen_ops_parser.py)
**"The Fixer"**
A multi-threaded worker that fixes "unparsed" ingredients using Mealie's local NLP engine.
* **API Driven:** Zero downtime for your users.

### 3. Library Cleaner (kitchen_ops_cleaner.py)
**"The Janitor"**
Scans for "junk" content and broken imports.
* **Safe Mode:** All deletions are simulated by default (DRY_RUN=true).

---

## 🗄️ Database & API Instructions

KitchenOps uses two different methods to interact with your data.

### 📂 SQLite Instructions (The "Sandwich" Command)

> [!CAUTION]
> **CRITICAL: SQLite corruption risk.**
> Because SQLite locks the database file, running the **Tagger** while Mealie is active **will result in database corruption.** The KitchenOps launcher includes a safety prompt, but you should always manually stop your container first.

**The Sandwich:**
docker stop mealie && docker run -it --rm --env-file .env ghcr.io/d0rk4ce/kitchen-ops:latest && docker start mealie

---

### 🐘 Postgres Credentials

> [!TIP] 
> **Where are my passwords?**
> * **Standard Install:** Check your docker-compose.yml or .env file for POSTGRES_PASSWORD.
> * **Community Script Install:** Look for a `mealie.creds` file. In many production environments, this is located at:
>    * `/root/mealie.creds` (Root-level script installs)
>    * `~/mealie/mealie.creds` (Standard home directory)

**Note:** Unlike SQLite, Postgres users do **not** need to stop their containers! 🚀

---

## ⚙️ Configuration (.env)

| Variable | Default | Description |
| :--- | :--- | :--- |
| DRY_RUN | true | Set to false to apply changes. |
| SCRIPT_TO_RUN | tagger | Choose tagger, parser, cleaner, or all. |
| MEALIE_URL | - | Your Mealie address. |
| MEALIE_API_TOKEN | - | API token from User Profile. |
| DB_TYPE | sqlite | Switch to postgres for no-downtime tagging. |

---

## 📦 Installation & Usage

1. **Prepare:** Create a .env file locally.
2. **Pull:** docker pull ghcr.io/d0rk4ce/kitchen-ops:latest
3. **Run:** docker run -it --rm --env-file .env ghcr.io/d0rk4ce/kitchen-ops:latest

> [!IMPORTANT]
> **Safety Lock:** When running on SQLite, the container will pause and ask for confirmation that Mealie is stopped. Use the `-it` flag to ensure you can see and answer this prompt!

## 📄 License
MIT License.
