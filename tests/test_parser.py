"""Tests for kitchen_ops_parser.py"""

import json, os
import pytest

os.environ["DRY_RUN"] = "true"
os.environ["MEALIE_API_TOKEN"] = "test-token"
os.environ["MEALIE_URL"] = "http://localhost:9999"

import kitchen_ops_parser as parser


class TestHistory:
    def test_load_nonexistent_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(parser, "HISTORY_FILE", str(tmp_path / "nonexistent.json"))
        assert parser.load_history() == set()

    def test_round_trip(self, tmp_path, monkeypatch):
        path = str(tmp_path / "history.json")
        monkeypatch.setattr(parser, "HISTORY_FILE", path)
        parser.HISTORY_SET = {"slug-a", "slug-b", "slug-c"}
        parser.save_history()
        assert parser.load_history() == {"slug-a", "slug-b", "slug-c"}

    def test_load_corrupt_file(self, tmp_path, monkeypatch):
        path = str(tmp_path / "bad.json")
        with open(path, "w") as f:
            f.write("not valid json")
        monkeypatch.setattr(parser, "HISTORY_FILE", path)
        assert parser.load_history() == set()


class TestFoodCache:
    def test_cache_hit(self, monkeypatch):
        with parser.CACHE_LOCK:
            parser.FOOD_CACHE["chicken breast"] = "food-id-123"
        assert parser.get_id_for_food("Chicken Breast") == "food-id-123"

    def test_cache_miss(self):
        assert parser.get_id_for_food("nonexistent_ingredient_xyz") is None

    def test_none_name(self):
        assert parser.get_id_for_food(None) is None

    def test_empty_name(self):
        assert parser.get_id_for_food("") is None


class TestSession:
    def test_returns_session(self):
        s = parser.get_session()
        assert s is not None
        assert "Authorization" in s.headers

    def test_thread_local_reuse(self):
        assert parser.get_session() is parser.get_session()
