import sqlite3
import os
import tracker.config as config
import logging


class MetadataDB:
    def __init__(self, db_path=config.DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.conn = self._create_connection()
        self._create_table()

    def _create_connection(self):
        try:
            conn = sqlite3.connect(self.db_path)
            return conn
        except sqlite3.Error as e:
            logging.error(f"Error connecting to database: {e}")
            return None

    def _create_table(self):
        # --- MODIFIED ---
        # Added access_count and total_time_spent_hrs
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS files (
            path TEXT PRIMARY KEY,
            name TEXT,
            size INTEGER,
            created_at TEXT,
            modified_at TEXT,
            accessed_at TEXT,
            is_deleted INTEGER DEFAULT 0,
            access_count INTEGER DEFAULT 0,
            total_time_spent_hrs REAL DEFAULT 0.0,
            extra_json TEXT
        );
        """
        try:
            c = self.conn.cursor()
            c.execute(create_table_sql)
            self.conn.commit()
        except sqlite3.Error as e:
            logging.error(f"Error creating table: {e}")

    def upsert(self, meta: dict):
        """
        Inserts or replaces a record in the files table.
        'meta' is a dictionary matching the file_metadata structure.
        """
        # --- MODIFIED ---
        # Updated to include new columns
        sql = ''' INSERT OR REPLACE INTO files(
                    path, name, size, created_at, modified_at, accessed_at, 
                    is_deleted, access_count, total_time_spent_hrs, extra_json
                )
                VALUES(
                    :path, :name, :size, :created_at, :modified_at, :accessed_at,
                    0, :access_count, :total_time_spent_hrs, :extra_json
                ) '''
        try:
            c = self.conn.cursor()
            c.execute(sql, meta)
            self.conn.commit()
        except sqlite3.Error as e:
            logging.error(f"Error upserting data for {meta.get('path')}: {e}")

    def mark_deleted(self, path: str):
        """Marks a file as deleted instead of removing it."""
        sql = ''' UPDATE files SET is_deleted = 1 WHERE path = ? '''
        try:
            c = self.conn.cursor()
            c.execute(sql, (path,))
            self.conn.commit()
        except sqlite3.Error as e:
            logging.error(f"Error marking file as deleted {path}: {e}")

    def get_modified_time(self, path: str):
        """Gets the stored modified_at time for a file."""
        sql = ''' SELECT modified_at FROM files WHERE path = ? AND is_deleted = 0 '''
        try:
            c = self.conn.cursor()
            c.execute(sql, (path,))
            result = c.fetchone()
            if result:
                return result[0]
            return None
        except sqlite3.Error as e:
            logging.error(f"Error getting modified time for {path}: {e}")
            return None

    def close(self):
        if self.conn:
            self.conn.close()
