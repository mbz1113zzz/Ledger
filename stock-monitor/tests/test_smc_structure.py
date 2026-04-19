from datetime import datetime, timezone
from smc.structure import StructureTracker
from smc.types import Candle


def _c(m, o, h, l, c):
    return Candle(ts=datetime(2026, 4, 19, 14, m, tzinfo=timezone.utc),
                  tf="5m", o=o, h=h, l=l, c=c, v=1000)


def test_fractal_swing_high_detected_after_window():
    st = StructureTracker(ticker="NVDA", fractal_window=5)
    bars = [
        _c(0, 100, 101, 99, 100),
        _c(5, 100, 102, 99, 101),
        _c(10, 101, 105, 100, 102),
        _c(15, 102, 103, 100, 101),
        _c(20, 101, 102, 99, 100),
    ]
    events = []
    for b in bars:
        events.extend(st.on_candle(b))
    kinds = [e.kind for e in events]
    assert "swing_high" in kinds


def test_bos_up_fires_when_new_high_breaks_prior_swing_high_in_uptrend():
    st = StructureTracker(ticker="NVDA", fractal_window=5)
    seq = [(0, 100, 101, 99, 100), (5, 100, 102, 99, 101),
           (10, 101, 105, 100, 102), (15, 102, 103, 100, 101),
           (20, 101, 102, 99, 100),
           (25, 100, 101, 98, 99),
           (30, 99, 100, 97, 98),
           (35, 98, 101, 97, 100),
           (40, 100, 106, 99, 106),
           ]
    events = []
    for args in seq:
        events.extend(st.on_candle(_c(*args)))
    kinds = [e.kind for e in events]
    assert "bos_up" in kinds


def test_choch_up_fires_when_downtrend_breaks_last_swing_high():
    st = StructureTracker(ticker="TSLA", fractal_window=5)
    seq = [(0, 100, 101, 99, 100),
           (5, 100, 103, 99, 101),
           (10, 101, 105, 100, 102),   # swing_high at 105
           (15, 102, 103, 100, 101),
           (20, 101, 102, 98, 99),
           (25, 99, 100, 95, 96),
           (30, 96, 98, 92, 93),       # swing_low at 92 (confirmed after idx 8)
           (35, 93, 98, 94, 97),
           (40, 97, 99, 95, 98),
           (45, 98, 99, 89, 90),       # breaks 92 -> bos_down, trend=down
           (50, 90, 108, 89, 107),     # breaks 105 with trend=down -> choch_up
           ]
    events = []
    for args in seq:
        events.extend(st.on_candle(_c(*args)))
    kinds = [e.kind for e in events]
    assert "choch_up" in kinds
