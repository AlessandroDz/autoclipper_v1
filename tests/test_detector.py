import numpy as np
import pytest

from autoclipper.detector import rms_db


def test_silencio_fica_muito_baixo():
    assert rms_db(np.zeros(16000, dtype=np.float32)) < -150


def test_senoide_em_escala_cheia_da_menos_3db():
    t = np.arange(16000) / 16000
    seno = np.sin(2 * np.pi * 440 * t).astype(np.float32)
    assert rms_db(seno) == pytest.approx(-3.01, abs=0.05)


def test_metade_do_volume_da_menos_6db():
    t = np.arange(16000) / 16000
    seno = np.sin(2 * np.pi * 440 * t).astype(np.float32)
    assert rms_db(seno / 2) - rms_db(seno) == pytest.approx(-6.02, abs=0.05)
