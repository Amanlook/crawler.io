"""Tests for the normalizer layer."""

from datetime import datetime, timezone

from services.collector.base import RawCreatorData, RawPostData
from services.normalizer.instagram import InstagramNormalizer
from services.normalizer.tiktok import TikTokNormalizer
from services.normalizer.youtube import YouTubeNormalizer
from services.normalizer.registry import get_normalizer


class TestInstagramNormalizer:
    def setup_method(self):
        self.normalizer = InstagramNormalizer()

    def test_normalize_creator_web_api_format(self):
        raw = RawCreatorData(
            platform="instagram",
            platform_id="12345678",
            username="testuser",
            raw_data={
                "username": "testuser",
                "full_name": "Test User",
                "biography": "Hello world",
                "profile_pic_url_hd": "https://example.com/pic.jpg",
                "is_verified": True,
                "edge_followed_by": {"count": 100000},
                "edge_follow": {"count": 500},
                "edge_owner_to_timeline_media": {"count": 200, "edges": []},
                "external_url": "https://testuser.com",
            },
            collected_at=datetime.now(timezone.utc),
        )

        result = self.normalizer.normalize_creator(raw)

        assert result.platform == "instagram"
        assert result.username == "testuser"
        assert result.display_name == "Test User"
        assert result.follower_count == 100000
        assert result.following_count == 500
        assert result.post_count == 200
        assert result.is_verified is True
        assert len(result.external_urls) == 1
        assert result.external_urls[0]["url"] == "https://testuser.com"

    def test_normalize_post_reel(self):
        raw = RawPostData(
            platform="instagram",
            platform_post_id="ABC123",
            creator_platform_id="12345678",
            raw_data={
                "shortcode": "ABC123",
                "product_type": "clips",
                "is_video": True,
                "video_url": "https://example.com/video.mp4",
                "display_url": "https://example.com/thumb.jpg",
                "dimensions": {"width": 1080, "height": 1920},
                "video_duration": 28.5,
                "edge_media_to_caption": {
                    "edges": [{"node": {"text": "Check this out! #travel #food @friend"}}]
                },
                "edge_media_preview_like": {"count": 5000},
                "edge_media_preview_comment": {"count": 120},
                "video_view_count": 50000,
                "taken_at_timestamp": 1711900800,
            },
            collected_at=datetime.now(timezone.utc),
        )

        result = self.normalizer.normalize_post(raw)

        assert result.post_type == "reel"
        assert result.like_count == 5000
        assert result.comment_count == 120
        assert result.view_count == 50000
        assert "travel" in result.hashtags
        assert "food" in result.hashtags
        assert "friend" in result.mentions
        assert result.media[0]["type"] == "video"

    def test_normalize_post_image(self):
        raw = RawPostData(
            platform="instagram",
            platform_post_id="DEF456",
            creator_platform_id="12345678",
            raw_data={
                "shortcode": "DEF456",
                "is_video": False,
                "display_url": "https://example.com/image.jpg",
                "dimensions": {"width": 1080, "height": 1080},
                "edge_media_to_caption": {"edges": [{"node": {"text": "Nice day"}}]},
                "edge_media_preview_like": {"count": 2000},
                "edge_media_preview_comment": {"count": 50},
                "taken_at_timestamp": 1711900800,
            },
            collected_at=datetime.now(timezone.utc),
        )

        result = self.normalizer.normalize_post(raw)

        assert result.post_type == "image"
        assert result.media[0]["type"] == "image"


