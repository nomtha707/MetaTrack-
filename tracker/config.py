import os
import sys
from dotenv import load_dotenv


def get_base_dir():
    """Get the base directory for the application (script or .exe)"""
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        # Running as a PyInstaller bundle (.exe)
        return os.path.dirname(sys.executable)
    else:
        # Running as a normal script (.py)
        return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


# 1. Get the single, reliable base directory
BASE_DIR = get_base_dir()

# 2. Load the .env file from the BASE_DIR
dotenv_path = os.path.join(BASE_DIR, '.env')
load_dotenv(dotenv_path)

# 2. Define other main directories relative to BASE_DIR
DB_DIR = os.path.join(BASE_DIR, 'db')
WATCH_PATH = r"D:/College_IIITDWD"  # Your hardcoded watch path

# 3. Define specific file paths
DB_PATH = os.path.join(DB_DIR, "metadata.db")
EMBEDDINGS_PATH = os.path.join(DB_DIR, "embeddings")

# 4. Configuration for model
EMBEDDING_BACKEND = 'sentence-transformers'

# 5. Create the database directory if it doesn't exist
os.makedirs(DB_DIR, exist_ok=True)

# 6. Get API Key from environment
# (The watcher.py will import this and use it)
# We no longer hardcode the key here.
API_KEY = os.environ.get("GOOGLE_API_KEY")
