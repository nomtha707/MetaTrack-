# tracker/vectorstore.py (Multi-Modal Version)
import numpy as np
import json
import os
import logging
from sklearn.neighbors import NearestNeighbors

class SimpleVectorStore:
    # We added 'dim' to the initialization so it can handle 384 (text) or 512 (image)
    def __init__(self, path, dim):
        self.path_np = path + ".npy"
        self.path_json = path + ".json"
        self.dim = dim  # The dimension size
        self.vectors = np.empty((0, self.dim), dtype=float) 
        self.path_to_index = {}  
        self.index_to_path = {}  
        self.index = None  
        self._load()
        self._rebuild_index()

    def _load(self):
        if os.path.exists(self.path_np) and os.path.exists(self.path_json):
            try:
                self.vectors = np.load(self.path_np)
                with open(self.path_json, 'r') as f:
                    self.path_to_index = json.load(f)

                self.index_to_path = {int(v): k for k, v in self.path_to_index.items()}

                # Check if dimensions match what we expect
                if self.vectors.shape[0] != len(self.path_to_index) or (self.vectors.shape[1] != self.dim and self.vectors.shape[0] > 0):
                    logging.warning(f"Vector store mismatch at {self.path_np}, resetting.")
                    self._reset()
                else:
                    logging.info(f"Loaded vector store: {self.vectors.shape[0]} embeddings of dim {self.dim}.")
            except Exception as e:
                logging.error(f"Error loading vector store, resetting: {e}")
                self._reset()
        else:
            logging.info(f"No vector store found at {self.path_np}, starting new.")
            self._reset()

    def _rebuild_index(self):
        if self.vectors is None or self.vectors.shape[0] == 0:
            self.index = None
            return
        try:
            self.index = NearestNeighbors(n_neighbors=10, metric='cosine')
            self.index.fit(self.vectors)
        except Exception as e:
            logging.error(f'Failed to build search index: {e}')
            self.index = None

    def _save(self):
        try:
            np.save(self.path_np, self.vectors)
            with open(self.path_json, 'w') as f:
                json.dump(self.path_to_index, f)
        except Exception as e:
            logging.error(f"Error saving vector store: {e}")

    def _reset(self):
        self.vectors = np.empty((0, self.dim), dtype=float)
        self.path_to_index = {}
        self.index_to_path = {}

    def upsert(self, path: str, vector: np.ndarray):
        if not isinstance(vector, np.ndarray) or vector.shape[0] != self.dim:
            logging.warning(f"Skipping upsert for {path}: vector dim {vector.shape[0]} != {self.dim}")
            return

        vector = vector.reshape(1, self.dim)

        if path in self.path_to_index:
            idx = self.path_to_index[path]
            self.vectors[idx] = vector
        else:
            self.vectors = np.vstack([self.vectors, vector])
            new_idx = self.vectors.shape[0] - 1
            self.path_to_index[path] = new_idx
            self.index_to_path[new_idx] = path

        self._save()
        self._rebuild_index()

    def delete(self, path: str):
        if path not in self.path_to_index:
            return

        idx_to_delete = self.path_to_index.pop(path)
        self.index_to_path.pop(idx_to_delete)
        self.vectors = np.delete(self.vectors, idx_to_delete, axis=0)

        # Rebuild maps
        new_path_to_index = {}
        new_index_to_path = {}
        for i, (p, old_idx) in enumerate(self.path_to_index.items()):
            new_path_to_index[p] = i
            new_index_to_path[i] = p

        self.path_to_index = new_path_to_index
        self.index_to_path = new_index_to_path

        self._save()
        self._rebuild_index()

    def query(self, emb, top_k=5):
        if self.index is None or self.vectors.shape[0] == 0:
            return []

        emb = np.asarray(emb, dtype=float).reshape(1, -1)
        k_neighbors = min(top_k, self.vectors.shape[0])
        if k_neighbors == 0:
            return []

        distances, indices = self.index.kneighbors(emb, n_neighbors=k_neighbors)

        results = []
        for dist, idx in zip(distances[0], indices[0]):
            results.append({
                'path': self.index_to_path[idx],
                'score': float(1 - dist)
            })
        return results