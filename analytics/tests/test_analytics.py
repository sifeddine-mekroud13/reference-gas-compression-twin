import numpy as np

from analytics import vibration
from analytics.anomaly import PCAMonitor, SimilarityModel, metrics, persistence


def _corr_data(n: int, rng: np.random.Generator) -> np.ndarray:
    lat = rng.normal(size=(n, 2))
    mix = np.array([[1, 0.8, 0.2, 0.0, 0.5], [0.0, 0.3, 1.0, 0.9, -0.4]])
    return lat @ mix + 0.1 * rng.normal(size=(n, 5))


def test_pca_false_alarm_near_alpha_and_detects_break() -> None:
    rng = np.random.default_rng(1)
    train = _corr_data(4000, rng)
    mon = PCAMonitor.fit(train)
    far = mon.flags(_corr_data(4000, rng)).mean()
    assert far < 0.04  # nominal 1 % per statistic, two statistics combined
    broken = _corr_data(500, rng)
    broken[:, 3] += 1.0  # correlation break, small in absolute terms
    assert mon.flags(broken).mean() > 0.9
    assert np.argmax(mon.contributions(broken).mean(0)) == 3


def test_similarity_model() -> None:
    rng = np.random.default_rng(2)
    m = SimilarityModel.fit(_corr_data(2000, rng))
    assert m.flags(_corr_data(1000, rng)).mean() < 0.05
    b = _corr_data(300, rng)
    b[:, 0] += 1.5
    assert m.flags(b).mean() > 0.8


def test_persistence_and_metrics() -> None:
    f = np.array([0, 1, 0, 0, 1, 1, 1, 0, 0], bool)
    a = persistence(f, 3, 5)
    assert not a[:5].any() and a[6]
    t = np.arange(9) * 10.0
    m = metrics(a, np.array([0, 0, 0, 0, 1, 1, 1, 1, 1]), t)
    assert m["false_alarm_rate"] == 0.0 and m["detection_delay_s"] == 10.0


def test_vibration_features_find_1x() -> None:
    rng = np.random.default_rng(0)
    x = vibration.waveform("unbalance", rng, 9000)
    feat = vibration.features(x, 9000)
    assert feat[0] > 15 and feat[0] > 3 * feat[1]
    w = vibration.waveform("oil_whirl", rng, 9000)
    assert vibration.features(w, 9000)[5] > 5


def test_vibration_classifier_beats_chance() -> None:
    r = vibration.evaluate()
    assert r["rf_accuracy"] > 0.9
    assert r["rule_accuracy"] > 1 / 6
