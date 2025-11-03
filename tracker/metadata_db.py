import sqlite3
import os
import tracker.config as config
import logging


class MetadataDB:
    def __init__(self, db_path=config.DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        # Create table on init to ensure it exists
        # This will use its own connection
        self._create_table()

    def _create_connection(self):
        """Creates a new database connection."""
        try:
            conn = sqlite3.connect(self.db_path)
            return conn
        except sqlite3.Error as e:
            logging.error(f"Error connecting to database: {e}")
            return None

    def _create_table(self):
        # --- MODIFIED ---
        # Added access_count and total_time_spent_hrs with default values
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
            conn = self._create_connection()  # Get new connection
            if not conn:
                return
            c = conn.cursor()
            c.execute(create_table_sql)
            conn.commit()
        except sqlite3.Error as e:
            logging.error(f"Error creating table: {e}")
        finally:
            if conn:
                conn.close()  # Close connection

    def upsert(self, meta: dict):
        """
        Inserts or replaces a record in the files table.
        This is now thread-safe.
        """
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
            conn = self._create_connection()  # Get new connection
            if not conn:
                return
            c = conn.cursor()
            c.execute(sql, meta)
            conn.commit()
        except sqlite3.Error as e:
            # This is the error you were seeing
            logging.error(f"Error upserting data for {meta.get('path')}: {e}")
        finally:
            if conn:
                conn.close()  # Close connection

    def mark_deleted(self, path: str):
        """Marks a file as deleted instead of removing it. Thread-safe."""
        sql = ''' UPDATE files SET is_deleted = 1 WHERE path = ? '''
        conn = None
        try:
            conn = self._create_connection()  # Get new connection
            if not conn:
                return
            c = conn.cursor()
            c.execute(sql, (path,))
            conn.commit()
        except sqlite3.Error as e:
            logging.error(f"Error marking file as deleted {path}: {e}")
        finally:
            if conn:
                conn.close()  # Close connection

    def get_modified_time(self, path: str):
        """Gets the stored modified_at time for a file. Thread-safe."""
        sql = ''' SELECT modified_at FROM files WHERE path = ? AND is_deleted = 0 '''
        conn = None
        result = None
        try:
            conn = self._create_connection()  # Get new connection
            if not conn:
                return None
            c = conn.cursor()
            c.execute(sql, (path,))
            result = c.fetchone()
            if result:
                return result[0]
            return None
        except sqlite3.Error as e:
            logging.error(f"Error getting modified time for {path}: {e}")
            return None
        finally:
            if conn:
                conn.close()  # Close connection

    # --- NEW FUNCTIONS FOR RECOMMENDER (Already Thread-Safe) ---

    def increment_access_count(self, path: str):
        """Increments the access_count for a file. Thread-safe."""
        sql = ''' UPDATE files 
                  SET access_count = access_count + 1 
                  WHERE path = ? '''
        conn = None
        try:
            conn = self._create_connection()  # Get new connection
            if not conn:
                return
            c = conn.cursor()
            c.execute(sql, (path,))
            conn.commit()
        except sqlite3.Error as e:
            logging.error(f"Error incrementing access count for {path}: {e}")
        finally:
            if conn:
                conn.close()  # Close connection

    def update_time_spent(self, path: str, hours_spent: float):
        """Adds to the total time spent on a file. Thread-safe."""
        sql = ''' UPDATE files 
                  SET total_time_spent_hrs = total_time_spent_hrs + ? 
                  WHERE path = ? '''
        conn = None
        try:
            conn = self._create_connection()  # Get new connection
            if not conn:
                return
            c = conn.cursor()
            c.execute(sql, (hours_spent, path))
            conn.commit()
        except sqlite3.Error as e:
            logging.error(f"Error updating time spent for {path}: {e}")
        finally:
            if conn:
                conn.close()  # Close connection

    def get_file_details(self, path: str):
        """Gets all details for a specific file path."""
        sql = ''' SELECT * FROM files WHERE path = ? AND is_deleted = 0 '''
        conn = None
        try:
            conn = self._create_connection()
            if not conn:
                return None

            # This makes the cursor return results as dictionaries
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute(sql, (path,))
            result = c.fetchone()

            if result:
                # Convert the Row object to a standard dict
                return dict(result)
            return None
        except sqlite3.Error as e:
            logging.error(f"Error getting file details for {path}: {e}")
            return None
        finally:
            if conn:
                conn.close()
    
    def get_files_by_path_and_filter(self, paths: list, sql_filter: str = "1=1"):
        """
        Gets details for a list of file paths, with an added SQL filter.
        """
        if not paths:
            return []

        # Create a string of placeholders like '(?, ?, ?)'
        placeholders = ', '.join('?' for _ in paths)

        # Combine the path list and the agent's filter
        sql = f''' SELECT * FROM files 
                   WHERE path IN ({placeholders}) 
                   AND ({sql_filter}) 
                   AND is_deleted = 0 '''

        conn = None
        try:
            conn = self._create_connection()
            if not conn:
                return []

            conn.row_factory = sqlite3.Row
            c = conn.cursor()

            # The 'paths' list is used as the arguments for the placeholders
            c.execute(sql, paths)
            results = c.fetchall()

            # Convert list of Row objects to a list of dicts
            return [dict(row) for row in results]

        except sqlite3.Error as e:
            logging.error(f"Error executing agent query: {e}\nSQL: {sql}")
            return []
        finally:
            if conn:
                conn.close()
    
    def get_files_by_filter_only(self, sql_filter: str = "1=1"):
        """
        Gets all file details using only a SQL filter.
        Used when the agent does not provide a semantic query.
        """
        
        sql = ""
        sql_filter_upper = sql_filter.strip().upper()
        
        where_clause = "1=1"
        order_by_clause = "" # Default to no sorting

        # Check if an ORDER BY clause exists and split it from the filter
        if "ORDER BY" in sql_filter_upper:
            # Find the index of ORDER BY
            order_by_index = sql_filter_upper.find("ORDER BY")
            
            # Everything before it is the WHERE clause
            where_clause = sql_filter[:order_by_index].strip()
            
            # Everything from it to the end is the ORDER BY clause
            order_by_clause = sql_filter[order_by_index:].strip()
            
            # If the where_clause is empty (e.g., plan was just "ORDER BY ..."), default it back to "1=1"
            if not where_clause:
                where_clause = "1=1"
        else:
            # No ORDER BY, the whole thing is a WHERE clause
            where_clause = sql_filter

        # Construct the final, valid query
        sql = f''' SELECT * FROM files 
                   WHERE ({where_clause}) 
                   AND is_deleted = 0 
                   {order_by_clause} ''' # Append ORDER BY (if it exists)
        
        conn = None
        try:
            conn = self._create_connection()
            if not conn:
                return []
            
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute(sql) # No parameters needed as they are in the string
            results = c.fetchall()
            
            return [dict(row) for row in results]
        
        except sqlite3.Error as e:
            logging.error(f"Error executing agent's pure SQL query: {e}\nSQL: {sql}")
            return []
        finally:
            if conn:
                conn.close()