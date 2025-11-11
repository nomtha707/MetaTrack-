# tracker/metadata_db.py (Full Thread-Safe Version)
import sqlite3
import os
import tracker.config as config
import logging


class MetadataDB:
    def __init__(self, db_path=config.DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._create_table()

    def _create_connection(self):
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            return conn
        except sqlite3.Error as e:
            logging.error(f"Error connecting to database: {e}")
            return None

    def _create_table(self):
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
        conn = None
        try:
            conn = self._create_connection()
            if not conn:
                return
            c = conn.cursor()
            c.execute(create_table_sql)
            conn.commit()
        except sqlite3.Error as e:
            logging.error(f"Error creating table: {e}")
        finally:
            if conn:
                conn.close()

    def upsert(self, meta: dict):
        sql = ''' INSERT OR REPLACE INTO files(
                    path, name, size, created_at, modified_at, accessed_at, 
                    is_deleted, extra_json
                  )
                  VALUES(
                    :path, :name, :size, :created_at, :modified_at, :accessed_at,
                    0, :extra_json
                  ) '''
        conn = None
        try:
            conn = self._create_connection()
            if not conn:
                return
            c = conn.cursor()
            c.execute(sql, meta)
            conn.commit()
        except sqlite3.Error as e:
            logging.error(f"Error upserting data for {meta.get('path')}: {e}")
        finally:
            if conn:
                conn.close()

    def mark_deleted(self, path: str):
        sql = ''' UPDATE files SET is_deleted = 1 WHERE path = ? '''
        conn = None
        try:
            conn = self._create_connection()
            if not conn:
                return
            c = conn.cursor()
            c.execute(sql, (path,))
            conn.commit()
        except sqlite3.Error as e:
            logging.error(f"Error marking file as deleted {path}: {e}")
        finally:
            if conn:
                conn.close()

    def get_modified_time(self, path: str):
        sql = ''' SELECT modified_at FROM files WHERE path = ? AND is_deleted = 0 '''
        conn = None
        try:
            conn = self._create_connection()
            if not conn:
                return None
            c = conn.cursor()
            c.execute(sql, (path,))
            result = c.fetchone()
            if result:
                return result["modified_at"]
            return None
        except sqlite3.Error as e:
            logging.error(f"Error getting modified time for {path}: {e}")
            return None
        finally:
            if conn:
                conn.close()

    def get_files_by_path_and_filter(self, paths: list, sql_filter: str = "1=1"):
        if not paths:
            return []
        placeholders = ', '.join('?' for _ in paths)
        sql = f''' SELECT * FROM files 
                   WHERE path IN ({placeholders}) 
                   AND ({sql_filter}) 
                   AND is_deleted = 0 '''
        conn = None
        try:
            conn = self._create_connection()
            if not conn:
                return []
            c = conn.cursor()
            c.execute(sql, paths)
            results = c.fetchall()
            return [dict(row) for row in results]
        except sqlite3.Error as e:
            logging.error(f"Error executing agent query: {e}\nSQL: {sql}")
            return []
        finally:
            if conn:
                conn.close()

    def get_files_by_filter_only(self, sql_filter: str = "1=1"):
        sql = ""
        sql_filter_upper = sql_filter.strip().upper()
        where_clause = "1=1"
        order_by_clause = ""
        if "ORDER BY" in sql_filter_upper:
            order_by_index = sql_filter_upper.find("ORDER BY")
            where_clause = sql_filter[:order_by_index].strip()
            order_by_clause = sql_filter[order_by_index:].strip()
            if not where_clause:
                where_clause = "1=1"
        else:
            where_clause = sql_filter
        sql = f''' SELECT * FROM files 
                   WHERE ({where_clause}) 
                   AND is_deleted = 0 
                   {order_by_clause} '''
        conn = None
        try:
            conn = self._create_connection()
            if not conn:
                return []
            c = conn.cursor()
            c.execute(sql)
            results = c.fetchall()
            return [dict(row) for row in results]
        except sqlite3.Error as e:
            logging.error(
                f"Error executing agent's pure SQL query: {e}\nSQL: {sql}")
            return []
        finally:
            if conn:
                conn.close()

    def get_recent_files(self, limit=5):
        sql = ''' SELECT * FROM files 
                  WHERE is_deleted = 0 
                  ORDER BY modified_at DESC 
                  LIMIT ? '''
        conn = None
        try:
            conn = self._create_connection()
            if not conn:
                return []
            c = conn.cursor()
            c.execute(sql, (limit,))
            results = c.fetchall()
            return [dict(row) for row in results]
        except sqlite3.Error as e:
            logging.error(f"Error getting recent files: {e}")
            return []
        finally:
            if conn:
                conn.close()

    def get_popular_files(self, limit=5):
        sql = ''' SELECT * FROM files 
                  WHERE is_deleted = 0 AND access_count > 0
                  ORDER BY access_count DESC, modified_at DESC
                  LIMIT ? '''
        conn = None
        try:
            conn = self._create_connection()
            if not conn:
                return []
            c = conn.cursor()
            c.execute(sql, (limit,))
            results = c.fetchall()
            return [dict(row) for row in results]
        except sqlite3.Error as e:
            logging.error(f"Error getting popular files: {e}")
            return []
        finally:
            if conn:
                conn.close()

    def increment_access_count(self, path: str):
        sql = ''' UPDATE files 
                  SET access_count = access_count + 1 
                  WHERE path = ? AND is_deleted = 0 '''
        conn = None
        try:
            conn = self._create_connection()
            if not conn:
                return
            c = conn.cursor()
            c.execute(sql, (path,))
            conn.commit()
        except sqlite3.Error as e:
            logging.error(f"Error incrementing access count for {path}: {e}")
        finally:
            if conn:
                conn.close()