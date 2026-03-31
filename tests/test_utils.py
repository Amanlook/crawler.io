"""Tests for shared utilities."""

from shared.db.models import generate_id


class TestGenerateId:
    def test_creator_prefix(self):
        id = generate_id("cr")
        assert id.startswith("cr_")
        assert len(id) == 19  # cr_ + 16 chars

    def test_post_prefix(self):
        id = generate_id("po")
        assert id.startswith("po_")

    def test_unique_ids(self):
        ids = {generate_id("cr") for _ in range(100)}
        assert len(ids) == 100  # All unique
