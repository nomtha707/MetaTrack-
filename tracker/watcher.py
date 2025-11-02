import os
import time
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from datetime import datetime
import tracker.config as config
from tracker.metadata_db import MetadataDB
from tracker.extractor import extract_text

# --- NEW LOGGING & TRACEBACK ---
import logging
import traceback

# --- NEW LLAMA-INDEX IMPORTS ---
from llama_index.core import Settings, StorageContext, VectorStoreIndex, Document
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.vector_stores.chroma import ChromaVectorStore
import chromadb

# --- LOGGING SETUP ---
log_path = os.path.join(config.BASE_DIR, 'watcher.log')
logging.basicConfig(
    filename=log_path,
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
# --- END LOGGING SETUP ---


def file_metadata(path: str):
    """Gets file metadata, converting timestamps to ISO format."""
    try:
        st = os.stat(path)
        return {
            'path': path,
            'name': os.path.basename(path),
            'size': st.st_size,
            'created_at': datetime.fromtimestamp(st.st_ctime).isoformat(),
            'modified_at': datetime.fromtimestamp(st.st_mtime).isoformat(),
            'accessed_at': datetime.fromtimestamp(st.st_atime).isoformat(),
            'extra_json': '{}'
        }
    except Exception as e:
        logging.error(f'Error getting metadata for {path}: {e}')
        return None


class Handler(FileSystemEventHandler):
    # --- MODIFIED __init__ ---
    # Removed embedder and vstore, added LlamaIndex 'index'
    def __init__(self, db, index):
        self.db = db
        self.index = index
        self.excluded_dirs = ['.venv', 'site-packages',
                              '__pycache__', '.git', '.vscode', 'db', 'model']
        self.valid_extensions = ('.txt', '.md', '.py', '.csv', '.docx', '.pdf')

    def _is_path_excluded(self, path):
        if not path or not isinstance(path, str):
            return True

        filename = os.path.basename(path)
        if filename.startswith('~$') or filename.startswith('.'):
            return True

        normalized_path = f"/{path.replace('\\', '/')}/"
        if any(f"/{excluded_dir}/" in normalized_path for excluded_dir in self.excluded_dirs):
            return True
        if not path.lower().endswith(self.valid_extensions):
            return True
        return False

    # --- MODIFIED process_file ---
    # Implements the new LlamaIndex/ChromaDB indexing pipeline
    def process_file(self, path):
        """Processes a file for indexing in both SQLite and ChromaDB."""
        try:
            if self._is_path_excluded(path):
                return

            if not os.path.exists(path):
                logging.warning(f"File not found, skipping: {path}")
                return

            # 1. Extract text (Keep your existing extractor.py logic)
            logging.info(f"Extracting text from: {path}")
            text = extract_text(path)

            # 2. Get file metadata (Keep your existing logic)
            meta = file_metadata(path)
            if not meta:
                logging.error(f"Could not get metadata for: {path}")
                return

            # 3. --- NEW ---
            #    Add default behavioral data to the metadata
            meta['access_count'] = 0
            meta['total_time_spent_hrs'] = 0.0

            # 4. Upsert to SQLite (Use your existing MetadataDB class)
            self.db.upsert(meta)

            # 5. --- NEW ---
            #    Create a LlamaIndex Document object.
            #    The 'doc_id' MUST be the file path for updates to work.
            document = Document(
                text=text,
                doc_id=path,
                metadata={
                    'path': path,
                    'name': meta.get('name'),
                    'created_at': meta.get('created_at'),
                    'modified_at': meta.get('modified_at'),
                    'size': meta.get('size')
                }
            )

            # 6. --- NEW ---
            #    Insert the document into LlamaIndex (which handles embedding and saving to ChromaDB)
            self.index.insert(document)
            logging.info(f"Indexed (Chroma/SQLite): {path}")

        except Exception as e:
            error_message = f"❌ Error processing {path}: {e}\n{traceback.format_exc()}"
            logging.error(error_message)

    def on_created(self, event):
        if event.is_directory:
            return
        self.process_file(event.src_path)

    def on_modified(self, event):
        if event.is_directory:
            return
        self.process_file(event.src_path)

    # --- MODIFIED on_deleted ---
    def on_deleted(self, event):
        if event.is_directory:
            return

        path = event.src_path
        if self._is_path_excluded(path):
            return

        try:
            # 1. Mark as deleted in SQLite (Keep existing logic)
            self.db.mark_deleted(path)

            # 2. --- NEW ---
            #    Delete the document from LlamaIndex/ChromaDB
            self.index.delete_ref_doc(path, delete_from_docstore=True)
            logging.info(f"Deleted (Chroma/SQLite): {path}")
        except Exception as e:
            logging.error(
                f"Error deleting {path}: {e}\n{traceback.format_exc()}")


# --- MODIFIED main block ---
if __name__ == '__main__':
    try:
        logging.info("--- Watcher starting up... ---")

        # 1. Define paths (e.g., from a config file)
        SQLITE_DB_PATH = config.DB_PATH
        CHROMA_DB_PATH = os.path.join(config.DB_DIR, "chroma_db")
        EMBED_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
        WATCH_PATH = config.WATCH_PATH

        # 2. Set up the embedding model (use CPU to be safe)
        logging.info(f"Initializing embedding model: {EMBED_MODEL_NAME}")
        Settings.embed_model = HuggingFaceEmbedding(
            model_name=EMBED_MODEL_NAME,
            device="cpu"
        )

        # 3. Set up the LlamaIndex Storage
        logging.info(f"Initializing SQLite DB at: {SQLITE_DB_PATH}")
        db_instance = MetadataDB(SQLITE_DB_PATH)  # Your existing SQLite class

        logging.info(f"Initializing ChromaDB at: {CHROMA_DB_PATH}")
        chroma_client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
        chroma_collection = chroma_client.get_or_create_collection(
            "document_store")
        vector_store = ChromaVectorStore(chroma_collection=chroma_collection)
        storage_context = StorageContext.from_defaults(
            vector_store=vector_store)

        # 4. Create the main LlamaIndex Index object
        logging.info("Loading/Creating VectorStoreIndex...")
        index = VectorStoreIndex.from_documents(
            [], storage_context=storage_context
        )
        logging.info("VectorStoreIndex ready.")

        # --- Instantiate Handler with new 'index' object ---
        event_handler = Handler(db_instance, index)

        # --- Initial Scan ---
        logging.info(f"Performing initial scan of {WATCH_PATH}...")
        excluded_dirs = event_handler.excluded_dirs

        if os.path.exists(WATCH_PATH):
            for root, dirs, files in os.walk(WATCH_PATH, topdown=True):
                dirs[:] = [
                    d for d in dirs if d not in excluded_dirs and not d.startswith('.')]

                is_excluded_root = any(
                    f"/{excluded_dir}/" in f"/{root.replace('\\', '/')}/" for excluded_dir in excluded_dirs)
                if is_excluded_root:
                    continue

                for filename in files:
                    try:
                        file_path = os.path.join(root, filename)
                        # --- MODIFIED ---
                        # Call new process_file, no check_modified_time needed
                        # LlamaIndex 'insert' is an upsert, so it's safe to call
                        event_handler.process_file(file_path)
                    except Exception as e:
                        logging.error(
                            f"Error during initial scan of {filename}: {e}\n{traceback.format_exc()}")

            logging.info("Initial scan complete.")
        else:
            logging.error(f"Error: Watch path '{WATCH_PATH}' does not exist.")
            exit()
        # --- End Initial Scan ---

        observer = Observer()
        observer.schedule(event_handler, WATCH_PATH, recursive=True)
        observer.start()
        logging.info(f"Watcher started on {WATCH_PATH}.")

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logging.info("Watcher stopped by user.")
            observer.stop()
        observer.join()
        db_instance.close()

    except Exception as e:
        logging.error(
            f"🔥🔥🔥 FATAL STARTUP ERROR: {e}\n{traceFback.format_exc()}")
