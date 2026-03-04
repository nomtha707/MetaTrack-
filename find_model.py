# find_model.py
from sentence_transformers import SentenceTransformer
import os

# Dictionary of our two brains: (Model Name on HuggingFace, Local Folder Path)
models = {
    'text': ('all-MiniLM-L6-v2', 'model/all-MiniLM-L6-v2'),
    'image': ('clip-ViT-B-32', 'model/clip-ViT-B-32') # The CLIP model
}

for model_type, (model_name, save_path) in models.items():
    if os.path.isdir(save_path):
        print(f"[{model_type.upper()}] Model already exists at: {save_path}")
    else:
        print(f"[{model_type.upper()}] Downloading '{model_name}' to '{save_path}'...")
        # Download and save
        model = SentenceTransformer(model_name)
        model.save(save_path)
        print(f"[{model_type.upper()}] Download complete.\n")