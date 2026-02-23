# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added
- Created `CHANGELOG.md` to track project release changes.

### Changed
- **Major Architecture Update**: Completely migrated the `kitchen_ops_tagger.py` from direct SQLite/Postgres database manipulation to standard Mealie API operations. This drastically improves safety by removing the risk of SQLite database corruption.
- Consolidated Runner Scripts: Safely merged `launcher.sh` functionality directly into `entrypoint.sh` and removed `launcher.sh`. The extensive "Database Safety" auto-stop/start code for the Mealie container was removed from `entrypoint.sh` since no tools directly modify the database anymore.
- Simplified Documentation: Rewrote `README.md` and `.env.example` to remove strict database configuration requirements. Database connectivity is now completely optional, serving solely as a read-only speed booster (Accelerator Mode) for the Batch Parser and Library Cleaner tools. 

### Removed
- `API_tagger.py` (renamed to `kitchen_ops_tagger.py`).
- `launcher.sh` (merged into `entrypoint.sh`).
