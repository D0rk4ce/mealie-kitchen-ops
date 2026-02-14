"""Tests for kitchen_ops_tagger.py — SQL safety, dialect translation, and tagging logic."""

import os
import re
import sqlite3
import uuid

import pytest

# Force SQLite + DRY_RUN off for testing
os.environ["DB_TYPE"] = "sqlite"
os.environ["SQLITE_PATH"] = ":memory:"
os.environ["DRY_RUN"] = "false"

import kitchen_ops_tagger as tagger


# ==========================================
# FIXTURES
# ==========================================

def _create_schema(conn: sqlite3.Connection) -> None:
    """Create the minimal Mealie schema for testing."""
    conn.executescript("""
        CREATE TABLE groups (id TEXT PRIMARY KEY);
        CREATE TABLE tags (id TEXT PRIMARY KEY, group_id TEXT, name TEXT, slug TEXT);
        CREATE TABLE tools (id TEXT PRIMARY KEY, group_id TEXT, name TEXT, slug TEXT, on_hand INTEGER DEFAULT 0);
        CREATE TABLE recipes (id TEXT PRIMARY KEY, name TEXT, description TEXT);
        CREATE TABLE ingredient_foods (id TEXT PRIMARY KEY, name TEXT);
        CREATE TABLE recipes_ingredients (recipe_id TEXT, food_id TEXT);
        CREATE TABLE recipes_to_tags (recipe_id TEXT, tag_id TEXT, PRIMARY KEY (recipe_id, tag_id));
        CREATE TABLE recipes_to_tools (recipe_id TEXT, tool_id TEXT, PRIMARY KEY (recipe_id, tool_id));
        CREATE TABLE recipe_instructions (recipe_id TEXT, text TEXT);

        INSERT INTO groups (id) VALUES ('test-group-id');
    """)


@pytest.fixture
def db():
    """Create a fresh in-memory DBWrapper with the test schema."""
    wrapper = tagger.DBWrapper()
    _create_schema(wrapper.conn)
    yield wrapper
    wrapper.close()


@pytest.fixture
def group_id():
    return "test-group-id"


# ==========================================
# DBWrapper TESTS
# ==========================================

class TestDBWrapper:
    """Tests for the database adapter layer."""

    def test_regexp_normal_match(self):
        assert tagger.DBWrapper._regexp("chicken", "Grilled Chicken Breast") is True

    def test_regexp_case_insensitive(self):
        assert tagger.DBWrapper._regexp("CHICKEN", "grilled chicken breast") is True

    def test_regexp_no_match(self):
        assert tagger.DBWrapper._regexp("beef", "Grilled Chicken Breast") is False

    def test_regexp_none_item(self):
        assert tagger.DBWrapper._regexp("chicken", None) is False

    def test_regexp_none_expr(self):
        assert tagger.DBWrapper._regexp(None, "chicken") is False

    def test_regexp_bad_pattern(self):
        assert tagger.DBWrapper._regexp("[invalid", "test") is False

    def test_regexp_word_boundary_conversion(self):
        """\\y (Postgres) should be converted to \\b (Python)."""
        assert tagger.DBWrapper._regexp(r"\ychicken\y", "I love chicken!") is True
        assert tagger.DBWrapper._regexp(r"\ychicken\y", "I love chickens!") is False

    def test_execute_returns_self(self, db):
        """execute() should always return self, even on error."""
        result = db.execute("SELECT 1")
        assert result is db

    def test_execute_returns_self_on_error(self, db):
        """execute() should return self even when SQL is invalid."""
        result = db.execute("SELECT * FROM nonexistent_table_xyz")
        assert result is db

    def test_fetch_all_after_error(self, db):
        """fetch_all() should return [] after a failed query."""
        db.execute("SELECT * FROM nonexistent_table_xyz")
        assert db.fetch_all() == []

    def test_fetch_one_after_error(self, db):
        """fetch_one() should return None after a failed query."""
        db.execute("SELECT * FROM nonexistent_table_xyz")
        assert db.fetch_one() is None

    def test_dialect_translation_regexp(self, db):
        """Postgres ~* operator should be translated to REGEXP for SQLite."""
        db.conn.execute("INSERT INTO ingredient_foods (id, name) VALUES ('f1', 'chicken breast')")
        result = db.execute("SELECT id FROM ingredient_foods WHERE name ~* 'chicken'").fetch_all()
        assert len(result) == 1
        assert result[0][0] == "f1"

    def test_dialect_translation_not_regexp(self, db):
        """Postgres !~* operator should be translated to NOT REGEXP."""
        db.conn.execute("INSERT INTO ingredient_foods (id, name) VALUES ('f1', 'chicken broth')")
        db.conn.execute("INSERT INTO ingredient_foods (id, name) VALUES ('f2', 'chicken breast')")
        result = db.execute(
            "SELECT id FROM ingredient_foods WHERE name ~* 'chicken' AND name !~* 'broth'"
        ).fetch_all()
        assert len(result) == 1
        assert result[0][0] == "f2"

    def test_placeholder_sqlite(self, db):
        assert db.placeholder == "?"


