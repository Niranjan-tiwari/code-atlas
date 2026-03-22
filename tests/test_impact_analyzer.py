"""
Tests for Code Change Impact Analyzer

Covers:
  - Code parsing helpers (symbol extraction, import extraction, appearance detection)
  - Core analyze_impact with a mock retriever
  - analyze_diff_impact for diff-based analysis
  - Edge cases (empty input, no matches, special characters)
"""

import pytest
from unittest.mock import MagicMock, patch
from src.tools.impact_analyzer import (
    _extract_defined_symbols,
    _extract_imports,
    _symbol_appears_in,
    _extract_symbols_from_diff,
    analyze_impact,
    analyze_diff_impact,
)


# ============================================================
# Helpers: Symbol Extraction
# ============================================================

class TestExtractDefinedSymbols:

    def test_go_function(self):
        code = 'func ProcessPayment(ctx context.Context, amount float64) error {'
        assert "ProcessPayment" in _extract_defined_symbols(code, "GO")

    def test_go_method(self):
        code = 'func (s *Service) HandleRequest(w http.ResponseWriter, r *http.Request) {'
        assert "HandleRequest" in _extract_defined_symbols(code, "GO")

    def test_python_function(self):
        code = 'def calculate_total(items: list) -> float:'
        assert "calculate_total" in _extract_defined_symbols(code, "PY")

    def test_python_class(self):
        code = 'class PaymentProcessor:'
        assert "PaymentProcessor" in _extract_defined_symbols(code, "PY")

    def test_python_class_with_base(self):
        code = 'class PaymentProcessor(BaseProcessor):'
        assert "PaymentProcessor" in _extract_defined_symbols(code, "PY")

    def test_js_function(self):
        code = 'function sendMessage(payload) {'
        assert "sendMessage" in _extract_defined_symbols(code, "JS")

    def test_js_arrow_const(self):
        code = 'const validateInput = (data) => {'
        assert "validateInput" in _extract_defined_symbols(code, "JS")

    def test_js_async_arrow(self):
        code = 'const fetchData = async (url) => {'
        assert "fetchData" in _extract_defined_symbols(code, "JS")

    def test_ts_class(self):
        code = 'export class UserService {'
        assert "UserService" in _extract_defined_symbols(code, "TS")

    def test_multiple_symbols(self):
        code = """
def foo():
    pass

def bar():
    pass

class Baz:
    pass
"""
        syms = _extract_defined_symbols(code, "PY")
        assert "foo" in syms
        assert "bar" in syms
        assert "Baz" in syms

    def test_empty_code(self):
        assert _extract_defined_symbols("", "GO") == []

    def test_unknown_language_fallback(self):
        code = "func MyFunc() {"
        syms = _extract_defined_symbols(code, "UNKNOWN")
        assert "MyFunc" in syms


# ============================================================
# Helpers: Import Extraction
# ============================================================

class TestExtractImports:

    def test_go_single_import(self):
        code = 'import "fmt"'
        imports = _extract_imports(code)
        assert "fmt" in imports

    def test_go_multi_import(self):
        code = '''import (
    "fmt"
    "net/http"
    "github.com/org/repo/pkg"
)'''
        imports = _extract_imports(code)
        assert "fmt" in imports
        assert "net/http" in imports

    def test_python_import(self):
        code = "from src.tools.impact_analyzer import analyze_impact"
        imports = _extract_imports(code)
        assert any("impact_analyzer" in i for i in imports)

    def test_js_import(self):
        code = 'import { useState } from "react"'
        imports = _extract_imports(code)
        assert "react" in imports

    def test_require(self):
        code = "const express = require('express')"
        imports = _extract_imports(code)
        assert "express" in imports

    def test_empty(self):
        assert _extract_imports("x = 1 + 2") == []


# ============================================================
# Helpers: Symbol Appearance Detection
# ============================================================

