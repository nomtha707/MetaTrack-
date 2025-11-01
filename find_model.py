from sentence_transformers import SentenceTransformer
import os

# This is the public name of the model
model_name = 'all-MiniLM-L6-v2'

# This is the local folder it will be saved to.
# Your embedder.py script is built to look for this exact path.
save_path = 'model/all-MiniLM-L6-v2'

# Check if it already exists before downloading
if os.path.isdir(save_path):
    print(f"Model already exists at: {save_path}")
else:
    print(f"Downloading model '{model_name}' to '{save_path}'...")

    # Download the model from the internet
    model = SentenceTransformer(model_name)

    # Save it to the local folder
    model.save(save_path)

    print("Download complete.")
