import torch
from sentence_transformers import SentenceTransformer
import clip
from PIL import Image
import numpy as np
import time
import threading
import gc
import logging

class Embedder:
    def __init__(self, timeout_seconds=600): # 600 seconds = 10 minutes
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.timeout = timeout_seconds
        
        # 1. Models start completely empty to save RAM!
        self.text_model = None
        self.clip_model = None
        self.clip_preprocess = None
        
        # 2. State tracking
        self.last_used = time.time()
        self.lock = threading.Lock() # Prevents background watcher and UI from crashing
        
        # 3. Start the Background Memory Manager
        self.monitor_thread = threading.Thread(target=self._memory_monitor, daemon=True)
        self.monitor_thread.start()
        
        logging.info("MetaTrack Memory Manager initialized (Models Sleeping).")

    def _load_models(self):
        """Loads the heavy AI models into RAM only if they aren't loaded yet."""
        if self.text_model is None:
            logging.info("Waking up AI Models... Loading into RAM/VRAM.")
            
            # Load MiniLM
            self.text_model = SentenceTransformer('all-MiniLM-L6-v2', device=self.device)
            
            # Load CLIP
            self.clip_model, self.clip_preprocess = clip.load("ViT-B/32", device=self.device)
            
            logging.info("AI Models successfully loaded and ready.")

    def _unload_models(self):
        """Destroys the models and forces Windows to take the RAM back."""
        if self.text_model is not None:
            logging.info(f"{self.timeout/60} minutes of inactivity. Putting AI Models to sleep to save RAM...")
            
            # Delete references
            self.text_model = None
            self.clip_model = None
            self.clip_preprocess = None
            
            # Force memory cleanup
            gc.collect() 
            if self.device == "cuda":
                torch.cuda.empty_cache()

    def _memory_monitor(self):
        """Runs silently in the background checking the clock."""
        while True:
            time.sleep(30) # Wake up every 30 seconds to check the time
            with self.lock:
                if self.text_model is not None:
                    # If the timer has expired, flush the memory
                    if time.time() - self.last_used > self.timeout:
                        self._unload_models()

    def embed_text(self, text):
        """Generates text embeddings safely."""
        with self.lock:
            self._load_models() # Make sure brain is awake
            self.last_used = time.time() # Reset the timer
            
            embedding = self.text_model.encode(text, convert_to_numpy=True)
            return embedding

    def embed_image(self, image_path):
        """Generates image embeddings safely."""
        with self.lock:
            self._load_models() # Make sure brain is awake
            self.last_used = time.time() # Reset the timer
            
            try:
                image = Image.open(image_path).convert("RGB")
                image_input = self.clip_preprocess(image).unsqueeze(0).to(self.device)
                with torch.no_grad():
                    embedding = self.clip_model.encode_image(image_input).cpu().numpy()[0]
                return embedding
            except Exception as e:
                logging.error(f"Error embedding image {image_path}: {e}")
                return np.zeros(512) # Fallback empty vector for CLIP

    def embed_query_for_image_search(self, text):
        """Generates text embeddings using CLIP to search for images."""
        with self.lock:
            self._load_models() # Make sure brain is awake
            self.last_used = time.time() # Reset the timer
            
            try:
                # CLIP needs text tokenized specifically for its own image-matching brain
                text_input = clip.tokenize([text]).to(self.device)
                with torch.no_grad():
                    embedding = self.clip_model.encode_text(text_input).cpu().numpy()[0]
                return embedding
            except Exception as e:
                logging.error(f"Error embedding query for image search '{text}': {e}")
                return np.zeros(512) # Fallback empty vector