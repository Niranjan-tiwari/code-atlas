"""
Code Change Impact Analyzer

Given a function, class, or symbol name, traces all callers and dependents
across all indexed repositories to answer:
  "If I change X, what breaks?"

Uses a combination of:
  1. ChromaDB document-contains search (keyword match in code chunks)
  2. Semantic embedding search (catches renames, wrappers, indirect usage)
  3. Code parsing to extract function signatures, imports, and call sites
"""

import re
import time
import logging
from typing import List, Dict, Optional
from collections import defaultdict

logger = logging.getLogger("impact_analyzer")


# ---------------------------------------------------------------------------
# Code parsing helpers
# ---------------------------------------------------------------------------

_FUNC_PATTERNS = {
    "GO": [
        re.compile(r"func\s+(?:\([^)]*\)\s+)?(\w+)\s*\("),           # func Foo(  / func (r *R) Foo(
    ],
    "PY": [
        re.compile(r"(?:^|\n)\s*def\s+(\w+)\s*\(", re.MULTILINE),    # def foo(
        re.compile(r"(?:^|\n)\s*class\s+(\w+)\s*[\(:]", re.MULTILINE),# class Foo(
    ],
    "JS": [
        re.compile(r"function\s+(\w+)\s*\("),                         # function foo(
        re.compile(r"(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?(?:\([^)]*\)\s*=>|function)"),
        re.compile(r"(?:^|\n)\s*(?:export\s+)?class\s+(\w+)", re.MULTILINE),
    ],
    "TS": [],  # same as JS, filled below
}
_FUNC_PATTERNS["TS"] = _FUNC_PATTERNS["JS"]
_FUNC_PATTERNS["PYTHON"] = _FUNC_PATTERNS["PY"]
_FUNC_PATTERNS["JAVASCRIPT"] = _FUNC_PATTERNS["JS"]
_FUNC_PATTERNS["TYPESCRIPT"] = _FUNC_PATTERNS["TS"]
_FUNC_PATTERNS["GOLANG"] = _FUNC_PATTERNS["GO"]

_IMPORT_PATTERNS = [
    re.compile(r'import\s+"([^"]+)"'),                                # Go: import "pkg"
    re.compile(r'import\s+\(([^)]+)\)', re.DOTALL),                   # Go: import ( ... )
    re.compile(r"(?:from\s+(\S+)\s+)?import\s+(.+)", re.MULTILINE),  # Python: from X import Y
    re.compile(r'(?:import|require)\s*\(\s*["\']([^"\']+)'),          # JS/TS: import("x"), require("x")
    re.compile(r'from\s+["\']([^"\']+)["\']'),                        # JS/TS: from "x"
]


def _extract_defined_symbols(code: str, language: str) -> List[str]:
    """Extract function / class names defined in a code chunk."""
    lang = language.upper().replace("PYTHON", "PY").replace("GOLANG", "GO")
    patterns = _FUNC_PATTERNS.get(lang, [])
    symbols = []
    for pat in patterns:
        symbols.extend(pat.findall(code))
    # Fallback: generic func/def/class
    if not symbols:
        for m in re.finditer(r"(?:func|def|class)\s+(\w+)", code):
            symbols.append(m.group(1))
    return list(dict.fromkeys(symbols))  # dedupe preserving order


def _extract_imports(code: str) -> List[str]:
    """Extract imported packages / modules from a code chunk."""
    imports = []
    for pat in _IMPORT_PATTERNS:
        for m in pat.finditer(code):
            for g in m.groups():
                if g:
                    for line in g.strip().splitlines():
                        cleaned = line.strip().strip('"').strip("'").strip(",")
                        if cleaned and not cleaned.startswith("#") and not cleaned.startswith("//"):
                            imports.append(cleaned)
    return list(dict.fromkeys(imports))


def _symbol_appears_in(code: str, symbol: str) -> List[Dict]:
    """Find how a symbol is used in a code chunk: call, import, type reference, etc."""
    appearances = []
    lines = code.splitlines()
    for i, line in enumerate(lines, 1):
        if symbol not in line:
            continue
        # Classify usage — check definition first (it also contains '(' which
        # would otherwise match the call pattern)
        usage = "reference"
        stripped = line.strip()
        if re.search(rf"(?:func|def|class)\s+(?:\([^)]*\)\s+)?{re.escape(symbol)}\b", line):
            usage = "definition"
        elif re.search(rf"(?:import|from)\s.*\b{re.escape(symbol)}\b", line):
            usage = "import"
        elif re.search(rf"\b{re.escape(symbol)}\s*\(", line):
            usage = "call"
        elif re.search(rf":\s*{re.escape(symbol)}\b|{re.escape(symbol)}\s*\{{", line):
            usage = "type_usage"
        appearances.append({"line": i, "usage": usage, "text": stripped[:200]})
    return appearances


