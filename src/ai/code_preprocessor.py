"""
Code-Specific Preprocessing for RAG Indexing & Search

Improves retrieval quality by:
1. Stripping comments (reduces noise in embeddings)
2. Extracting function/class signatures separately (high-value tokens)
3. Weighting docstrings higher (they describe intent)
4. Extracting imports as features (dependency signals)
5. Normalizing identifiers (camelCase/snake_case -> words)

Used in two places:
- Indexing: preprocess code before embedding
- Search: preprocess query to match indexed style
"""

import logging
import re
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("code_preprocessor")


class CodePreprocessor:
    """
    Preprocesses code for better embedding and retrieval quality.
    
    Supports: Python, Go, JavaScript/TypeScript, Java, Ruby, Rust
    """
    
    # Language -> comment patterns
    COMMENT_PATTERNS = {
        'python': {
            'line': r'#.*$',
            'block_start': r'(\"\"\"|\'\'\')' ,
            'block_end': r'(\"\"\"|\'\'\')' ,
        },
        'go': {
            'line': r'//.*$',
            'block_start': r'/\*',
            'block_end': r'\*/',
        },
        'javascript': {
            'line': r'//.*$',
            'block_start': r'/\*',
            'block_end': r'\*/',
        },
        'typescript': {
            'line': r'//.*$',
            'block_start': r'/\*',
            'block_end': r'\*/',
        },
        'java': {
            'line': r'//.*$',
            'block_start': r'/\*',
            'block_end': r'\*/',
        },
        'rust': {
            'line': r'//.*$',
            'block_start': r'/\*',
            'block_end': r'\*/',
        },
    }
    
    # Function/class signature patterns by language
    SIGNATURE_PATTERNS = {
        'python': [
            r'^(\s*def\s+\w+\s*\([^)]*\)(?:\s*->.*?)?)\s*:',
            r'^(\s*class\s+\w+(?:\([^)]*\))?)\s*:',
            r'^(\s*async\s+def\s+\w+\s*\([^)]*\)(?:\s*->.*?)?)\s*:',
        ],
        'go': [
            r'^(func\s+(?:\([^)]+\)\s+)?\w+\s*\([^)]*\)(?:\s*(?:\([^)]*\)|\w+))?)\s*\{',
            r'^(type\s+\w+\s+(?:struct|interface))\s*\{',
        ],
        'javascript': [
            r'^(\s*(?:export\s+)?(?:async\s+)?function\s+\w+\s*\([^)]*\))',
            r'^(\s*(?:export\s+)?class\s+\w+(?:\s+extends\s+\w+)?)',
            r'^(\s*(?:const|let|var)\s+\w+\s*=\s*(?:async\s+)?\([^)]*\)\s*=>)',
        ],
        'typescript': [
            r'^(\s*(?:export\s+)?(?:async\s+)?function\s+\w+\s*(?:<[^>]+>)?\s*\([^)]*\)(?:\s*:\s*\w+)?)',
            r'^(\s*(?:export\s+)?(?:abstract\s+)?class\s+\w+(?:<[^>]+>)?(?:\s+(?:extends|implements)\s+\w+)?)',
            r'^(\s*(?:export\s+)?interface\s+\w+(?:<[^>]+>)?)',
        ],
    }
    
    # Import patterns by language
    IMPORT_PATTERNS = {
        'python': [
            r'^import\s+(.+)$',
            r'^from\s+(\S+)\s+import\s+(.+)$',
        ],
        'go': [
            r'import\s+"([^"]+)"',
            r'import\s+\w+\s+"([^"]+)"',
        ],
        'javascript': [
            r"import\s+.*?from\s+['\"]([^'\"]+)['\"]",
            r"(?:const|let|var)\s+.*?=\s*require\(['\"]([^'\"]+)['\"]\)",
        ],
        'typescript': [
            r"import\s+.*?from\s+['\"]([^'\"]+)['\"]",
        ],
    }
    
    @classmethod
    def detect_language(cls, file_path: str) -> str:
        """Detect language from file extension"""
        ext_map = {
            '.py': 'python',
            '.go': 'go',
            '.js': 'javascript',
            '.jsx': 'javascript',
            '.ts': 'typescript',
            '.tsx': 'typescript',
            '.java': 'java',
            '.rs': 'rust',
            '.rb': 'ruby',
        }
        for ext, lang in ext_map.items():
            if file_path.endswith(ext):
                return lang
        return 'unknown'
    
    @classmethod
    def strip_comments(cls, code: str, language: str) -> str:
        """
        Strip comments from code to reduce embedding noise.
        Keeps the code structure but removes natural language noise.
        """
        patterns = cls.COMMENT_PATTERNS.get(language)
        if not patterns:
            return code
        
        lines = code.split('\n')
        result = []
        in_block = False
        
        for line in lines:
            if in_block:
                if re.search(patterns['block_end'], line):
                    in_block = False
                continue
            
            if re.search(patterns['block_start'], line):
                # Check if block start and end are on the same line
                remaining = re.sub(patterns['block_start'], '', line, count=1)
                if not re.search(patterns['block_end'], remaining):
                    in_block = True
                continue
            
            # Strip line comments
            cleaned = re.sub(patterns['line'], '', line)
            if cleaned.strip():
                result.append(cleaned)
        
        return '\n'.join(result)
    
    @classmethod
    def extract_signatures(cls, code: str, language: str) -> List[str]:
        """
        Extract function/class signatures.
        These are high-value tokens for search (function names, parameter types).
        """
        patterns = cls.SIGNATURE_PATTERNS.get(language, [])
        signatures = []
        
        for pattern in patterns:
            matches = re.findall(pattern, code, re.MULTILINE)
            for match in matches:
                sig = match.strip() if isinstance(match, str) else match[0].strip()
                if sig:
                    signatures.append(sig)
        
        return signatures
    
    @classmethod
    def extract_docstrings(cls, code: str, language: str) -> List[str]:
        """
        Extract docstrings/doc comments (high intent signal).
        """
        docstrings = []
        
        if language == 'python':
            # Triple-quoted strings after def/class
            pattern = r'(?:def|class)\s+\w+[^:]*:\s*\n\s*(\"\"\"[\s\S]*?\"\"\"|\'\'\'[\s\S]*?\'\'\')'
            matches = re.findall(pattern, code)
            for m in matches:
                cleaned = m.strip().strip('"\'')
                if cleaned:
                    docstrings.append(cleaned)
        
        elif language in ('go', 'java', 'javascript', 'typescript', 'rust'):
            # Block comments before func/type/class
            pattern = r'/\*\*([\s\S]*?)\*/\s*\n\s*(?:func|type|class|export|pub)'
            matches = re.findall(pattern, code)
            for m in matches:
                cleaned = re.sub(r'^\s*\*\s?', '', m, flags=re.MULTILINE).strip()
                if cleaned:
                    docstrings.append(cleaned)
        
        return docstrings
    
    @classmethod
    def extract_imports(cls, code: str, language: str) -> List[str]:
        """
        Extract import statements as features.
        Imports signal what the code depends on.
        """
        patterns = cls.IMPORT_PATTERNS.get(language, [])
        imports = []
        
        for pattern in patterns:
            matches = re.findall(pattern, code, re.MULTILINE)
            for match in matches:
                if isinstance(match, tuple):
                    imports.extend(m.strip() for m in match if m.strip())
                else:
                    imports.append(match.strip())
        
        return imports
    
    @classmethod
    def preprocess_for_indexing(
        cls,
        code: str,
        language: str,
        include_signatures: bool = True,
        include_docstrings: bool = True,
        strip_comments_flag: bool = False
    ) -> Dict:
        """
        Full preprocessing pipeline for indexing.
        
        Returns:
            Dict with:
            - code: Original or cleaned code
            - signatures: Extracted function/class signatures
            - docstrings: Extracted docstrings
            - imports: Extracted imports
            - enriched_text: Combined text for embedding (weighted)
        """
        signatures = cls.extract_signatures(code, language) if include_signatures else []
        docstrings = cls.extract_docstrings(code, language) if include_docstrings else []
        imports = cls.extract_imports(code, language)
        
        cleaned_code = cls.strip_comments(code, language) if strip_comments_flag else code
        
        # Build enriched text: signatures + docstrings get extra weight
        # by appearing both in original form and normalized form
        enriched_parts = [cleaned_code]
        
        if signatures:
            sig_text = '\n'.join(signatures)
            enriched_parts.append(f"\n--- Signatures ---\n{sig_text}")
        
        if docstrings:
            doc_text = '\n'.join(docstrings)
            enriched_parts.append(f"\n--- Documentation ---\n{doc_text}")
        
        enriched_text = '\n'.join(enriched_parts)
        
        return {
            'code': cleaned_code,
            'signatures': signatures,
            'docstrings': docstrings,
            'imports': imports,
            'enriched_text': enriched_text,
        }
    
    @classmethod
    def preprocess_query(cls, query: str) -> str:
        """
        Preprocess a search query for better matching.
        
        - Normalize identifiers (split camelCase/snake_case)
        - Expand abbreviations
        - Keep original intact for exact matching
        """
        parts = [query]
        
        # Split camelCase identifiers
        camel_expanded = re.sub(r'([a-z])([A-Z])', r'\1 \2', query)
        camel_expanded = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1 \2', camel_expanded)
        if camel_expanded != query:
            parts.append(camel_expanded)
        
        # Split snake_case
        snake_expanded = re.sub(r'_', ' ', query)
        if snake_expanded != query:
            parts.append(snake_expanded)
        
        # Split dot.notation
        dot_expanded = re.sub(r'\.', ' ', query)
        if dot_expanded != query:
            parts.append(dot_expanded)
        
        return ' '.join(set(' '.join(parts).split()))
