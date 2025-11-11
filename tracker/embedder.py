# tracker/embedder.py (Text-Only Version)
import os
import numpy as np
import sys
import traceback
import logging
from sentence_transformers import SentenceTransformer

# Suppress obnoxious image warnings
logging.getLogger("PIL").setLevel(logging.WARNING)

# --- FUNCTION TO GET MODEL PATH (Unchanged) ---


def get_model_path():
    """Finds the path to the bundled 'all-MiniLM-L6-v2' model."""
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        bundle_dir = os.path.dirname(sys.executable)
        model_dir = os.path.join(bundle_dir, 'model', 'all-MiniLM-L6-v2')
        if os.path.isdir(model_dir):
            return model_dir
    return 'all-MiniLM-L6-v2'


class Embedder:
    def __init__(self, backend='sentence-transformers'):
        self.text_model = None
        self.text_dim = 384  # Default

        # --- Load Text Model ---
        try:
            model_name_or_path = get_model_path()
            logging.info(f"Loading text model from: {model_name_or_path}")
            self.text_model = SentenceTransformer(model_name_or_path)
            self.text_dim = self.text_model.get_sentence_embedding_dimension()
        except Exception as e:
            logging.error(
                f"Failed to load SentenceTransformer: {e}\n{traceback.format_exc()}")

    def embed_text(self, text: str) -> np.ndarray:
        """Embeds a string of text. Returns a text vector."""
        if not text or not self.text_model:
            return np.zeros(self.text_dim, dtype=float)
        try:
            emb = self.text_model.encode(text, show_progress_bar=False)
            return np.array(emb, dtype=float)
        except Exception as e:
            logging.error(f"Error embedding text: {e}")
            return np.zeros(self.text_dim, dtype=float)

    # This is the only embed function we need for the agent
    def embed_query_for_text_search(self, query: str) -> np.ndarray:
        """Embeds a text query to search for TEXT."""
        return self.embed_text(query)  # Use the text model
