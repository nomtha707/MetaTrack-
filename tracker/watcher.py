# tracker/watcher.py (Agent Version - Patched)
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
from tracker.vectorstore import SimpleVectorStore
from flask import Flask, request, jsonify
import logging
import traceback

# --- NEW AGENT IMPORTS ---
import google.generativeai as genai
# -------------------------

# --- GLOBAL VARIABLES ---
db = None
embedder = None
vstore = None
agent_model = None  # The LLM "brain"
# ------------------------

# --- LOGGING SETUP (unchanged) ---
log_path = os.path.join(config.BASE_DIR, 'watcher.log')
logging.basicConfig(filename=log_path, level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

# --- AGENT PROMPT (unchanged) ---
AGENT_SYSTEM_PROMPT = """
You are a "Local File Search Agent". Your job is to analyze a user's natural language
query and convert it into a JSON plan that a Python script can execute.

The script has two data sources:
1. A semantic vector store (for finding files by *meaning*).
2. An SQLite 'files' table (for *filtering* by metadata).

The 'files' table has these columns: 
path, name, size, created_at, modified_at, access_count, total_time_spent_hrs.

Respond ONLY with a single, minified JSON object. Do not add markdown or any other text.

The JSON plan MUST have two keys:
1. "semantic_query": A string. This is the re-phrased query to be sent to the vector store.
   If the user is ONLY asking for metadata (e.g., "newest files"), set this to null.
2. "sql_filter": A string. This is a valid SQLite `WHERE` clause.
   - Use 'path' for file types (e.g., "path LIKE '%.py'").
   - Use metadata columns for sorting/filtering (e.g., "modified_at > '2025-10-30'").
   - If no filter is needed, use "1=1".
   - DO NOT add 'ORDER BY' here.

Examples:
User Query: file on prolog system
{"semantic_query": "document about the Prolog programming language", "sql_filter": "1=1"}

User Query: python script about machine learning
{"semantic_query": "python code for machine learning", "sql_filter": "path LIKE '%.py'"}

User Query: Find my most recently modified document
{"semantic_query": null, "sql_filter": "path LIKE '%.docx' ORDER BY modified_at DESC LIMIT 1"}

User Query: recent presentations
{"semantic_query": "presentations", "sql_filter": "path LIKE '%.pptx' ORDER BY modified_at DESC"}

User Query: misspelledw wordd
{"semantic_query": "misspelled word", "sql_filter": "1=1"}
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
        logging.info(f"Agent received query: {query_text}")

        # --- 1. "THINK": Ask the LLM agent for a plan ---
        try:
            full_prompt = AGENT_SYSTEM_PROMPT + "\nUser Query: " + query_text
            response = agent_model.generate_content(full_prompt)
            plan_json = response.text
            plan = json.loads(plan_json)
        except Exception as e:
            raw_response_text = response.text if response else "N/A (call failed)"
            logging.error(
                f"Agent API error: {e}\nRaw Response: {raw_response_text}")
            return jsonify({"error": f"Agent 'brain' failed: {e}"}), 500

        logging.info(f"Agent Plan: {plan}")

        semantic_query = plan.get("semantic_query")
        sql_filter = plan.get("sql_filter", "1=1")

        # --- 2. "ACT": Execute the plan ---

        if semantic_query:
            # --- HYBRID SEARCH (Semantic + SQL Filter) ---
            query_vector = embedder.embed(semantic_query)
            # Fetch Top 20 to get a good candidate pool
            vector_results = vstore.query(query_vector, top_k=20)
            search_paths = [res['path'] for res in vector_results]

            if not search_paths:
                return jsonify([])

            # Filter the 20 candidates using the agent's SQL
            final_results = db.get_files_by_path_and_filter(
                search_paths, sql_filter)

            # Re-apply the semantic score to the filtered results
            path_to_score = {res['path']: res['score']
                             for res in vector_results}
            final_results_with_score = []
            for row in final_results:
                row_with_score = dict(row)
                row_with_score['score'] = path_to_score.get(row['path'], 0)
                final_results_with_score.append(row_with_score)

            # Sort by the semantic score, highest first
            final_results_with_score.sort(
                key=lambda x: x['score'], reverse=True)

            # --- THIS IS THE FIX for "Top 5" ---
            # Finally, return only the top 5 of the filtered/sorted list
            return jsonify(final_results_with_score[:5])

        else:
            # --- PURE METADATA SEARCH (No Semantic Query) ---
            # --- THIS IS THE FIX for "Recently Modified" ---
            # Call our new database function that only uses the SQL filter
            final_results = db.get_files_by_filter_only(sql_filter)
            # Add the limit here!
            return jsonify(final_results[:5])

    except Exception as e:
        logging.error(f"Error during search: {e}\n{traceback.format_exc()}")
        return jsonify({"error": "Internal server error"}), 500


def run_flask_app():
    logging.info("Starting Flask server on http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, debug=False)

# --- WATCHDOG FILE HANDLER (Unchanged) ---


def file_metadata(path: str):
    # (Unchanged)
    try:
        st = os.stat(path)
        return {'path': path, 'name': os.path.basename(path), 'size': st.st_size, 'created_at': datetime.fromtimestamp(st.st_ctime).isoformat(), 'modified_at': datetime.fromtimestamp(st.st_mtime).isoformat(), 'accessed_at': datetime.fromtimestamp(st.st_atime).isoformat(), 'extra_json': '{}'}
    except Exception as e:
        logging.error(f'Error getting metadata for {path}: {e}')
        return None


class Handler(FileSystemEventHandler):
    # (Unchanged)
    def __init__(self):
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
        global db, embedder, vstore
        try:
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
            logging.info(f"Processing: {path}")
            text = extract_text(path)
            emb = embedder.embed(text)
            db.upsert(current_meta)
            vstore.upsert(path, emb)
            logging.info(f"Indexed: {path}")
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
        if not self._is_path_excluded(path):
            db.mark_deleted(path)
            vstore.delete(path)
            logging.info(f'Deleted from index: {path}')


# --- MAIN EXECUTION ---
if __name__ == '__main__':
    try:
        logging.info("--- MetaTrack Agent Server starting up... ---")

        # --- 1. Configure the API key ---
        api_key = config.API_KEY
        if not api_key:
            logging.error("FATAL: GOOGLE_API_KEY not found in .env file")
            raise ValueError("GOOGLE_API_KEY not found in .env file")
        genai.configure(api_key=api_key)

        # --- 2. Load all local components ---
        logging.info("Loading local components...")
        db = MetadataDB(config.DB_PATH)
        embedder = Embedder(backend=config.EMBEDDING_BACKEND)
        vstore = SimpleVectorStore(path=config.EMBEDDINGS_PATH)
        logging.info("All local components loaded.")

        # --- 3. ⚠️ MODIFIED MODEL NAME ---
        logging.info("Initializing agent brain (Gemini)...")
        # Use the newer, faster model that is available on the free tier
        agent_model = genai.GenerativeModel('gemini-2.5-flash')
        logging.info("Agent brain is online.")

        # --- 4. Start the Flask Server in a new thread ---
        server_thread = threading.Thread(target=run_flask_app, daemon=True)
        server_thread.start()

        # --- 5. Start the File Watcher (Initial Scan) ---
        path = config.WATCH_PATH
        event_handler = Handler()
        logging.info(f"Performing initial scan of {path}...")
        # (Initial scan logic is unchanged)
        if os.path.exists(path):
            for root, dirs, files in os.walk(path, topdown=True):
                dirs[:] = [
                    d for d in dirs if d not in event_handler.excluded_dirs and not d.startswith('.')]
                is_excluded_root = any(
                    f"/{excluded_dir}/" in f"/{root.replace('\\', '/')}/" for excluded_dir in event_handler.excluded_dirs)
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

        # --- 6. Start the File Watcher (Monitoring) ---
        observer = Observer()
        observer.schedule(event_handler, path, recursive=True)
        observer.start()
        logging.info(f"Watcher started on {path}.")

        # Keep main thread alive
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
