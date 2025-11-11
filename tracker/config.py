# tracker/config.py (Stable Text-Only Version)
import os
import sys
from dotenv import load_dotenv


def get_base_dir():
    """Get the base directory for the application (script or .exe)"""
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        return os.path.dirname(sys.executable)
    else:
        return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


# 1. Get the single, reliable base directory
BASE_DIR = get_base_dir()

# 2. Load the .env file from the BASE_DIR
dotenv_path = os.path.join(BASE_DIR, '.env')
load_dotenv(dotenv_path)

# --- Watch Path (Your single, stable folder) ---
# Or your single folder
WATCH_PATH = r"D:/College_IIITDWD"

# --- Valid file types ---
VALID_EXTENSIONS = ('.txt', '.md', '.py', '.csv', '.docx', '.pdf')

# --- Excluded directories ---
EXCLUDED_DIRS = [
    '$RECYCLE.BIN', '__pycache__', 'node_modules', '.git', '.vscode',
    '.idea', 'db', 'dist', 'model', '.venv', 'venv', 'env'
]

# --- Database & Model Paths ---
DB_DIR = os.path.join(BASE_DIR, 'db')
DB_PATH = os.path.join(DB_DIR, "metadata.db")
EMBEDDINGS_PATH = os.path.join(
    DB_DIR, "embeddings")  # Base name for .npy/.json

# --- API Key (Unchanged) ---
API_KEY = os.environ.get("GOOGLE_API_KEY")
