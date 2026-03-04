# tracker/embedder.py
import os
import numpy as np
import sys
import traceback
import logging
from sentence_transformers import SentenceTransformer
from PIL import Image  # Required for loading images

logging.getLogger("PIL").setLevel(logging.WARNING)

def get_model_path(folder_name):
    """Dynamically finds the model folder, even when bundled as an .exe"""
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        bundle_dir = os.path.dirname(sys.executable)
        model_dir = os.path.join(bundle_dir, 'model', folder_name)
        if os.path.isdir(model_dir):
            return model_dir
    return folder_name

class Embedder:
    def __init__(self):
        self.text_model = None
        self.image_model = None
        self.text_dim = 384
        self.image_dim = 512  # CLIP's dimension size

        # --- 1. Load Text Model ---
        try:
            text_path = get_model_path('all-MiniLM-L6-v2')
            logging.info(f"Loading TEXT model from: {text_path}")
            self.text_model = SentenceTransformer(text_path)
        except Exception as e:
            logging.error(f"Failed to load Text Model: {e}")

        # --- 2. Load Image Model (CLIP) ---
        try:
            image_path = get_model_path('clip-ViT-B-32')
            logging.info(f"Loading IMAGE model from: {image_path}")
            self.image_model = SentenceTransformer(image_path)
        except Exception as e:
            logging.error(f"Failed to load Image Model: {e}")

    def embed_text(self, text: str) -> np.ndarray:
        """Standard text embedding for documents."""
        if not text or not self.text_model:
            return np.zeros(self.text_dim, dtype=float)
        emb = self.text_model.encode(text, show_progress_bar=False)
        return np.array(emb, dtype=float)

    def embed_image(self, image_path: str) -> np.ndarray:
        """Reads a .jpg/.png and converts the pixels into semantic math."""
        if not os.path.exists(image_path) or not self.image_model:
            return np.zeros(self.image_dim, dtype=float)
        try:
            img = Image.open(image_path)
            emb = self.image_model.encode(img, show_progress_bar=False)
            return np.array(emb, dtype=float)
        except Exception as e:
            logging.error(f"Error embedding image {image_path}: {e}")
            return np.zeros(self.image_dim, dtype=float)

    def embed_query_for_image_search(self, text_query: str) -> np.ndarray:
        """
        MAGIC TRICK: To search for an image using text, we pass the text 
        into the IMAGE model. CLIP bridges the gap between words and pixels.
        """
        if not text_query or not self.image_model:
            return np.zeros(self.image_dim, dtype=float)
        emb = self.image_model.encode(text_query, show_progress_bar=False)
        return np.array(emb, dtype=float)