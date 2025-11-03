# search.py (Client Version - Patched)
import requests
import sys

SERVER_URL = "http://127.0.0.1:5000/search"


def check_server():
    """Checks if the MetaTrack server is running."""
    try:
        # We use a HEAD request to '/' as a lightweight check
        response = requests.head("http://127.0.0.1:5000", timeout=1)
        return True
    except requests.exceptions.ConnectionError:
        return False


def search_metatrack(query_text):
    """Sends the query to the server and returns results."""
    try:
        response = requests.post(SERVER_URL, json={'query': query_text})

        if response.status_code == 200:
            return response.json()
        else:
            print(f"Error from server: {response.json().get('error')}")
            return None

    except requests.exceptions.ConnectionError:
        print("Error: Could not connect to the MetaTrack server.")
        print("Please make sure the watcher is running in another terminal.")
        return None
    except Exception as e:
        print(f"An unknown error occurred: {e}")
        return None


# --- Main search loop ---
if __name__ == "__main__":
    if not check_server():
        print("Error: The MetaTrack server (watcher.py) is not running.")
        print("Please start the watcher first in a separate terminal.")
        sys.exit(1)

    print("MetaTrack Search is ready.")
    print("-" * 40)

    while True:
        query_text = input("\nEnter your search query (or 'q' to quit): ")
        if query_text.lower() == 'q':
            break

        if not query_text.strip():
            continue

        results = search_metatrack(query_text)

        if not results:
            print("No matching files found.\n")
            continue

        print(f"\nFound {len(results)} matching files:\n")

        for res in results:
            print(f"--- Result ---")
            print(f"  File:          {res.get('name', 'N/A')}")
            print(f"  Path:          {res.get('path', 'N/A')}")

            # --- THIS IS THE FIX ---
            # Only print the score if it exists
            if 'score' in res:
                print(
                    f"  Match Score:   {res['score']:.4f} (higher is better)")

            if 'modified_at' in res:
                print(f"  Last Modified: {res['modified_at']}")
            if 'access_count' in res:
                print(f"  Access Count:  {res['access_count']}")

            print("-" * 14 + "\n")

    print("Goodbye!")
