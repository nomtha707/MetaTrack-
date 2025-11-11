# tracker/vectorstore.py (Numpy/SKLearn Version)
import numpy as np
import json
import os
import logging
import tracker.config as config
from sklearn.neighbors import NearestNeighbors

TEXT_DIM = 384  # This is fixed for our text model


class SimpleVectorStore:
    def __init__(self, path=config.EMBEDDINGS_PATH):
        self.path_np = path + ".npy"
        self.path_json = path + ".json"
        self.vectors = np.empty((0, TEXT_DIM), dtype=float)  # Default shape
        self.path_to_index = {}  # Maps file path to numpy row index
        self.index_to_path = {}  # Maps numpy row index to file path
        self.index = None  # This will hold the NearestNeighbors index
        self._load()
        self._rebuild_index()

    def _load(self):
        if os.path.exists(self.path_np) and os.path.exists(self.path_json):
            try:
                self.vectors = np.load(self.path_np)
                with open(self.path_json, 'r') as f:
                    self.path_to_index = json.load(f)

                self.index_to_path = {v: k for k,
                                      v in self.path_to_index.items()}

                if self.vectors.shape[0] != len(self.path_to_index):
                    logging.warning("Vector store mismatch, resetting.")
                    self._reset()
                else:
                    logging.info(
                        f"Loaded vector store: {self.vectors.shape[0]} embeddings.")
            except Exception as e:
                logging.error(f"Error loading vector store, resetting: {e}")
                self._reset()
        else:
            logging.info("No vector store found, starting new.")
            self._reset()

    def _rebuild_index(self):
        """Rebuilds the scikit-learn search index."""
        if self.vectors is None or self.vectors.shape[0] == 0:
            self.index = None
            return

        try:
            self.index = NearestNeighbors(n_neighbors=10, metric='cosine')
            self.index.fit(self.vectors)
            logging.info(
                f"Search index rebuilt with {self.vectors.shape[0]} items.")
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
        self.vectors = np.empty((0, TEXT_DIM), dtype=float)
        self.path_to_index = {}
        self.index_to_path = {}

    def upsert(self, path: str, vector: np.ndarray):
        if not isinstance(vector, np.ndarray) or vector.shape[0] != TEXT_DIM:
            logging.warning(
                f"Skipping upsert for {path}: vector dim {vector.shape[0]} != {TEXT_DIM}")
            return

        vector = vector.reshape(1, TEXT_DIM)

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
            new_idx = i
            new_path_to_index[p] = new_idx
            new_index_to_path[new_idx] = p

        self.path_to_index = new_path_to_index
        self.index_to_path = new_index_to_path

        self._save()
        self._rebuild_index()
        logging.info(f"Deleted {path} from vector store.")

    def query(self, emb, top_k=5):
        """Queries the vector store for the top_k most similar vectors."""
        if self.index is None or self.vectors.shape[0] == 0:
            logging.warning("Query attempted, but search index is empty.")
            return []

        emb = np.asarray(emb, dtype=float).reshape(1, -1)

        k_neighbors = min(top_k, self.vectors.shape[0])
        if k_neighbors == 0:
            return []

        distances, indices = self.index.kneighbors(
            emb, n_neighbors=k_neighbors)

        results = []
        for dist, idx in zip(distances[0], indices[0]):
            results.append({
                'path': self.index_to_path[idx],
                'score': float(1 - dist)
            })
        return results
