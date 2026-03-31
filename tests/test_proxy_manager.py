"""Tests for the proxy manager."""

from services.collector.proxy_manager import Proxy, ProxyManager, ProxyType


class TestProxy:
    def test_success_rate_initial(self):
        p = Proxy(host="1.2.3.4", port=8080, username="u", password="p", proxy_type=ProxyType.RESIDENTIAL)
        assert p.success_rate == 1.0

    def test_success_rate_after_failures(self):
        p = Proxy(host="1.2.3.4", port=8080, username="u", password="p", proxy_type=ProxyType.RESIDENTIAL)
        p.record_success()
        p.record_success()
        p.record_failure(429, "instagram")
        # 2 success, 1 fail = 0.667
        assert round(p.success_rate, 2) == 0.67

    def test_cooldown_on_429(self):
        p = Proxy(host="1.2.3.4", port=8080, username="u", password="p", proxy_type=ProxyType.RESIDENTIAL)
        p.record_failure(429, "instagram")
        assert p.in_cooldown("instagram") is True
        assert p.in_cooldown("tiktok") is False  # Different platform

    def test_cooldown_on_403(self):
        p = Proxy(host="1.2.3.4", port=8080, username="u", password="p", proxy_type=ProxyType.RESIDENTIAL)
        p.record_failure(403, "tiktok")
        assert p.in_cooldown("tiktok") is True

    def test_url_format(self):
        p = Proxy(host="proxy.example.com", port=9090, username="user", password="pass", proxy_type=ProxyType.DATACENTER)
        assert p.url == "http://user:pass@proxy.example.com:9090"


class TestProxyManager:
    def test_pool_stats_empty(self):
        pm = ProxyManager.__new__(ProxyManager)
        pm._pools = {ProxyType.RESIDENTIAL: [], ProxyType.DATACENTER: []}
        stats = pm.pool_stats
        assert stats["residential"]["total"] == 0
        assert stats["datacenter"]["total"] == 0

    def test_get_proxy_returns_none_when_empty(self):
        pm = ProxyManager.__new__(ProxyManager)
        pm._pools = {ProxyType.RESIDENTIAL: [], ProxyType.DATACENTER: []}
        result = pm.get_proxy("instagram")
        assert result is None

    def test_report_success(self):
        pm = ProxyManager.__new__(ProxyManager)
        pm._pools = {ProxyType.RESIDENTIAL: [], ProxyType.DATACENTER: []}
        p = Proxy(host="1.2.3.4", port=8080, username="u", password="p", proxy_type=ProxyType.RESIDENTIAL)
        pm.report_result(p, "instagram", True)
        assert p._success_count == 1

    def test_report_failure_sets_cooldown(self):
        pm = ProxyManager.__new__(ProxyManager)
        pm._pools = {ProxyType.RESIDENTIAL: [], ProxyType.DATACENTER: []}
        p = Proxy(host="1.2.3.4", port=8080, username="u", password="p", proxy_type=ProxyType.RESIDENTIAL)
        pm.report_result(p, "instagram", False, 429)
        assert p.in_cooldown("instagram") is True
