"""
GraphRAG: Knowledge Graph Integration for Code

Code is naturally a graph:
- Files import other files
- Functions call other functions
- Classes extend other classes

GraphRAG enables multi-hop retrieval:
1. Find a function via vector search
2. Automatically "hop" to its imports
3. Pull in related definitions
4. Understand the full architecture
"""

import logging
import re
from typing import List, Dict, Set, Optional, Tuple
from collections import defaultdict

logger = logging.getLogger("graphrag")


class CodeGraph:
    """
    Knowledge graph of code relationships
    
    Nodes: Files, Functions, Classes
    Edges: Imports, Calls, Extends
    """
    
    def __init__(self):
        self.nodes: Dict[str, Dict] = {}  # node_id -> node_data
        self.edges: List[Tuple[str, str, str]] = []  # (from, to, relation_type)
        self.file_to_nodes: Dict[str, List[str]] = defaultdict(list)
    
    def add_file(self, file_path: str, repo: str, language: str):
        """Add a file node"""
        node_id = f"{repo}:{file_path}"
        self.nodes[node_id] = {
            'type': 'file',
            'file_path': file_path,
            'repo': repo,
            'language': language
        }
        self.file_to_nodes[file_path].append(node_id)
    
    def add_function(self, function_name: str, file_path: str, repo: str):
        """Add a function node"""
        node_id = f"{repo}:{file_path}:{function_name}"
        self.nodes[node_id] = {
            'type': 'function',
            'name': function_name,
            'file_path': file_path,
            'repo': repo
        }
        self.file_to_nodes[file_path].append(node_id)
    
    def add_import(self, from_file: str, to_file: str, repo: str):
        """Add an import edge"""
        from_id = f"{repo}:{from_file}"
        to_id = f"{repo}:{to_file}"
        
        if from_id in self.nodes and to_id in self.nodes:
            self.edges.append((from_id, to_id, 'imports'))
    
    def add_call(self, caller_file: str, caller_func: str, callee_file: str, callee_func: str, repo: str):
        """Add a function call edge"""
        caller_id = f"{repo}:{caller_file}:{caller_func}"
        callee_id = f"{repo}:{callee_file}:{callee_func}"
        
        if caller_id in self.nodes and callee_id in self.nodes:
            self.edges.append((caller_id, callee_id, 'calls'))
    
    def get_neighbors(self, node_id: str, relation_type: Optional[str] = None) -> List[str]:
        """Get neighboring nodes"""
        neighbors = []
        for from_node, to_node, rel_type in self.edges:
            if relation_type and rel_type != relation_type:
                continue
            if from_node == node_id:
                neighbors.append(to_node)
            elif to_node == node_id:
                neighbors.append(from_node)
        return neighbors
    
    def get_imports(self, file_path: str, repo: str) -> List[str]:
        """Get all files imported by this file"""
        file_id = f"{repo}:{file_path}"
        imported_files = []
        
        for from_id, to_id, rel_type in self.edges:
            if rel_type == 'imports' and from_id == file_id:
                imported_file = self.nodes[to_id].get('file_path')
                if imported_file:
                    imported_files.append(imported_file)
        
        return imported_files


