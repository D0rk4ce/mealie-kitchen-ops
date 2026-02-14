"""Tests for kitchen_ops_tagger.py"""

import os, sqlite3, unittest.mock, uuid
import pytest
import yaml

os.environ["DB_TYPE"] = "sqlite"
os.environ["SQLITE_PATH"] = ":memory:"
os.environ["DRY_RUN"] = "false"

import kitchen_ops_tagger as tagger

# MOCK CONFIG LOADING FOR TESTS
# Since the tagger loads config at module level, we might need to patch the dicts directly
# if they are already loaded, or patch open() if we reload.
# Simpler approach: Patch the global dictionaries in the module.

MOCK_CONFIG = {
    "cheese_types": {"Soft & Creamy": "mozzarella"},
    "protein_tags": {
        "Chicken": {"regex": "chicken", "exclude": "broth"},
        "Beef": {"regex": "hamburger", "exclude": "beef leaf"},
        "Pork": {"regex": "ham", "exclude": "hamburger"}
    },
    "cuisine_fingerprints": {"Italian": "mozzarella"},
    "text_tags": {"Vegan": ["vegan"]},
    "tools_matches": {"Wok": ["wok"]}
}

@pytest.fixture(autouse=True)
def mock_config_dicts():
    with unittest.mock.patch.object(tagger, 'CHEESE_TYPES', MOCK_CONFIG["cheese_types"]), \
         unittest.mock.patch.object(tagger, 'SQL_INGREDIENT_TAGS', MOCK_CONFIG["protein_tags"]), \
         unittest.mock.patch.object(tagger, 'SQL_CUISINE_FINGERPRINTS', MOCK_CONFIG["cuisine_fingerprints"]), \
         unittest.mock.patch.object(tagger, 'TEXT_ONLY_TAGS', MOCK_CONFIG["text_tags"]), \
         unittest.mock.patch.object(tagger, 'TOOLS_MATCHES', MOCK_CONFIG["tools_matches"]):
        yield


class TestWrapWordBoundaries:
    def test_single_term(self):
        assert tagger._wrap_word_boundaries("ham") == r"\yham\y"

    def test_multiple_terms(self):
        assert tagger._wrap_word_boundaries("ham|bacon|pork") == r"\yham\y|\ybacon\y|\ypork\y"


def _create_schema(conn: sqlite3.Connection) -> None:
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
    wrapper = tagger.DBWrapper()
    _create_schema(wrapper.conn)
    yield wrapper
    wrapper.close()


@pytest.fixture
def group_id():
    return "test-group-id"


class TestDBWrapper:
    def test_regexp_match(self):
        assert tagger.DBWrapper._regexp("chicken", "Grilled Chicken Breast") is True
        assert tagger.DBWrapper._regexp("beef", "Grilled Chicken Breast") is False

    def test_regexp_case_insensitive(self):
        assert tagger.DBWrapper._regexp("CHICKEN", "grilled chicken breast") is True

    def test_regexp_none(self):
        assert tagger.DBWrapper._regexp(None, "chicken") is False
        assert tagger.DBWrapper._regexp("chicken", None) is False

    def test_execute_returns_self(self, db):
        assert db.execute("SELECT 1") is db

    def test_fetch_methods_safe(self, db):
        # Should return empty/None on query error (simulated by invalid SQL)
        db.execute("SELECT * FROM non_existent_table")
        assert db.fetch_all() == []
        assert db.fetch_one() is None

    def test_placeholder_sqlite(self, db):
        assert db.placeholder == "?"


class TestSlugAndHelpers:
    def test_make_slug_basic(self):
        assert tagger._make_slug("Hello World") == "hello-world"

    def test_make_slug_symbols(self):
        assert tagger._make_slug("Blue & Funky/Co") == "blue-and-funky-co"

    def test_get_group_id(self, db):
        assert tagger.get_group_id(db) == "test-group-id"


