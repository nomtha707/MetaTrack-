# tracker/watcher.py (Updated)
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

# --- NEW LOGGING SETUP ---
import logging
import traceback

# This will create a 'watcher.log' file in your project's root folder
log_path = os.path.join(config.BASE_DIR, 'watcher.log')
logging.basicConfig(
    filename=log_path,
    level=logging.INFO,  # <-- CHANGED: Log INFO messages, not just ERROR
    format='%(asctime)s - %(levelname)s - %(message)s'
)
# --- END NEW LOGGING SETUP ---


def file_metadata(path: str):
    """Gets file metadata, converting timestamps to ISO format."""
    try:
        st = os.stat(path)
        return {
            'path': path,
            'name': os.path.basename(path),
            'size': st.st_size,
            # --- USE ISO FORMAT ---
            'created_at': datetime.fromtimestamp(st.st_ctime).isoformat(),
            'modified_at': datetime.fromtimestamp(st.st_mtime).isoformat(),
            'accessed_at': datetime.fromtimestamp(st.st_atime).isoformat(),
            'extra_json': '{}'
        }
    except Exception as e:
        # --- CHANGED: Use logging ---
        logging.error(f'Error getting metadata for {path}: {e}')
        return None


class Handler(FileSystemEventHandler):
    def __init__(self, db, embedder, vstore):
        self.db = db
        self.embedder = embedder
        self.vstore = vstore
        self.excluded_dirs = ['.venv', 'site-packages',
                              '__pycache__', '.git', '.vscode']
        self.valid_extensions = ('.txt', '.md', '.py', '.csv', '.docx', '.pdf')

    def _is_path_excluded(self, path):
        if not path or not isinstance(path, str):
            return True

        # --- NEW: Ignore MS Office temp files ---
        filename = os.path.basename(path)
        if filename.startswith('~$'):
            return True
        # --- END NEW ---

        normalized_path = f"/{path.replace('\\', '/')}/"
        if any(f"/{excluded_dir}/" in normalized_path for excluded_dir in self.excluded_dirs):
            return True
        if not path.lower().endswith(self.valid_extensions):
            return True
        return False

    def process_file(self, path, check_modified_time=False):
        """Processes a file for indexing. If check_modified_time is True, only processes if newer than DB record."""
        try:  # --- NEW OUTER TRY BLOCK ---
            if self._is_path_excluded(path):
                return

            if not os.path.exists(path):
                return

            # --- MODIFICATION TIME CHECK ---
            current_meta = file_metadata(path)
            if not current_meta:
                return  # Skip if we can't get metadata

            if check_modified_time:
                stored_mod_time_str = self.db.get_modified_time(path)
                if stored_mod_time_str:
                    # Compare ISO format strings directly
                    if current_meta['modified_at'] <= stored_mod_time_str:
                        # logging.info(f"Skipping unchanged file: {path}") # Optional: for debugging
                        return  # File hasn't changed, skip processing
            # --- END CHECK ---

            # Skip large files (adjust size as needed)
            MAX_FILE_SIZE = 100 * 1024 * 1024
            if current_meta['size'] > MAX_FILE_SIZE:
                # --- CHANGED: Use logging ---
                logging.warning(
                    f"Skipping large file ({current_meta['size'] / (1024*1024):.2f} MB): {path}")
                return

            # --- CHANGED: Use logging ---
            logging.info(f"Processing: {path}")
            logging.info(f"  Extracting text...")
            text = extract_text(path)
            logging.info(f"  Text extracted (length: {len(text)}).")

            logging.info(f"  Generating embedding...")
            emb = self.embedder.embed(text)
            logging.info(
                f"  Embedding generated (shape: {emb.shape if hasattr(emb, 'shape') else 'N/A'}).")

            # Metadata is already fetched, use current_meta
            logging.info(f"  Upserting metadata to DB...")
            self.db.upsert(current_meta)  # Use the already fetched metadata
            logging.info(f"  Metadata upserted.")

            logging.info(f"  Upserting embedding to VectorStore...")
            self.vstore.upsert(path, emb)
            logging.info(f"  Embedding upserted.")

            logging.info(f"Indexed: {path}")

        except Exception as e:
            # --- THIS IS THE NEW, CRITICAL PART ---
            # Write the full error to our log file
            error_message = f"❌ Error processing {path}: {e}\n{traceback.format_exc()}"
            # --- CHANGED: Use logging ---
            logging.error(error_message)
            # --- END CRITICAL PART ---

    # Event methods call process_file WITHOUT the time check (always process changes)
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
            # --- CHANGED: Use logging ---
            logging.info(f'Deleted from index: {path}')


