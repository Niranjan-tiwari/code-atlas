"""
Test Generator: Find untested functions and generate test stubs/full tests.
Uses RAG to find existing test patterns and generates matching tests.
"""

import re
import logging
from typing import Dict, List, Optional

logger = logging.getLogger("test_generator")


def generate_tests(retriever, repo_name: str, file_path: str = "") -> dict:
    """
    Generate tests for a repo or specific file.
    
    Args:
        retriever: RAGRetriever instance
        repo_name: Repository name
        file_path: Optional specific file to generate tests for
    """
    if not repo_name:
        return {"error": "Missing repo_name"}
    
    # Find functions in the repo
    functions = retriever.search_code("func ", n_results=15, repo_filter=repo_name)
    
    # Find existing tests
    tests = retriever.search_code("func Test", n_results=10, repo_filter=repo_name)
    
    # Extract function signatures
    func_sigs = []
    for r in functions:
        code = r.get("code", "")
        fpath = r.get("file", "")
        
        if file_path and file_path not in fpath:
            continue
        if "_test.go" in fpath:
            continue
        
        for match in re.finditer(r'func\s+(?:\([^)]+\)\s+)?(\w+)\s*\(([^)]*)\)\s*(?:(\([^)]*\)|[^{]*))?{', code):
            name = match.group(1)
            params = match.group(2)
            returns = (match.group(3) or "").strip()
            
            if name[0].isupper():  # Only exported functions
                func_sigs.append({
                    "name": name,
                    "params": params.strip(),
                    "returns": returns,
                    "file": fpath
                })
    
    # Check which functions already have tests
    tested_funcs = set()
    for r in tests:
        code = r.get("code", "")
        for match in re.finditer(r'func\s+Test(\w+)', code):
            tested_funcs.add(match.group(1))
    
    # Find untested functions
    untested = [f for f in func_sigs if f["name"] not in tested_funcs and f"Test{f['name']}" not in tested_funcs]
    
    # Generate test stubs
    generated = []
    for func in untested[:10]:
        test_code = _generate_go_test(func, tests)
        generated.append({
            "function": func["name"],
            "source_file": func["file"],
            "test_file": func["file"].replace(".go", "_test.go"),
            "test_code": test_code
        })
    
    # Try LLM-powered test generation
    llm_tests = []
    try:
        import os
        if os.environ.get("SKIP_LLM"):
            raise RuntimeError("LLM skipped")
        from src.ai.llm.manager import LLMManager
        llm = LLMManager()
        if llm.get_available_providers() and untested:
            func = untested[0]
            # Get function code for context
            func_code = ""
            for r in functions:
                if func["name"] in r.get("code", ""):
                    func_code = r["code"][:500]
                    break
            
            existing_test = tests[0]["code"][:300] if tests else ""
            
            prompt = f"""Generate a Go test for this function. Match the testing style of the codebase.

Function:
{func_code}

Existing test style:
{existing_test}

Generate a complete test function with table-driven tests if appropriate."""
            
            response = llm.generate(prompt, max_tokens=500, temperature=0.3)
            llm_tests.append({
                "function": func["name"],
                "test_code": response.content,
                "model": response.model
            })
    except Exception:
        pass
    
    return {
        "repo": repo_name,
        "total_functions": len(func_sigs),
        "tested_functions": len(tested_funcs),
        "untested_functions": len(untested),
        "coverage_pct": round(len(tested_funcs) / max(len(func_sigs), 1) * 100, 1),
        "generated_stubs": generated,
        "llm_tests": llm_tests,
        "untested": [{"name": f["name"], "file": f["file"]} for f in untested[:20]]
    }


def _generate_go_test(func: dict, existing_tests: list) -> str:
    """Generate a Go test stub"""
    name = func["name"]
    params = func["params"]
    returns = func["returns"]
    
    test = f"""func Test{name}(t *testing.T) {{
\ttests := []struct {{
\t\tname string
\t\t// TODO: add test fields
\t}}{{
\t\t{{"basic test"}},
\t}}
\t
\tfor _, tt := range tests {{
\t\tt.Run(tt.name, func(t *testing.T) {{
\t\t\t// TODO: call {name}() and assert results
\t\t}})
\t}}
}}"""
    return test