class TestSymbolAppearsIn:

    def test_function_call(self):
        code = "result = ProcessPayment(ctx, 100)"
        apps = _symbol_appears_in(code, "ProcessPayment")
        assert len(apps) == 1
        assert apps[0]["usage"] == "call"

    def test_definition(self):
        code = "func ProcessPayment(ctx context.Context) error {"
        apps = _symbol_appears_in(code, "ProcessPayment")
        assert any(a["usage"] == "definition" for a in apps)

    def test_import_reference(self):
        code = "from payments import ProcessPayment"
        apps = _symbol_appears_in(code, "ProcessPayment")
        assert any(a["usage"] == "import" for a in apps)

    def test_type_usage(self):
        code = "var p ProcessPayment"
        apps = _symbol_appears_in(code, "ProcessPayment")
        assert len(apps) >= 1

    def test_multiple_lines(self):
        code = """import ProcessPayment
result = ProcessPayment(ctx)
log.Info("done")
"""
        apps = _symbol_appears_in(code, "ProcessPayment")
        assert len(apps) == 2
        usages = {a["usage"] for a in apps}
        assert "import" in usages
        assert "call" in usages

    def test_no_match(self):
        code = "x = 1 + 2"
        assert _symbol_appears_in(code, "ProcessPayment") == []

    def test_line_numbers_correct(self):
        code = "line1\nProcessPayment()\nline3"
        apps = _symbol_appears_in(code, "ProcessPayment")
        assert apps[0]["line"] == 2


# ============================================================
# Helpers: Diff Symbol Extraction
# ============================================================

class TestExtractSymbolsFromDiff:

    def test_added_function(self):
        diff = """+func NewHandler(w http.ResponseWriter) {
+    // ...
+}"""
        syms = _extract_symbols_from_diff(diff)
        assert "NewHandler" in syms

    def test_added_python_def(self):
        diff = """+def process_order(order_id: int):
+    pass"""
        syms = _extract_symbols_from_diff(diff)
        assert "process_order" in syms

    def test_context_lines_ignored(self):
        diff = """ func ExistingFunc() {
+    newLine()
 }"""
        syms = _extract_symbols_from_diff(diff)
        assert "ExistingFunc" not in syms

    def test_multiple_symbols(self):
        diff = """+func Foo() {
+}
+func Bar() {
+}"""
        syms = _extract_symbols_from_diff(diff)
        assert "Foo" in syms
        assert "Bar" in syms

    def test_no_symbols(self):
        diff = """+    x := 1
+    y := 2"""
        assert _extract_symbols_from_diff(diff) == []


# ============================================================
# Mock Retriever
# ============================================================

def _make_mock_retriever(chunks=None):
    """
    Build a mock RAGRetriever with a fake unified collection.
    `chunks` is a list of (code, metadata_dict) tuples.
    """
    retriever = MagicMock()
    retriever._collections = {}

    if chunks is None:
        chunks = []

    # Build a fake unified collection
    unified = MagicMock()
    unified.count.return_value = len(chunks)

    def fake_query(**kwargs):
        docs, metas, dists = [], [], []
        where_doc = kwargs.get("where_document", {})
        contains = where_doc.get("$contains", "")
        n = kwargs.get("n_results", 10)
        for code, meta in chunks:
            if contains and contains not in code:
                continue
            docs.append(code)
            metas.append(meta)
            dists.append(0.1)
            if len(docs) >= n:
                break
        return {
            "documents": [docs],
            "metadatas": [metas],
            "distances": [dists],
        }

    unified.query = fake_query
    retriever._unified = unified

    # search_code returns formatted results
    def fake_search(query, n_results=10, repo_filter=None, language_filter=None):
        results = []
        for code, meta in chunks:
            results.append({
                "code": code,
                "repo": meta.get("repo", "unknown"),
                "file": meta.get("file", "unknown"),
                "language": meta.get("language", "GO"),
                "distance": 0.1,
                "chunk_idx": 0,
                "total_chunks": 1,
                "collection": "unified_code",
                "hybrid_score": 0.1,
                "keyword_boost": 0,
            })
            if len(results) >= n_results:
                break
        return results

    retriever.search_code = fake_search
    return retriever


