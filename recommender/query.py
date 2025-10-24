# Simple CLI for querying the vector store
import config
from tracker.embedder import Embedder
from tracker.vectorstore import SimpleVectorStore
from tracker.metadata_db import MetadataDB


def semantic_query(query_text, top_k=5):
    embedder = Embedder(backend=config.EMBEDDING_BACKEND)
    vstore = SimpleVectorStore(path=config.EMBEDDINGS_PATH)
    db = MetadataDB(config.DB_PATH)
    qemb = embedder.embed(query_text)
    results = vstore.query(qemb, top_k=top_k)
    out = []
    for r in results:
        m = db.get(r['id'])
        out.append({'path': r['id'], 'score': r['score'], 'meta': m})
    return out


if __name__ == '__main__':
    import sys
    q = ' '.join(sys.argv[1:]) if len(sys.argv) > 1 else input('Query: ')
    res = semantic_query(q)
    for r in res:
        print(r['score'], r['path'])