# ==========================================
# SLUG TESTS
# ==========================================

class TestMakeSlug:
    def test_basic(self):
        assert tagger._make_slug("Hello World") == "hello-world"

    def test_slash(self):
        assert tagger._make_slug("Lamb/Goat") == "lamb-goat"

    def test_ampersand(self):
        assert tagger._make_slug("Blue & Funky") == "blue-and-funky"


# ==========================================
# TAG / TOOL CREATION TESTS
# ==========================================

class TestEnsureTag:
    def test_creates_new_tag(self, db, group_id):
        tag_id = tagger.ensure_tag(db, "TestTag", group_id)
        assert tag_id is not None
        row = db.execute("SELECT name, slug FROM tags WHERE id = ?", (tag_id,)).fetch_one()
        assert row == ("TestTag", "testtag")

    def test_idempotent(self, db, group_id):
        id1 = tagger.ensure_tag(db, "TestTag", group_id)
        id2 = tagger.ensure_tag(db, "TestTag", group_id)
        assert id1 == id2

    def test_special_characters_in_name(self, db, group_id):
        """Names with & and / should produce safe slugs."""
        tag_id = tagger.ensure_tag(db, "Blue & Funky", group_id)
        assert tag_id is not None
        row = db.execute("SELECT slug FROM tags WHERE id = ?", (tag_id,)).fetch_one()
        assert row[0] == "blue-and-funky"


class TestEnsureTool:
    def test_creates_new_tool(self, db, group_id):
        tool_id = tagger.ensure_tool(db, "Air Fryer", group_id)
        assert tool_id is not None
        row = db.execute("SELECT name, slug FROM tools WHERE id = ?", (tool_id,)).fetch_one()
        assert row == ("Air Fryer", "air-fryer")

    def test_idempotent(self, db, group_id):
        id1 = tagger.ensure_tool(db, "Wok", group_id)
        id2 = tagger.ensure_tool(db, "Wok", group_id)
        assert id1 == id2


# ==========================================
# LINK TESTS (idempotency)
# ==========================================

class TestLinkTag:
    def test_links_tag(self, db, group_id):
        db.conn.execute("INSERT INTO recipes (id, name) VALUES ('r1', 'Test Recipe')")
        tag_id = tagger.ensure_tag(db, "TestTag", group_id)
        tagger.link_tag(db, "r1", tag_id)
        row = db.execute("SELECT COUNT(*) FROM recipes_to_tags WHERE recipe_id = 'r1'").fetch_one()
        assert row[0] == 1

    def test_no_duplicate_links(self, db, group_id):
        db.conn.execute("INSERT INTO recipes (id, name) VALUES ('r1', 'Test Recipe')")
        tag_id = tagger.ensure_tag(db, "TestTag", group_id)
        tagger.link_tag(db, "r1", tag_id)
        tagger.link_tag(db, "r1", tag_id)  # Second call should be a no-op
        row = db.execute("SELECT COUNT(*) FROM recipes_to_tags WHERE recipe_id = 'r1'").fetch_one()
        assert row[0] == 1


class TestLinkTool:
    def test_links_tool(self, db, group_id):
        db.conn.execute("INSERT INTO recipes (id, name) VALUES ('r1', 'Test Recipe')")
        tool_id = tagger.ensure_tool(db, "Wok", group_id)
        tagger.link_tool(db, "r1", tool_id)
        row = db.execute("SELECT COUNT(*) FROM recipes_to_tools WHERE recipe_id = 'r1'").fetch_one()
        assert row[0] == 1

    def test_no_duplicate_links(self, db, group_id):
        db.conn.execute("INSERT INTO recipes (id, name) VALUES ('r1', 'Test Recipe')")
        tool_id = tagger.ensure_tool(db, "Wok", group_id)
        tagger.link_tool(db, "r1", tool_id)
        tagger.link_tool(db, "r1", tool_id)
        row = db.execute("SELECT COUNT(*) FROM recipes_to_tools WHERE recipe_id = 'r1'").fetch_one()
        assert row[0] == 1


