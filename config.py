import os.path

# --- This is the new, important part ---
# Get the absolute path to the directory where this config.py file lives
# This ensures all paths are relative to your project folder, not where the .exe is run
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Configuration for paths and model choices
WATCH_PATH = r"D:/College_IIITDWD"    # This is already absolute, so it's fine.

# --- These paths are now based on BASE_DIR ---
DB_DIR = os.path.join(BASE_DIR, "db")
DATA_DIR = os.path.join(BASE_DIR, "data")

DB_PATH = os.path.join(DB_DIR, "metadata.db")
EMBEDDINGS_PATH = os.path.join(DB_DIR, "embeddings.joblib")
TEXT_CACHE_DIR = os.path.join(DATA_DIR, "text_cache")

# Create the directories if they don't exist
os.makedirs(DB_DIR, exist_ok=True)
os.makedirs(os.path.join(DATA_DIR, "text_cache"), exist_ok=True)

# --- The rest is the same ---
# Embedding options: 'sentence-transformers' or 'tfidf'
EMBEDDING_BACKEND = 'sentence-transformers'
# If you want a remote vector DB, implement in vectorstore.py
