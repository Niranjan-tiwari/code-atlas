"""
Vector database for code indexing and search (Qdrant embedded, on-disk).
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional

from .vector_backend import vector_db_path
from .qdrant_rag_support import ensure_qdrant_collection, qdrant_upsert_points


class VectorDB:
    """Qdrant-backed vector store for code chunks."""

    def __init__(
        self,
        persist_directory: Optional[str] = None,
        collection_name: str = "code_snippets",
    ):
        self.persist_directory = Path(persist_directory or vector_db_path())
        self.persist_directory.mkdir(parents=True, exist_ok=True)
        self.collection_name = collection_name
        self.logger = logging.getLogger("vector_db")

        self._emb_fn = None
        try:
            from src.ai.embeddings.ollama_embed import get_best_embedding_function

            self._emb_fn = get_best_embedding_function()
        except Exception:
            pass

        if self._emb_fn is None:
            from src.ai.embeddings.ollama_embed import SentenceTransformerEmbedding

            emb = SentenceTransformerEmbedding("default")
            emb._load()
            self._emb_fn = emb

        emb_name = getattr(self._emb_fn, "model", getattr(self._emb_fn, "model_name", "default"))
        from .vector_backend import open_embedded_qdrant_client

        self.client = open_embedded_qdrant_client(str(self.persist_directory), mkdir=False)
        dim = self._embedding_dim()
        ensure_qdrant_collection(self.client, self.collection_name, dim)
        self.logger.info(
            f"Qdrant collection ready: {self.collection_name} (embedding: {emb_name}, dim={dim})"
        )

    def _embedding_dim(self) -> int:
        d = getattr(self._emb_fn, "dims", None)
        if d is not None:
            return int(d)
        v = self._emb_fn(["dim_probe"])
        if v and v[0]:
            return len(v[0])
        return 384

    def add_documents(
        self,
        documents: List[str],
        metadatas: Optional[List[Dict]] = None,
        ids: Optional[List[str]] = None,
    ):
        if not documents:
            return
        if ids is None:
            ids = [f"doc_{i}" for i in range(len(documents))]
        if metadatas is None:
            metadatas = [{}] * len(documents)

        vectors = self._emb_fn(documents)
        qdrant_upsert_points(
            self.client,
            self.collection_name,
            documents,
            vectors,
            metadatas,
            ids,
        )
        self.logger.info(f"Added {len(documents)} documents to {self.collection_name}")

    def search(
        self,
        query: str,
        n_results: int = 5,
        where: Optional[Dict] = None,
    ) -> List[Dict]:
        from .qdrant_rag_support import (
            client_query_vectors,
            scored_to_distance,
            where_dict_to_filter,
        )

        qe = self._emb_fn([query])
        flt = where_dict_to_filter(where)
        hits = client_query_vectors(
            self.client,
            self.collection_name,
            qe[0],
            n_results,
            flt,
            with_payload=True,
        )
        out = []
        for hit in hits:
            p = dict(hit.payload or {})
            doc = p.pop("document", "")
            out.append(
                {
                    "document": doc,
                    "metadata": p,
                    "distance": scored_to_distance(hit.score),
                    "id": str(hit.id),
                }
            )
        self.logger.info(f"Search returned {len(out)} results")
        return out

    def get_collection_info(self) -> Dict:
        try:
            count = int(self.client.count(self.collection_name, exact=True).count)
            return {
                "name": self.collection_name,
                "count": count,
                "persist_directory": str(self.persist_directory),
                "backend": "qdrant",
            }
        except Exception as e:
            self.logger.error(f"Error getting collection info: {e}")
            return {"name": self.collection_name, "count": 0, "backend": "qdrant"}

    def delete_collection(self):
        try:
            self.client.delete_collection(collection_name=self.collection_name)
            self.logger.warning(f"Deleted collection: {self.collection_name}")
        except Exception as e:
            self.logger.error(f"Error deleting collection: {e}")


def test_vector_db():
    print("🧪 Testing Vector DB...")
    db = VectorDB(collection_name="test_snippets_tmp")
    test_docs = [
        "def add_logging(message):\n    logger.info(message)",
        "def handle_error(error):\n    logger.error(error)",
        "def process_data(data):\n    return data.process()",
    ]
    test_metadata = [
        {"repo": "test", "file": "test1.py"},
        {"repo": "test", "file": "test2.py"},
        {"repo": "test", "file": "test3.py"},
    ]
    db.add_documents(test_docs, test_metadata)
    results = db.search("logging function", n_results=2)
    print(f"✅ Found {len(results)} results")
    for i, result in enumerate(results, 1):
        print(f"\n{i}. {result['document'][:50]}...")
        print(f"   Metadata: {result['metadata']}")
    info = db.get_collection_info()
    print(f"\n📊 Collection: {info['name']}, Documents: {info['count']}")
    db.delete_collection()
    print("\n✅ Vector DB test passed!")


if __name__ == "__main__":
    test_vector_db()
