# Implementing Your Own Retriever

If you wish to plug your own retriever and into search agents already implemented in this repo, you may simply create a new searcher class that inherits from `BaseSearcher` in `searcher/searchers/base.py`.

`searcher/searchers/custom_searcher.py` now contains a working HTML-to-MD example: it delegates ranking to BM25/FAISS and reads snippets and full documents from a fixed local Corpus type/profile. See [the custom agent example](pre-exp/custom-example.md) for endpoint configuration and runnable commands. To implement another searcher, provide these methods:

- `__init__`: Initialize the searcher from `args` passed from the command line.
- `parse_args`: Parse the arguments your searcher needs from the command line (e.g., `parser.add_argument("--my-arg", type=str, default="default_value")`).
- `search`: Perform a search from a query, and return a list of documents.
- `get_document`: Get a complete document by its docid.
- `search_type`: Get the type of the searcher.
- `search_description`: The prompt to be passed to the LLM describing the search tool.
- `get_document_description`: The prompt to be passed to the LLM describing the get_document tool.

Then, for any command described in the docs, you may simply replace the `--searcher-type` argument with `custom`, and pass in the arguments your searcher needs.

For example, instead of running:
```bash
python search_agent/oss_client.py --model openai/gpt-oss-120b --searcher-type bm25 --index-path indexes/bm25/
```
you may run:
```bash
.venv/bin/python search_agent/custom_agent.py --model YOUR_MODEL \
  --base-url http://127.0.0.1:8000/v1 \
  --searcher-type custom --ranking-searcher bm25 --index-path indexes/bm25/ \
  --corpus-data-dir ../HTML-to-MD/data \
  --document-type turndown --document-profile default-v1
```

This BM25 example requires a prepared index and Java 21; the linked guide uses the existing dense index instead. The custom agent preserves structured SDK errors and profile metadata in search results. Other clients' existing search handlers may discard those extra fields.
