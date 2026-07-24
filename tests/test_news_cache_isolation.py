"""Tests for cache isolation in news aggregation.

Verifies that preprocess_with_groq does not mutate cached news items
and never exposes internal _relevance keys to callers.
"""

import pytest
from unittest.mock import MagicMock, patch
from app.services import news_aggregator
from app.services.cache import aggregated_news_cache, get_cached, set_cached


@pytest.fixture
def sample_news_items():
    """Create sample news items for testing."""
    return [
        {
            'title': 'Stock A surges on earnings',
            'summary': 'Original summary for A',
            'link': 'http://example.com/1',
            'publisher': 'TestNews',
            'published': 1000000,
        },
        {
            'title': 'Stock B faces headwinds',
            'summary': 'Original summary for B',
            'link': 'http://example.com/2',
            'publisher': 'TestNews',
            'published': 1000001,
        },
        {
            'title': 'Stock C launches new product',
            'summary': 'Original summary for C',
            'link': 'http://example.com/3',
            'publisher': 'TestNews',
            'published': 1000002,
        },
        {
            'title': 'Market trends show decline',
            'summary': 'Original summary for market',
            'link': 'http://example.com/4',
            'publisher': 'TestNews',
            'published': 1000003,
        },
    ]


@pytest.fixture
def mock_groq_client():
    """Create a mock Groq client."""
    client = MagicMock()
    # Simulate Groq response: scores 8, 3, 6, 7
    # Only items 0, 2, 3 have score >= 5, so item 1 should be filtered out
    groq_response = """1. [8] Stock A surges significantly
2. [3] Stock B faces minor challenges
3. [6] Stock C launches innovative product
4. [7] Market shows declining trend"""

    client.chat.completions.create.return_value.choices[0].message.content = groq_response
    return client


