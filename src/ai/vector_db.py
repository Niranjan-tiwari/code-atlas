"""
Vector Database wrapper using ChromaDB
Indexes code and enables similarity search
"""

import os
import logging
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import chromadb
from chromadb.config import Settings


class VectorDB:
    """Vector database for code indexing and search"""
    
    def __init__(self, persist_directory: str = "./data/vector_db", collection_name: str = "code_snippets"):
        """
        Initialize vector database
        
        Args:
            persist_directory: Directory to persist data
            collection_name: Name of the collection
        """
        self.persist_directory = Path(persist_directory)
        self.persist_directory.mkdir(parents=True, exist_ok=True)
        
        self.collection_name = collection_name
        self.logger = logging.getLogger("vector_db")
        
        # Get best embedding function (Ollama bge-m3 if available)
        self._emb_fn = None
        try:
            from src.ai.embeddings.ollama_embed import get_best_embedding_function
            self._emb_fn = get_best_embedding_function()
        except Exception:
            pass
        
        emb_name = getattr(self._emb_fn, 'model', 'default') if self._emb_fn else 'default'
        
        # Initialize ChromaDB client
        self.client = chromadb.PersistentClient(
            path=str(self.persist_directory),
            settings=Settings(anonymized_telemetry=False)
        )
        
        # Get or create collection
        try:
            self.collection = self.client.get_collection(
                name=collection_name,
                embedding_function=self._emb_fn
            )
            self.logger.info(f"Loaded existing collection: {collection_name} (embedding: {emb_name})")
        except Exception:
            self.collection = self.client.create_collection(
                name=collection_name,
                embedding_function=self._emb_fn,
                metadata={
                    "hnsw:space": "cosine",
                    "hnsw:construction_ef": 100,
                    "hnsw:M": 8
                }
            )
            self.logger.info(f"Created new collection: {collection_name} (embedding: {emb_name})")
    
    def add_documents(
        self,
        documents: List[str],
        metadatas: Optional[List[Dict]] = None,
        ids: Optional[List[str]] = None
    ):
        """
        Add documents to vector database
        
        Args:
            documents: List of text documents (code snippets)
            metadatas: List of metadata dicts (repo, file_path, etc.)
            ids: List of unique IDs
        """
        if not documents:
            return
        
        # Generate IDs if not provided
        if ids is None:
            ids = [f"doc_{i}" for i in range(len(documents))]
        
        # Default metadata if not provided
        if metadatas is None:
            metadatas = [{}] * len(documents)
        
        try:
            self.collection.add(
                documents=documents,
                metadatas=metadatas,
                ids=ids
            )
            self.logger.info(f"Added {len(documents)} documents to collection")
        except Exception as e:
            self.logger.error(f"Error adding documents: {e}")
            raise
    
    def search(
        self,
        query: str,
        n_results: int = 5,
        where: Optional[Dict] = None
    ) -> List[Dict]:
        """
        Search for similar documents
        
        Args:
            query: Search query text
            n_results: Number of results to return
            where: Metadata filter (e.g., {"repo": "webhook-generation"})
        
        Returns:
            List of result dicts with document, metadata, distance
        """
        try:
            results = self.collection.query(
                query_texts=[query],
                n_results=n_results,
                where=where
            )
            
            # Format results
            formatted_results = []
            if results['documents'] and len(results['documents'][0]) > 0:
                for i in range(len(results['documents'][0])):
                    formatted_results.append({
                        'document': results['documents'][0][i],
                        'metadata': results['metadatas'][0][i] if results['metadatas'] else {},
                        'distance': results['distances'][0][i] if results['distances'] else None,
                        'id': results['ids'][0][i] if results['ids'] else None
                    })
            
            self.logger.info(f"Search returned {len(formatted_results)} results")
            return formatted_results
        
        except Exception as e:
            self.logger.error(f"Error searching: {e}")
            return []
    
    def get_collection_info(self) -> Dict:
        """Get information about the collection"""
        try:
            count = self.collection.count()
            return {
                'name': self.collection_name,
                'count': count,
                'persist_directory': str(self.persist_directory)
            }
        except Exception as e:
            self.logger.error(f"Error getting collection info: {e}")
            return {'name': self.collection_name, 'count': 0}
    
    def delete_collection(self):
        """Delete the collection (use with caution!)"""
        try:
            self.client.delete_collection(name=self.collection_name)
            self.logger.warning(f"Deleted collection: {self.collection_name}")
        except Exception as e:
            self.logger.error(f"Error deleting collection: {e}")


def test_vector_db():
    """Simple test function"""
    print("🧪 Testing Vector DB...")
    
    # Create vector DB
    db = VectorDB()
    
    # Add test documents
    test_docs = [
        "def add_logging(message):\n    logger.info(message)",
        "def handle_error(error):\n    logger.error(error)",
        "def process_data(data):\n    return data.process()"
    ]
    
    test_metadata = [
        {"repo": "test", "file": "test1.py"},
        {"repo": "test", "file": "test2.py"},
        {"repo": "test", "file": "test3.py"}
    ]
    
    db.add_documents(test_docs, test_metadata)
    
    # Search
    results = db.search("logging function", n_results=2)
    
    print(f"✅ Found {len(results)} results")
    for i, result in enumerate(results, 1):
        print(f"\n{i}. {result['document'][:50]}...")
        print(f"   Metadata: {result['metadata']}")
    
    # Collection info
    info = db.get_collection_info()
    print(f"\n📊 Collection: {info['name']}, Documents: {info['count']}")
    
    print("\n✅ Vector DB test passed!")


if __name__ == "__main__":
    test_vector_db()