# --- THIS IS THE UPDATED BLOCK AT THE END OF watcher.py ---
if __name__ == '__main__':

    # --- NEW GLOBAL TRY...EXCEPT BLOCK ---
    try:
        # --- CHANGED: Use logging.info ---
        logging.info("--- Watcher starting up... ---")

        path = config.WATCH_PATH
        db = MetadataDB(config.DB_PATH)
        embedder = Embedder(backend=config.EMBEDDING_BACKEND)
        vstore = SimpleVectorStore(path=config.EMBEDDINGS_PATH)
        event_handler = Handler(db, embedder, vstore)

        # --- CHANGED: Use logging.info ---
        logging.info(f"Performing initial scan of {path}...")
        logging.info(
            f"Performing initial scan of {path} (only processing new/modified files)...")
        excluded_dirs = event_handler.excluded_dirs  # Use handler's excluded list

        # --- !! UNCOMMENTED INITIAL SCAN !! ---
        if os.path.exists(path):
            processed_count = 0
            skipped_count = 0
            for root, dirs, files in os.walk(path, topdown=True):
                dirs[:] = [
                    d for d in dirs if d not in excluded_dirs and not d.startswith('.')]
                files = [f for f in files if not f.startswith('.')]

                is_excluded_root = any(
                    f"/{excluded_dir}/" in f"/{root.replace('\\', '/')}/" or f"\\{excluded_dir}\\" in f"\\{root}\\" for excluded_dir in excluded_dirs)
                if is_excluded_root:
                    continue

                for filename in files:
                    try:
                        file_path = os.path.join(root, filename)
                        # --- CALL process_file WITH check_modified_time=True ---
                        # The function itself handles extension checks now
                        event_handler.process_file(
                            file_path, check_modified_time=True)
                        # We can't easily check return value here, logic moved inside process_file
                        # For simplicity, we won't count processed/skipped accurately here unless process_file returns status
                    except Exception as e:
                        # --- CHANGED: Use logging.error ---
                        logging.error(
                            f"Error during initial scan of {filename}: {e}\n{traceback.format_exc()}")

            # --- CHANGED: Use logging.info ---
            logging.info("Initial scan complete.")
        else:
            # --- CHANGED: Use logging.error ---
            logging.error(f"Error: Watch path '{path}' does not exist.")
            logging.error(
                f"Error: Watch path '{path}' does not exist. Please check config.py.")
            exit()
        # --- !! END OF UNCOMMENTED BLOCK !! ---

        observer = Observer()
        observer.schedule(event_handler, path, recursive=True)
        observer.start()
        # --- CHANGED: Use logging.info ---
        logging.info(f"Watcher started on {path}.")

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            # --- CHANGED: Use logging.info ---
            logging.info("Watcher stopped by user.")
            observer.stop()
        observer.join()

    except Exception as e:
        # --- THIS WILL CATCH ANY STARTUP CRASH ---
        # --- This one stays as ERROR ---
        logging.error(
            f"🔥🔥🔥 FATAL STARTUP ERROR: {e}\n{traceback.format_exc()}")
    # --- END NEW GLOBAL BLOCK ---