# ---------------------------------------------------------------------------
# Core impact analysis
# ---------------------------------------------------------------------------

def analyze_impact(
    retriever,
    symbol: str,
    repo_filter: Optional[str] = None,
    max_results: int = 50,
    include_definitions: bool = True,
    include_semantic: bool = True,
) -> Dict:
    """
    Analyse the impact of changing a function, class, or symbol.

    Args:
        retriever: RAGRetriever (must have _unified or _collections)
        symbol: function / class / constant name to trace
        repo_filter: optional repo scope (None = all repos)
        max_results: max affected chunks to return
        include_definitions: also return where the symbol is defined
        include_semantic: include semantic (embedding) search in addition
                          to keyword search

    Returns:
        {
            "symbol": "ProcessPayment",
            "definition_sites": [ ... ],   # where it's defined
            "impact": [ ... ],             # where it's used
            "summary": { ... },            # counts by repo, by usage type
            "time_ms": 123
        }
    """
    if not symbol or not symbol.strip():
        return {"error": "Missing 'symbol' parameter"}

    symbol = symbol.strip()
    t0 = time.time()

    # ------------------------------------------------------------------
    # Step 1: Keyword search — find chunks whose text contains the symbol
    # ------------------------------------------------------------------
    keyword_hits = _keyword_search(retriever, symbol, repo_filter, max_results * 2)

    # ------------------------------------------------------------------
    # Step 2 (optional): Semantic search — catches indirect references
    # ------------------------------------------------------------------
    semantic_hits = []
    if include_semantic:
        queries = [
            f"{symbol} function call usage",
            f"import {symbol}",
            f"{symbol} caller invocation",
        ]
        for q in queries:
            results = retriever.search_code(
                q, n_results=max_results, repo_filter=repo_filter
            )
            for r in results:
                code = r.get("code", "")
                if symbol in code:
                    semantic_hits.append(r)

    # ------------------------------------------------------------------
    # Step 3: Merge and de-duplicate
    # ------------------------------------------------------------------
    seen_keys = set()
    all_hits = []
    for r in keyword_hits + semantic_hits:
        key = (r.get("repo", ""), r.get("file", ""), r.get("chunk_idx", 0))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        all_hits.append(r)

    # ------------------------------------------------------------------
    # Step 4: Classify each hit — definition vs. usage
    # ------------------------------------------------------------------
    definitions = []
    impacts = []

    for r in all_hits:
        code = r.get("code", "")
        repo = r.get("repo", "unknown")
        file_path = r.get("file", "unknown")
        language = r.get("language", "unknown")

        appearances = _symbol_appears_in(code, symbol)
        if not appearances:
            continue

        usage_types = {a["usage"] for a in appearances}
        is_definition = "definition" in usage_types

        entry = {
            "repo": repo,
            "file": file_path,
            "language": language,
            "appearances": appearances,
            "usage_types": sorted(usage_types),
            "code_preview": code[:300],
            "distance": round(r.get("distance", 0) or 0, 4),
        }

        if is_definition:
            entry["defined_symbols"] = _extract_defined_symbols(code, language)
            definitions.append(entry)
        else:
            entry["imports"] = _extract_imports(code)
            impacts.append(entry)

    # Sort impacts by distance (most relevant first)
    impacts.sort(key=lambda x: x["distance"])
    definitions.sort(key=lambda x: x["distance"])

    # Trim
    impacts = impacts[:max_results]

    # ------------------------------------------------------------------
    # Step 5: Build summary
    # ------------------------------------------------------------------
    repos_affected = defaultdict(int)
    files_affected = set()
    usage_counts = defaultdict(int)

    for entry in impacts:
        repos_affected[entry["repo"]] += 1
        files_affected.add(f"{entry['repo']}/{entry['file']}")
        for a in entry["appearances"]:
            usage_counts[a["usage"]] += 1

    summary = {
        "total_affected_repos": len(repos_affected),
        "total_affected_files": len(files_affected),
        "repos": dict(sorted(repos_affected.items(), key=lambda x: -x[1])),
        "usage_breakdown": dict(usage_counts),
        "definition_count": len(definitions),
    }

    elapsed = round((time.time() - t0) * 1000)

    result = {
        "symbol": symbol,
        "definition_sites": definitions if include_definitions else [],
        "impact": impacts,
        "summary": summary,
        "time_ms": elapsed,
    }
    return result


