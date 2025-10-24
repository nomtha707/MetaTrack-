# Simple on-disk vector store using numpy + sklearn NearestNeighbors as a fallback
import os
import numpy as np
from joblib import dump, load
from sklearn.neighbors import NearestNeighbors


class SimpleVectorStore:
    def __init__(self, path='./db/embeddings.joblib'):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.path = path
        # structure: {'ids': [path,...], 'embs': np.array([...])}
        if os.path.exists(path):
            data = load(path)
            self.ids = data.get('ids', [])
            self.embs = data.get('embs', None)
        else:
            self.ids = []
            self.embs = None
        self._rebuild_index()

    def _rebuild_index(self):
        if self.embs is None or len(self.ids) == 0:
            self.index = None
            return
        try:
            self.index = NearestNeighbors(n_neighbors=10, metric='cosine')
            self.index.fit(self.embs)
        except Exception as e:
            print('Failed to build index', e)
            self.index = None

    def upsert(self, id: str, emb: np.ndarray):
        emb = np.asarray(emb, dtype=float)
        if self.embs is None:
            self.ids = [id]
            self.embs = emb.reshape(1, -1)
        else:
            # replace if exists
            if id in self.ids:
                idx = self.ids.index(id)
                self.embs[idx] = emb
            else:
                self.ids.append(id)
                # pad to same dimension if necessary
                if emb.shape[0] != self.embs.shape[1]:
                    # try to resize smaller/greater by zero-padding/truncating
                    new_dim = max(emb.shape[0], self.embs.shape[1])
                    new_embs = np.zeros((self.embs.shape[0], new_dim))
                    new_embs[:, :self.embs.shape[1]] = self.embs
                    emb2 = np.zeros((new_dim,))
                    emb2[:emb.shape[0]] = emb
                    self.embs = new_embs
                    emb = emb2
                self.embs = np.vstack([self.embs, emb.reshape(1, -1)])
        self._persist()
        self._rebuild_index()

    def delete(self, id: str):
        if id in self.ids:
            idx = self.ids.index(id)
            self.ids.pop(idx)
            self.embs = np.delete(self.embs, idx, axis=0)
            if len(self.ids) == 0:
                self.embs = None
            self._persist()
            self._rebuild_index()

    def query(self, emb, top_k=5):
        if self.index is None:
            return []
        import numpy as np
        emb = np.asarray(emb, dtype=float).reshape(1, -1)
        distances, indices = self.index.kneighbors(
            emb, n_neighbors=min(top_k, len(self.ids)))
        results = []
        for dist, idx in zip(distances[0], indices[0]):
            results.append({'id': self.ids[idx], 'score': float(1-dist)})
        return results

    def _persist(self):
        dump({'ids': self.ids, 'embs': self.embs}, self.path)
