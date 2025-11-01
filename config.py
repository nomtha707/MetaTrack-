import os
import sys

# --- THIS IS THE NEW, CORRECT PATH LOGIC ---


def get_base_dir():
    """Get the base directory for the application (script or .exe)"""
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        # Running as a PyInstaller bundle (.exe)
        # sys.executable is ...project/dist/MetaTracker.exe
        # os.path.dirname(sys.executable) is ...project/dist
        # We want ...project, so we go up one level ("..")
        return os.path.abspath(os.path.join(os.path.dirname(sys.executable), ".."))
    else:
        # Running as a normal script (.py)
        # __file__ is ...project/config.py
        # os.path.dirname(os.path.abspath(__file__)) is ...project
        return os.path.dirname(os.path.abspath(__file__))


# Get the absolute path to the project's root
BASE_DIR = get_base_dir()
# --- End new logic ---


# Configuration for paths and model choices
WATCH_PATH = r"D:/College_IIITDWD"

# --- These paths are now based on the CORRECT BASE_DIR ---
DB_DIR = os.path.join(BASE_DIR, "db")
DATA_DIR = os.path.join(BASE_DIR, "data")

DB_PATH = os.path.join(DB_DIR, "metadata.db")
EMBEDDINGS_PATH = os.path.join(DB_DIR, "embeddings.joblib")
TEXT_CACHE_DIR = os.path.join(DATA_DIR, "text_cache")

# Create the directories if they don't exist
os.makedirs(DB_DIR, exist_ok=True)
os.makedirs(os.path.join(DATA_DIR, "text_cache"), exist_ok=True)

# --- Use the 'tfidf' backend to avoid model-loading crashes ---
EMBEDDING_BACKEND = 'tfidf'
