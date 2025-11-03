import os
import numpy as np
import sys
import traceback
import logging

# --- FUNCTION TO GET MODEL PATH ---


def get_model_path():
    """
    Find the path to the 'all-MiniLM-L6-v2' model.
    If running as a PyInstaller bundle, it will be in a bundled 'model' dir.
    Otherwise, it's None, and sentence-transformers will download it.
    """
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        # Running as a bundled .exe
        bundle_dir = os.path.dirname(sys.executable)
        model_dir = os.path.join(bundle_dir, 'model', 'all-MiniLM-L6-v2')
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

                model_name_or_path = get_model_path()
                logging.info(f"Loading model from: {model_name_or_path}")
                # This print statement is the one you saw in your console
                print(f"Loading model from: {model_name_or_path}")

                self.model = SentenceTransformer(model_name_or_path)
                self.dim_size = 384
            except Exception as e:
                logging.error(
                    f"Failed to load SentenceTransformer: {e}\n{traceback.format_exc()}")
                self.model = None
                self.backend = 'fallback'
                self.dim_size = 32  # Fallback dimension
        else:
            self.model = None
            self.backend = 'fallback'
            self.dim_size = 32

    def embed(self, text: str):
        if not text:
            # Return zero vector of the correct dimension
            return np.zeros(self.dim_size, dtype=float)

        if self.backend == 'sentence-transformers' and self.model is not None:
            emb = self.model.encode(text, show_progress_bar=False)
            return np.array(emb, dtype=float)
        else:
            # fallback: use a simple hashing vector (32-dims)
            import hashlib
            h = hashlib.sha256(text.encode('utf-8')).digest()
            vec = np.frombuffer(h, dtype='u1').astype(float)  # shape (32,)
            return vec
