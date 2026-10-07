#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

# .env uses KEY=value lines. Export sourced entries so uv and its child Python inherit them.
if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

: "${ATRIA_API_KEY:?Set ATRIA_API_KEY in .env or export it in your shell}"

uv run search_agent/custom_agent.py \
  --model Atria-Dawn-Preview \
  --base-url https://discovery-api.intern-ai.org.cn/v1 \
  --api-key-env ATRIA_API_KEY \
  --searcher-type custom --ranking-searcher faiss \
  --index-path 'indexes/qwen3-embedding-8b/corpus.shard*.pkl' \
  --model-name Qwen/Qwen3-Embedding-8B --normalize \
  --corpus-data-dir ../HTML-to-MD/data \
  --document-type turndown --document-profile default-v1 \
  --num-threads 1 --k 5 --snippet-max-tokens 512 \
  --max_tokens 20000 --max-iterations 100 \
  --output-dir runs/custom/atria-turndown-smoke \
  --query-template QUERY_TEMPLATE \
  --query queries/test.tsv
