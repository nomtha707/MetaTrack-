import os
import time
import json
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from pathlib import Path
import config
from tracker.metadata_db import MetadataDB
from tracker.extractor import extract_text
from tracker.embedder import Embedder
from tracker.vectorstore import SimpleVectorStore


def file_metadata(path: str):
    try:
        st = os.stat(path)
        return {
            'path': path,
            'name': os.path.basename(path),
            'size': st.st_size,
            'created_at': time.ctime(st.st_ctime),
            'modified_at': time.ctime(st.st_mtime),
            'accessed_at': time.ctime(st.st_atime),
            'extra_json': '{}'
        }
    except Exception as e:
        print('stat error', e)
        return None


class Handler(FileSystemEventHandler):
    def __init__(self, db, embedder, vstore):
        self.db = db
        self.embedder = embedder
        self.vstore = vstore
        # --- ADD EXCLUDED DIRS TO HANDLER ---
        self.excluded_dirs = ['.venv', 'site-packages', '__pycache__', '.git', '.vscode']
        self.valid_extensions = ('.txt', '.md', '.py', '.csv', '.docx', '.pdf')

    # --- ADD THIS HELPER METHOD ---
    def _is_path_excluded(self, path):
        # Check if path is None or not a string
        if not path or not isinstance(path, str):
            return True
        # Normalize path separators for consistent checking
        normalized_path = f"/{path.replace('\\', '/')}/"
        if any(f"/{excluded_dir}/" in normalized_path for excluded_dir in self.excluded_dirs):
            return True
        if not path.lower().endswith(self.valid_extensions):
            return True
        return False

    def process_file(self, path):
        if self._is_path_excluded(path):
            return

        if not os.path.exists(path):
            return

        # --- ADD FILE SIZE CHECK HERE ---
        try:
            # Skip files larger than 100MB (adjust as needed)
            MAX_FILE_SIZE = 100 * 1024 * 1024
            file_size = os.path.getsize(path)
            if file_size > MAX_FILE_SIZE:
                print(
                    f"Skipping large file ({file_size / (1024*1024):.2f} MB): {path}")
                return  # Stop processing this file
        except Exception as e:
            print(f"Could not get size for {path}: {e}")
            return  # Skip if size check fails
        # --- END FILE SIZE CHECK ---

        # --- MORE DEBUG PRINTS ---
        print(f"Processing: {path}")
        try:
            print(f"  Extracting text...")
            text = extract_text(path)
            print(f"  Text extracted (length: {len(text)}).")

            print(f"  Generating embedding...")
            emb = self.embedder.embed(text)
            print(
                f"  Embedding generated (shape: {emb.shape if hasattr(emb, 'shape') else 'N/A'}).")

            print(f"  Getting metadata...")
            meta = file_metadata(path)
            if not meta:
                print(f"  Failed to get metadata for {path}")
                return  # Skip if metadata failed
            print(f"  Metadata retrieved.")

            print(f"  Upserting metadata to DB...")
            self.db.upsert(meta)
            print(f"  Metadata upserted.")

            print(f"  Upserting embedding to VectorStore...")
            # This is where embeddings.joblib is created/updated
            self.vstore.upsert(path, emb)
            print(f"  Embedding upserted.")

            print(f"Indexed: {path}")  # Moved the final confirmation here

        except Exception as e:
            # Ensure errors are printed
            print(f"❌ Error processing {path}: {e}")

    # --- UPDATE EVENT METHODS ---
    def on_created(self, event):
        if event.is_directory:
            return
        # Check exclusion before processing
        if not self._is_path_excluded(event.src_path):
            self.process_file(event.src_path)

    def on_modified(self, event):
        if event.is_directory:
            return
        # Check exclusion before processing
        if not self._is_path_excluded(event.src_path):
            self.process_file(event.src_path)

    def on_deleted(self, event):
        if event.is_directory:
            return
        path = event.src_path
        # Check exclusion before deleting (optional but consistent)
        if not self._is_path_excluded(path):
            self.db.mark_deleted(path)
            self.vstore.delete(path)
            print('Deleted from index', path)


if __name__ == '__main__':
    # --- 1. Initialize Components ONCE ---
    path = config.WATCH_PATH
    db = MetadataDB(config.DB_PATH)
    embedder = Embedder(backend=config.EMBEDDING_BACKEND)
    vstore = SimpleVectorStore(path=config.EMBEDDINGS_PATH)
    # Create the handler using the components
    event_handler = Handler(db, embedder, vstore)
    
    # --- 2. Perform Initial Scan ---
    print(f"Performing initial scan of {path}...")
    # --- ADD THIS LIST ---
    excluded_dirs = ['.venv', 'site-packages', '__pycache__', '.git', '.vscode'] # Add any other folders to exclude
    
    if os.path.exists(path):
        for root, dirs, files in os.walk(path, topdown=True): # Use topdown=True
            # --- MODIFY dirs[:] TO EXCLUDE FOLDERS ---
            # This stops os.walk from even going *into* these folders
            dirs[:] = [d for d in dirs if d not in excluded_dirs and not d.startswith('.')]
            files = [f for f in files if not f.startswith('.')]

            # --- ADD PATH CHECK BEFORE PROCESSING FILES ---
            # Check if the current 'root' directory is inside an excluded folder
            is_excluded = any(f"/{excluded_dir}/" in f"/{root.replace('\\', '/')}/" or f"\\{excluded_dir}\\" in f"\\{root}\\" for excluded_dir in excluded_dirs)
            if is_excluded:
                continue # Skip processing files in this excluded directory
        
            for filename in files:
                try:
                    file_path = os.path.join(root, filename)
                    # --- ADD FILE EXTENSION FILTER (Optional but Recommended) ---
                    # Only process files with specific extensions you care about
                    valid_extensions = ('.txt', '.md', '.py', '.csv', '.docx', '.pdf') 
                    if file_path.lower().endswith(valid_extensions): 
                        print(f"Found: {file_path}...")
                        event_handler.process_file(file_path)
                except Exception as e:
                    print(f"Error during initial scan of {filename}: {e}")
        print("Initial scan complete.")
    # --- 3. Setup and Start Observer ---
    observer = Observer()
    # Schedule the *same* handler
    observer.schedule(event_handler, path, recursive=True)
    observer.start()  # Start watching for *new* changes after the scan
    print('Started watcher on', path)

    # --- 4. Keep Watcher Running ---
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nWatcher stopped by user.")
        observer.stop()
    observer.join()
