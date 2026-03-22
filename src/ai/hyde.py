"""
HyDE (Hypothetical Document Embeddings) Query Expansion

Before searching, ask a fast LLM to generate a hypothetical code snippet
that would solve the query. Then search using that fake code instead of
the user's natural language query.

"Code matches code" better than "English matches code"

Enhanced with:
- Synonym expansion for code terminology
- Code-specific preprocessing (extract identifiers, normalize naming)
- Multi-strategy expansion (HyDE + synonyms + related terms)
"""

import logging
import re
from typing import Optional, Dict, List, Set

logger = logging.getLogger("hyde")

# Code synonym dictionary - maps common abbreviations and alternatives
CODE_SYNONYMS: Dict[str, List[str]] = {
    "db": ["database", "datastore", "storage"],
    "database": ["db", "datastore", "storage", "sql", "postgres", "mysql", "sqlite"],
    "auth": ["authentication", "authorization", "login", "signin"],
    "authentication": ["auth", "login", "signin", "session", "token", "jwt"],
    "login": ["signin", "auth", "authenticate", "session"],
    "api": ["endpoint", "route", "handler", "rest", "http"],
    "endpoint": ["api", "route", "handler", "url", "path"],
    "err": ["error", "exception", "failure", "fault"],
    "error": ["err", "exception", "failure", "fault", "panic", "crash"],
    "config": ["configuration", "settings", "preferences", "options"],
    "configuration": ["config", "settings", "preferences", "env"],
    "msg": ["message", "notification", "alert"],
    "message": ["msg", "notification", "alert", "event"],
    "req": ["request", "http", "input"],
    "request": ["req", "http", "input", "payload"],
    "resp": ["response", "reply", "output"],
    "response": ["resp", "reply", "output", "result"],
    "repo": ["repository", "git", "codebase"],
    "repository": ["repo", "git", "codebase", "project"],
    "fn": ["function", "func", "method", "handler"],
    "function": ["fn", "func", "method", "handler", "def"],
    "pkg": ["package", "module", "library"],
    "package": ["pkg", "module", "library", "import"],
    "ctx": ["context", "state"],
    "context": ["ctx", "state", "scope"],
    "middleware": ["interceptor", "handler", "filter", "hook"],
    "cache": ["redis", "memcache", "store", "memo"],
    "queue": ["kafka", "rabbitmq", "nats", "pubsub", "event"],
    "test": ["testing", "spec", "unittest", "pytest", "mock"],
    "deploy": ["deployment", "release", "ci", "cd", "pipeline"],
    "log": ["logging", "logger", "trace", "debug", "print"],
    "user": ["account", "profile", "member", "client"],
    "payment": ["billing", "invoice", "charge", "stripe", "transaction"],
    "search": ["find", "query", "lookup", "filter", "retrieve"],
    "send": ["emit", "dispatch", "publish", "push", "notify"],
    "worker": ["job", "task", "background", "async", "goroutine"],
    "validate": ["validation", "check", "verify", "sanitize"],
    "connect": ["connection", "dial", "open", "establish"],
    "parse": ["parsing", "decode", "unmarshal", "deserialize"],
    "serialize": ["marshal", "encode", "json", "format"],
}


class QueryExpander:
    """
    Expands queries with synonyms and related code terms.
    Works independently of LLM - pure keyword/synonym expansion.
    """
    
    @staticmethod
    def expand_with_synonyms(query: str, max_additions: int = 5) -> str:
        """
        Expand query with code synonyms using round-robin to ensure
        all query words get fair synonym coverage.
        
        Example:
            "db connection error" -> "db connection error database err datastore exception"
        """
        # Preserve original word order, deduplicate
        words = list(dict.fromkeys(re.findall(r'\b\w+\b', query.lower())))
        word_set = set(words)
        additions: List[str] = []
        added_set: Set[str] = set()
        
        # Collect candidate synonyms per word (preserving query word order)
        word_synonyms = {}
        for word in words:
            syns = [s for s in CODE_SYNONYMS.get(word, []) if s not in word_set]
            if syns:
                word_synonyms[word] = syns
        
        # Round-robin: take one synonym from each word per round
        indices = {w: 0 for w in word_synonyms}
        while len(additions) < max_additions:
            added_this_round = False
            for word in word_synonyms:
                if len(additions) >= max_additions:
                    break
                idx = indices[word]
                syns = word_synonyms[word]
                while idx < len(syns) and syns[idx] in added_set:
                    idx += 1
                if idx < len(syns):
                    additions.append(syns[idx])
                    added_set.add(syns[idx])
                    indices[word] = idx + 1
                    added_this_round = True
            if not added_this_round:
                break
        
        if additions:
            expanded = f"{query} {' '.join(additions)}"
            logger.debug(f"Synonym expansion: +{len(additions)} terms")
            return expanded
        
        return query
    
    @staticmethod
    def extract_code_identifiers(query: str) -> List[str]:
        """
        Extract potential code identifiers from query.
        
        Handles camelCase, snake_case, dot.notation, etc.
        """
        identifiers = []
        
        # camelCase or PascalCase
        camel_matches = re.findall(r'\b[a-z]+(?:[A-Z][a-z]+)+\b', query)
        identifiers.extend(camel_matches)
        
        # PascalCase
        pascal_matches = re.findall(r'\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\b', query)
        identifiers.extend(pascal_matches)
        
        # snake_case
        snake_matches = re.findall(r'\b[a-z]+(?:_[a-z]+)+\b', query)
        identifiers.extend(snake_matches)
        
        # dot.notation (e.g., http.StatusOK, os.path)
        dot_matches = re.findall(r'\b\w+\.\w+(?:\.\w+)*\b', query)
        identifiers.extend(dot_matches)
        
        return list(set(identifiers))
    
    @staticmethod
    def normalize_code_terms(query: str) -> str:
        """
        Normalize code terms for better matching:
        - Split camelCase: getUserName -> get User Name
        - Split snake_case: get_user_name -> get user name
        - Keep original query intact
        """
        # Split camelCase
        camel_expanded = re.sub(r'([a-z])([A-Z])', r'\1 \2', query)
        camel_expanded = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1 \2', camel_expanded)
        
        # Split snake_case
        snake_expanded = re.sub(r'_', ' ', camel_expanded)
        
        # Combine original + expanded (for both exact and fuzzy matching)
        if snake_expanded.lower() != query.lower():
            return f"{query} {snake_expanded}"
        return query


