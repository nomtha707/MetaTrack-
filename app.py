# app.py (Final Dashboard GUI)
import customtkinter as ctk
import requests
import os
import sys
import threading

# --- SERVER SETTINGS ---
SERVER_BASE_URL = "http://127.0.0.1:5000"
SEARCH_URL = f"{SERVER_BASE_URL}/search"
RECENT_URL = f"{SERVER_BASE_URL}/get_recent_files"
POPULAR_URL = f"{SERVER_BASE_URL}/get_popular_files"

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

        # --- 1. Create the Main TabView ---
        self.tab_view = ctk.CTkTabview(self, anchor="w")
        self.tab_view.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        self.tab_view.add("Home")
        self.tab_view.add("Search")

        # --- 2. Populate the "Home" Tab ---
        self.home_tab = self.tab_view.tab("Home")
        self.home_tab.grid_columnconfigure(0, weight=1)
        self.home_tab.grid_rowconfigure(1, weight=1)  # Recent files
        self.home_tab.grid_rowconfigure(3, weight=1)  # Popular files

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

        # --- 3. Populate the "Search" Tab ---
        self.search_tab = self.tab_view.tab("Search")
        self.search_tab.grid_columnconfigure(0, weight=1)
        self.search_tab.grid_rowconfigure(2, weight=1)

        self.search_top_frame = ctk.CTkFrame(self.search_tab, corner_radius=0)
        self.search_top_frame.grid(
            row=0, column=0, sticky="ew", padx=10, pady=10)
        self.search_top_frame.grid_columnconfigure(0, weight=1)

        self.search_entry = ctk.CTkEntry(
            self.search_top_frame,
            placeholder_text="Enter your query...",
            height=35,
            font=("Arial", 14)
        )
        self.search_entry.grid(row=0, column=0, sticky="ew", padx=10, pady=10)
        self.search_entry.bind("<Return>", self.search_event)

        self.search_button = ctk.CTkButton(
            self.search_top_frame,
            text="Search",
            command=self.search_event,
            height=35
        )
        self.search_button.grid(row=0, column=1, padx=(0, 10), pady=10)

        self.search_status_label = ctk.CTkLabel(
            self.search_tab, text="Ready.", text_color="gray", font=self.status_font)
        self.search_status_label.grid(
            row=1, column=0, sticky="ew", padx=20, pady=0)

        self.search_results_frame = ctk.CTkScrollableFrame(self.search_tab)
        self.search_results_frame.grid(
            row=2, column=0, sticky="nsew", padx=10, pady=10)
        self.search_results_frame.grid_columnconfigure(0, weight=1)

        # --- 4. Initial Load ---
        self.check_server_and_load_home()

    def create_file_widget(self, parent_frame, file_info, row_index):
        """Creates a single clickable file widget."""
        path = file_info.get('path', 'N/A')
        name = file_info.get('name', 'N/A')

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

        info_label = ctk.CTkLabel(
            res_frame, text=info_text, anchor="w", text_color="gray", font=self.info_font)
        info_label.grid(row=2, column=0, sticky="w", padx=10, pady=(0, 10))

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
                         text="No recent files found.").pack()
        else:
            for i, file in enumerate(recent_files):
                self.create_file_widget(self.recent_files_frame, file, i)

        if not popular_files:
            ctk.CTkLabel(self.popular_files_frame,
                         text="No popular files found.").pack()
        else:
            for i, file in enumerate(popular_files):
                self.create_file_widget(self.popular_files_frame, file, i)

    def search_event(self, event=None):
        query = self.search_entry.get()
        if not query:
            return
        self.search_status_label.configure(
            text="Searching...", text_color="yellow")
        self.search_button.configure(state="disabled")
        threading.Thread(target=self.run_search,
                         args=(query,), daemon=True).start()

    def run_search(self, query):
        """The actual search logic."""
        try:
            response = requests.post(SEARCH_URL, json={'query': query})

            if response.status_code == 200:
                results = response.json()
                self.after(0, self.display_search_results, results)
            else:
                error_msg = response.json().get('error', 'Unknown server error')
                # Use lambda to correctly pass the keyword argument
                self.after(0, lambda: self.display_error(
                    error_msg, is_search=True))

        except requests.exceptions.ConnectionError:
            # Use lambda here too
            self.after(0, lambda: self.display_error(
                "Error: Could not connect to MetaTrack server.", is_search=True))

        except Exception as e:
            # And use lambda here
            self.after(0, lambda: self.display_error(
                f"An unknown error occurred: {e}", is_search=True))

    def display_error(self, message, is_search=False):
        if is_search:
            for widget in self.search_results_frame.winfo_children():
                widget.destroy()
            self.search_status_label.configure(text=message, text_color="red")
            self.search_button.configure(state="normal")
        else:
            self.recent_label.configure(text=message, text_color="red")
            self.popular_label.configure(text="")

    def display_search_results(self, results):
        for widget in self.search_results_frame.winfo_children():
            widget.destroy()
        self.search_button.configure(state="normal")
        if not results:
            self.search_status_label.configure(
                text="No results found.", text_color="gray")
            return
        self.search_status_label.configure(
            text=f"Found {len(results)} matching files.", text_color="green")
        for i, res in enumerate(results):
            self.create_file_widget(self.search_results_frame, res, i)


if __name__ == "__main__":
    app = App()
    app.mainloop()