# ============================================================
# Core: analyze_impact
# ============================================================

class TestAnalyzeImpact:

    def test_empty_symbol_returns_error(self):
        retriever = _make_mock_retriever()
        result = analyze_impact(retriever, "")
        assert "error" in result

    def test_whitespace_symbol_returns_error(self):
        retriever = _make_mock_retriever()
        result = analyze_impact(retriever, "   ")
        assert "error" in result

    def test_finds_definition(self):
        chunks = [
            ("func ProcessPayment(ctx context.Context) error {\n    return nil\n}",
             {"repo": "payments", "file": "handler.go", "language": "GO"}),
        ]
        retriever = _make_mock_retriever(chunks)
        result = analyze_impact(retriever, "ProcessPayment")

        assert result["symbol"] == "ProcessPayment"
        assert len(result["definition_sites"]) >= 1
        assert result["definition_sites"][0]["repo"] == "payments"

    def test_finds_callers(self):
        chunks = [
            ("func ProcessPayment(ctx context.Context) error {\n    return nil\n}",
             {"repo": "payments", "file": "handler.go", "language": "GO"}),
            ("func main() {\n    err := ProcessPayment(ctx, 100)\n    log.Print(err)\n}",
             {"repo": "gateway", "file": "main.go", "language": "GO"}),
        ]
        retriever = _make_mock_retriever(chunks)
        result = analyze_impact(retriever, "ProcessPayment")

        assert len(result["impact"]) >= 1
        caller = result["impact"][0]
        assert caller["repo"] == "gateway"
        assert "call" in caller["usage_types"]

    def test_cross_repo_impact(self):
        chunks = [
            ("func SendMessage(msg string) {}",
             {"repo": "messaging-core", "file": "send.go", "language": "GO"}),
            ("import (\n    \"messaging-core\"\n)\nfunc relay() {\n    SendMessage(\"hello\")\n}",
             {"repo": "rcs-sender", "file": "relay.go", "language": "GO"}),
            ("err := SendMessage(payload)\nif err != nil { return err }",
             {"repo": "whatsapp-sender", "file": "dispatch.go", "language": "GO"}),
        ]
        retriever = _make_mock_retriever(chunks)
        result = analyze_impact(retriever, "SendMessage")

        summary = result["summary"]
        assert summary["total_affected_repos"] >= 2
        affected_repos = summary["repos"]
        assert "rcs-sender" in affected_repos or "whatsapp-sender" in affected_repos

    def test_summary_structure(self):
        chunks = [
            ("func Foo() {}", {"repo": "a", "file": "x.go", "language": "GO"}),
            ("Foo()\nFoo()", {"repo": "b", "file": "y.go", "language": "GO"}),
        ]
        retriever = _make_mock_retriever(chunks)
        result = analyze_impact(retriever, "Foo")

        assert "symbol" in result
        assert "definition_sites" in result
        assert "impact" in result
        assert "summary" in result
        assert "time_ms" in result
        assert isinstance(result["time_ms"], int)

    def test_no_matches(self):
        retriever = _make_mock_retriever([
            ("x := 1 + 2", {"repo": "a", "file": "a.go", "language": "GO"})
        ])
        result = analyze_impact(retriever, "NonExistentSymbol")
        assert result["impact"] == []
        assert result["summary"]["total_affected_repos"] == 0

    def test_repo_filter(self):
        chunks = [
            ("func Foo() {}", {"repo": "a", "file": "x.go", "language": "GO"}),
            ("Foo()", {"repo": "b", "file": "y.go", "language": "GO"}),
        ]
        retriever = _make_mock_retriever(chunks)
        result = analyze_impact(retriever, "Foo", repo_filter="a")
        assert result["symbol"] == "Foo"

    def test_include_definitions_false(self):
        chunks = [
            ("func Foo() {}", {"repo": "a", "file": "x.go", "language": "GO"}),
        ]
        retriever = _make_mock_retriever(chunks)
        result = analyze_impact(retriever, "Foo", include_definitions=False)
        assert result["definition_sites"] == []

    def test_include_semantic_false(self):
        chunks = [
            ("func Foo() {}", {"repo": "a", "file": "x.go", "language": "GO"}),
            ("Foo()", {"repo": "b", "file": "y.go", "language": "GO"}),
        ]
        retriever = _make_mock_retriever(chunks)
        result = analyze_impact(retriever, "Foo", include_semantic=False)
        assert result["symbol"] == "Foo"


