import numpy as np

from agent.wakeword import Features, WakeModel, augment


def test_fit_length_and_training_pipeline(tmp_path):
    rng = np.random.default_rng(0)
    # Без мережевих моделей: перевіряємо довжину й саму регресію на штучних векторах
    assert len(Features.fit_length(np.ones(100, dtype=np.int16))) == 25600
    assert len(Features.fit_length(np.ones(40000, dtype=np.int16))) == 25600
    assert len(augment(np.ones(1000, dtype=np.int16), rng, 3)) == 4
    pos = [rng.normal(1.0, 0.3, 288) for _ in range(30)]
    neg = [rng.normal(-1.0, 0.3, 288) for _ in range(60)]
    model, stats = WakeModel.train(pos, neg)
    assert stats["positives_ok"] > 0.9 and stats["negatives_rejected"] > 0.9
    model.save(tmp_path / "m.json")
    loaded = WakeModel.load(tmp_path / "m.json")
    assert loaded.score(np.full(288, 1.0)) > loaded.threshold > loaded.score(np.full(288, -1.0))