class TestTikTokNormalizer:
    def setup_method(self):
        self.normalizer = TikTokNormalizer()

    def test_normalize_creator(self):
        raw = RawCreatorData(
            platform="tiktok",
            platform_id="987654",
            username="tiktokuser",
            raw_data={
                "user": {
                    "uniqueId": "tiktokuser",
                    "nickname": "TikTok Star",
                    "signature": "Making videos ✨",
                    "avatarLarger": "https://example.com/avatar.jpg",
                    "verified": True,
                },
                "stats": {
                    "followerCount": 500000,
                    "followingCount": 100,
                    "heartCount": 10000000,
                    "videoCount": 200,
                },
            },
            collected_at=datetime.now(timezone.utc),
        )

        result = self.normalizer.normalize_creator(raw)

        assert result.platform == "tiktok"
        assert result.username == "tiktokuser"
        assert result.follower_count == 500000
        assert result.post_count == 200
        assert result.is_verified is True

    def test_normalize_post(self):
        raw = RawPostData(
            platform="tiktok",
            platform_post_id="111222333",
            creator_platform_id="987654",
            raw_data={
                "id": "111222333",
                "desc": "Dancing tutorial #dance #viral",
                "createTime": "1711900800",
                "video": {
                    "playAddr": "https://example.com/video.mp4",
                    "cover": "https://example.com/cover.jpg",
                    "duration": 15,
                    "width": 576,
                    "height": 1024,
                },
                "stats": {
                    "diggCount": 25000,
                    "commentCount": 300,
                    "shareCount": 1500,
                    "playCount": 500000,
                    "collectCount": 800,
                },
                "challenges": [{"title": "dance"}, {"title": "viral"}],
            },
            collected_at=datetime.now(timezone.utc),
        )

        result = self.normalizer.normalize_post(raw)

        assert result.post_type == "short"
        assert result.like_count == 25000
        assert result.share_count == 1500
        assert result.view_count == 500000
        assert "dance" in result.hashtags
        assert "viral" in result.hashtags


class TestYouTubeNormalizer:
    def setup_method(self):
        self.normalizer = YouTubeNormalizer()

    def test_normalize_creator(self):
        raw = RawCreatorData(
            platform="youtube",
            platform_id="UC_CHANNEL_ID",
            username="ytchannel",
            raw_data={
                "snippet": {
                    "title": "YouTube Channel",
                    "description": "We make great videos",
                    "customUrl": "@ytchannel",
                    "thumbnails": {"high": {"url": "https://example.com/channel.jpg"}},
                },
                "statistics": {
                    "subscriberCount": "2000000",
                    "videoCount": "500",
                    "viewCount": "500000000",
                },
                "brandingSettings": {"channel": {"keywords": "tech"}},
            },
            collected_at=datetime.now(timezone.utc),
        )

        result = self.normalizer.normalize_creator(raw)

        assert result.platform == "youtube"
        assert result.follower_count == 2000000
        assert result.post_count == 500
        assert result.display_name == "YouTube Channel"

    def test_normalize_post_short(self):
        raw = RawPostData(
            platform="youtube",
            platform_post_id="dQw4w9WgXcQ",
            creator_platform_id="UC_CHANNEL_ID",
            raw_data={
                "snippet": {
                    "title": "Quick Tip #shorts",
                    "description": "A 30 second tip #productivity",
                    "publishedAt": "2026-03-30T10:00:00Z",
                    "thumbnails": {
                        "maxres": {"url": "https://example.com/thumb.jpg", "width": 1280, "height": 720}
                    },
                },
                "statistics": {
                    "viewCount": "1000000",
                    "likeCount": "50000",
                    "commentCount": "2000",
                },
                "contentDetails": {"duration": "PT30S"},
            },
            collected_at=datetime.now(timezone.utc),
        )

        result = self.normalizer.normalize_post(raw)

        assert result.post_type == "short"  # <= 60s
        assert result.view_count == 1000000
        assert result.like_count == 50000
        assert "shorts" in result.hashtags or "productivity" in result.hashtags


class TestNormalizerRegistry:
    def test_get_instagram_normalizer(self):
        n = get_normalizer("instagram")
        assert isinstance(n, InstagramNormalizer)

    def test_get_tiktok_normalizer(self):
        n = get_normalizer("tiktok")
        assert isinstance(n, TikTokNormalizer)

    def test_get_youtube_normalizer(self):
        n = get_normalizer("youtube")
        assert isinstance(n, YouTubeNormalizer)

    def test_unknown_platform_raises(self):
        import pytest
        with pytest.raises(ValueError):
            get_normalizer("facebook")
