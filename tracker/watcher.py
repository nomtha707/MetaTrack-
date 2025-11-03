import os
import time
import json
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from pathlib import Path
from datetime import datetime
import tracker.config as config
from tracker.metadata_db import MetadataDB
from tracker.extractor import extract_text
from tracker.embedder import Embedder
from tracker.vectorstore import SimpleVectorStore

# --- LOGGING SETUP ---
import logging
import traceback

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
    def __init__(self, db, embedder, vstore):
        self.db = db
        self.embedder = embedder
        self.vstore = vstore
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

    def process_file(self, path, check_modified_time=False):
        """Processes a file for indexing."""
        try:
            if self._is_path_excluded(path):
                return

            if not os.path.exists(path):
                return

            current_meta = file_metadata(path)
            if not current_meta:
                return

            if check_modified_time:
                stored_mod_time_str = self.db.get_modified_time(path)
                if stored_mod_time_str:
                    if current_meta['modified_at'] <= stored_mod_time_str:
                        return

            MAX_FILE_SIZE = 100 * 1024 * 1024
            if current_meta['size'] > MAX_FILE_SIZE:
                logging.warning(
                    f"Skipping large file ({current_meta['size'] / (1024*1024):.2f} MB): {path}")
                return

            logging.info(f"Processing: {path}")
            logging.info(f"  Extracting text...")
            text = extract_text(path)
            logging.info(f"  Text extracted (length: {len(text)}).")

            logging.info(f"  Generating embedding...")
            emb = self.embedder.embed(text)
            logging.info(f"  Embedding generated (shape: {emb.shape}).")

            logging.info(f"  Upserting metadata to DB...")
            self.db.upsert(current_meta)
            logging.info(f"  Metadata upserted.")

            logging.info(f"  Upserting embedding to VectorStore...")
            self.vstore.upsert(path, emb)
            logging.info(f"  Embedding upserted.")

            logging.info(f"Indexed: {path}")

        except Exception as e:
            error_message = f"❌ Error processing {path}: {e}\n{traceback.format_exc()}"
            logging.error(error_message)

    def on_created(self, event):
        if event.is_directory:
            return
        self.process_file(event.src_path, check_modified_time=False)

    def on_modified(self, event):
        if event.is_directory:
            return
        self.process_file(event.src_path, check_modified_time=False)

    def on_deleted(self, event):
        if event.is_directory:
            return
        path = event.src_path
        if not self._is_path_excluded(path):
            self.db.mark_deleted(path)
            self.vstore.delete(path)
            logging.info(f'Deleted from index: {path}')


if __name__ == '__main__':
    try:
        logging.info("--- Watcher starting up... ---")

        path = config.WATCH_PATH
        db = MetadataDB(config.DB_PATH)
        embedder = Embedder(backend=config.EMBEDDING_BACKEND)
        vstore = SimpleVectorStore(path=config.EMBEDDINGS_PATH)
        event_handler = Handler(db, embedder, vstore)

        logging.info(f"Performing initial scan of {path}...")
        logging.info(
            f"Performing initial scan of {path} (only processing new/modified files)...")
        excluded_dirs = event_handler.excluded_dirs

        if os.path.exists(path):
            for root, dirs, files in os.walk(path, topdown=True):
                dirs[:] = [
                    d for d in dirs if d not in excluded_dirs and not d.startswith('.')]

                is_excluded_root = any(
                    f"/{excluded_dir}/" in f"/{root.replace('\\', '/')}/" for excluded_dir in excluded_dirs)
                if is_excluded_root:
                    continue

                for filename in files:
                    try:
                        file_path = os.path.join(root, filename)
                        event_handler.process_file(
                            file_path, check_modified_time=True)
                    except Exception as e:
                        logging.error(
                            f"Error during initial scan of {filename}: {e}\n{traceback.format_exc()}")

            logging.info("Initial scan complete.")
        else:
            logging.error(f"Error: Watch path '{path}' does not exist.")
            exit()

        observer = Observer()
        observer.schedule(event_handler, path, recursive=True)
        observer.start()
        logging.info(f"Watcher started on {path}.")

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logging.info("Watcher stopped by user.")
            observer.stop()

        observer.join()
        db.close()

    except Exception as e:
        logging.error(
            f"🔥🔥🔥 FATAL STARTUP ERROR: {e}\n{traceback.format_exc()}")
