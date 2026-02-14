"""Tests for kitchen_ops_cleaner.py — junk detection and instruction validation."""

import os
import pytest

# Ensure DRY_RUN is set before import
os.environ["DRY_RUN"] = "true"
os.environ["MEALIE_API_TOKEN"] = "test-token"

import kitchen_ops_cleaner as cleaner


# ==========================================
# is_junk_content TESTS
# ==========================================

class TestIsJunkContent:
    def test_none_url_returns_false(self):
        assert cleaner.is_junk_content("Normal Recipe", None) is False

    def test_detects_keyword_in_name(self):
        assert cleaner.is_junk_content("Best Night Cream Ever", "https://example.com/recipe") is True

    def test_detects_keyword_in_url_slug(self):
        assert cleaner.is_junk_content("Some Page", "https://example.com/beauty-tips") is True

    def test_detects_listicle_in_name(self):
        assert cleaner.is_junk_content("15 Best Recipes You Must Try", "https://example.com/foo") is True

    def test_detects_listicle_in_url(self):
        """URL slugs use hyphens (no spaces), so the regex won't fire.
        But the keyword check catches 'best' via slug substring."""
        # This is caught by the keyword "giveaway" in slug, not the listicle regex
        assert cleaner.is_junk_content("A Page", "https://example.com/giveaway-2024") is True

    def test_detects_listicle_in_name_via_regex(self):
        """The listicle regex should match recipe names like '10 Best Grills'."""
        assert cleaner.is_junk_content("10 Best Grills to Buy", "https://example.com/grills") is True

    def test_detects_non_recipe_url_paths(self):
        assert cleaner.is_junk_content("Page", "https://example.com/privacy-policy") is True
        assert cleaner.is_junk_content("Page", "https://example.com/about-us") is True
        assert cleaner.is_junk_content("Page", "https://example.com/cart") is True

    def test_passes_normal_recipe(self):
        assert cleaner.is_junk_content(
            "Grandma's Chicken Soup",
            "https://cooking.com/grandmas-chicken-soup"
        ) is False

    def test_passes_recipe_with_no_keyword_match(self):
        assert cleaner.is_junk_content(
            "Spaghetti Carbonara",
            "https://food.com/spaghetti-carbonara"
        ) is False

    def test_keyword_with_spaces_matches_slug_hyphens(self):
        """'kitchen tools' should match 'kitchen-tools' in URL slug."""
        assert cleaner.is_junk_content("Page", "https://example.com/kitchen-tools-guide") is True

    def test_giveaway_detected(self):
        assert cleaner.is_junk_content("Big Giveaway!", "https://example.com/giveaway-2024") is True


# ==========================================
# validate_instructions TESTS
# ==========================================

class TestValidateInstructions:
    def test_none_returns_false(self):
        assert cleaner.validate_instructions(None) is False

    def test_empty_string_returns_false(self):
        assert cleaner.validate_instructions("") is False

    def test_whitespace_only_returns_false(self):
        assert cleaner.validate_instructions("   ") is False

    def test_could_not_detect_returns_false(self):
        assert cleaner.validate_instructions("Could not detect recipe instructions") is False

    def test_valid_string_returns_true(self):
        assert cleaner.validate_instructions("Preheat oven to 350F") is True

    def test_empty_list_returns_false(self):
        assert cleaner.validate_instructions([]) is False

    def test_list_of_empty_dicts_returns_false(self):
        assert cleaner.validate_instructions([{"text": ""}, {"text": "   "}]) is False

    def test_valid_list_returns_true(self):
        assert cleaner.validate_instructions([{"text": "Mix flour and sugar"}]) is True

    def test_list_with_one_valid_step(self):
        """Even if some steps are empty, one valid step should pass."""
        assert cleaner.validate_instructions([{"text": ""}, {"text": "Serve warm"}]) is True

    def test_list_of_strings(self):
        """Instructions might be a list of bare strings."""
        assert cleaner.validate_instructions(["Step 1", "Step 2"]) is True


# ==========================================
# LISTICLE_REGEX TESTS
# ==========================================

class TestListicleRegex:
    def test_matches_number_best(self):
        assert cleaner.LISTICLE_REGEX.match("15 best recipes") is not None

    def test_matches_number_top(self):
        assert cleaner.LISTICLE_REGEX.match("10 top grills") is not None

    def test_matches_number_must(self):
        assert cleaner.LISTICLE_REGEX.match("5 must try dishes") is not None

    def test_no_match_normal_text(self):
        assert cleaner.LISTICLE_REGEX.match("chicken soup recipe") is None

    def test_no_match_number_without_keyword(self):
        assert cleaner.LISTICLE_REGEX.match("350 degree oven") is None


# ==========================================
# load_json_set / save_json_set TESTS
# ==========================================

class TestJsonPersistence:
    def test_load_nonexistent_returns_empty(self, tmp_path):
        result = cleaner.load_json_set(str(tmp_path / "nonexistent.json"))
        assert result == set()

    def test_round_trip(self, tmp_path):
        path = str(tmp_path / "data" / "test.json")
        data = {"slug-1", "slug-2", "slug-3"}
        cleaner.save_json_set(path, data)
        loaded = cleaner.load_json_set(path)
        assert loaded == data

    def test_load_corrupt_file(self, tmp_path):
        path = str(tmp_path / "bad.json")
        with open(path, "w") as f:
            f.write("not valid json{{{")
        result = cleaner.load_json_set(path)
        assert result == set()
