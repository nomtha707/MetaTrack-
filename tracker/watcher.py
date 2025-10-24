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

    def process_file(self, path):
        if not os.path.exists(path):
            return
        meta = file_metadata(path)
        if not meta:
            return
        text = extract_text(path)
        self.db.upsert(meta)
        emb = self.embedder.embed(text)
        self.vstore.upsert(path, emb)
        print('Indexed', path)

    def on_created(self, event):
        if event.is_directory:
            return
        self.process_file(event.src_path)

    def on_modified(self, event):
        if event.is_directory:
            return
        self.process_file(event.src_path)

    def on_deleted(self, event):
        if event.is_directory:
            return
        path = event.src_path
        self.db.mark_deleted(path)
        self.vstore.delete(path)
        print('Deleted from index', path)


if __name__ == '__main__':
    path = config.WATCH_PATH
    db = MetadataDB(config.DB_PATH)
    embedder = Embedder(backend=config.EMBEDDING_BACKEND)
    vstore = SimpleVectorStore(path=config.EMBEDDINGS_PATH)

    event_handler = Handler(db, embedder, vstore)
    observer = Observer()
    observer.schedule(event_handler, path, recursive=True)
    observer.start()
    print('Started watcher on', path)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
