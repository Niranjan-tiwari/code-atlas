"""
AST-Based Code Chunking using tree-sitter

Splits code based on actual syntax structure (functions, classes, methods)
rather than arbitrary line boundaries. Prevents functions from being cut in half.
"""

import logging
from typing import List, Dict, Tuple, Optional
from pathlib import Path

logger = logging.getLogger("ast_chunker")


class ASTChunker:
    """
    AST-based code chunker using tree-sitter
    
    Supports:
    - Go (tree-sitter-go)
    - Python (tree-sitter-python)
    - JavaScript/TypeScript (tree-sitter-javascript)
    - Java (tree-sitter-java)
    """
    
    def __init__(self):
        self.parsers = {}
        self._init_parsers()
    
    def _init_parsers(self):
        """Initialize tree-sitter parsers for supported languages"""
        try:
            from tree_sitter import Language, Parser
            
            # Try to load tree-sitter languages
            # Note: Requires building tree-sitter languages first
            # See: https://github.com/tree-sitter/py-tree-sitter
            
            # For now, we'll use a fallback approach
            # Users need to build tree-sitter languages separately
            self.use_tree_sitter = False
            
            # Try to import pre-built languages if available
            try:
                # This would work if tree-sitter languages are installed
                # go_lang = Language('build/my-languages.so', 'go')
                # self.parsers['go'] = Parser(go_lang)
                # self.use_tree_sitter = True
                pass
            except Exception as e:
                logger.debug(f"Tree-sitter not available, using regex fallback: {e}")
                
        except ImportError:
            logger.warning("tree-sitter not installed. Install with: pip install tree-sitter")
            logger.warning("Falling back to regex-based AST chunking")
            self.use_tree_sitter = False
    
    def chunk(
        self,
        content: str,
        language: str,
        max_chunk_size: int = 1000,
        min_chunk_size: int = 100
    ) -> List[Dict]:
        """
        Chunk code using AST parsing
        
        Returns:
            List of chunk dicts with:
            - code: The code chunk
            - type: 'function', 'class', 'method', 'block'
            - start_line: Starting line number
            - end_line: Ending line number
            - parent: Parent context (if available)
        """
        if self.use_tree_sitter and language in self.parsers:
            return self._chunk_with_tree_sitter(content, language, max_chunk_size)
        else:
            # Fallback to regex-based AST chunking
            return self._chunk_with_regex(content, language, max_chunk_size, min_chunk_size)
    
    def _chunk_with_tree_sitter(
        self,
        content: str,
        language: str,
        max_chunk_size: int
    ) -> List[Dict]:
        """Chunk using tree-sitter parser"""
        parser = self.parsers[language]
        tree = parser.parse(bytes(content, 'utf8'))
        
        chunks = []
        lines = content.split('\n')
        
        def traverse(node, parent_type=None):
            """Traverse AST and extract chunks"""
            node_type = node.type
            
            # Extract function/class/method nodes
            if node_type in ['function_declaration', 'method_declaration', 
                           'class_declaration', 'function_definition', 'class_definition']:
                chunk_code = content[node.start_byte:node.end_byte]
                
                if len(chunk_code) <= max_chunk_size:
                    chunks.append({
                        'code': chunk_code,
                        'type': node_type,
                        'start_line': node.start_point[0] + 1,
                        'end_line': node.end_point[0] + 1,
                        'parent': parent_type
                    })
                else:
                    # If too large, try to split by inner blocks
                    for child in node.children:
                        traverse(child, node_type)
            else:
                # Continue traversing
                for child in node.children:
                    traverse(child, parent_type or node_type)
        
        traverse(tree.root_node)
        return chunks
    
    def _chunk_with_regex(
        self,
        content: str,
        language: str,
        max_chunk_size: int,
        min_chunk_size: int
    ) -> List[Dict]:
        """
        Regex-based AST chunking (fallback when tree-sitter unavailable)
        
        Uses language-specific patterns to detect functions/classes
        """
        lines = content.split('\n')
        chunks = []
        
        if language == 'go':
            return self._chunk_go_regex(content, lines, max_chunk_size, min_chunk_size)
        elif language in ['py', 'python']:
            return self._chunk_python_regex(content, lines, max_chunk_size, min_chunk_size)
        elif language in ['js', 'javascript', 'ts', 'typescript']:
            return self._chunk_js_regex(content, lines, max_chunk_size, min_chunk_size)
        else:
            # Generic chunking
            return self._chunk_generic(content, lines, max_chunk_size, min_chunk_size)
    
    def _chunk_go_regex(
        self,
        content: str,
        lines: List[str],
        max_chunk_size: int,
        min_chunk_size: int
    ) -> List[Dict]:
        """Chunk Go code by detecting function boundaries"""
        import re
        
        chunks = []
        current_chunk = []
        current_start = 0
        brace_count = 0
        in_function = False
        
        for i, line in enumerate(lines):
            stripped = line.strip()
            
            # Skip empty lines and comments at start
            if not stripped or stripped.startswith('//') or stripped.startswith('package ') or stripped.startswith('import '):
                if not in_function:
                    continue
            
            # Detect function start (more flexible pattern)
            func_match = (
                re.match(r'^func\s+(\([^)]+\)\s+)?([a-zA-Z_][a-zA-Z0-9_]*)\s*\(', stripped) or
                re.match(r'^func\s+\([^)]+\)\s+[a-zA-Z_][a-zA-Z0-9_]*\s*\(', stripped) or
                (stripped.startswith('func ') and '(' in stripped)
            )
            if func_match:
                # Save previous chunk if exists
                if current_chunk and in_function:
                    chunk_code = '\n'.join(current_chunk)
                    if min_chunk_size <= len(chunk_code) <= max_chunk_size:
                        chunks.append({
                            'code': chunk_code,
                            'type': 'function',
                            'start_line': current_start + 1,
                            'end_line': i,
                            'parent': None
                        })
                
                # Start new chunk
                current_chunk = [line]
                current_start = i
                in_function = True
                brace_count = line.count('{') - line.count('}')
            elif in_function:
                current_chunk.append(line)
                brace_count += line.count('{') - line.count('}')
                
                # Function ends when braces balance
                if brace_count == 0:
                    chunk_code = '\n'.join(current_chunk)
                    if min_chunk_size <= len(chunk_code) <= max_chunk_size:
                        chunks.append({
                            'code': chunk_code,
                            'type': 'function',
                            'start_line': current_start + 1,
                            'end_line': i + 1,
                            'parent': None
                        })
                    current_chunk = []
                    in_function = False
        
        # Add remaining chunk
        if current_chunk and in_function:
            chunk_code = '\n'.join(current_chunk)
            if len(chunk_code) >= min_chunk_size:
                chunks.append({
                    'code': chunk_code,
                    'type': 'function',
                    'start_line': current_start + 1,
                    'end_line': len(lines),
                    'parent': None
                })
        
        return chunks
    
    def _chunk_python_regex(
        self,
        content: str,
        lines: List[str],
        max_chunk_size: int,
        min_chunk_size: int
    ) -> List[Dict]:
        """Chunk Python code by detecting function/class boundaries"""
        import re
        
        chunks = []
        current_chunk = []
        current_start = 0
        indent_level = 0
        in_block = False
        
        for i, line in enumerate(lines):
            stripped = line.strip()
            
            # Detect function/class definition
            func_match = re.match(r'^(def|class)\s+([a-zA-Z_][a-zA-Z0-9_]*)', stripped)
            if func_match:
                # Save previous chunk
                if current_chunk and in_block:
                    chunk_code = '\n'.join(current_chunk)
                    if min_chunk_size <= len(chunk_code) <= max_chunk_size:
                        chunks.append({
                            'code': chunk_code,
                            'type': 'function' if 'def' in current_chunk[0] else 'class',
                            'start_line': current_start + 1,
                            'end_line': i,
                            'parent': None
                        })
                
                # Start new chunk
                current_chunk = [line]
                current_start = i
                in_block = True
                indent_level = len(line) - len(line.lstrip())
            elif in_block:
                # Check if we're still in the same block (same or deeper indent)
                current_indent = len(line) - len(line.lstrip()) if line.strip() else indent_level + 1
                
                if line.strip() and current_indent <= indent_level and not line.strip().startswith('#'):
                    # Block ended
                    chunk_code = '\n'.join(current_chunk)
                    if min_chunk_size <= len(chunk_code) <= max_chunk_size:
                        chunks.append({
                            'code': chunk_code,
                            'type': 'function',
                            'start_line': current_start + 1,
                            'end_line': i,
                            'parent': None
                        })
                    current_chunk = []
                    in_block = False
                else:
                    current_chunk.append(line)
        
        # Add remaining chunk
        if current_chunk and in_block:
            chunk_code = '\n'.join(current_chunk)
            if len(chunk_code) >= min_chunk_size:
                chunks.append({
                    'code': chunk_code,
                    'type': 'function',
                    'start_line': current_start + 1,
                    'end_line': len(lines),
                    'parent': None
                })
        
        return chunks
    
    def _chunk_js_regex(
        self,
        content: str,
        lines: List[str],
        max_chunk_size: int,
        min_chunk_size: int
    ) -> List[Dict]:
        """Chunk JavaScript/TypeScript code"""
        import re
        
        chunks = []
        current_chunk = []
        current_start = 0
        brace_count = 0
        in_function = False
        
        for i, line in enumerate(lines):
            stripped = line.strip()
            
            # Detect function/class/method
            func_match = re.match(
                r'^(function|const\s+\w+\s*=\s*\(|class\s+\w+|async\s+function|export\s+(function|class))',
                stripped
            )
            if func_match:
                if current_chunk and in_function:
                    chunk_code = '\n'.join(current_chunk)
                    if min_chunk_size <= len(chunk_code) <= max_chunk_size:
                        chunks.append({
                            'code': chunk_code,
                            'type': 'function',
                            'start_line': current_start + 1,
                            'end_line': i,
                            'parent': None
                        })
                
                current_chunk = [line]
                current_start = i
                in_function = True
                brace_count = line.count('{') - line.count('}')
            elif in_function:
                current_chunk.append(line)
                brace_count += line.count('{') - line.count('}')
                
                if brace_count == 0:
                    chunk_code = '\n'.join(current_chunk)
                    if min_chunk_size <= len(chunk_code) <= max_chunk_size:
                        chunks.append({
                            'code': chunk_code,
                            'type': 'function',
                            'start_line': current_start + 1,
                            'end_line': i + 1,
                            'parent': None
                        })
                    current_chunk = []
                    in_function = False
        
        if current_chunk and in_function:
            chunk_code = '\n'.join(current_chunk)
            if len(chunk_code) >= min_chunk_size:
                chunks.append({
                    'code': chunk_code,
                    'type': 'function',
                    'start_line': current_start + 1,
                    'end_line': len(lines),
                    'parent': None
                })
        
        return chunks
    
    def _chunk_generic(
        self,
        content: str,
        lines: List[str],
        max_chunk_size: int,
        min_chunk_size: int
    ) -> List[Dict]:
        """Generic line-based chunking"""
        chunks = []
        current_chunk = []
        current_length = 0
        current_start = 0
        
        for i, line in enumerate(lines):
            line_length = len(line) + 1
            
            if current_length + line_length > max_chunk_size and current_chunk:
                chunk_code = '\n'.join(current_chunk)
                if len(chunk_code) >= min_chunk_size:
                    chunks.append({
                        'code': chunk_code,
                        'type': 'block',
                        'start_line': current_start + 1,
                        'end_line': i,
                        'parent': None
                    })
                current_chunk = [line]
                current_length = line_length
                current_start = i
            else:
                current_chunk.append(line)
                current_length += line_length
        
        if current_chunk:
            chunk_code = '\n'.join(current_chunk)
            if len(chunk_code) >= min_chunk_size:
                chunks.append({
                    'code': chunk_code,
                    'type': 'block',
                    'start_line': current_start + 1,
                    'end_line': len(lines),
                    'parent': None
                })
        
        return chunks
