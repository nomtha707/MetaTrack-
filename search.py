# search.py (Find-Only Chatbot Client)
import requests
import sys

SERVER_URL = "http://127.0.0.1:5000/search"


def check_server():
    """Checks if the MetaTrack server is running."""
    try:
        requests.head("http://127.0.0.1:5000", timeout=1)
        return True
    except requests.exceptions.ConnectionError:
        return False


def search_metatrack(query_text):
    """Sends the query to the server."""
    try:
        # We no longer send "mode". The server will just do "find".
        response = requests.post(SERVER_URL, json={'query': query_text})

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

    print("MetaTrack Search is ready.")
    print("-" * 40)

    while True:
        # --- Simplified: No more F/A prompt ---
        query_text = input("Enter your search query (or 'q' to quit): ")
        if query_text.lower() == 'q':
            break
        if not query_text.strip():
            continue

        # --- Send Request ---
        results = search_metatrack(query_text)

        if not results:
            print("No results found.\n")
            continue

        print("\n" + "=" * 20 + " RESULTS " + "=" * 20)

        # --- Simplified: We only get one type of response now ---
        print(f"\nANSWER:\n{results.get('answer')}\n")
        print(f"Source: {results.get('source', 'N/A')}")
        print("\n" + "=" * 49)

    print("Goodbye!")
