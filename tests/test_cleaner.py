"""Tests for kitchen_ops_cleaner.py"""

import os, unittest.mock
import pytest

os.environ["DRY_RUN"] = "true"
os.environ["MEALIE_API_TOKEN"] = "test-token"

import kitchen_ops_cleaner as cleaner

# Mock config
MOCK_KEYWORDS = ["cleaning", "review", "giveaway", "kitchen tools"]

@pytest.fixture(autouse=True)
def mock_keywords():
    with unittest.mock.patch.object(cleaner, 'HIGH_RISK_KEYWORDS', MOCK_KEYWORDS):
        yield

class TestIsJunkContent:
    def test_none_url_returns_false(self):
        assert cleaner.is_junk_content("Normal Recipe", None) is False

    def test_detects_keyword_in_name(self):
        assert cleaner.is_junk_content("Review of X", "http://x") is True

    def test_detects_keyword_in_url(self):
        assert cleaner.is_junk_content("Page", "http://x/cleaning-tips") is True

    def test_passes_normal(self):
        assert cleaner.is_junk_content("Chicken Soup", "http://x/chicken-soup") is False

class TestValidateInstructions:
    def test_empty(self):
        assert cleaner.validate_instructions([]) is False

    def test_valid(self):
        assert cleaner.validate_instructions("Cook it") is True

class TestJsonPersistence:
    def test_round_trip(self, tmp_path):
        path = str(tmp_path / "test.json")
        data = {"a", "b"}
        cleaner.save_json_set(path, data)
        assert cleaner.load_json_set(path) == data
