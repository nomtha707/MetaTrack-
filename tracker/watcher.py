# tracker/watcher.py (Full RAG Version)
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

# --- AGENT IMPORTS ---
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

# --- AGENT PROMPT 1: SEARCH PLANNER (unchanged) ---
AGENT_SYSTEM_PROMPT = """
You are a "Local File Search Agent". Your job is to analyze a user's natural language
query and convert it into a JSON plan that a Python script can execute.
(Rest of prompt is the same...)
...
User Query: misspelledw wordd
{"semantic_query": "misspelled word", "sql_filter": "1=1"}
"""

# --- AGENT PROMPT 2: RAG ANSWER GENERATOR (NEW) ---
RAG_SYSTEM_PROMPT = """
You are a helpful AI assistant. Your task is to answer the user's question based *only*
on the provided context. Do not use any outside knowledge. If the answer is not in the
context, say so. Be concise.

CONTEXT:
---
{context_text}
---

USER'S QUESTION:
{query_text}

ANSWER:
"""
# --- END NEW PROMPT ---


# --- FLASK SERVER APP ---
app = Flask(__name__)


@app.route('/search', methods=['POST'])
def search_endpoint():
    global db, embedder, vstore, agent_model

    data = request.json
    query_text = data.get('query')
    mode = data.get('mode', 'find')

    if not query_text:
        return jsonify({"error": "No query provided"}), 400
    if not all([db, embedder, vstore, agent_model]):
        return jsonify({"error": "Server components not initialized"}), 500

    response = None
    try:
        logging.info(f"Agent received query: '{query_text}' in mode: '{mode}'")

        # --- 1. "THINK": Ask the LLM agent for a plan ---
        try:
            today_date = datetime.now().strftime("%Y-%m-%d")
            user_prompt = f"Today's date is {today_date}. User query is: '{query_text}'"
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

        # --- 2. "ACT": Execute based on MODE ---

        if mode == "ask":
            # --- RAG "ASK" MODE ---
            logging.info("Executing 'ASK' (RAG) logic...")

            # 1. Embed the user's raw query to find the best file
            query_vector = embedder.embed(query_text)
            vector_results = vstore.query(query_vector, top_k=20)
            search_paths = [res['path'] for res in vector_results]

            if not search_paths:
                return jsonify({"answer": "Sorry, I couldn't find any files matching that.", "source": None})

            # 2. Filter the candidates using the agent's SQL plan
            final_results_from_db = db.get_files_by_path_and_filter(
                search_paths, sql_filter)

            if not final_results_from_db:
                return jsonify({"answer": "I found some files, but none matched your filters.", "source": None})

            # --- THIS IS THE FIX ---
            # Re-apply the semantic score, just like in "Find" mode
            path_to_score = {res['path']: res['score']
                             for res in vector_results}
            final_results_with_score = []
            for row in final_results_from_db:
                row_with_score = dict(row)
                row_with_score['score'] = path_to_score.get(row['path'], 0)
                final_results_with_score.append(row_with_score)

            # Sort by the semantic score, highest first
            final_results_with_score.sort(
                key=lambda x: x['score'], reverse=True)
            # --- END OF FIX ---

            # 3. Get the single best file after filtering AND sorting
            top_result = final_results_with_score[0]  # Get the top match
            top_path = top_result['path']
            logging.info(f"RAG: Retrieving text from: {top_path}")

            context_text = extract_text(top_path)
            if not context_text:
                return jsonify({"answer": "Sorry, I found the file but couldn't read its content.", "source": top_path})

            # 4. Generate the answer
            rag_prompt = RAG_SYSTEM_PROMPT.format(
                context_text=context_text, query_text=query_text)
            gen_response = agent_model.generate_content(rag_prompt)

            return jsonify({
                "answer": gen_response.text,
                "source": top_path
            })

        elif mode == "find":
            # --- "FIND" MODE ---
            logging.info("Executing 'FIND' (Search) logic...")

            # --- THIS IS THE FIX ---
            semantic_query = plan.get("semantic_query")
            # --- END OF FIX ---

            if semantic_query:
                # Hybrid Search
                query_vector = embedder.embed(semantic_query)
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
                return jsonify(final_results_with_score[:5])

            else:
                # Pure Metadata Search
                final_results_from_db = db.get_files_by_filter_only(sql_filter)
                return jsonify(final_results_from_db[:5])

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

        # --- 3. ✅ MODIFIED: Initialize the agent "brain" ---
        logging.info("Initializing agent brain (Gemini)...")
        # We set the "system instruction" here, when we create the model
        agent_model = genai.GenerativeModel(
            'gemini-2.5-flash',
            system_instruction=AGENT_SYSTEM_PROMPT
        )
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
