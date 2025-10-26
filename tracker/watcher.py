# tracker/watcher.py (Updated)
import os
import time
import json
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from pathlib import Path
from datetime import datetime  # Import datetime
import config
from tracker.metadata_db import MetadataDB
from tracker.extractor import extract_text
from tracker.embedder import Embedder
from tracker.vectorstore import SimpleVectorStore


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
        print(f'Error getting metadata for {path}: {e}')
        return None


class Handler(FileSystemEventHandler):
    def __init__(self, db, embedder, vstore):
        self.db = db
        self.embedder = embedder
        self.vstore = vstore
        self.excluded_dirs = ['.venv', 'site-packages', '__pycache__', '.git', '.vscode']
        self.valid_extensions = ('.txt', '.md', '.py', '.csv', '.docx', '.pdf')

    def _is_path_excluded(self, path):
        if not path or not isinstance(path, str):
            return True
        normalized_path = f"/{path.replace('\\', '/')}/"
        if any(f"/{excluded_dir}/" in normalized_path for excluded_dir in self.excluded_dirs):
            return True
        if not path.lower().endswith(self.valid_extensions):
            return True
        return False

    def process_file(self, path, check_modified_time=False):
        """Processes a file for indexing. If check_modified_time is True, only processes if newer than DB record."""
        if self._is_path_excluded(path):
            return

        if not os.path.exists(path):
            return

        try:
            # --- MODIFICATION TIME CHECK ---
            current_meta = file_metadata(path)
            if not current_meta:
                return  # Skip if we can't get metadata

            if check_modified_time:
                stored_mod_time_str = self.db.get_modified_time(path)
                if stored_mod_time_str:
                    # Compare ISO format strings directly
                    if current_meta['modified_at'] <= stored_mod_time_str:
                        # print(f"Skipping unchanged file: {path}") # Optional: for debugging
                        return  # File hasn't changed, skip processing
            # --- END CHECK ---

            # Skip large files (adjust size as needed)
            MAX_FILE_SIZE = 100 * 1024 * 1024
            if current_meta['size'] > MAX_FILE_SIZE:
                print(
                    f"Skipping large file ({current_meta['size'] / (1024*1024):.2f} MB): {path}")
                return

            print(f"Processing: {path}")
            print(f"  Extracting text...")
            text = extract_text(path)
            print(f"  Text extracted (length: {len(text)}).")

            print(f"  Generating embedding...")
            emb = self.embedder.embed(text)
            print(
                f"  Embedding generated (shape: {emb.shape if hasattr(emb, 'shape') else 'N/A'}).")

            # Metadata is already fetched, use current_meta
            print(f"  Upserting metadata to DB...")
            self.db.upsert(current_meta)  # Use the already fetched metadata
            print(f"  Metadata upserted.")

            print(f"  Upserting embedding to VectorStore...")
            self.vstore.upsert(path, emb)
            print(f"  Embedding upserted.")

            print(f"Indexed: {path}")

        except Exception as e:
            print(f"❌ Error processing {path}: {e}")

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
            print('Deleted from index', path)


if __name__ == '__main__':
    path = config.WATCH_PATH
    db = MetadataDB(config.DB_PATH)
    embedder = Embedder(backend=config.EMBEDDING_BACKEND)
    vstore = SimpleVectorStore(path=config.EMBEDDINGS_PATH)
    event_handler = Handler(db, embedder, vstore)

    print(
        f"Performing initial scan of {path} (only processing new/modified files)...")
    excluded_dirs = event_handler.excluded_dirs  # Use handler's excluded list

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
                    processed = event_handler.process_file(
                        file_path, check_modified_time=True)
                    # We can't easily check return value here, logic moved inside process_file
                    # For simplicity, we won't count processed/skipped accurately here unless process_file returns status
                except Exception as e:
                    print(f"Error during initial scan of {filename}: {e}")
        # Need a better way to count processed/skipped if needed
        print(f"Initial scan complete.")  # Simplified message
    else:
        print(
            f"Error: Watch path '{path}' does not exist. Please check config.py.")
        exit()

    observer = Observer()
    observer.schedule(event_handler, path, recursive=True)
    observer.start()
    print('Started watcher on', path)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nWatcher stopped by user.")
        observer.stop()
    observer.join()
