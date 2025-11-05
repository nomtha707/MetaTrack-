# app.py (Beautified GUI Client)
import customtkinter as ctk
import requests
import os
import sys
import threading

# --- SERVER SETTINGS ---
SERVER_URL = "http://127.0.0.1:5000/search"

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
        self.title("MetaTrack Search")
        self.geometry("800x600")  # Made window a bit bigger
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)  # Row 2 (results) will expand

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        # --- Define Fonts ---
        self.link_font = ctk.CTkFont(family="Arial", size=16, weight="bold")
        self.path_font = ctk.CTkFont(family="Arial", size=12, slant="italic")
        self.info_font = ctk.CTkFont(family="Arial", size=12, weight="bold")
        self.status_font = ctk.CTkFont(family="Arial", size=12)

        # --- 1. Top Frame (Query) ---
        self.top_frame = ctk.CTkFrame(self, corner_radius=0)
        self.top_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=10)
        self.top_frame.grid_columnconfigure(
            0, weight=1)  # Entry box will expand

        self.entry = ctk.CTkEntry(
            self.top_frame,
            placeholder_text="Enter your query...",
            height=35,
            font=("Arial", 14)
        )
        self.entry.grid(row=0, column=0, sticky="ew", padx=10, pady=10)
        self.entry.bind("<Return>", self.search_event)  # Bind Enter key

        self.search_button = ctk.CTkButton(
            self.top_frame,
            text="Search",
            command=self.search_event,
            height=35
        )
        self.search_button.grid(row=0, column=1, padx=(0, 10), pady=10)

        # --- NEW: Clear Button ---
        self.clear_button = ctk.CTkButton(
            self.top_frame,
            text="Clear",
            command=self.clear_results_event,
            height=35,
            fg_color="gray"
        )
        self.clear_button.grid(row=0, column=2, padx=(0, 10), pady=10)

        # --- 2. Status Bar ---
        self.status_label = ctk.CTkLabel(
            self, text="Ready. (Make sure MetaTrack.exe is running!)", text_color="gray", font=self.status_font)
        self.status_label.grid(row=1, column=0, sticky="ew", padx=20, pady=0)

        # --- 3. Results Frame (Scrollable) ---
        self.scrollable_frame = ctk.CTkScrollableFrame(self)
        self.scrollable_frame.grid(
            row=2, column=0, sticky="nsew", padx=10, pady=10)
        self.scrollable_frame.grid_columnconfigure(0, weight=1)

    def search_event(self, event=None):
        """Starts the search in a new thread."""
        query = self.entry.get()
        if not query:
            return

        self.status_label.configure(text="Searching...", text_color="yellow")
        self.search_button.configure(state="disabled")
        self.clear_button.configure(state="disabled")

        threading.Thread(target=self.run_search,
                         args=(query,), daemon=True).start()

    def run_search(self, query):
        """The actual search logic."""
        try:
            response = requests.post(SERVER_URL, json={'query': query})

            if response.status_code == 200:
                results = response.json()
                self.after(0, self.display_results, results)
            else:
                error_msg = response.json().get('error', 'Unknown server error')
                self.after(0, self.display_error, error_msg)

        except requests.exceptions.ConnectionError:
            self.after(0, self.display_error,
                       "Error: Could not connect to MetaTrack server. Is it running?")
        except Exception as e:
            self.after(0, self.display_error,
                       f"An unknown error occurred: {e}")

    def clear_results(self):
        """Clears all widgets from the scrollable frame."""
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()

    def clear_results_event(self):
        """Called by the 'Clear' button."""
        self.clear_results()
        self.entry.delete(0, 'end')
        self.status_label.configure(text="Ready.", text_color="gray")

    def display_error(self, message):
        """Displays an error message in the status bar."""
        self.clear_results()
        self.status_label.configure(text=message, text_color="red")
        self.search_button.configure(state="normal")
        self.clear_button.configure(state="normal")

    def display_results(self, results):
        """Displays the results in the scrollable frame."""
        self.clear_results()
        self.search_button.configure(state="normal")
        self.clear_button.configure(state="normal")

        if not results:
            self.status_label.configure(
                text="No results found.", text_color="gray")
            return

        self.status_label.configure(
            text=f"Found {len(results)} matching files.", text_color="green")

        for i, res in enumerate(results):
            path = res.get('path', 'N/A')
            name = res.get('name', 'N/A')

            res_frame = ctk.CTkFrame(self.scrollable_frame, fg_color="gray14")
            res_frame.grid(row=i, column=0, sticky="ew", pady=(0, 8))
            res_frame.grid_columnconfigure(0, weight=1)

            # 1. The File Name (Clickable to open file)
            name_label = ctk.CTkLabel(
                res_frame,
                text=name,
                text_color="#6495ED",  # Cornflower blue
                cursor="hand2",
                anchor="w",
                font=self.link_font  # Apply new font
            )
            name_label.grid(row=0, column=0, sticky="w", padx=10, pady=(10, 0))
            name_label.bind("<Button-1>", lambda e, p=path: open_file(p))

            # 2. The Path (Clickable to open folder)
            path_label = ctk.CTkLabel(
                res_frame,
                text=os.path.dirname(path),  # Show just the folder
                text_color="gray",
                cursor="hand2",
                anchor="w",
                font=self.path_font  # Apply new font
            )
            path_label.grid(row=1, column=0, sticky="w", padx=10, pady=(0, 5))
            path_label.bind("<Button-1>", lambda e, p=path: open_folder(p))

            # 3. The Score/Date
            info_text = ""
            if 'score' in res:
                info_text += f"Score: {res['score']:.2f}  "
            if 'modified_at' in res:
                # Just the date
                info_text += f"Modified: {res['modified_at'].split('T')[0]}"

            info_label = ctk.CTkLabel(
                res_frame, text=info_text, anchor="w", text_color="gray", font=self.info_font)
            info_label.grid(row=2, column=0, sticky="w", padx=10, pady=(0, 10))


if __name__ == "__main__":
    app = App()
    app.mainloop()
