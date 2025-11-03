# search.py (Full RAG Client)
import requests
import sys

SERVER_URL = "http://127.0.0.1:5000/search"


def check_server():
    try:
        requests.head("http://127.0.0.1:5000", timeout=1)
        return True
    except requests.exceptions.ConnectionError:
        return False


def search_metatrack(query_text, mode):
    """Sends the query and mode to the server."""
    try:
        response = requests.post(
            SERVER_URL, json={'query': query_text, 'mode': mode})

        if response.status_code == 200:
            return response.json()
        else:
            print(f"Error from server: {response.json().get('error')}")
            return None

    except requests.exceptions.ConnectionError:
        print("Error: Could not connect to the MetaTrack server.")
        return None
    except Exception as e:
        print(f"An unknown error occurred: {e}")
        return None


# --- Main search loop ---
if __name__ == "__main__":
    if not check_server():
        print("Error: The MetaTrack server (watcher.py) is not running.")
        sys.exit(1)

    print("MetaTrack RAG Search is ready.")
    print("Type 'q' to quit at any time.")
    print("-" * 40)

    while True:
        # --- NEW: Get Mode ---
        mode_input = input(
            "Do you want to [F]ind files or [A]sk a question? (F/A): ").lower()
        if mode_input == 'q':
            break
        if mode_input not in ['f', 'a']:
            print("Invalid mode. Please enter 'F' or 'A'.")
            continue

        mode = "find" if mode_input == 'f' else "ask"

        # --- Get Query ---
        query_text = input("Enter your query: ")
        if query_text.lower() == 'q':
            break
        if not query_text.strip():
            continue

        # --- Send Request ---
        results = search_metatrack(query_text, mode)

        if not results:
            print("No results found.\n")
            continue

        print("\n" + "=" * 20 + " RESULTS " + "=" * 20)

        # --- NEW: Handle different response types ---

        if mode == "find":
            # This is a LIST of files
            print(f"Found {len(results)} matching files:\n")
            for res in results:
                print(f"  File:          {res.get('name', 'N/A')}")
                print(f"  Path:          {res.get('path', 'N/A')}")
                if 'score' in res:
                    print(f"  Match Score:   {res['score']:.4f}")
                if 'modified_at' in res:
                    print(f"  Last Modified: {res['modified_at']}")
                print("-" * 14 + "\n")

        elif mode == "ask":
            # This is a DICTIONARY with an answer
            print(f"\nANSWER:\n{results.get('answer')}\n")
            print(f"Source: {results.get('source')}")
            print("\n" + "=" * 49)

    print("Goodbye!")
