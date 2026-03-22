"""
Parent-Child Indexing Strategy

Stores two types of vectors:
1. Child Chunks: Small, granular pieces (best for exact matching)
2. Parent Chunks: Entire function/class containing the child (provides deep context)

Search Flow: Search for child, but feed entire parent to LLM
"""

import logging
from typing import List, Dict, Optional
from dataclasses import dataclass

logger = logging.getLogger("parent_child_indexing")


@dataclass
class ParentChildChunk:
    """Represents a chunk with parent context"""
    child_code: str  # The granular chunk (for embedding/search)
    parent_code: str  # The full parent context (for LLM)
    child_metadata: Dict
    parent_metadata: Dict
    chunk_type: str  # 'function', 'class', 'method', 'block'
    start_line: int
    end_line: int


class ParentChildIndexer:
    """
    Creates parent-child chunk relationships
    
    Strategy:
    1. Parse code into structural chunks (functions, classes)
    2. For each chunk, create:
       - Child: The chunk itself (for precise matching)
       - Parent: The chunk + its imports + surrounding context
    3. Store both with relationship metadata
    """
    
    def __init__(self, parent_context_lines: int = 10):
        """
        Args:
            parent_context_lines: Number of lines before/after to include in parent
        """
        self.parent_context_lines = parent_context_lines
    
    def create_parent_child_chunks(
        self,
        content: str,
        language: str,
        file_path: str,
        repo_name: str
    ) -> List[ParentChildChunk]:
        """
        Create parent-child chunk pairs from code
        
        Args:
            content: Full file content
            language: Programming language
            file_path: Relative file path
            repo_name: Repository name
            
        Returns:
            List of ParentChildChunk objects
        """
        from .ast_chunker import ASTChunker
        
        chunker = ASTChunker()
        ast_chunks = chunker.chunk(content, language)
        
        lines = content.split('\n')
        parent_child_chunks = []
        
        for ast_chunk in ast_chunks:
            # Child: The AST chunk itself
            child_code = ast_chunk['code']
            child_start = ast_chunk['start_line'] - 1  # Convert to 0-indexed
            child_end = ast_chunk['end_line']  # Already 1-indexed
            
            # Parent: Child + surrounding context + imports
            parent_start = max(0, child_start - self.parent_context_lines)
            parent_end = min(len(lines), child_end + self.parent_context_lines)
            
            # Include imports/package declarations at the top
            import_lines = self._extract_imports(lines, language)
            
            # Build parent code
            parent_lines = []
            
            # Add imports first
            if import_lines:
                parent_lines.extend(import_lines)
                parent_lines.append("")  # Blank line separator
            
            # Add context before child
            if parent_start < child_start:
                parent_lines.extend(lines[parent_start:child_start])
            
            # Add child code
            parent_lines.extend(lines[child_start:child_end])
            
            # Add context after child
            if child_end < parent_end:
                parent_lines.extend(lines[child_end:parent_end])
            
            parent_code = '\n'.join(parent_lines)
            
            # Create metadata
            child_metadata = {
                'repo': repo_name,
                'file': file_path,
                'language': language,
                'chunk_type': ast_chunk['type'],
                'is_child': True,
                'start_line': ast_chunk['start_line'],
                'end_line': ast_chunk['end_line'],
                'parent_start_line': parent_start + 1,
                'parent_end_line': parent_end
            }
            
            parent_metadata = {
                'repo': repo_name,
                'file': file_path,
                'language': language,
                'chunk_type': ast_chunk['type'],
                'is_parent': True,
                'child_start_line': ast_chunk['start_line'],
                'child_end_line': ast_chunk['end_line'],
                'includes_imports': bool(import_lines),
                'context_lines': self.parent_context_lines
            }
            
            parent_child_chunk = ParentChildChunk(
                child_code=child_code,
                parent_code=parent_code,
                child_metadata=child_metadata,
                parent_metadata=parent_metadata,
                chunk_type=ast_chunk['type'],
                start_line=ast_chunk['start_line'],
                end_line=ast_chunk['end_line']
            )
            
            parent_child_chunks.append(parent_child_chunk)
        
        logger.info(
            f"Created {len(parent_child_chunks)} parent-child chunk pairs "
            f"from {file_path}"
        )
        
        return parent_child_chunks
    
    def _extract_imports(self, lines: List[str], language: str) -> List[str]:
        """Extract import/package declarations from code"""
        imports = []
        
        if language == 'go':
            # Go: package declaration + imports
            for line in lines[:50]:  # Check first 50 lines
                stripped = line.strip()
                if stripped.startswith('package ') or stripped.startswith('import '):
                    imports.append(line)
                elif stripped.startswith('(') and 'import' in '\n'.join(lines[:lines.index(line)+5]):
                    # Multi-line import block
                    imports.append(line)
        
        elif language in ['py', 'python']:
            # Python: import statements
            for line in lines[:50]:
                stripped = line.strip()
                if stripped.startswith('import ') or stripped.startswith('from '):
                    imports.append(line)
        
        elif language in ['js', 'javascript', 'ts', 'typescript']:
            # JavaScript: import/require statements
            for line in lines[:50]:
                stripped = line.strip()
                if stripped.startswith('import ') or stripped.startswith('const ') and 'require' in stripped:
                    imports.append(line)
        
        return imports
    
    def get_parent_for_child(
        self,
        child_chunk_id: str,
        vector_db_collection
    ) -> Optional[str]:
        """
        Retrieve parent code for a child chunk ID
        
        Args:
            child_chunk_id: ID of the child chunk
            vector_db_collection: ChromaDB collection
            
        Returns:
            Parent code string or None
        """
        try:
            # Query for parent chunk linked to this child
            results = vector_db_collection.get(
                ids=[child_chunk_id],
                include=['metadatas']
            )
            
            if results['metadatas'] and results['metadatas'][0]:
                metadata = results['metadatas'][0]
                parent_start = metadata.get('parent_start_line')
                parent_end = metadata.get('parent_end_line')
                
                if parent_start and parent_end:
                    # Retrieve parent chunk
                    # Note: In real implementation, you'd store parent chunks separately
                    # and link them via metadata
                    parent_id = f"{child_chunk_id}_parent"
                    parent_results = vector_db_collection.get(
                        ids=[parent_id],
                        include=['documents']
                    )
                    
                    if parent_results['documents'] and parent_results['documents'][0]:
                        return parent_results['documents'][0]
            
            return None
            
        except Exception as e:
            logger.warning(f"Error retrieving parent for child {child_chunk_id}: {e}")
            return None
