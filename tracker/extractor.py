# tracker/extractor.py (High-Speed Optimized Version)
import os
from docx import Document
import fitz  
import logging

fitz.TOOLS.mupdf_display_errors(False)

# We set a limit: 5,000 characters is more than enough context 
# for all-MiniLM-L6-v2 to understand what the file is about.
MAX_CHARS_TO_EXTRACT = 5000 

def extract_text(filepath: str) -> str:
    ext = os.path.splitext(filepath)[1].lower()
    extracted_text = ""
    
    try:
        # --- TEXT, MARKDOWN, PYTHON, CSV ---
        if ext in ['.txt', '.md', '.py', '.csv']:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                # Only read the first chunk of the file directly
                extracted_text = f.read(MAX_CHARS_TO_EXTRACT)
                
        # --- WORD DOCUMENTS ---
        elif ext == '.docx':
            doc = Document(filepath)
            paragraphs = []
            current_len = 0
            for p in doc.paragraphs:
                paragraphs.append(p.text)
                current_len += len(p.text)
                if current_len > MAX_CHARS_TO_EXTRACT:
                    break  # Stop parsing the Word doc early
            extracted_text = "\n".join(paragraphs)

        # --- PDFs (Using Blazing Fast PyMuPDF) ---
        elif ext == '.pdf':
            pages_text = []
            current_len = 0
            with fitz.open(filepath) as pdf:
                for page in pdf:
                    text = page.get_text("text")
                    if text:
                        pages_text.append(text)
                        current_len += len(text)
                    
                    if current_len > MAX_CHARS_TO_EXTRACT:
                        break  # Stop reading pages once we hit the limit!
                        
            extracted_text = "\n".join(pages_text)
            
        else:
            return ''

        # Final safety truncation
        return extracted_text[:MAX_CHARS_TO_EXTRACT]

    except Exception as e:
        logging.error(f"Error extracting {filepath}: {e}")
        return ''