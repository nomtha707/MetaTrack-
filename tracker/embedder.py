import os
import numpy as np

BACKEND = os.environ.get('EMBEDDING_BACKEND', 'sentence-transformers')


class Embedder:
    def __init__(self, backend='sentence-transformers'):
        self.backend = backend
        if backend == 'sentence-transformers':
            try:
                from sentence_transformers import SentenceTransformer
                self.model = SentenceTransformer('all-MiniLM-L6-v2')
            except Exception as e:
                print(
                    'SentenceTransformers not available, falling back to tfidf. Error:', e)
                self.model = None
                self.backend = 'tfidf'
        else:
            self.model = None
            # tfidf will be created lazily in VectorStore

    def embed(self, text: str):
        if not text:
            return np.zeros(384, dtype=float) if self.backend == 'sentence-transformers' else np.zeros(1)
        if self.backend == 'sentence-transformers' and self.model is not None:
            emb = self.model.encode(text, show_progress_bar=False)
            return np.array(emb, dtype=float)
        else:
            # fallback: use a simple hashing vector (not ideal but works offline)
            import hashlib
            h = hashlib.sha256(text.encode('utf-8')).digest()
            vec = np.frombuffer(h, dtype='u1').astype(float)
            return vec