class GraphRAGBuilder:
    """Builds code knowledge graph from repositories"""
    
    def __init__(self):
        self.graph = CodeGraph()
    
    def build_from_file(
        self,
        content: str,
        file_path: str,
        repo: str,
        language: str
    ):
        """Build graph nodes and edges from a file"""
        self.graph.add_file(file_path, repo, language)
        
        if language == 'go':
            self._parse_go_file(content, file_path, repo)
        elif language in ['py', 'python']:
            self._parse_python_file(content, file_path, repo)
        elif language in ['js', 'javascript', 'ts', 'typescript']:
            self._parse_js_file(content, file_path, repo)
    
    def _parse_go_file(self, content: str, file_path: str, repo: str):
        """Parse Go file for imports and functions"""
        lines = content.split('\n')
        
        # Extract imports
        imports = []
        in_import_block = False
        
        for line in lines:
            stripped = line.strip()
            
            if stripped.startswith('import '):
                if '(' in line:
                    in_import_block = True
                else:
                    # Single import
                    import_path = self._extract_go_import(line)
                    if import_path:
                        imports.append(import_path)
            elif in_import_block:
                if stripped.startswith(')'):
                    in_import_block = False
                else:
                    import_path = self._extract_go_import(line)
                    if import_path:
                        imports.append(import_path)
            
            # Extract function names
            func_match = re.match(r'^func\s+(\([^)]+\)\s+)?([a-zA-Z_][a-zA-Z0-9_]*)', stripped)
            if func_match:
                func_name = func_match.group(2)
                self.graph.add_function(func_name, file_path, repo)
        
        # Add import edges (simplified - would need to resolve paths)
        for imp in imports:
            # In real implementation, resolve import path to actual file
            # For now, just log
            logger.debug(f"Found import in {file_path}: {imp}")
    
    def _extract_go_import(self, line: str) -> Optional[str]:
        """Extract import path from Go import line"""
        # Match: import "path/to/package"
        match = re.search(r'import\s+"([^"]+)"', line)
        if match:
            return match.group(1)
        
        # Match: import alias "path/to/package"
        match = re.search(r'import\s+\w+\s+"([^"]+)"', line)
        if match:
            return match.group(1)
        
        return None
    
    def _parse_python_file(self, content: str, file_path: str, repo: str):
        """Parse Python file for imports and functions"""
        lines = content.split('\n')
        
        for line in lines:
            stripped = line.strip()
            
            # Extract imports
            if stripped.startswith('import ') or stripped.startswith('from '):
                # Simplified - would need full AST parsing for accuracy
                logger.debug(f"Found import in {file_path}: {stripped}")
            
            # Extract function/class definitions
            func_match = re.match(r'^(def|class)\s+([a-zA-Z_][a-zA-Z0-9_]*)', stripped)
            if func_match:
                name = func_match.group(2)
                node_type = 'function' if func_match.group(1) == 'def' else 'class'
                self.graph.add_function(name, file_path, repo)
    
    def _parse_js_file(self, content: str, file_path: str, repo: str):
        """Parse JavaScript/TypeScript file"""
        lines = content.split('\n')
        
        for line in lines:
            stripped = line.strip()
            
            # Extract imports
            if stripped.startswith('import ') or 'require(' in stripped:
                logger.debug(f"Found import in {file_path}: {stripped}")
            
            # Extract function/class definitions
            func_match = re.match(
                r'^(function|const\s+(\w+)\s*=\s*\(|class\s+(\w+)|export\s+(function|class))',
                stripped
            )
            if func_match:
                # Extract name (varies by pattern)
                name = func_match.group(2) or func_match.group(3) or "anonymous"
                self.graph.add_function(name, file_path, repo)


class GraphRAGRetriever:
    """
    Multi-hop retrieval using code graph
    
    When a vector match is found, automatically retrieve:
    1. The matched code
    2. Its imports (dependencies)
    3. Functions that call it (dependents)
    4. Related files in the same module
    """
    
    def __init__(self, code_graph: CodeGraph):
        self.graph = code_graph
    
    def multi_hop_retrieve(
        self,
        initial_results: List[Dict],
        hops: int = 1,
        max_additional: int = 5
    ) -> List[Dict]:
        """
        Perform multi-hop retrieval from initial vector search results
        
        Args:
            initial_results: Initial vector search results
            hops: Number of hops to traverse (1 = direct neighbors)
            max_additional: Maximum additional results to add
            
        Returns:
            Expanded list of results with related code
        """
        expanded_results = list(initial_results)
        seen_files: Set[str] = set()
        
        # Mark initial results as seen
        for result in initial_results:
            file_path = result.get('file', '')
            repo = result.get('repo', '')
            if file_path:
                seen_files.add(f"{repo}:{file_path}")
        
        # For each initial result, find related files
        for result in initial_results[:max_additional]:
            file_path = result.get('file', '')
            repo = result.get('repo', '')
            
            if not file_path:
                continue
            
            # Get imports (files this file depends on)
            imports = self.graph.get_imports(file_path, repo)
            
            for imported_file in imports[:2]:  # Limit to 2 imports per file
                file_key = f"{repo}:{imported_file}"
                if file_key not in seen_files:
                    # Create a placeholder result for the imported file
                    expanded_results.append({
                        'code': f"[Import from {file_path}]",
                        'file': imported_file,
                        'repo': repo,
                        'language': result.get('language', 'unknown'),
                        'distance': result.get('distance', 0.0) + 0.1,  # Slightly less relevant
                        'is_import': True,
                        'imported_by': file_path
                    })
                    seen_files.add(file_key)
        
        logger.info(
            f"Multi-hop retrieval: {len(initial_results)} → {len(expanded_results)} results"
        )
        
        return expanded_results
