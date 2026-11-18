"""Detecção de eventos no áudio com YAMNet (Google) + volume."""
import csv
import threading

import numpy as np

GRUPOS = {
    "risada": ["Laughter", "Giggle", "Snicker", "Belly laugh", "Chuckle, chortle"],
    "grito": ["Screaming", "Shout", "Yell", "Bellow", "Whoop", "Battle cry"],
    "explosao": ["Explosion", "Boom"],
}


def rms_db(audio: np.ndarray) -> float:
    """Volume em dB de um trecho float32 [-1, 1]."""
    return float(20 * np.log10(np.sqrt(np.mean(audio ** 2)) + 1e-9))


class DetectorAudio:
    """Carrega o YAMNet uma vez e é compartilhado entre todas as lives."""

    def __init__(self):
        import tensorflow as tf
        import tensorflow_hub as hub

        self.modelo = hub.load("https://tfhub.dev/google/yamnet/1")
        caminho = self.modelo.class_map_path().numpy().decode()
        with tf.io.gfile.GFile(caminho) as f:
            nomes = [linha["display_name"] for linha in csv.DictReader(f)]

        self.indices = {
            grupo: [nomes.index(n) for n in classes if n in nomes]
            for grupo, classes in GRUPOS.items()
        }
        self.idx_musica = nomes.index("Music")
        self.lock = threading.Lock()

    def analisar(self, audio: np.ndarray):
        """audio: float32 mono 16 kHz. Retorna ({grupo: prob}, prob_musica)."""
        with self.lock:
            scores, _, _ = self.modelo(audio)
        s = scores.numpy().max(axis=0)
        grupos = {g: float(s[idx].max()) if idx else 0.0 for g, idx in self.indices.items()}
        return grupos, float(s[self.idx_musica])
