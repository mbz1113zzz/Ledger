from sources.health import SourceHealth


def test_disables_after_threshold():
    h = SourceHealth("test")
    assert not h.disabled
    for _ in range(SourceHealth.THRESHOLD - 1):
        h.record_4xx(403)
    assert not h.disabled
    h.record_4xx(403)
    assert h.disabled


def test_success_resets_counter():
    h = SourceHealth("test")
    h.record_4xx(403)
    h.record_4xx(403)
    h.record_success()
    for _ in range(SourceHealth.THRESHOLD - 1):
        h.record_4xx(403)
    assert not h.disabled


def test_success_re_enables():
    h = SourceHealth("test")
    for _ in range(SourceHealth.THRESHOLD):
        h.record_4xx(403)
    assert h.disabled
    h.record_success()
    assert not h.disabled
