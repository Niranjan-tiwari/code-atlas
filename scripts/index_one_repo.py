#!/usr/bin/env python3
"""
Index one repository into vector DB
Test with webhook-generation repo
"""

import sys
import os
from pathlib import Path
from typing import List, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.ai.vector_db import VectorDB
from src.ai.chunking import ASTChunker, ParentChildIndexer
import json


def load_repo_config():
    """Load repo config"""
    config_path = Path(__file__).parent.parent / "config" / "repos_config.json"
    with open(config_path, 'r') as f:
        config = json.load(f)
    return config.get("repos", [])


def get_repo_path(repo_name: str, base_path: str) -> Path:
    """Get full path to repository"""
    repos = load_repo_config()
    for repo in repos:
        if repo["name"] == repo_name:
            return Path(base_path) / repo["local_path"]
    return Path(base_path) / repo_name


def load_code_files(repo_path: Path, languages: List[str] = None) -> List[Tuple[str, str, str]]:
    """
    Load code files from repository (supports multiple languages)
    
    Args:
        repo_path: Path to repository
        languages: List of languages to index (e.g., ['go', 'py', 'js'])
                   If None, auto-detect from common patterns
    
    Returns:
        List of (file_path, content, language) tuples
    """
    if languages is None:
        # Auto-detect: check what files exist
        languages = []
        for ext in ['.go', '.py', '.js', '.ts', '.java', '.rb']:
            if list(repo_path.rglob(f"*{ext}")):
                languages.append(ext[1:])  # Remove dot
        
        # Default to Go if nothing found (most repos are Go)
        if not languages:
            languages = ['go']
    
    # Map languages to file extensions
    ext_map = {
        'go': '.go',
        'python': '.py',
        'py': '.py',
        'javascript': '.js',
        'js': '.js',
        'typescript': '.ts',
        'ts': '.ts',
        'java': '.java',
        'ruby': '.rb',
        'rb': '.rb'
    }
    
    extensions = [ext_map.get(lang.lower(), f'.{lang}') for lang in languages]
    
    files = []
    
    # Skip common directories
    skip_dirs = {
        '.git', '__pycache__', '.venv', 'venv', 'node_modules', 
        '.pytest_cache', 'vendor', 'bin', '.idea', '.vscode'
    }
    
    for ext in extensions:
        for code_file in repo_path.rglob(f"*{ext}"):
            # Skip if in excluded directory
            if any(skip in str(code_file) for skip in skip_dirs):
                continue
            
            try:
                with open(code_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    # Only add non-empty files
                    if content.strip():
                        lang = ext[1:]  # Remove dot
                        files.append((
                            str(code_file.relative_to(repo_path)), 
                            content,
                            lang
                        ))
            except Exception as e:
                print(f"⚠️  Error reading {code_file}: {e}")
    
    return files


def chunk_code(content: str, language: str = "go", chunk_size: int = 1000, overlap: int = 200) -> List[str]:
    """
    Split code into chunks (language-aware)
    
    Args:
        content: Code content
        language: Programming language (go, py, js, etc.)
        chunk_size: Maximum chunk size (characters)
        overlap: Overlap between chunks (lines)
    
    Returns:
        List of code chunks
    """
    lines = content.split('\n')
    chunks = []
    
    # For Go, try to chunk by functions/packages
    if language == 'go':
        chunks = chunk_go_code(content, chunk_size, overlap)
        if chunks:
            return chunks
    
    # Fallback: line-based chunking for all languages
    i = 0
    while i < len(lines):
        chunk_lines = []
        chunk_length = 0
        
        # Build chunk
        while i < len(lines) and chunk_length < chunk_size:
            line = lines[i]
            chunk_lines.append(line)
            chunk_length += len(line) + 1  # +1 for newline
            i += 1
        
        if chunk_lines:
            chunks.append('\n'.join(chunk_lines))
        
        # Move back for overlap
        if i < len(lines):
            i = max(0, i - overlap)
    
    return chunks


def chunk_go_code(content: str, chunk_size: int = 1000, overlap: int = 200) -> List[str]:
    """
    Chunk Go code intelligently (by functions, methods, packages)
    
    Args:
        content: Go code content
        chunk_size: Maximum chunk size
        overlap: Overlap in characters
    
    Returns:
        List of code chunks
    """
    chunks = []
    lines = content.split('\n')
    
    current_chunk = []
    current_length = 0
    
    for line in lines:
        line_length = len(line) + 1
        
        # Check if this is a function/method start (Go pattern)
        is_function_start = (
            line.strip().startswith('func ') or
            line.strip().startswith('func(') or
            'func(' in line and '{' in line
        )
        
        # If chunk is getting large and we hit a function boundary, save chunk
        if current_length > chunk_size * 0.7 and is_function_start and current_chunk:
            chunks.append('\n'.join(current_chunk))
            # Keep some overlap
            overlap_lines = current_chunk[-overlap//50:] if len(current_chunk) > overlap//50 else []
            current_chunk = overlap_lines + [line]
            current_length = sum(len(l) + 1 for l in current_chunk)
        else:
            current_chunk.append(line)
            current_length += line_length
    
    # Add remaining chunk
    if current_chunk:
        chunks.append('\n'.join(current_chunk))
    
    return chunks


def index_repo(repo_name: str = "webhook-generation", base_path: str = "/path/to/your/repos"):
    """Index one repository"""
    print(f"🚀 Indexing repository: {repo_name}")
    print("=" * 60)
    
    # Get repo path
    repo_path = get_repo_path(repo_name, base_path)
    print(f"📁 Repository path: {repo_path}")
    
    if not repo_path.exists():
        print(f"❌ Repository not found: {repo_path}")
        return
    
    # Load code files (Go, Python, etc.)
    print("\n📂 Loading code files...")
    files = load_code_files(repo_path)
    
    # Group by language
    lang_counts = {}
    for _, _, lang in files:
        lang_counts[lang] = lang_counts.get(lang, 0) + 1
    
    print(f"✅ Found {len(files)} code files")
    for lang, count in lang_counts.items():
        print(f"   - {lang.upper()}: {count} files")
    
    if not files:
        print("⚠️  No code files found!")
        return
    
    # Initialize vector DB
    print("\n🗄️  Initializing vector database...")
    db = VectorDB(collection_name=f"repo_{repo_name}")
    
    # Process files with AST chunking
    print("\n📝 Processing files with AST-based chunking...")
    all_documents = []
    all_metadatas = []
    all_ids = []
    
    # Initialize AST chunker and parent-child indexer
    ast_chunker = ASTChunker()
    parent_child_indexer = ParentChildIndexer()
    
    doc_id = 0
    use_ast_chunking = True  # Enable AST chunking by default
    
    for file_path, content, language in files:
        try:
            if use_ast_chunking:
                # Try AST-based chunking first
                try:
                    # Create parent-child chunks
                    parent_child_chunks = parent_child_indexer.create_parent_child_chunks(
                        content=content,
                        language=language,
                        file_path=file_path,
                        repo_name=repo_name
                    )
                    
                    # Add both child and parent chunks
                    for pc_chunk in parent_child_chunks:
                        # Add child chunk (for precise matching)
                        all_documents.append(pc_chunk.child_code)
                        all_metadatas.append({
                            **pc_chunk.child_metadata,
                            "chunk_type": pc_chunk.chunk_type,
                            "is_child": True
                        })
                        all_ids.append(f"{repo_name}_{file_path}_child_{doc_id}")
                        doc_id += 1
                        
                        # Add parent chunk (for deep context)
                        all_documents.append(pc_chunk.parent_code)
                        all_metadatas.append({
                            **pc_chunk.parent_metadata,
                            "chunk_type": pc_chunk.chunk_type,
                            "is_parent": True,
                            "child_id": f"{repo_name}_{file_path}_child_{doc_id-1}"
                        })
                        all_ids.append(f"{repo_name}_{file_path}_parent_{doc_id}")
                        doc_id += 1
                    
                    continue  # Successfully used AST chunking
                except Exception as e:
                    print(f"  ⚠️  AST chunking failed for {file_path}: {e}, using fallback")
            
            # Fallback to original chunking
            chunks = chunk_code(content, language=language)
            for chunk_idx, chunk in enumerate(chunks):
                all_documents.append(chunk)
                all_metadatas.append({
                    "repo": repo_name,
                    "file": file_path,
                    "language": language,
                    "chunk": chunk_idx,
                    "total_chunks": len(chunks),
                    "chunk_method": "fallback"
                })
                all_ids.append(f"{repo_name}_{file_path}_{chunk_idx}")
                doc_id += 1
                
        except Exception as e:
            print(f"  ❌ Error processing {file_path}: {e}")
            continue
    
    print(f"✅ Created {len(all_documents)} chunks from {len(files)} files")
    if use_ast_chunking:
        print(f"   Using AST-based chunking with parent-child indexing")
    
    # Add to vector DB
    print("\n💾 Adding to vector database...")
    db.add_documents(all_documents, all_metadatas, all_ids)
    
    # Collection info
    info = db.get_collection_info()
    print(f"\n📊 Collection: {info['name']}")
    print(f"📊 Total documents: {info['count']}")
    
    # Test search
    print("\n🔍 Testing search...")
    test_queries = [
        "logging function",
        "error handling",
        "api endpoint"
    ]
    
    for query in test_queries:
        print(f"\n🔎 Query: '{query}'")
        results = db.search(query, n_results=3)
        print(f"   Found {len(results)} results")
        for i, result in enumerate(results[:2], 1):
            doc_preview = result['document'][:100].replace('\n', ' ')
            print(f"   {i}. {doc_preview}...")
            print(f"      File: {result['metadata'].get('file', 'unknown')}")
    
    print("\n✅ Repository indexed successfully!")
    print(f"📁 Data stored in: ./data/vector_db/")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Index repository into vector DB")
    parser.add_argument("--repo", default="webhook-generation", help="Repository name")
    parser.add_argument("--base-path", default="/path/to/your/repos", help="Base path")
    
    args = parser.parse_args()
    
    try:
        index_repo(args.repo, args.base_path)
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
