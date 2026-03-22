# Filling in GitHub’s “About” section

The **About** area (right sidebar on `github.com/you/code-atlas`) is set in the **web UI** (or GitHub CLI), not by a special file in the repo.

## In the browser

1. Open **https://github.com/Niranjan-tiwari/code-atlas**
2. Click **⚙ Settings** (repo settings)
3. Under **General**, find **Repository name** / **Description**
4. Paste **Description** (≤350 characters), e.g.:

   ```text
   Multi-repo semantic search & RAG (ChromaDB + LLMs), parallel GitLab automation, REST API & dashboard. Python.
   ```

5. **Website** (optional): your portfolio or docs URL
6. Save, then on the **Code** tab click **⚙** next to **About** to add **Topics** and enable **Releases** / **Packages** if you want

### Suggested topics

Add any that fit (helps discovery):

`python` · `rag` · `chromadb` · `semantic-search` · `gitlab` · `llm` · `langchain` · `code-search` · `developer-tools` · `multi-repo`

## With GitHub CLI (`gh`)

```bash
gh repo edit Niranjan-tiwari/code-atlas \
  --description "Multi-repo semantic search & RAG (ChromaDB + LLMs), parallel GitLab automation, REST API & dashboard." \
  --add-topic python --add-topic rag --add-topic chromadb --add-topic gitlab --add-topic llm
```

Optional homepage:

```bash
gh repo edit Niranjan-tiwari/code-atlas --homepage "https://github.com/Niranjan-tiwari"
```
