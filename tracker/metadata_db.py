import sqlite3
import os
from typing import Optional, Dict


class MetadataDB:
    def __init__(self, path: str):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self._ensure()

    def _ensure(self):
        cur = self.conn.cursor()
        cur.execute('''
        CREATE TABLE IF NOT EXISTS files (
            path TEXT PRIMARY KEY,
            name TEXT,
            size INTEGER,
            created_at TEXT,
            modified_at TEXT,
            accessed_at TEXT,
            active INTEGER,
            extra_json TEXT
        )
        ''')
        self.conn.commit()

    def upsert(self, meta: Dict):
        cur = self.conn.cursor()
        cur.execute('''
        INSERT INTO files (path,name,size,created_at,modified_at,accessed_at,active,extra_json)
        VALUES (?,?,?,?,?,?,?,?)
        ON CONFLICT(path) DO UPDATE SET
            name=excluded.name,
            size=excluded.size,
            created_at=excluded.created_at,
            modified_at=excluded.modified_at,
            accessed_at=excluded.accessed_at,
            active=excluded.active,
            extra_json=excluded.extra_json
        ''', (
            meta.get('path'), meta.get('name'), meta.get(
                'size'), meta.get('created_at'),
            meta.get('modified_at'), meta.get(
                'accessed_at'), 1, meta.get('extra_json')
        ))
        self.conn.commit()

    def mark_deleted(self, path: str):
        cur = self.conn.cursor()
        cur.execute('UPDATE files SET active=0 WHERE path=?', (path,))
        self.conn.commit()

    def fetch_all_active(self):
        cur = self.conn.cursor()
        cur.execute(
            'SELECT path,name,size,created_at,modified_at,accessed_at FROM files WHERE active=1')
        return cur.fetchall()

    def get(self, path: str) -> Optional[Dict]:
        cur = self.conn.cursor()
        cur.execute('SELECT * FROM files WHERE path=?', (path,))
        row = cur.fetchone()
        if not row:
            return None
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row))
