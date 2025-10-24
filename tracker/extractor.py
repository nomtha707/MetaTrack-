import os
from docx import Document
import io
try:
    import pdfplumber
except Exception:
    pdfplumber = None

# lightweight text extraction for common types.


def extract_text(filepath: str) -> str:
    ext = os.path.splitext(filepath)[1].lower()
    try:
        if ext in ['.txt', '.md', '.py', '.csv']:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                return f.read()
        elif ext == '.docx':
            doc = Document(filepath)
            return "\n".join(p.text for p in doc.paragraphs)
        elif ext == '.pdf' and pdfplumber is not None:
            text = []
            with pdfplumber.open(filepath) as pdf:
                for page in pdf.pages:
                    p = page.extract_text()
                    if p:
                        text.append(p)
            return "\n".join(text)
        else:
            # unknown type - try binary -> no text
            return ''
    except Exception as e:
        print(f"Error extracting {filepath}: {e}")
        return ''
