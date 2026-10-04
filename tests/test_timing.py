import time

from orvix.core.interfaces import Risk, max_risk
from orvix.core.timing import Timings


def test_stage_and_mark():
    t = Timings()
    with t.stage("x"):
        time.sleep(0.01)
    t.mark("first")
    d = t.as_dict()
    assert d["stage:x"] >= 10
    assert "mark:first" in d


def test_max_risk():
    assert max_risk(Risk.SAFE, Risk.CONFIRM) is Risk.CONFIRM
    assert max_risk(Risk.CONFIRM, Risk.BLOCKED, Risk.SAFE) is Risk.BLOCKED
    assert max_risk() is Risk.SAFE
