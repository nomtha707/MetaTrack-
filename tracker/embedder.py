import os
import numpy as np
import sys  # --- Import sys
import traceback

BACKEND = os.environ.get('EMBEDDING_BACKEND', 'sentence-transformers')

# --- NEW FUNCTION TO GET MODEL PATH ---


def get_model_path():
    """
    Find the path to the 'all-MiniLM-L6-v2' model.
    If running as a PyInstaller bundle, it will be in a bundled 'model' dir.
    Otherwise, it's None, and sentence-transformers will download it.
    """
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        # Running as a bundled .exe
        # We will bundle the model into a 'model' folder next to the .exe
        # sys.executable is ...project/dist/MetaTracker.exe
        # os.path.dirname(sys.executable) is ...project/dist
        bundle_dir = os.path.dirname(sys.executable)
        model_dir = os.path.join(bundle_dir, 'model', 'all-MiniLM-L6-v2')

        # Check if our bundled model exists
        if os.path.isdir(model_dir):
            return model_dir

    # Running as a .py script OR bundled model not found.
    # Let sentence-transformers handle it (download or use cache)
    return 'all-MiniLM-L6-v2'
# --- END NEW FUNCTION ---


class Embedder:
    def __init__(self, backend='sentence-transformers'):
        self.backend = backend
        if backend == 'sentence-transformers':
            try:
                from sentence_transformers import SentenceTransformer

                # --- THIS IS THE UPDATED PART ---
                model_name_or_path = get_model_path()
                print(f"Loading model from: {model_name_or_path}")
                # --- END UPDATED PART ---

                self.model = SentenceTransformer(model_name_or_path)
            except Exception as e:
                print(
                    'SentenceTransformers not available, falling back to tfidf. Error:', e)
                # Log this error if it happens
                import logging
                logging.error(
                    f"Failed to load SentenceTransformer: {e}\n{traceback.format_exc()}")
                self.model = None
                self.backend = 'tfidf'
        else:
            self.model = None
            # tfidf will be created lazily in VectorStore

    def embed(self, text: str):
        if not text:
            # --- FIX FOR DATABASE MISMATCH ---
            # Return 384-dim zero vector if ST is intended, otherwise simple hash
            return np.zeros(384, dtype=float) if self.backend == 'sentence-transformers' else np.zeros(32, dtype=float)
            # --- END FIX ---

        if self.backend == 'sentence-transformers' and self.model is not None:
            emb = self.model.encode(text, show_progress_bar=False)
            return np.array(emb, dtype=float)
        else:
            # fallback: use a simple hashing vector (32-dims)
            import hashlib
            h = hashlib.sha256(text.encode('utf-8')).digest()
            vec = np.frombuffer(h, dtype='u1').astype(float)  # shape (32,)
            return vec
