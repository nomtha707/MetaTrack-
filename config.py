# Configuration for paths and model choices
WATCH_PATH = r"D:/College_IIITDWD"    # change to directories you want to monitor
DB_PATH = "./db/metadata.db"
# fallback vector store (numpy + joblib)
EMBEDDINGS_PATH = "./db/embeddings.joblib"
TEXT_CACHE_DIR = "./data/text_cache"
# Embedding options: 'sentence-transformers' or 'tfidf'
EMBEDDING_BACKEND = 'sentence-transformers'
# If you want a remote vector DB, implement in vectorstore.py
