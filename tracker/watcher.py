# tracker/watcher.py (Multimodal Two-Tower Server)
import pystray
from PIL import Image, ImageDraw
import webview
from flask import render_template
import os
import sys
import time
import json
import re
import threading
import tkinter as tk
from tkinter import filedialog
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from datetime import datetime
import tracker.config as config
from tracker.metadata_db import MetadataDB
from tracker.extractor import extract_text
from tracker.embedder import Embedder
from tracker.vectorstore import SimpleVectorStore
# -------------------------------------

from flask import Flask, request, jsonify
import logging
import traceback
import ctypes

# --- AGENT IMPORTS ---
import google.generativeai as genai
# -------------------------

# --- GLOBAL VARIABLES ---
db = None
embedder = None
vstore_text = None   # Text database
vstore_image = None  # Image database
agent_model = None
# NEW: Dynamic File Watcher Globals
observer = None
event_handler = None
active_watches = {}
# NEW: The Live Sync Tracker
sync_status = {
    "total": 0,
    "scanned": 0,
    "is_syncing": False,
    "current_file": "Standing by..."
}
# ------------------------

# --- LOGGING SETUP ---
log_path = os.path.join(config.BASE_DIR, 'watcher.log')
logging.basicConfig(filename=log_path, level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

# --- HELPER: DETECT CLOUD FILES ---
def is_cloud_file(filepath):
    try:
        attrs = ctypes.windll.kernel32.GetFileAttributesW(filepath)
        if attrs == -1: return False
        FILE_ATTRIBUTE_OFFLINE = 0x1000
        FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x400000 
        if (attrs & FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS) or (attrs & FILE_ATTRIBUTE_OFFLINE):
            return True
        return False
    except:
        return False

# --- AGENT PROMPT 1: SEARCH PLANNER ---
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
    - You MUST extract the main subject (e.g., "prolog", "dog in a park", "sharp objects").
    - CRITICAL: DO NOT include words like "file", "image", "picture", "photo", "document", "scan", or "screenshot". 
    - Example: If the user asks "give me screenshots of code", the semantic_query MUST be exactly "code".
4.  **"sql_filter": This is for *all* metadata and file type filters.**
    - Use `path LIKE '%.docx'` for "word document".
    - Use `path LIKE '%.py'` for "python script".
    - Use `(path LIKE '%.jpg' OR path LIKE '%.png' OR path LIKE '%.jpeg')` for "images", "pictures", or "screenshots".
    - Use `modified_at LIKE 'YYYY-MM-DD%'` for dates.
    - If no filter is needed, use "1=1".
5.  If the query is *only* metadata (e.g., "newest files"), set "semantic_query" to null.
"""

# --- AGENT PROMPT 2: CHATBOT SUMMARY ---
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

def _generate_snippet(full_text: str, query: str, snippet_length=250):
    if not full_text: return None
    full_text_lower = full_text.lower()
    query_lower = query.lower()
    best_match_index = full_text_lower.find(query_lower)
    
    if best_match_index == -1:
        query_words = set(re.findall(r'\w+', query_lower))
        if not query_words: return None 
        for word in query_words:
            if len(word) > 3: 
                best_match_index = full_text_lower.find(word)
                if best_match_index != -1: break 
                
    if best_match_index == -1:
        return full_text.strip().replace("\n", " ")[:snippet_length]
        
    start = max(0, best_match_index - 75) 
    end = min(len(full_text), best_match_index + snippet_length - 75) 
    return full_text[start:end].strip().replace("\n", " ")

def chunk_text(text, chunk_size=150, overlap=30):
    """Slices long text into small overlapping chunks for the AI to read."""
    if not text: return []
    words = text.split()
    chunks = []
    
    for i in range(0, len(words), chunk_size - overlap):
        chunk = " ".join(words[i:i + chunk_size])
        chunks.append(chunk)
        if i + chunk_size >= len(words):
            break
            
    return chunks

def _scan_directory_task(path):
    """The background worker that safely counts and processes files."""
    global sync_status, event_handler
    sync_status["is_syncing"] = True
    
    excluded_dirs_lower = [d.lower() for d in config.EXCLUDED_DIRS]
    
    # 1. Fast Pre-count (to get the denominator for the progress bar)
    files_to_process = []
    for root, dirs, files in os.walk(path, topdown=True, onerror=walk_error_handler):
        dirs[:] = [d for d in dirs if d.lower() not in excluded_dirs_lower and not d.startswith('.')]
        for filename in files:
            file_path = os.path.join(root, filename)
            if not event_handler._is_path_excluded(file_path):
                files_to_process.append(file_path)
    
    # Add to the running total (in case they add multiple folders at once)
    sync_status["total"] += len(files_to_process)
    
    # 2. Process the files
    for file_path in files_to_process:
        sync_status["current_file"] = os.path.basename(file_path)
        event_handler.process_file(file_path, True)
        sync_status["scanned"] += 1
        
    # 3. Check if all tasks are complete
    if sync_status["scanned"] >= sync_status["total"]:
        sync_status["is_syncing"] = False
        sync_status["current_file"] = "All systems up to date."

def start_watching_folder(path):
    global observer, event_handler, active_watches
    if path in active_watches or not os.path.exists(path): return
    
    logging.info(f"Performing initial scan for new folder: {path}")
    
    # Spawn the heavy lifting into a background thread
    threading.Thread(target=_scan_directory_task, args=(path,), daemon=True).start()
    
    # Attach the live Watchdog listener so it catches future changes
    try:
        watch = observer.schedule(event_handler, path, recursive=True)
        active_watches[path] = watch
    except Exception as e:
        logging.error(f"Failed to watch {path}: {e}")

def stop_watching_folder(path):
    global observer, active_watches
    if path in active_watches:
        try:
            observer.unschedule(active_watches[path])
            del active_watches[path]
            logging.info(f"Live tracking stopped for: {path}")
        except Exception as e:
            logging.error(f"Error stopping watch for {path}: {e}")

# --- PYINSTALLER TEMPLATE FIX ---
if getattr(sys, 'frozen', False):
    # If running as a compiled .exe, look inside the PyInstaller folder
    template_dir = os.path.join(sys._MEIPASS, 'tracker', 'templates')
else:
    # If running as a normal python script, look in the normal folder
    template_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')

app = Flask(__name__, template_folder=template_dir)

# --- THE FRONTEND UI ---
@app.route('/')
def home():
    return render_template('index.html')

@app.route('/search', methods=['POST'])
def search_endpoint():
    global db, embedder, vstore_text, vstore_image, agent_model

    data = request.json
    query_text = data.get('query')
    chat_history = data.get('history', [])

    if not query_text:
        return jsonify({"error": "No query provided"}), 400

    try:
        history_str = "\n".join([f"{msg['role']}: {msg['text']}" for msg in chat_history])
        history_str_with_query = history_str + f"\nuser: {query_text}"

        today = datetime.now()
        user_prompt = f"Today is {today.strftime('%A')}, {today.strftime('%Y-%m-%d')}.\n--- CHAT HISTORY ---\n{history_str}\n--- USER'S LATEST QUERY ---\n{query_text}"
        response = agent_model.generate_content(user_prompt)
        plan_json = response.text.strip("```json\n").strip("```")
        plan = json.loads(plan_json)

        sql_filter = plan.get("sql_filter", "1=1")
        semantic_query = plan.get("semantic_query")
        keyword_search_term = semantic_query 

        final_results_map = {}

        if semantic_query:
            # --- TWO-TOWER SEARCH: Query BOTH databases ---
            
            # 1. Ask the Text Brain
            q_vec_text = embedder.embed_text(semantic_query)
            text_results = vstore_text.query(q_vec_text, top_k=10)
            
            # 2. Ask the Image Brain
            q_vec_image = embedder.embed_query_for_image_search(semantic_query)
            image_results = vstore_image.query(q_vec_image, top_k=10)

            # 3. Combine them
            vector_results = text_results + image_results
            
            # 4. Clean the chunk tags and find the highest score for each file
            best_scores = {}
            for res in vector_results:
                # This strips the "::chunk_1" tag right off the path!
                clean_path = res['path'].split('::chunk_')[0] 
                score = res['score']
                
                # Keep the highest score if multiple chunks from the same file match
                if clean_path not in best_scores or score > best_scores[clean_path]:
                    best_scores[clean_path] = score

            search_paths = list(best_scores.keys())
            
            if search_paths:
                filtered_semantic_results = db.get_files_by_path_and_filter(search_paths, sql_filter)
                for res in filtered_semantic_results:
                    res_dict = dict(res)
                    # Assign the highest chunk score back to the file
                    res_dict['score'] = best_scores.get(res['path'], 0)
                    final_results_map[res['path']] = res_dict
        else:
            metadata_results = db.get_files_by_filter_only(sql_filter)
            for res in metadata_results:
                res_dict = dict(res)
                res_dict['score'] = 0
                final_results_map[res['path']] = res_dict

        if keyword_search_term:
            keyword_results = db.get_files_by_keyword(keyword_search_term, limit=5)
            for res in keyword_results:
                res_dict = dict(res)
                existing_score = final_results_map.get(res['path'], {}).get('score', 0)
                res_dict['score'] = existing_score + 1.0  
                final_results_map[res['path']] = res_dict

        final_sorted_list = sorted(final_results_map.values(), key=lambda x: x.get('score', 0), reverse=True)
        final_results = final_sorted_list[:5] 

        augmented_results = []
        for res_dict in final_results:
            try:
                ext = os.path.splitext(res_dict['path'])[1].lower()
                # Images don't have text to preview, so we give them a tag
                if ext in ['.jpg', '.jpeg', '.png']:
                    res_dict['snippet'] = "[Image File]"
                else:
                    full_text = extract_text(res_dict['path'])
                    res_dict['snippet'] = _generate_snippet(full_text, query_text)
                    
                db.increment_access_count(res_dict['path'])
                augmented_results.append(res_dict)
            except Exception as e:
                res_dict['snippet'] = "Error generating preview."
                augmented_results.append(res_dict)

        if not augmented_results:
            return jsonify({"answer": "I looked, but I couldn't find any files matching that.", "files": []})

        file_list_str = json.dumps(augmented_results)
        summary_prompt = CHATBOT_SUMMARY_PROMPT.format(
            chat_history=history_str_with_query, query_text=query_text, file_list_json=file_list_str
        )
        summary_response = agent_model.generate_content(summary_prompt)

        return jsonify({"answer": summary_response.text, "files": augmented_results})

    except Exception as e:
        logging.error(f"Error during search: {e}\n{traceback.format_exc()}")
        return jsonify({"error": "Internal server error"}), 500
    
@app.route('/open_file', methods=['POST'])
def open_file_endpoint():
    global db
    data = request.json
    filepath = data.get('path')
    
    if filepath and os.path.exists(filepath):
        try:
            # os.startfile is the magic Windows command to open a file normally
            os.startfile(filepath) 
            
            # Since they clicked it, let's bump the popularity score!
            db.increment_access_count(filepath)
            
            return jsonify({"status": "success"})
        except Exception as e:
            logging.error(f"Failed to open file {filepath}: {e}")
            return jsonify({"error": str(e)}), 500
            
    return jsonify({"error": "File not found on disk"}), 404

@app.route('/open_folder', methods=['POST'])
def open_folder_endpoint():
    data = request.json
    filepath = data.get('path')
    
    if filepath and os.path.exists(filepath):
        try:
            # Get the directory that contains the file
            folder_path = os.path.dirname(filepath)
            
            # Open that directory in Windows Explorer
            os.startfile(folder_path) 
            return jsonify({"status": "success"})
        except Exception as e:
            logging.error(f"Failed to open folder for {filepath}: {e}")
            return jsonify({"error": str(e)}), 500
            
    return jsonify({"error": "Path not found on disk"}), 404

@app.route('/check_setup', methods=['GET'])
def check_setup():
    # Check if the user has saved a key locally
    key_path = 'api_key.txt'
    if os.path.exists(key_path):
        with open(key_path, 'r') as f:
            if len(f.read().strip()) > 10:
                return jsonify({"status": "ready"})
    return jsonify({"status": "needs_key"})

@app.route('/save_key', methods=['POST'])
def save_key():
    data = request.json
    api_key = data.get('api_key', '').strip()
    
    if api_key:
        # Save it to a local text file next to the executable
        with open('api_key.txt', 'w') as f:
            f.write(api_key)
            
        # Instantly wire the AI brain with the new key!
        genai.configure(api_key=api_key)
        return jsonify({"status": "success"})
        
    return jsonify({"error": "Invalid key"}), 400

@app.route('/get_settings', methods=['GET'])
def get_settings():
    # 1. Get the folders
    paths = []
    if os.path.exists(config.SETTINGS_PATH):
        with open(config.SETTINGS_PATH, 'r') as f:
            paths = json.load(f).get('watch_paths', [])

    # 2. Get the masked API Key securely
    masked_key = "Not Set"
    key_path = 'api_key.txt'
    if os.path.exists(key_path):
        with open(key_path, 'r') as f:
            key = f.read().strip()
            if len(key) > 15:
                # Show first 10 and last 4 characters, hide the rest
                masked_key = f"{key[:10]}...{key[-4:]}"
                
    return jsonify({"watch_paths": paths, "masked_key": masked_key})

@app.route('/sync_status', methods=['GET'])
def get_sync_status():
    global sync_status
    return jsonify(sync_status)

@app.route('/add_folder', methods=['POST'])
def add_folder():
    # Open native Windows folder picker safely
    root = tk.Tk()
    root.attributes("-topmost", True)
    root.withdraw()
    folder_path = filedialog.askdirectory(parent=root, title="Select a folder for MetaTrack to watch")
    root.destroy()
    
    if folder_path:
        paths = []
        if os.path.exists(config.SETTINGS_PATH):
            with open(config.SETTINGS_PATH, 'r') as f:
                paths = json.load(f).get('watch_paths', [])
        
        if folder_path not in paths:
            paths.append(folder_path)
            with open(config.SETTINGS_PATH, 'w') as f:
                json.dump({"watch_paths": paths}, f)
                
            threading.Thread(target=start_watching_folder, args=(folder_path,), daemon=True).start()
                
        return jsonify({"status": "success", "watch_paths": paths})
    return jsonify({"status": "cancelled"})

@app.route('/remove_folder', methods=['POST'])
def remove_folder():
    path_to_remove = request.json.get('path')
    paths = []
    if os.path.exists(config.SETTINGS_PATH):
        with open(config.SETTINGS_PATH, 'r') as f:
            paths = json.load(f).get('watch_paths', [])
            
    if path_to_remove in paths:
        paths.remove(path_to_remove)
        with open(config.SETTINGS_PATH, 'w') as f:
            json.dump({"watch_paths": paths}, f)
            
        stop_watching_folder(path_to_remove)
            
    return jsonify({"status": "success", "watch_paths": paths})

@app.route('/get_recent_files', methods=['GET'])
def get_recent_files():
    return jsonify(db.get_recent_files(limit=5))

@app.route('/get_popular_files', methods=['GET'])
def get_popular_files():
    return jsonify(db.get_popular_files(limit=5))

def run_flask_app():
    app.run(host="127.0.0.1", port=5000, debug=False)

def file_metadata(path: str):
    try:
        st = os.stat(path)
        return {'path': path, 'name': os.path.basename(path), 'size': st.st_size, 'created_at': datetime.fromtimestamp(st.st_ctime).isoformat(), 'modified_at': datetime.fromtimestamp(st.st_mtime).isoformat(), 'accessed_at': datetime.fromtimestamp(st.st_atime).isoformat(), 'extra_json': '{}'}
    except:
        return None

class Handler(FileSystemEventHandler):
    def __init__(self):
        self.excluded_dirs = config.EXCLUDED_DIRS
        self.valid_extensions = config.VALID_EXTENSIONS

    def _is_path_excluded(self, path):
        if not path or not isinstance(path, str): return True
        filename = os.path.basename(path)
        if filename.startswith('~$') or filename.startswith('.'): return True
        path_lower = path.lower().replace('\\', '/')
        for excluded_dir in self.excluded_dirs:
            if f'/{excluded_dir.lower()}/' in path_lower: return True
        if not path.lower().endswith(self.valid_extensions): return True
        return False

    def process_file(self, path, check_modified_time=False):
        global db, embedder, vstore_text, vstore_image
        try:
            if self._is_path_excluded(path): return
            if not os.path.exists(path): return
            if is_cloud_file(path): return 

            current_meta = file_metadata(path)
            if not current_meta: return
            if check_modified_time:
                stored_mod_time_str = db.get_modified_time(path)
                if stored_mod_time_str and current_meta['modified_at'] <= stored_mod_time_str:
                    return
                    
            if current_meta['size'] > 100 * 1024 * 1024: return

            # --- ROUTING LOGIC: Text vs Image ---
            ext = os.path.splitext(path)[1].lower()
            
            # 1. ALWAYS try to extract text first (Extractor will use OCR for images!)
            text = extract_text(path)
            if text:
                # If it found text (even inside an image), chop it and save it to the Text Brain
                chunks = chunk_text(text)
                for i, chunk in enumerate(chunks):
                    emb = embedder.embed_text(chunk)
                    chunk_path = f"{path}::chunk_{i}"
                    vstore_text.upsert(chunk_path, emb)

            # 2. If it's an image, ALSO send it to the Image Brain
            if ext in ['.jpg', '.jpeg', '.png']:
                logging.info(f"Processing visual data for (image): {path}")
                emb = embedder.embed_image(path)
                vstore_image.upsert(path, emb)
                
            elif not text:
                logging.info(f"Processed file with no readable text: {path}")
            
            db.upsert(current_meta)
        except Exception as e:
            logging.error(f"Error processing {path}: {e}")

    def on_created(self, event):
        if not event.is_directory: self.process_file(event.src_path, False)

    def on_modified(self, event):
        if not event.is_directory: self.process_file(event.src_path, True)

    def on_deleted(self, event):
        global db, vstore_text, vstore_image
        if not event.is_directory and not self._is_path_excluded(event.src_path):
            db.mark_deleted(event.src_path)
            # Delete from BOTH stores just to be safe
            vstore_text.delete(event.src_path)
            vstore_image.delete(event.src_path)

def walk_error_handler(exception):
    pass

if __name__ == '__main__':
    try:
        # --- 0. INITIALIZE CORE COMPONENTS ---
        key_path = 'api_key.txt'
        if os.path.exists(key_path):
            with open(key_path, 'r') as f:
                genai.configure(api_key=f.read().strip())

        db = MetadataDB(config.DB_PATH)
        embedder = Embedder()  
        
        vstore_text = SimpleVectorStore(path=config.EMBEDDINGS_PATH + "_text", dim=384)
        vstore_image = SimpleVectorStore(path=config.EMBEDDINGS_PATH + "_image", dim=512)

        agent_model = genai.GenerativeModel('gemini-2.5-flash', system_instruction=AGENT_SYSTEM_PROMPT)

        # --- 1. START FLASK SERVER IN BACKGROUND ---
        def start_server():
            # Run Flask silently so the Desktop Window can connect to it
            app.run(port=5000, debug=False, use_reloader=False)

        server_thread = threading.Thread(target=start_server, daemon=True)
        server_thread.start()

        # ---> THE FIX: Give Flask 1.5 seconds to fully wake up! <---
        time.sleep(1.5)

        # --- 2. RUN TRACKER IN BACKGROUND ---
        def run_tracker():
            global observer, event_handler
            event_handler = Handler()
            observer = Observer()
            observer.start() # Start the engine empty

            watch_paths = []
            if os.path.exists(config.SETTINGS_PATH):
                with open(config.SETTINGS_PATH, 'r') as f:
                    watch_paths = json.load(f).get('watch_paths', [])

            # Feed it the saved folders one by one
            for path in watch_paths:
                start_watching_folder(path)

            try:
                while True: time.sleep(1)
            except KeyboardInterrupt:
                if observer.is_alive(): observer.stop()
            if observer.is_alive(): observer.join()

        tracker_thread = threading.Thread(target=run_tracker, daemon=True)
        tracker_thread.start()

        # --- 3. SETUP THE NATIVE DESKTOP WINDOW ---
        # Notice we point it to the localhost URL where Flask is running
        window = webview.create_window('MetaTrack Search Agent', 'http://127.0.0.1:5000', width=1200, height=800)

        # Intercept the 'X' button! Hide the window instead of killing the app.
        def on_closing():
            window.hide()
            return False 
            
        window.events.closing += on_closing

        # --- 4. SYSTEM TRAY (THE MASTER CONTROLLER) ---
        def setup_tray():
            # Draw a temporary Dark Academia / Purple icon for the taskbar
            image = Image.new('RGB', (64, 64), color='#0A091A')
            draw = ImageDraw.Draw(image)
            draw.rectangle([16, 16, 48, 48], fill='#9D74E5')

            def on_open(icon, item):
                window.show()

            def on_quit(icon, item):
                # Safely destroy everything and kill the ghost processes
                icon.stop()
                window.destroy()
                os._exit(0) 

            # Create the Right-Click Menu
            menu = pystray.Menu(
                pystray.MenuItem('Open Dashboard', on_open, default=True),
                pystray.MenuItem('Quit MetaTrack', on_quit)
            )
            
            # Start the taskbar icon
            icon = pystray.Icon("MetaTrack", image, "MetaTrack Search Agent", menu)
            icon.run()

        # Run the Tray icon in a background thread
        tray_thread = threading.Thread(target=setup_tray, daemon=True)
        tray_thread.start()

        # --- 5. START THE UI ENGINE (Must be on main thread) ---
        webview.start()

    except Exception as e:
        logging.error(f"FATAL ERROR: {e}\n{traceback.format_exc()}")