# tracker/watcher.py (Stable Text-Only Server with Home Endpoints)
import os
import time
import json
import threading
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from datetime import datetime
import tracker.config as config
from tracker.metadata_db import MetadataDB
from tracker.extractor import extract_text
from tracker.embedder import Embedder
from tracker.vectorstore import SimpleVectorStore  # <-- This is the correct import
from flask import Flask, request, jsonify
import logging
import traceback

# --- AGENT IMPORTS ---
import google.generativeai as genai
# -------------------------

# --- GLOBAL VARIABLES ---
db = None
embedder = None
vstore = None
agent_model = None
# ------------------------

# --- LOGGING SETUP ---
log_path = os.path.join(config.BASE_DIR, 'watcher.log')
logging.basicConfig(filename=log_path, level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

# --- AGENT PROMPT (This is your final, working prompt) ---
AGENT_SYSTEM_PROMPT = """
You are a "Local File Search Agent". Your job is to analyze a user's natural language
query and convert it into a JSON plan that a Python script can execute.
(The user will provide today's date and day of the week in their query).

The script has two data sources:
1. A semantic vector store (for finding files by *meaning*).
2. An SQLite 'files' table (for *filtering* by metadata).

--- DATABASE SCHEMA ---
The 'files' table has these columns: 
path, name, size, created_at, modified_at, access_count.
(The 'accessed_at' column is unreliable and should NOT be used.)

--- RULES ---
1.  Respond ONLY with a single, minified JSON object. Do not add markdown or any other text.
2.  The JSON plan MUST have two keys: "semantic_query" and "sql_filter".
3.  "semantic_query": This is the re-phrased query for the vector store.
    - If the user is ONLY asking for metadata (e.g., "newest files"), set this to null.
4.  "sql_filter": This is a valid SQLite `WHERE` clause (or "1=1" if no filter).
    - To filter by a date, use the `LIKE` operator (e.g., `modified_at LIKE '2025-10-28%'`).
    - Use `modified_at` for ALL date-related queries (e.g., "modified", "opened").
    - Use "1=1" if no specific filter is needed.

--- RELATIVE DATE RULES ---
- (e.g., If today is Wednesday, 2025-11-05, "last week" is 2025-10-27 to 2025-11-02, and "last Tuesday" is 2025-10-28).

--- EXAMPLES ---
User Query: file on prolog system
{"semantic_query": "document about the Prolog programming language", "sql_filter": "1=1"}

User Query: Find my most recently modified document
{"semantic_query": null, "sql_filter": "path LIKE '%.docx' ORDER BY modified_at DESC LIMIT 1"}

User Query: (Today is Wednesday, 2025-11-05) files opened last tuesday
{"semantic_query": null, "sql_filter": "modified_at LIKE '2025-10-28%'"}
"""

# --- FLASK SERVER APP ---
app = Flask(__name__)


@app.route('/search', methods=['POST'])
def search_endpoint():
    global db, embedder, vstore, agent_model
    data = request.json
    query_text = data.get('query')
    if not query_text:
        return jsonify({"error": "No query provided"}), 400
    if not all([db, embedder, vstore, agent_model]):
        return jsonify({"error": "Server components not initialized"}), 500
    response = None
    try:
        logging.info(f"Agent received 'Find' query: '{query_text}'")
        try:
            today = datetime.now()
            today_date_str = today.strftime("%Y-%m-%d")
            day_of_week_str = today.strftime("%A")
            user_prompt = f"Today is {day_of_week_str}, {today_date_str}. User query is: '{query_text}'"
            response = agent_model.generate_content(user_prompt)
            plan_json = response.text
            if plan_json.startswith("```json"):
                plan_json = plan_json.strip("```json\n").strip("```")
            plan = json.loads(plan_json)
        except Exception as e:
            raw_response_text = response.text if response else "N/A (call failed)"
            logging.error(
                f"Agent API error: {e}\nRaw Response: {raw_response_text}")
            return jsonify({"error": f"Agent 'brain' failed: {e}"}), 500

        logging.info(f"Agent Plan: {plan}")
        sql_filter = plan.get("sql_filter", "1=1")
        logging.info("Executing 'FIND' (Search) logic...")
        semantic_query = plan.get("semantic_query")

        if semantic_query:
            # Hybrid Search
            query_vector = embedder.embed_text(
                semantic_query)  # Use embed_text
            vector_results = vstore.query(query_vector, top_k=20)
            search_paths = [res['path'] for res in vector_results]
            if not search_paths:
                return jsonify([])
            final_results_from_db = db.get_files_by_path_and_filter(
                search_paths, sql_filter)

            path_to_score = {res['path']: res['score']
                             for res in vector_results}
            final_results_with_score = []
            for row in final_results_from_db:
                row_with_score = dict(row)
                row_with_score['score'] = path_to_score.get(row['path'], 0)
                final_results_with_score.append(row_with_score)
            final_results_with_score.sort(
                key=lambda x: x['score'], reverse=True)

            top_5_results = final_results_with_score[:5]
            for res in top_5_results:
                db.increment_access_count(res['path'])  # Update access count
            return jsonify(top_5_results)
        else:
            # Pure Metadata Search
            final_results_from_db = db.get_files_by_filter_only(sql_filter)
            top_5_results = final_results_from_db[:5]
            for res in top_5_results:
                db.increment_access_count(res['path'])  # Update access count
            return jsonify(top_5_results)
    except Exception as e:
        logging.error(f"Error during search: {e}\n{traceback.format_exc()}")
        return jsonify({"error": "Internal server error"}), 500


@app.route('/get_recent_files', methods=['GET'])
def get_recent_files():
    global db
    try:
        files = db.get_recent_files(limit=5)
        return jsonify(files)
    except Exception as e:
        logging.error(
            f"Error in /get_recent_files: {e}\n{traceback.format_exc()}")
        return jsonify({"error": "Could not retrieve recent files"}), 500


@app.route('/get_popular_files', methods=['GET'])
def get_popular_files():
    global db
    try:
        files = db.get_popular_files(limit=5)
        return jsonify(files)
    except Exception as e:
        logging.error(
            f"Error in /get_popular_files: {e}\n{traceback.format_exc()}")
        return jsonify({"error": "Could not retrieve popular files"}), 500


def run_flask_app():
    logging.info(
        "Starting Flask server on [http://127.0.0.1:5000](http://127.0.0.1:5000)")
    app.run(host="127.0.0.1", port=5000, debug=False)

# --- WATCHDOG HANDLER (Now uses config for extensions) ---


def file_metadata(path: str):  # Moved to top level
    try:
        st = os.stat(path)
        return {'path': path, 'name': os.path.basename(path), 'size': st.st_size, 'created_at': datetime.fromtimestamp(st.st_ctime).isoformat(), 'modified_at': datetime.fromtimestamp(st.st_mtime).isoformat(), 'accessed_at': datetime.fromtimestamp(st.st_atime).isoformat(), 'extra_json': '{}'}
    except Exception as e:
        logging.error(f'Error getting metadata for {path}: {e}')
        return None


# --- WATCHDOG HANDLER (Now uses config for extensions) ---
class Handler(FileSystemEventHandler):
    def __init__(self):
        # Pull from the config file
        self.excluded_dirs = config.EXCLUDED_DIRS
        self.valid_extensions = config.VALID_EXTENSIONS

    def _is_path_excluded(self, path):
        if not path or not isinstance(path, str):
            return True
        filename = os.path.basename(path)
        if filename.startswith('~$') or filename.startswith('.'):
            return True

        # Use a standard path format ('/') to check
        path_lower = path.lower().replace('\\', '/')

        # Check if any part of the path contains a forbidden directory name
        # e.g., 'c:/users/me/.venv/lib/...'
        for excluded_dir in self.excluded_dirs:
            if f'/{excluded_dir.lower()}/' in path_lower:
                return True

        if not path.lower().endswith(self.valid_extensions):
            return True
        return False

    def process_file(self, path, check_modified_time=False):
        global db, embedder, vstore
        try:
            # This check is now robust
            if self._is_path_excluded(path):
                return

            if not os.path.exists(path):
                return
            current_meta = file_metadata(path)
            if not current_meta:
                return
            if check_modified_time:
                stored_mod_time_str = db.get_modified_time(path)
                if stored_mod_time_str and current_meta['modified_at'] <= stored_mod_time_str:
                    return
            MAX_FILE_SIZE = 100 * 1024 * 1024
            if current_meta['size'] > MAX_FILE_SIZE:
                logging.warning(f"Skipping large file: {path}")
                return

            logging.info(f"Processing (text): {path}")
            text = extract_text(path)
            emb = embedder.embed_text(text)
            db.upsert(current_meta)
            vstore.upsert(path, emb)
            logging.info(f"Indexed (text): {path}")
        except Exception as e:
            logging.error(
                f"Error processing {path}: {e}\n{traceback.format_exc()}")

    def on_created(self, event):
        if event.is_directory:
            return
        self.process_file(event.src_path, check_modified_time=False)

    def on_modified(self, event):
        if event.is_directory:
            return
        self.process_file(event.src_path, check_modified_time=False)

    def on_deleted(self, event):
        global db, vstore
        if event.is_directory:
            return
        path = event.src_path
        # We must check the path again, as it might be from an excluded dir
        if not self._is_path_excluded(path):
            db.mark_deleted(path)
            vstore.delete(path)
            logging.info(f'Deleted from index: {path}')


if __name__ == '__main__':
    try:
        logging.info("--- MetaTrack Agent Server starting up... ---")

        api_key = config.API_KEY
        if not api_key:
            raise ValueError("GOOGLE_API_KEY not found in .env file")
        genai.configure(api_key=api_key)

        logging.info("Loading local components...")
        db = MetadataDB(config.DB_PATH)
        embedder = Embedder()  # Text-only embedder
        vstore = SimpleVectorStore(
            path=config.EMBEDDINGS_PATH)  # Numpy vector store
        logging.info("All local components loaded.")

        logging.info("Initializing agent brain (Gemini)...")
        agent_model = genai.GenerativeModel(
            'gemini-2.5-flash',  # Or your working model
            system_instruction=AGENT_SYSTEM_PROMPT
        )
        logging.info("Agent brain is online.")

        server_thread = threading.Thread(target=run_flask_app, daemon=True)
        server_thread.start()

        path = config.WATCH_PATH  # Your single, stable path
        event_handler = Handler()
        logging.info(f"Performing initial scan of {path}...")
        if os.path.exists(path):
            for root, dirs, files in os.walk(path, topdown=True):

                # --- THIS IS THE CORRECTED SCAN LOGIC ---
                # Prune excluded directories so we don't even walk them
                dirs[:] = [d for d in dirs if d.lower(
                ) not in config.EXCLUDED_DIRS and not d.startswith('.')]

                for filename in files:
                    file_path = os.path.join(root, filename)
                    # We can just call process_file, since its own
                    # _is_path_excluded() check is now very reliable.
                    try:
                        event_handler.process_file(
                            file_path, check_modified_time=True)
                    except Exception as e:
                        logging.error(
                            f"Error during initial scan of {filename}: {e}\n{traceback.format_exc()}")
            logging.info("Initial scan complete.")
            # --- END OF CORRECTED LOGIC ---
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

    except Exception as e:
        logging.error(
            f"🔥🔥🔥 FATAL STARTUP ERROR: {e}\n{traceback.format_exc()}")