# ==========================================
# PHASE INTEGRATION TESTS
# ==========================================

class TestPhases:
    def _seed_recipe_with_ingredient(self, db, recipe_name, food_name):
        """Helper: create a recipe with one ingredient."""
        rid = str(uuid.uuid4())
        fid = str(uuid.uuid4())
        db.conn.execute(f"INSERT INTO recipes (id, name) VALUES (?, ?)", (rid, recipe_name))
        db.conn.execute(f"INSERT INTO ingredient_foods (id, name) VALUES (?, ?)", (fid, food_name))
        db.conn.execute(f"INSERT INTO recipes_ingredients (recipe_id, food_id) VALUES (?, ?)", (rid, fid))
        return rid

    def test_phase_1_cheese_tags(self, db, group_id):
        """Phase 1 should tag a recipe containing mozzarella as 'Soft & Creamy'."""
        rid = self._seed_recipe_with_ingredient(db, "Caprese Salad", "mozzarella")
        tagger.phase_1_cheese(db, group_id)
        rows = db.execute(
            "SELECT t.name FROM recipes_to_tags rt JOIN tags t ON rt.tag_id = t.id WHERE rt.recipe_id = ?",
            (rid,)
        ).fetch_all()
        tag_names = [r[0] for r in rows]
        assert "Soft & Creamy" in tag_names

    def test_phase_2_protein_tags(self, db, group_id):
        """Phase 2 should tag a recipe containing chicken breast as 'Chicken'."""
        rid = self._seed_recipe_with_ingredient(db, "Grilled Chicken", "chicken breast")
        tagger.phase_2_protein(db, group_id)
        rows = db.execute(
            "SELECT t.name FROM recipes_to_tags rt JOIN tags t ON rt.tag_id = t.id WHERE rt.recipe_id = ?",
            (rid,)
        ).fetch_all()
        tag_names = [r[0] for r in rows]
        assert "Chicken" in tag_names

    def test_phase_2_excludes_broth(self, db, group_id):
        """Phase 2 should NOT tag 'chicken broth' as Chicken protein."""
        rid = self._seed_recipe_with_ingredient(db, "Soup Base", "chicken broth")
        tagger.phase_2_protein(db, group_id)
        rows = db.execute(
            "SELECT t.name FROM recipes_to_tags rt JOIN tags t ON rt.tag_id = t.id WHERE rt.recipe_id = ?",
            (rid,)
        ).fetch_all()
        tag_names = [r[0] for r in rows]
        assert "Chicken" not in tag_names

    def test_phase_4_text_tags(self, db, group_id):
        """Phase 4 should tag a recipe named 'Vegan Tacos' with 'Vegan'."""
        rid = str(uuid.uuid4())
        db.conn.execute("INSERT INTO recipes (id, name, description) VALUES (?, 'Vegan Tacos', 'A tasty dish')", (rid,))
        tagger.phase_4_text(db, group_id)
        rows = db.execute(
            "SELECT t.name FROM recipes_to_tags rt JOIN tags t ON rt.tag_id = t.id WHERE rt.recipe_id = ?",
            (rid,)
        ).fetch_all()
        tag_names = [r[0] for r in rows]
        assert "Vegan" in tag_names

    def test_phase_5_tools(self, db, group_id):
        """Phase 5 should tag a recipe with 'wok' in its instructions."""
        rid = str(uuid.uuid4())
        db.conn.execute("INSERT INTO recipes (id, name) VALUES (?, 'Stir Fry')", (rid,))
        db.conn.execute("INSERT INTO recipe_instructions (recipe_id, text) VALUES (?, 'Heat the wok over high flame')", (rid,))
        tagger.phase_5_tools(db, group_id)
        rows = db.execute(
            "SELECT t.name FROM recipes_to_tools rt JOIN tools t ON rt.tool_id = t.id WHERE rt.recipe_id = ?",
            (rid,)
        ).fetch_all()
        tool_names = [r[0] for r in rows]
        assert "Wok" in tool_names


# ==========================================
# get_group_id
# ==========================================

class TestGetGroupId:
    def test_returns_id(self, db):
        gid = tagger.get_group_id(db)
        assert gid == "test-group-id"

    def test_returns_none_for_empty_db(self):
        empty_db = tagger.DBWrapper()
        empty_db.conn.execute("CREATE TABLE groups (id TEXT)")
        assert tagger.get_group_id(empty_db) is None
        empty_db.close()