class TestCacheIsolation:
    """Ensure cached news items are never mutated by preprocess_with_groq."""

    def test_cached_items_unchanged_after_preprocess(self, sample_news_items, mock_groq_client):
        """Verify that items in aggregated_news_cache remain unchanged after preprocessing.

        This is the core bug fix: preprocess_with_groq must not mutate the
        input items or the cached objects.
        """
        # Clear cache
        aggregated_news_cache.clear()

        # Store items in cache
        cache_key = "agg_TEST"
        set_cached(aggregated_news_cache, cache_key, sample_news_items)

        # Get the cached items
        cached_items = get_cached(aggregated_news_cache, cache_key)
        assert cached_items is not None

        # Store original state for comparison
        original_items = [dict(item) for item in cached_items]

        # Call preprocess_with_groq with stubbed Groq client
        with patch('app.services.news_aggregator._get_groq_client', return_value=mock_groq_client):
            result = news_aggregator.preprocess_with_groq(cached_items, "TEST")

        # Verify result is different from input (it's filtered)
        assert len(result) == 3  # Items 0, 2, 3 should pass (scores 8, 6, 7)

        # Verify cached items are still in the cache and unchanged
        cached_after = get_cached(aggregated_news_cache, cache_key)
        assert cached_after is not None
        assert len(cached_after) == 4  # All original items still there

        # Verify no _relevance key in cached items
        for idx, item in enumerate(cached_after):
            assert '_relevance' not in item, f"Cached item {idx} has leaked _relevance key"
            # Verify summaries are unchanged from originals
            assert item['summary'] == original_items[idx]['summary'], \
                f"Cached item {idx} summary was mutated"
            assert item['title'] == original_items[idx]['title']
            assert item['link'] == original_items[idx]['link']

    def test_no_relevance_key_in_returned_items(self, sample_news_items, mock_groq_client):
        """Verify that returned items never contain the internal _relevance key."""
        with patch('app.services.news_aggregator._get_groq_client', return_value=mock_groq_client):
            result = news_aggregator.preprocess_with_groq(sample_news_items, "TEST")

        # Verify no _relevance key in any returned item
        for item in result:
            assert '_relevance' not in item, "Returned item exposes internal _relevance key"

    def test_no_relevance_key_in_input_items(self, sample_news_items, mock_groq_client):
        """Verify that input items are not mutated by the function."""
        original_items = [dict(item) for item in sample_news_items]

        with patch('app.services.news_aggregator._get_groq_client', return_value=mock_groq_client):
            _ = news_aggregator.preprocess_with_groq(sample_news_items, "TEST")

        # Verify input items are unchanged
        for idx, item in enumerate(sample_news_items):
            assert '_relevance' not in item, f"Input item {idx} has _relevance key"
            assert item == original_items[idx], f"Input item {idx} was mutated"

    def test_exception_fallback_no_mutation(self, sample_news_items):
        """Verify that exception fallback returns input unchanged without mutations."""
        original_items = [dict(item) for item in sample_news_items]

        # Mock Groq client to raise an exception
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception("Network error")

        with patch('app.services.news_aggregator._get_groq_client', return_value=mock_client):
            with patch('app.services.news_aggregator.note_groq_error'):
                result = news_aggregator.preprocess_with_groq(sample_news_items, "TEST")

        # Result should be the original input (unchanged)
        assert result is sample_news_items

        # Verify no _relevance key was added, and nothing else was rewritten
        for idx, item in enumerate(result):
            assert '_relevance' not in item
            assert item == original_items[idx], f"Input item {idx} was mutated"

    def test_empty_groq_response_no_mutation(self, sample_news_items):
        """Verify that empty or unparseable Groq response doesn't mutate items."""
        original_items = [dict(item) for item in sample_news_items]

        # Mock Groq client with unparseable response
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value.choices[0].message.content = "invalid response"

        with patch('app.services.news_aggregator._get_groq_client', return_value=mock_client):
            result = news_aggregator.preprocess_with_groq(sample_news_items, "TEST")

        # With unparseable response, all items default to score 10 and should be included
        # But summaries should remain unchanged
        assert len(result) == 4
        for idx, item in enumerate(result):
            assert '_relevance' not in item
            assert item['summary'] == original_items[idx]['summary']

    def test_partial_groq_response_with_cache(self, sample_news_items, mock_groq_client):
        """Test integration: cache + partial Groq response + filtering."""
        aggregated_news_cache.clear()

        cache_key = "agg_TEST2"
        set_cached(aggregated_news_cache, cache_key, sample_news_items)

        with patch('app.services.news_aggregator._get_groq_client', return_value=mock_groq_client):
            result = news_aggregator.preprocess_with_groq(sample_news_items, "TEST2")

        # Should have 3 items (scores 8, 6, 7; item 1 with score 3 filtered out)
        assert len(result) == 3

        # Verify result items don't have _relevance
        for item in result:
            assert '_relevance' not in item

        # Verify cached items still intact
        cached = get_cached(aggregated_news_cache, cache_key)
        assert len(cached) == 4
        for item in cached:
            assert '_relevance' not in item

    def test_no_client_returns_input_unchanged(self, sample_news_items):
        """Verify that when Groq client is None, input is returned unchanged."""
        original_items = [dict(item) for item in sample_news_items]

        with patch('app.services.news_aggregator._get_groq_client', return_value=None):
            result = news_aggregator.preprocess_with_groq(sample_news_items, "TEST")

        # Should return original items unchanged
        assert result is sample_news_items
        for idx, item in enumerate(result):
            assert '_relevance' not in item
            assert item == original_items[idx], f"Input item {idx} was mutated"

    def test_empty_news_items_no_mutation(self):
        """Verify that empty input is handled correctly."""
        empty_items = []

        with patch('app.services.news_aggregator._get_groq_client', return_value=MagicMock()):
            result = news_aggregator.preprocess_with_groq(empty_items, "TEST")

        assert result is empty_items

    def test_summaries_updated_in_copies_only(self, sample_news_items, mock_groq_client):
        """Verify that summary updates only affect returned copies, not originals."""
        original_items = [dict(item) for item in sample_news_items]

        with patch('app.services.news_aggregator._get_groq_client', return_value=mock_groq_client):
            result = news_aggregator.preprocess_with_groq(sample_news_items, "TEST")

        # Result should have updated summaries
        assert result[0]['summary'] == 'Stock A surges significantly'  # Item 0 in result
        assert result[1]['summary'] == 'Stock C launches innovative product'  # Item 2 in result
        assert result[2]['summary'] == 'Market shows declining trend'  # Item 3 in result

        # Original items should still have original summaries
        assert sample_news_items[0]['summary'] == original_items[0]['summary']
        assert sample_news_items[1]['summary'] == original_items[1]['summary']
        assert sample_news_items[2]['summary'] == original_items[2]['summary']
        assert sample_news_items[3]['summary'] == original_items[3]['summary']

    def test_no_client_and_empty_items(self):
        """Verify edge case: no client and empty items."""
        with patch('app.services.news_aggregator._get_groq_client', return_value=None):
            result = news_aggregator.preprocess_with_groq([], "TEST")

        assert result == []
