from sources.health import SourceHealth


def test_disables_after_threshold():
    h = SourceHealth("test")
    assert not h.disabled
    for _ in range(SourceHealth.THRESHOLD - 1):
        h.record_http_error(403)
    assert not h.disabled
    h.record_http_error(403)
    assert h.disabled


def test_success_resets_counter():
    h = SourceHealth("test")
    h.record_http_error(403)
    h.record_http_error(403)
    h.record_success()
    for _ in range(SourceHealth.THRESHOLD - 1):
        h.record_http_error(403)
    assert not h.disabled


def test_success_re_enables():
    h = SourceHealth("test")
    for _ in range(SourceHealth.THRESHOLD):
        h.record_http_error(403)
    assert h.disabled
    h.record_success()
    assert not h.disabled


def test_snapshot_includes_counters_and_timestamps():
    h = SourceHealth("test")
    h.record_success(duration_ms=12.5)
    h.record_error(reason="upstream_error", duration_ms=8.0)
    snap = h.snapshot()
    assert snap["request_count"] == 2
    assert snap["success_count"] == 1
    assert snap["error_count"] == 1
    assert snap["last_duration_ms"] == 8.0
    assert snap["last_success_at"] is not None
    assert snap["last_error_at"] is not None


def test_http_429_is_classified_as_quota_exhausted():
    h = SourceHealth("test")
    h.record_http_error(429, duration_ms=15.6)
    snap = h.snapshot()
    assert snap["reason"] == "quota_exhausted"
    assert snap["last_status"] == 429
    assert snap["consecutive_4xx"] == 1


def test_non_4xx_error_resets_disable_streak():
    h = SourceHealth("test")
    h.record_http_error(403)
    h.record_http_error(403)
    h.record_timeout(duration_ms=5)
    assert h.snapshot()["consecutive_4xx"] == 0