def _keyword_search(
    retriever, symbol: str, repo_filter: Optional[str], max_results: int
) -> List[Dict]:
    """
    Search ChromaDB for chunks whose document text contains *symbol*.

    Uses ChromaDB's where_document $contains filter for fast keyword matching,
    then falls back to a broader query-embedding search if that yields nothing.
    """
    hits: List[Dict] = []

    where_doc = {"$contains": symbol}
    where_meta = {"repo": repo_filter} if repo_filter else None

    def _query_collection(collection, col_name, n):
        """Query a single collection for keyword matches."""
        try:
            count = collection.count()
            if count == 0:
                return []
            n_ask = min(n, count)
            kwargs = {
                "query_texts": [symbol],
                "n_results": n_ask,
                "where_document": where_doc,
            }
            if where_meta:
                kwargs["where"] = where_meta
            try:
                results = collection.query(**kwargs)
            except Exception:
                # Some collections may not support where_document; fall back
                kwargs.pop("where_document", None)
                results = collection.query(**kwargs)

            formatted = []
            docs = results.get("documents", [[]])[0]
            metas = results.get("metadatas", [[]])[0]
            dists = results.get("distances", [[]])[0]
            for i in range(len(docs)):
                if symbol not in (docs[i] or ""):
                    continue
                meta = metas[i] if i < len(metas) else {}
                formatted.append({
                    "code": docs[i],
                    "repo": meta.get("repo", col_name.replace("repo_", "")),
                    "file": meta.get("file", "unknown"),
                    "language": meta.get("language", "unknown"),
                    "distance": dists[i] if i < len(dists) else None,
                    "chunk_idx": meta.get("chunk", 0),
                    "total_chunks": meta.get("total_chunks", 1),
                    "collection": col_name,
                })
            return formatted
        except Exception as exc:
            logger.debug(f"Keyword search in {col_name} failed: {exc}")
            return []

    # Prefer unified collection
    if retriever._unified:
        hits = _query_collection(retriever._unified, "unified_code", max_results)
    else:
        # Search per-repo collections in parallel
        from concurrent.futures import ThreadPoolExecutor, as_completed
        cols = list(retriever._collections.items())
        if repo_filter:
            cols = [(n, c) for n, c in cols if n == f"repo_{repo_filter}"]
        with ThreadPoolExecutor(max_workers=min(16, max(1, len(cols)))) as ex:
            futs = {
                ex.submit(_query_collection, col, name, max_results // max(1, len(cols)) + 5): name
                for name, col in cols
            }
            for f in as_completed(futs):
                try:
                    hits.extend(f.result())
                except Exception:
                    pass
    return hits


# ---------------------------------------------------------------------------
# Convenience: impact from a diff (find changed symbols, then trace them)
# ---------------------------------------------------------------------------

def analyze_diff_impact(
    retriever,
    diff_text: str,
    repo_name: Optional[str] = None,
    max_results: int = 50,
) -> Dict:
    """
    Given a unified diff, extract the changed function/class names,
    then run impact analysis on each.

    Returns:
        {
            "changed_symbols": ["Foo", "Bar"],
            "per_symbol": { "Foo": { ... impact ... }, "Bar": { ... } },
            "aggregate_summary": { ... },
            "time_ms": 123
        }
    """
    t0 = time.time()
    symbols = _extract_symbols_from_diff(diff_text)

    if not symbols:
        return {
            "changed_symbols": [],
            "per_symbol": {},
            "aggregate_summary": {"total_affected_repos": 0, "total_affected_files": 0},
            "note": "No function/class changes detected in diff",
            "time_ms": round((time.time() - t0) * 1000),
        }

    per_symbol = {}
    all_repos = set()
    all_files = set()

    for sym in symbols:
        result = analyze_impact(
            retriever, sym, repo_filter=None,  # search ALL repos
            max_results=max_results, include_semantic=True,
        )
        per_symbol[sym] = result
        all_repos.update(result.get("summary", {}).get("repos", {}).keys())
        for entry in result.get("impact", []):
            all_files.add(f"{entry['repo']}/{entry['file']}")

    return {
        "changed_symbols": symbols,
        "per_symbol": per_symbol,
        "aggregate_summary": {
            "total_affected_repos": len(all_repos),
            "total_affected_files": len(all_files),
            "affected_repos": sorted(all_repos),
        },
        "time_ms": round((time.time() - t0) * 1000),
    }


def _extract_symbols_from_diff(diff_text: str) -> List[str]:
    """
    Extract function/class names from added/modified lines in a unified diff.
    Looks at lines starting with '+' (added) that define functions or classes.
    """
    symbols = []
    for line in diff_text.splitlines():
        if not line.startswith("+"):
            continue
        # Remove the leading '+'
        code_line = line[1:]
        for m in re.finditer(r"(?:func|def|class)\s+(?:\([^)]*\)\s+)?(\w+)", code_line):
            name = m.group(1)
            if name and len(name) > 1 and name not in symbols:
                symbols.append(name)
    return symbols