# ============================================================
# Core: analyze_diff_impact
# ============================================================

class TestAnalyzeDiffImpact:

    def test_diff_with_new_function(self):
        diff = """+func NewHandler(w http.ResponseWriter) {
+    fmt.Fprintln(w, "ok")
+}"""
        chunks = [
            ("func NewHandler(w http.ResponseWriter) {\n    fmt.Fprintln(w, \"ok\")\n}",
             {"repo": "api", "file": "handler.go", "language": "GO"}),
            ("NewHandler(w)",
             {"repo": "router", "file": "routes.go", "language": "GO"}),
        ]
        retriever = _make_mock_retriever(chunks)
        result = analyze_diff_impact(retriever, diff)

        assert "NewHandler" in result["changed_symbols"]
        assert "per_symbol" in result
        assert "NewHandler" in result["per_symbol"]

    def test_empty_diff(self):
        retriever = _make_mock_retriever()
        result = analyze_diff_impact(retriever, "")
        assert result["changed_symbols"] == []
        assert "note" in result

    def test_diff_no_functions(self):
        diff = """+    timeout := 60
+    retries := 3"""
        retriever = _make_mock_retriever()
        result = analyze_diff_impact(retriever, diff)
        assert result["changed_symbols"] == []

    def test_aggregate_summary(self):
        diff = "+func Alpha() {\n+}\n+func Beta() {\n+}"
        chunks = [
            ("func Alpha() {}", {"repo": "a", "file": "a.go", "language": "GO"}),
            ("Alpha()", {"repo": "b", "file": "b.go", "language": "GO"}),
            ("func Beta() {}", {"repo": "c", "file": "c.go", "language": "GO"}),
            ("Beta()", {"repo": "d", "file": "d.go", "language": "GO"}),
        ]
        retriever = _make_mock_retriever(chunks)
        result = analyze_diff_impact(retriever, diff)

        assert "Alpha" in result["changed_symbols"]
        assert "Beta" in result["changed_symbols"]
        agg = result["aggregate_summary"]
        assert agg["total_affected_repos"] >= 1


# ============================================================
# Edge Cases
# ============================================================

class TestEdgeCases:

    def test_symbol_with_special_regex_chars(self):
        retriever = _make_mock_retriever([
            ("fmt.Println(x)", {"repo": "a", "file": "a.go", "language": "GO"})
        ])
        result = analyze_impact(retriever, "fmt.Println")
        assert "error" not in result

    def test_very_long_code_chunk(self):
        big_code = "func Foo() {\n" + "    x := 1\n" * 500 + "}\n" + "Foo()\n"
        retriever = _make_mock_retriever([
            (big_code, {"repo": "a", "file": "big.go", "language": "GO"})
        ])
        result = analyze_impact(retriever, "Foo")
        assert result["symbol"] == "Foo"

    def test_unicode_in_code(self):
        code = 'def greet():\n    print("Héllo wörld")\n'
        retriever = _make_mock_retriever([
            (code, {"repo": "a", "file": "a.py", "language": "PY"})
        ])
        result = analyze_impact(retriever, "greet")
        assert result["symbol"] == "greet"

    def test_python_multiline_code(self):
        code = """
from payments import ProcessPayment

class OrderHandler:
    def handle(self, order):
        result = ProcessPayment(order.amount)
        return result
"""
        apps = _symbol_appears_in(code, "ProcessPayment")
        usages = {a["usage"] for a in apps}
        assert "import" in usages
        assert "call" in usages