class HyDEExpander:
    """
    Hypothetical Document Embeddings query expansion.
    
    Multi-strategy expansion:
    1. Synonym expansion (fast, no LLM)
    2. Code identifier extraction (fast, no LLM)
    3. HyDE hypothetical code generation (needs LLM)
    
    Strategy:
    1. User asks: "How do I handle errors?"
    2. Synonym expansion adds: "exception fault panic"
    3. LLM generates: "func handleError(err error) { ... }" (hypothetical code)
    4. Combined signal for vector DB search
    """
    
    def __init__(self, llm_manager=None):
        self.llm_manager = llm_manager
        self.query_expander = QueryExpander()
    
    def expand_query(
        self,
        query: str,
        language: str = "go",
        use_fast_model: bool = True
    ) -> str:
        """
        Generate hypothetical code snippet for the query.
        Falls back to synonym expansion if no LLM available.
        """
        # Always apply synonym expansion (fast, no LLM needed)
        synonym_expanded = self.query_expander.expand_with_synonyms(query)
        
        # Normalize code terms
        normalized = self.query_expander.normalize_code_terms(synonym_expanded)
        
        if not self.llm_manager:
            logger.info("No LLM manager, using synonym+normalization expansion only")
            return normalized
        
        try:
            provider = "gemini" if use_fast_model else None
            prompt = self._build_expansion_prompt(query, language)
            
            response = self.llm_manager.generate(
                prompt=prompt,
                provider=provider,
                temperature=0.7,
                max_tokens=300
            )
            
            hypothetical_code = response.content.strip()
            
            # Extract code block if wrapped in markdown
            if "```" in hypothetical_code:
                lines = hypothetical_code.split('\n')
                code_lines = []
                in_code_block = False
                for line in lines:
                    if line.strip().startswith('```'):
                        in_code_block = not in_code_block
                        continue
                    if in_code_block:
                        code_lines.append(line)
                hypothetical_code = '\n'.join(code_lines)
            
            logger.info(f"HyDE expanded query to {len(hypothetical_code)} chars")
            
            # Combine: original + synonyms + hypothetical code
            expanded_query = (
                f"{normalized}\n\nHypothetical code:\n{hypothetical_code}"
            )
            return expanded_query
            
        except Exception as e:
            logger.warning(f"HyDE LLM expansion failed: {e}, using synonym expansion")
            return normalized
    
    def _build_expansion_prompt(self, query: str, language: str) -> str:
        """Build prompt for generating hypothetical code"""
        
        language_examples = {
            'go': '''Example:
Query: "How do I handle HTTP errors?"
Hypothetical code:
```go
func handleHTTPError(w http.ResponseWriter, err error) {
    if err != nil {
        http.Error(w, err.Error(), http.StatusInternalServerError)
        return
    }
}
```''',
            'python': '''Example:
Query: "How do I handle HTTP errors?"
Hypothetical code:
```python
def handle_http_error(response, error):
    if error:
        response.status_code = 500
        response.json({"error": str(error)})
```''',
            'javascript': '''Example:
Query: "How do I handle HTTP errors?"
Hypothetical code:
```javascript
function handleHttpError(res, err) {
    if (err) {
        res.status(500).json({ error: err.message });
    }
}
```'''
        }
        
        example = language_examples.get(language.lower(), language_examples['go'])
        
        prompt = f"""Generate a hypothetical code snippet that would answer this query.

Query: "{query}"

Generate a short code snippet in {language} that demonstrates how to solve this problem.
The code doesn't need to be complete or runnable - just show the structure and approach.

{example}

Now generate hypothetical code for the query above:"""
        
        return prompt
    
    def expand_for_search(
        self,
        query: str,
        language: str = "go",
        use_hypothetical_only: bool = False
    ) -> str:
        """
        Expand query specifically for vector search.
        
        Args:
            query: Original query
            language: Target language
            use_hypothetical_only: If True, use only hypothetical code
            
        Returns:
            Expanded query string for vector search
        """
        hypothetical = self.expand_query(query, language)
        
        if use_hypothetical_only:
            if "Hypothetical code:" in hypothetical:
                return hypothetical.split("Hypothetical code:")[-1].strip()
            return hypothetical
        
        return hypothetical
