import os
import sys


def get_base_dir():
    """Get the base directory for the application (script or .exe)"""
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        # Running as a PyInstaller bundle (.exe)
        # sys.executable is .../dist/MetaTracker.exe
        # We want the .../dist folder as the base.
        return os.path.dirname(sys.executable)
    else:
        # Running as a normal script (.py)
        # __file__ is .../project/tracker/config.py
        # os.path.dirname(__file__) is .../project/tracker
        # We want the .../project folder, so we go up one level.
        return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


# 1. Get the single, reliable base directory
BASE_DIR = get_base_dir()

# 2. Define other main directories relative to BASE_DIR
DB_DIR = os.path.join(BASE_DIR, 'db')
WATCH_PATH = r"D:/College_IIITDWD"  # Your hardcoded watch path

# 3. Define specific file paths
DB_PATH = os.path.join(DB_DIR, "metadata.db")
# This is the base name for our vector store files (e.g., embeddings.npy, embeddings.json)
EMBEDDINGS_PATH = os.path.join(DB_DIR, "embeddings")

# 4. Configuration for model
EMBEDDING_BACKEND = 'sentence-transformers'

# 5. Create the database directory if it doesn't exist
os.makedirs(DB_DIR, exist_ok=True)
