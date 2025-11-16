# app.py (Final GUI with "Top-Result-Only" and no snippets)
import customtkinter as ctk
from tkinter import filedialog
import requests
import os
import sys
import json
import threading

# --- SERVER SETTINGS ---
SERVER_BASE_URL = "http://127.0.0.1:5000"
SEARCH_URL = f"{SERVER_BASE_URL}/search"
RECENT_URL = f"{SERVER_BASE_URL}/get_recent_files"
POPULAR_URL = f"{SERVER_BASE_URL}/get_popular_files"

# --- CONFIG PATH ---
SETTINGS_PATH = os.path.join(os.path.dirname(
    os.path.abspath(__file__)), 'db', 'settings.json')

# --- CLICK HANDLER FUNCTIONS ---


def open_file(path: str):
    """Opens the file itself with its default application."""
    try:
        os.startfile(path)
    except Exception as e:
        print(f"Error opening file: {e}")


def open_folder(path: str):
    """Opens the folder that contains the file."""
    try:
        os.startfile(os.path.dirname(path))
    except Exception as e:
        print(f"Error opening folder: {e}")

# --- MAIN APP CLASS ---


class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        # --- Window Setup ---
        self.title("MetaTrack Dashboard")
        self.geometry("800x600")
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        # --- Define Fonts ---
        self.title_font = ctk.CTkFont(family="Arial", size=18, weight="bold")
        self.link_font = ctk.CTkFont(family="Arial", size=16, weight="bold")
        self.path_font = ctk.CTkFont(family="Arial", size=12, slant="italic")
        self.info_font = ctk.CTkFont(family="Arial", size=12, weight="bold")
        self.status_font = ctk.CTkFont(family="Arial", size=12)
        self.chat_font = ctk.CTkFont(family="Arial", size=14)

        self.watched_folders = []
        self.chat_history_for_agent = []
        self.chat_widget_count = 0
        self.last_search_results = []  # <-- NEW: To store all 5 results

        # --- 1. Create the Main TabView ---
        self.tab_view = ctk.CTkTabview(self, anchor="w")
        self.tab_view.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        self.tab_view.add("Home")
        self.tab_view.add("Search")
        self.tab_view.add("Settings")

        # --- 2. Populate the "Home" Tab ---
        self.home_tab = self.tab_view.tab("Home")
        self.home_tab.grid_columnconfigure(0, weight=1)
        self.home_tab.grid_rowconfigure(1, weight=1)
        self.home_tab.grid_rowconfigure(3, weight=1)
        # (Rest of Home tab setup is unchanged)
        self.recent_label = ctk.CTkLabel(
            self.home_tab, text="Recently Modified", font=self.title_font, anchor="w")
        self.recent_label.grid(
            row=0, column=0, sticky="ew", padx=10, pady=(10, 5))
        self.recent_files_frame = ctk.CTkScrollableFrame(self.home_tab)
        self.recent_files_frame.grid(
            row=1, column=0, sticky="nsew", padx=10, pady=5)
        self.recent_files_frame.grid_columnconfigure(0, weight=1)
        self.popular_label = ctk.CTkLabel(
            self.home_tab, text="Frequently Accessed", font=self.title_font, anchor="w")
        self.popular_label.grid(
            row=2, column=0, sticky="ew", padx=10, pady=(10, 5))
        self.popular_files_frame = ctk.CTkScrollableFrame(self.home_tab)
        self.popular_files_frame.grid(
            row=3, column=0, sticky="nsew", padx=10, pady=5)
        self.popular_files_frame.grid_columnconfigure(0, weight=1)

        # --- 3. Populate the "Search" Tab (Chat Layout) ---
        self.search_tab = self.tab_view.tab("Search")
        self.search_tab.grid_columnconfigure(0, weight=1)
        self.search_tab.grid_rowconfigure(
            0, weight=1)  # Chat history will expand

        # This is now a ScrollableFrame to hold widgets
        self.chat_frame = ctk.CTkScrollableFrame(self.search_tab)
        self.chat_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        self.chat_frame.grid_columnconfigure(0, weight=1)

        # Frame for typing
        self.chat_input_frame = ctk.CTkFrame(self.search_tab, corner_radius=0)
        self.chat_input_frame.grid(
            row=1, column=0, sticky="ew", padx=10, pady=10)
        self.chat_input_frame.grid_columnconfigure(0, weight=1)
        # (Rest of Search tab input is unchanged)
        self.chat_entry = ctk.CTkEntry(
            self.chat_input_frame, placeholder_text="Enter your query...", height=35, font=self.chat_font)
        self.chat_entry.grid(row=0, column=0, sticky="ew", padx=10, pady=10)
        self.chat_entry.bind("<Return>", self.search_event)
        self.chat_send_button = ctk.CTkButton(
            self.chat_input_frame, text="Send", command=self.search_event, height=35)
        self.chat_send_button.grid(row=0, column=1, padx=(0, 10), pady=10)

        # --- 4. Populate the "Settings" Tab (Unchanged) ---
        self.settings_tab = self.tab_view.tab("Settings")
        self.settings_tab.grid_columnconfigure(0, weight=1)
        self.settings_tab.grid_rowconfigure(1, weight=1)
        # (Rest of Settings tab setup is unchanged)
        self.settings_title = ctk.CTkLabel(
            self.settings_tab, text="Watched Folders", font=self.title_font, anchor="w")
        self.settings_title.grid(
            row=0, column=0, sticky="ew", padx=10, pady=(10, 5))
        self.settings_frame = ctk.CTkScrollableFrame(self.settings_tab)
        self.settings_frame.grid(
            row=1, column=0, sticky="nsew", padx=10, pady=5)
        self.settings_frame.grid_columnconfigure(0, weight=1)
        self.folder_widgets = {}
        self.settings_button_frame = ctk.CTkFrame(
            self.settings_tab, corner_radius=0, fg_color="transparent")
        self.settings_button_frame.grid(
            row=2, column=0, sticky="ew", padx=10, pady=10)
        self.add_folder_button = ctk.CTkButton(
            self.settings_button_frame, text="Add Folder...", command=self.add_folder)
        self.add_folder_button.pack(side="left", padx=5)
        self.settings_status_label = ctk.CTkLabel(
            self.settings_button_frame, text="Changes require restarting the server (watcher.py).", text_color="gray")
        self.settings_status_label.pack(side="right", padx=10)

        # --- 5. Initial Load ---
        self.load_settings()
        self.check_server_and_load_home()

    # --- WIDGET CREATION (FIX 1: No Snippet) ---
    def create_file_widget(self, parent_frame, file_info, row_index):
        """Creates a single clickable file widget in the specified frame."""
        path = file_info.get('path', 'N/A')
        name = file_info.get('name', 'N/A')
        # Snippet is no longer used

        res_frame = ctk.CTkFrame(parent_frame, fg_color="gray14")
        res_frame.grid(row=row_index, column=0, sticky="ew", pady=(0, 8))
        res_frame.grid_columnconfigure(0, weight=1)

        name_label = ctk.CTkLabel(
            res_frame, text=name, text_color="#6495ED",
            cursor="hand2", anchor="w", font=self.link_font
        )
        name_label.grid(row=0, column=0, sticky="w", padx=10, pady=(10, 0))
        name_label.bind("<Button-1>", lambda e, p=path: open_file(p))

        path_label = ctk.CTkLabel(
            res_frame, text=os.path.dirname(path), text_color="gray",
            cursor="hand2", anchor="w", font=self.path_font
        )
        path_label.grid(row=1, column=0, sticky="w", padx=10, pady=(0, 5))
        path_label.bind("<Button-1>", lambda e, p=path: open_folder(p))

        info_text = ""
        if 'score' in file_info:
            info_text += f"Score: {file_info['score']:.2f}  "
        if 'modified_at' in file_info:
            info_text += f"Modified: {file_info['modified_at'].split('T')[0]}  "
        if 'access_count' in file_info and file_info['access_count'] > 0:
            info_text += f"Access Count: {file_info['access_count']}"

        if info_text:
            info_label = ctk.CTkLabel(
                res_frame, text=info_text, anchor="w", text_color="gray", font=self.info_font)
            info_label.grid(row=2, column=0, sticky="w", padx=10, pady=(0, 10))

    # --- HOME TAB LOGIC (Unchanged) ---
    def check_server_and_load_home(self):
        self.recent_label.configure(text="Checking server connection...")
        threading.Thread(target=self._check_server_thread, daemon=True).start()

    def _check_server_thread(self):
        try:
            requests.head(SERVER_BASE_URL, timeout=2)
            self.after(0, self.load_home_page_data)
        except requests.exceptions.ConnectionError:
            self.after(0, self.display_error,
                       "Error: Could not connect to MetaTrack server. Is it running?")

    def load_home_page_data(self):
        self.recent_label.configure(text="Loading Recent Files...")
        self.popular_label.configure(text="Loading Popular Files...")
        threading.Thread(target=self._fetch_home_lists, daemon=True).start()

    def _fetch_home_lists(self):
        recent_files, popular_files = [], []
        try:
            response_recent = requests.get(RECENT_URL)
            if response_recent.status_code == 200:
                recent_files = response_recent.json()
            response_popular = requests.get(POPULAR_URL)
            if response_popular.status_code == 200:
                popular_files = response_popular.json()
            self.after(0, self.display_home_lists, recent_files, popular_files)
        except Exception as e:
            self.after(0, self.display_error, f"Error fetching home data: {e}")

    def display_home_lists(self, recent_files, popular_files):
        for widget in self.recent_files_frame.winfo_children():
            widget.destroy()
        for widget in self.popular_files_frame.winfo_children():
            widget.destroy()
        self.recent_label.configure(text="Recently Modified")
        self.popular_label.configure(text="Frequently Accessed")
        if not recent_files:
            ctk.CTkLabel(self.recent_files_frame,
                         text="No files indexed.").pack()
        else:
            for i, file in enumerate(recent_files):
                self.create_file_widget(self.recent_files_frame, file, i)
        if not popular_files:
            ctk.CTkLabel(self.popular_files_frame,
                         text="No popular files found.").pack()
        else:
            for i, file in enumerate(popular_files):
                self.create_file_widget(self.popular_files_frame, file, i)

    # --- SEARCH TAB LOGIC (FIX 2: Show Top-1 + "Show More" button) ---
    def search_event(self, event=None):
        """Adds user query to chat and starts search thread."""
        query = self.chat_entry.get()
        if not query:
            return
        self.add_message_to_chat("You", query, is_user=True)
        self.chat_history_for_agent.append({"role": "user", "text": query})
        self.chat_entry.delete(0, 'end')
        self.chat_send_button.configure(state="disabled")
        threading.Thread(target=self.run_search, args=(
            query, self.chat_history_for_agent), daemon=True).start()

    def run_search(self, query, history):
        """Sends chat history to server."""
        try:
            response = requests.post(
                SEARCH_URL, json={'query': query, 'history': history})
            if response.status_code == 200:
                results = response.json()
                self.after(0, self.display_search_results, results)
            else:
                error_msg = response.json().get('error', 'Unknown server error')
                self.after(0, lambda: self.display_error(
                    error_msg, is_search=True))
        except requests.exceptions.ConnectionError:
            self.after(0, lambda: self.display_error(
                "Error: Could not connect to MetaTrack server.", is_search=True))
        except Exception as e:
            self.after(0, lambda: self.display_error(
                f"An unknown error occurred: {e}", is_search=True))

    def add_message_to_chat(self, user_name, text, is_user=False):
        """Adds a text bubble to the chat frame."""
        anchor = "e" if is_user else "w"
        justify = "right" if is_user else "left"
        frame = ctk.CTkFrame(self.chat_frame, fg_color="transparent")
        frame.grid(row=self.chat_widget_count, column=0,
                   sticky=anchor, padx=10, pady=5)
        label = ctk.CTkLabel(
            frame, text=f"{user_name}:", font=self.info_font, text_color="gray", anchor=anchor)
        label.pack(side="top", anchor=anchor)
        bubble = ctk.CTkLabel(
            frame, text=text, font=self.chat_font, wraplength=600, justify=justify,
            fg_color="gray14" if is_user else "gray20", corner_radius=10, padx=10, pady=5
        )
        bubble.pack(side="bottom", anchor=anchor, pady=(0, 5))
        self.chat_widget_count += 1
        self._scroll_to_bottom()

    def add_file_widgets_to_chat(self, files_list, show_all=False):
        """Adds clickable file widgets to the chat."""
        if not files_list:
            return

        # <-- Only show the first one
        files_to_show = files_list if show_all else files_list[:1]

        files_container = ctk.CTkFrame(self.chat_frame, fg_color="transparent")
        files_container.grid(row=self.chat_widget_count,
                             column=0, sticky="w", padx=10, pady=5)
        files_container.grid_columnconfigure(0, weight=1)
        self.chat_widget_count += 1

        for i, file_info in enumerate(files_to_show):
            self.create_file_widget(files_container, file_info, i)

        # Add a "Show more" button if we hid some results
        if not show_all and len(files_list) > 1:
            self.add_show_more_button(files_container, files_list)

        self._scroll_to_bottom()

    def add_show_more_button(self, container, files_list):
        """Adds a button to show the rest of the results."""
        button_frame = ctk.CTkFrame(container)
        button_frame.grid(row=1, column=0, sticky="w", pady=(5, 0))

        show_more_button = ctk.CTkButton(
            button_frame,
            text=f"Show {len(files_list) - 1} other results...",
            command=lambda: self.show_all_results(container, files_list),
            fg_color="gray25"
        )
        show_more_button.pack(side="left", padx=10, pady=5)

    def show_all_results(self, container, files_list):
        """Callback to replace the 'Top 1' with all results."""
        # Clear the old widgets from the container
        for widget in container.winfo_children():
            widget.destroy()

        # Redraw all files in that same container
        for i, file_info in enumerate(files_list):
            self.create_file_widget(container, file_info, i)
        self._scroll_to_bottom()

    def _scroll_to_bottom(self):
        """Forces the chat frame to scroll to the newest message."""
        self.after(50, self.chat_frame._parent_canvas.yview_moveto, 1.0)

    def display_error(self, message, is_search=False):
        """Displays an error message."""
        if is_search:
            self.add_message_to_chat("Error", message, is_user=False)
            self.chat_send_button.configure(state="normal")
        else:
            self.recent_label.configure(text=message, text_color="red")
            self.popular_label.configure(text="")

    def display_search_results(self, results):
        """Displays the agent's answer AND file widgets in the chat."""
        answer = results.get(
            'answer', "Sorry, I had a problem getting an answer.")
        files = results.get('files', [])

        # Store the full list in case the user wants to see it
        self.last_search_results = files

        # 1. Add the agent's text reply
        self.add_message_to_chat("Agent", answer, is_user=False)
        self.chat_history_for_agent.append({"role": "agent", "text": answer})

        # 2. Add the clickable file widgets (this will now only show Top-1)
        if files:
            self.add_file_widgets_to_chat(files, show_all=False)

        self.chat_send_button.configure(state="normal")

    # --- SETTINGS TAB LOGIC (Unchanged) ---
    def load_settings(self):
        self.watched_folders = []
        if os.path.exists(SETTINGS_PATH):
            try:
                with open(SETTINGS_PATH, 'r') as f:
                    settings = json.load(f)
                    self.watched_folders = settings.get('watch_paths', [])
            except Exception as e:
                print(f"Error reading settings.json: {e}")
        self.redraw_folder_list()

    def save_settings(self):
        try:
            os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
            with open(SETTINGS_PATH, 'w') as f:
                json.dump({'watch_paths': self.watched_folders}, f, indent=4)
            self.settings_status_label.configure(text_color="yellow")
        except Exception as e:
            print(f"Error saving settings.json: {e}")

    def redraw_folder_list(self):
        for widget in self.settings_frame.winfo_children():
            widget.destroy()
        self.folder_widgets = {}
        if not self.watched_folders:
            ctk.CTkLabel(self.settings_frame, text="No folders are being watched.").grid(
                row=0, column=0, padx=10, pady=10)
            return
        for i, folder_path in enumerate(self.watched_folders):
            frame = ctk.CTkFrame(self.settings_frame, fg_color="gray14")
            frame.grid(row=i, column=0, sticky="ew", pady=(0, 5), padx=5)
            frame.grid_columnconfigure(0, weight=1)
            label = ctk.CTkLabel(frame, text=folder_path, anchor="w")
            label.grid(row=0, column=0, sticky="ew", padx=10, pady=5)
            remove_button = ctk.CTkButton(
                frame, text="Remove", width=60,
                command=lambda p=folder_path: self.remove_folder(p),
                fg_color="red"
            )
            remove_button.grid(row=0, column=1, padx=10, pady=5)
            self.folder_widgets[folder_path] = frame

    def add_folder(self):
        folder_path = filedialog.askdirectory()
        if folder_path:
            folder_path = os.path.normpath(folder_path)
            if folder_path not in self.watched_folders:
                self.watched_folders.append(folder_path)
                self.save_settings()
                self.redraw_folder_list()

    def remove_folder(self, folder_path):
        if folder_path in self.watched_folders:
            self.watched_folders.remove(folder_path)
            self.save_settings()
            self.redraw_folder_list()


if __name__ == "__main__":
    app = App()
    app.mainloop()