class TestIdempotency:
    def test_ensure_tag_idempotent(self, db, group_id):
        id1 = tagger.ensure_tag(db, "Test", group_id)
        id2 = tagger.ensure_tag(db, "Test", group_id)
        assert id1 == id2
        assert db.execute("SELECT COUNT(*) FROM tags").fetch_one()[0] == 1

    def test_ensure_tool_idempotent(self, db, group_id):
        id1 = tagger.ensure_tool(db, "Wok", group_id)
        id2 = tagger.ensure_tool(db, "Wok", group_id)
        assert id1 == id2



class TestLinkOps:
    def test_creates_new_tag(self, db, group_id):
        tag_id = tagger.ensure_tag(db, "TestTag", group_id)
        assert tag_id is not None
        assert db.execute("SELECT slug FROM tags WHERE id = ?", (tag_id,)).fetch_one()[0] == "testtag"

    def test_links_tag(self, db, group_id):
        db.conn.execute("INSERT INTO recipes (id, name) VALUES ('r1', 'Test')")
        tag_id = tagger.ensure_tag(db, "TestTag", group_id)
        tagger.link_tag(db, "r1", tag_id)
        assert db.execute("SELECT COUNT(*) FROM recipes_to_tags").fetch_one()[0] == 1


class TestPhases:
    def _seed(self, db, recipe_name, food_name):
        rid, fid = str(uuid.uuid4()), str(uuid.uuid4())
        db.conn.execute("INSERT INTO recipes (id, name) VALUES (?, ?)", (rid, recipe_name))
        db.conn.execute("INSERT INTO ingredient_foods (id, name) VALUES (?, ?)", (fid, food_name))
        db.conn.execute("INSERT INTO recipes_ingredients (recipe_id, food_id) VALUES (?, ?)", (rid, fid))
        return rid

    def _get_tags(self, db, rid):
        rows = db.execute("SELECT t.name FROM recipes_to_tags rt JOIN tags t ON rt.tag_id = t.id WHERE rt.recipe_id = ?", (rid,)).fetch_all()
        return [r[0] for r in rows]

    def test_phase_1_cheese(self, db, group_id):
        rid = self._seed(db, "Salad", "mozzarella")
        tagger.phase_1_cheese(db, group_id)
        assert "Soft & Creamy" in self._get_tags(db, rid)

    def test_phase_2_protein(self, db, group_id):
        rid = self._seed(db, "Dish", "chicken")
        tagger.phase_2_protein(db, group_id)
        assert "Chicken" in self._get_tags(db, rid)

    def test_phase_2_excludes_broth(self, db, group_id):
        rid = self._seed(db, "Soup", "broth")
        tagger.phase_2_protein(db, group_id)
        assert "Chicken" not in self._get_tags(db, rid)

    def test_phase_2_ham_not_hamburger(self, db, group_id):
        """Regression: hamburger must NOT be tagged as Pork."""
        rid = self._seed(db, "Hamburger", "hamburger")
        tagger.phase_2_protein(db, group_id)
        tags = self._get_tags(db, rid)
        assert "Pork" not in tags
        assert "Beef" in tags

    def test_phase_2_chickpea_not_chicken(self, db, group_id):
        """Regression: chickpea must NOT be tagged as Chicken."""
        rid = self._seed(db, "Hummus", "chickpea")
        tagger.phase_2_protein(db, group_id)
        assert "Chicken" not in self._get_tags(db, rid)

    def test_phase_4_text(self, db, group_id):
        rid = str(uuid.uuid4())
        db.conn.execute("INSERT INTO recipes (id, name, description) VALUES (?, 'Vegan Dish', '')", (rid,))
        tagger.phase_4_text(db, group_id)
        assert "Vegan" in self._get_tags(db, rid)

    def test_phase_5_tools(self, db, group_id):
        rid = str(uuid.uuid4())
        db.conn.execute("INSERT INTO recipes (id, name) VALUES (?, 'Stir Fry')", (rid,))
        db.conn.execute("INSERT INTO recipe_instructions (recipe_id, text) VALUES (?, 'Use a wok')", (rid,))
        tagger.phase_5_tools(db, group_id)
        rows = db.execute("SELECT t.name FROM recipes_to_tools rt JOIN tools t ON rt.tool_id = t.id WHERE rt.recipe_id = ?", (rid,)).fetch_all()
        assert "Wok" in [r[0] for r in rows]
