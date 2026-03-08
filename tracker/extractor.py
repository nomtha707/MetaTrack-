import os
import logging
import fitz  
import docx
from rapidocr_onnxruntime import RapidOCR

fitz.TOOLS.mupdf_display_errors(False)

# The vital safety limit! ~800 words of context is plenty for the AI.
MAX_CHARS_TO_EXTRACT = 5000 

# Initialize the lightweight ONNX OCR reader lazily
_ocr_reader = None

def get_ocr_reader():
    global _ocr_reader
    if _ocr_reader is None:
        logging.info("Booting up Lightweight ONNX Vision Engine...")
        _ocr_reader = RapidOCR()
    return _ocr_reader

def extract_text(filepath: str) -> str:
    """Extracts text, using RapidOCR for images/scanned PDFs, optimized for CPUs."""
    if not os.path.exists(filepath):
        return ""
        
    ext = os.path.splitext(filepath)[1].lower()
    text = ""
    
    try:
        # --- TEXT, MARKDOWN, PYTHON, CSV ---
        if ext in ['.txt', '.md', '.py', '.csv']:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                text = f.read(MAX_CHARS_TO_EXTRACT)
                
        # --- WORD DOCUMENTS ---
        elif ext == '.docx':
            doc = docx.Document(filepath)
            paragraphs = []
            current_len = 0
            for p in doc.paragraphs:
                paragraphs.append(p.text)
                current_len += len(p.text)
                if current_len > MAX_CHARS_TO_EXTRACT:
                    break  
            text = "\n".join(paragraphs)
            
        # --- PDFs (Smart Reader + OCR) ---
        elif ext == '.pdf':
            doc = fitz.open(filepath)
            pages_text = []
            current_len = 0
            
            for page in doc:
                page_text = page.get_text("text").strip()
                
                # If there's standard digital text, use it
                if len(page_text) > 20:
                    pages_text.append(page_text)
                    current_len += len(page_text)
                else:
                    # Scanned image detected! Use RapidOCR.
                    logging.info(f"Scanned page detected in {os.path.basename(filepath)}. Running CPU OCR...")
                    pix = page.get_pixmap()
                    img_data = pix.tobytes("png")
                    
                    reader = get_ocr_reader()
                    # RapidOCR returns a tuple: (results, elapse_time)
                    result, _ = reader(img_data) 
                    
                    if result:
                        # Extract just the text strings from the result matrix
                        ocr_text = " ".join([item[1] for item in result])
                        pages_text.append(ocr_text)
                        current_len += len(ocr_text)
                
                if current_len > MAX_CHARS_TO_EXTRACT:
                    break 
                    
            text = "\n".join(pages_text)
                    
        # --- IMAGES (Standalone Screenshots) ---
        elif ext in ['.jpg', '.jpeg', '.png']:
            reader = get_ocr_reader()
            result, _ = reader(filepath)
            if result:
                text = " ".join([item[1] for item in result])

    except Exception as e:
        logging.error(f"Error extracting text from {filepath}: {e}")
        return ''
        
    return text[:MAX_CHARS_TO_EXTRACT].strip()