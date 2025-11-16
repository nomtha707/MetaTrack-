# tracker/watcher.py (Final Conversational Server)
import os
import time
import json
import re
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
agent_model = None
# ------------------------

# --- LOGGING SETUP ---
log_path = os.path.join(config.BASE_DIR, 'watcher.log')
logging.basicConfig(filename=log_path, level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

# --- AGENT PROMPT 1: SEARCH PLANNER (Upgraded for Chat) ---
AGENT_SYSTEM_PROMPT = """
You are a "Local File Search Agent". Your job is to analyze a user's *latest query*
and convert it into a JSON plan.
(The user will provide today's date and day of the week).

--- DATABASE SCHEMA ---
The 'files' table has columns: path, name, modified_at, access_count.

--- RULES ---
1.  Respond ONLY with a single, minified JSON object.
2.  The JSON plan MUST have two keys: "semantic_query" and "sql_filter".
3.  **"semantic_query": This is for the *core topic* of the search ONLY.**
    - You MUST extract the main subject (e.g., "prolog", "machine learning", "sharp objects").
4.  **"sql_filter": This is for *all* metadata and file type filters.**
    - Use `path LIKE '%.docx'` for "word document".
    - Use `path LIKE '%.py'` for "python script".
    - Use `modified_at LIKE 'YYYY-MM-DD%'` for dates.
    - If no filter is needed, use "1=1".
5.  If the query is *only* metadata (e.g., "newest files"), set "semantic_query" to null.

--- EXAMPLES ---
User Query: file on prolog system
{"semantic_query": "Prolog programming language", "sql_filter": "1=1"}

User Query: word document on the literature sharp objects
{"semantic_query": "sharp objects novel gillian flynn", "sql_filter": "path LIKE '%.docx'"}

User Query: python script about machine learning
{"semantic_query": "machine learning code", "sql_filter": "path LIKE '%.py'"}

User Query: (Today is Wednesday, 2025-11-05) files opened last tuesday
{"semantic_query": null, "sql_filter": "modified_at LIKE '2025-10-28%'"}
"""

# --- AGENT PROMPT 2: CHATBOT SUMMARY (Upgraded for Chat) ---
CHATBOT_SUMMARY_PROMPT = """
You are a friendly search assistant. Your job is to *only* describe the files
provided in the "FILE SEARCH RESULTS" JSON.

--- RULES ---
- **Your answer MUST be a summary of the files I am giving you.**
- **Do NOT add any new files or information that is not in the list.**
- **Do NOT hide any files.** If there are 5 files in the list, describe all 5.
- Pay close attention to the user's latest query to understand *why* they wanted this list.
- **You MUST format file lists as bullet points (`*`).**
- In your conversational reply, refer to files by their "name" (e.g., "prolog_doc.docx").

--- CHAT HISTORY (for context) ---
{chat_history}
---

--- USER'S LATEST QUERY ---
{query_text}

--- FILE SEARCH RESULTS (as JSON) ---
{file_list_json}
---

Friendly Answer:
"""

# --- THIS IS THE SNIPPET FUNCTION ---


def _generate_snippet(full_text: str, query: str, snippet_length=250):
    """
    Finds the best snippet from the text that matches the query.
    """
    if not full_text:
        return None

    # Clean up the text for better searching
    full_text_lower = full_text.lower()
    query_lower = query.lower()

    # Find the best match
    best_match_index = -1

    # Try finding the whole query first
    best_match_index = full_text_lower.find(query_lower)

    # If not found, try finding individual words
    if best_match_index == -1:
        query_words = set(re.findall(r'\w+', query_lower))
        if not query_words:
            return None  # No words to search for

        for word in query_words:
            if len(word) > 3:  # Ignore small words
                best_match_index = full_text_lower.find(word)
                if best_match_index != -1:
                    break  # Found a good word, use it

    # If no match at all, just return the start of the file
    if best_match_index == -1:
        return full_text.strip().replace("\n", " ")[:snippet_length]

    # We found a match, now extract the context
    start = max(0, best_match_index - 75)  # 75 chars before
    end = min(len(full_text), best_match_index +
              snippet_length - 75)  # 175 after

    snippet = full_text[start:end].strip().replace("\n", " ")
    return snippet
# --- END OF SNIPPET FUNCTION ---


# --- FLASK SERVER APP ---
app = Flask(__name__)


@app.route('/search', methods=['POST'])
def search_endpoint():
    global db, embedder, vstore, agent_model

    data = request.json
    query_text = data.get('query')  # This is the user's *original* query
    chat_history = data.get('history', [])

    if not query_text:
        return jsonify({"error": "No query provided"}), 400
    if not all([db, embedder, vstore, agent_model]):
        return jsonify({"error": "Server components not initialized"}), 500

    response = None
    try:
        logging.info(
            f"Agent received query: '{query_text}' with {len(chat_history)} history items.")

        history_str = "\n".join(
            [f"{msg['role']}: {msg['text']}" for msg in chat_history])
        history_str_with_query = history_str + f"\nuser: {query_text}"

        # --- 1. "THINK": Ask the LLM agent for a plan ---
        try:
            today = datetime.now()
            today_date_str = today.strftime("%Y-%m-%d")
            day_of_week_str = today.strftime("%A")
            user_prompt = f"Today is {day_of_week_str}, {today_date_str}.\n--- CHAT HISTORY ---\n{history_str}\n--- USER'S LATEST QUERY ---\n{query_text}"

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
        semantic_query = plan.get("semantic_query")

        # --- THIS IS THE FIX ---
        # For snippets and keyword search, we will *always* use the user's raw query.
        snippet_query = query_text
        # --- END OF FIX ---

        # --- 2. "ACT": Execute the "Find" plan ---
        logging.info("Executing 'FIND' (Hybrid Search) logic...")

        final_results_map = {}

        if semantic_query:
            # --- HYBRID SEARCH - PART 1: SEMANTIC (MEANING) ---
            query_vector = embedder.embed_text(semantic_query)
            vector_results = vstore.query(query_vector, top_k=10)

            search_paths = [res['path'] for res in vector_results]
            if search_paths:
                filtered_semantic_results = db.get_files_by_path_and_filter(
                    search_paths, sql_filter)
                for res in filtered_semantic_results:
                    res_dict = dict(res)
                    res_dict['score'] = next(
                        (v['score'] for v in vector_results if v['path'] == res['path']), 0)
                    final_results_map[res['path']] = res_dict
        else:
            # --- PURE METADATA SEARCH ---
            metadata_results = db.get_files_by_filter_only(sql_filter)
            for res in metadata_results:
                res_dict = dict(res)
                res_dict['score'] = 0
                final_results_map[res['path']] = res_dict

        # --- HYBRID SEARCH - PART 2: KEYWORD (LITERAL) ---
        # We now search keywords using the *original user query*
        keyword_results = db.get_files_by_keyword(snippet_query, limit=5)
        for res in keyword_results:
            res_dict = dict(res)
            existing_score = final_results_map.get(
                res['path'], {}).get('score', 0)
            res_dict['score'] = existing_score + 1.0  # Add 1.0 (massive bonus)
            final_results_map[res['path']] = res_dict

        final_sorted_list = sorted(final_results_map.values(
        ), key=lambda x: x.get('score', 0), reverse=True)
        final_results = final_sorted_list[:5]  # Get the top 5 from all sources

        # --- 3. AUGMENT WITH SNIPPETS & INCREMENT COUNT ---
        augmented_results = []
        for res_dict in final_results:
            try:
                full_text = extract_text(res_dict['path'])
                res_dict['snippet'] = _generate_snippet(
                    full_text, snippet_query)
                db.increment_access_count(res_dict['path'])
                augmented_results.append(res_dict)
            except Exception as e:
                logging.error(
                    f"Error generating snippet for {res_dict['path']}: {e}")
                res_dict['snippet'] = "Error generating preview."
                augmented_results.append(res_dict)

        # --- 4. GENERATE CHATBOT SUMMARY ---
        if not augmented_results:
            return jsonify({"answer": "I looked, but I couldn't find any files matching that.", "files": []})

        file_list_str = json.dumps(augmented_results)

        logging.info("Generating chatbot summary for file list...")

        summary_prompt = CHATBOT_SUMMARY_PROMPT.format(
            chat_history=history_str_with_query,
            query_text=query_text,
            file_list_json=file_list_str
        )
        summary_response = agent_model.generate_content(summary_prompt)

        # --- 5. RETURN BOTH! ---
        return jsonify({
            "answer": summary_response.text,
            "files": augmented_results
        })

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

# --- WATCHDOG HANDLER (Unchanged) ---


def file_metadata(path: str):
    try:
        st = os.stat(path)
        return {'path': path, 'name': os.path.basename(path), 'size': st.st_size, 'created_at': datetime.fromtimestamp(st.st_ctime).isoformat(), 'modified_at': datetime.fromtimestamp(st.st_mtime).isoformat(), 'accessed_at': datetime.fromtimestamp(st.st_atime).isoformat(), 'extra_json': '{}'}
    except Exception as e:
        logging.error(f'Error getting metadata for {path}: {e}')
        return None


class Handler(FileSystemEventHandler):
    def __init__(self):
        self.excluded_dirs = config.EXCLUDED_DIRS
        self.valid_extensions = config.VALID_EXTENSIONS

    def _is_path_excluded(self, path):
        if not path or not isinstance(path, str):
            return True
        filename = os.path.basename(path)
        if filename.startswith('~$') or filename.startswith('.'):
            return True
        path_lower = path.lower().replace('\\', '/')
        for excluded_dir in self.excluded_dirs:
            if f'/{excluded_dir.lower()}/' in path_lower:
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
        self.process_file(event.src_path, check_modified_time=True)

    def on_deleted(self, event):
        global db, vstore
        if event.is_directory:
            return
        path = event.src_path
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

        # --- THIS IS THE NEW DYNAMIC STARTUP LOGIC ---

        # 1. Load watch paths from settings.json
        watch_paths = []
        if os.path.exists(config.SETTINGS_PATH):
            try:
                with open(config.SETTINGS_PATH, 'r') as f:
                    settings = json.load(f)
                    watch_paths = settings.get('watch_paths', [])
            except Exception as e:
                logging.error(f"Error reading settings.json: {e}")

        if not watch_paths:
            logging.warning("No watch paths configured. Watcher is idle.")
            logging.warning(
                f"Please run the GUI (app.py) and add folders in the 'Settings' tab.")
        else:
            logging.info(f"Loaded {len(watch_paths)} paths from settings.")

        # 2. Start initial scan for all configured paths
        event_handler = Handler()
        for path in watch_paths:
            logging.info(f"Performing initial scan of {path}...")
            if os.path.exists(path):
                for root, dirs, files in os.walk(path, topdown=True):

                    dirs[:] = [d for d in dirs if d.lower(
                    ) not in config.EXCLUDED_DIRS and not d.startswith('.')]

                    for filename in files:
                        file_path = os.path.join(root, filename)
                        if not event_handler._is_path_excluded(file_path):
                            try:
                                event_handler.process_file(
                                    file_path, check_modified_time=True)
                            except Exception as e:
                                logging.error(
                                    f"Error during initial scan of {filename}: {e}\n{traceback.format_exc()}")
                logging.info(f"Initial scan complete for {path}.")
            else:
                logging.error(f"Error: Watch path '{path}' does not exist.")

        # 3. Start the observer for all configured paths
        observer = Observer()
        for path in watch_paths:
            if os.path.exists(path):
                observer.schedule(event_handler, path, recursive=True)
                logging.info(f"Watcher started on {path}.")

        if watch_paths:
            observer.start()

        # --- END OF NEW LOGIC ---

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logging.info("Watcher stopped by user.")
            if observer.is_alive():
                observer.stop()

        if observer.is_alive():
            observer.join()

    except Exception as e:
        logging.error(
            f"🔥🔥🔥 FATAL STARTUP ERROR: {e}\n{traceback.format_exc()}")
