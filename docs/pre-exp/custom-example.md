# 自定义正文实验示例

## 1. 新增客户端复用了什么？

`custom_agent.py` 从 GLM 客户端复制工具 handler 和 Chat Completions 循环，参数化端点与密钥；默认开启 `get_document`，使用含正文工具的提示模板。端点须支持 Chat Completions 工具调用，单纯支持 Responses 不适用。

依据：[循环](../../search_agent/custom_agent.py#L118)、[默认参数](../../search_agent/custom_agent.py#L423)。

## 2. 正文和排序如何组合？

`custom_searcher.py` 使用项目自带 BM25/FAISS 排序，通过 `html_to_md` 按 docid 读取正文。每次 run 固定 type/profile；search 摘要与 get_document 来自同一正文版本。缺正文保留原排名并返回错误，不补足候选、不回退原始语料；FAISS 排序器不加载原始正文库。

依据：[FAISS 排序适配](../../searcher/searchers/custom_searcher.py#L18)、[正文读取](../../searcher/searchers/custom_searcher.py#L87)、[摘要保留错误及来源](../../search_agent/custom_agent.py#L100)。

## 3. 怎样配置认证与比较正文版本？

`--base-url` 指向模型 API 的 `/v1`，`--api-key-env` 默认读取 `OPENAI_API_KEY`，也可指定其他环境变量名；没有密钥时用 `EMPTY`。比较正文版本时固定模型、题表、排序和预算，只替换 type/profile，并使用独立输出目录。

依据：[客户端认证](../../search_agent/custom_agent.py#L506)、[保存实验配置](../../search_agent/custom_agent.py#L311)。

## 4. 怎样准备共同覆盖题表？

`eligible-common.txt` 包含 Turndown 与主要 Jina 共同覆盖的 575 个原 query_id。按这些 ID 从 `queries.tsv` 提取无表头两列题表，保留原 ID，不能重新编号。下面同时生成全量题表和前 3 题的小样本；覆盖仅说明标注正文非空，不保证内容保真。

在仓库根目录运行；只处理问题文本，不向 agent 传入答案或 qrels：

```bash
.venv/bin/python - <<'PY'
import csv
from pathlib import Path

root = Path('docs/pre-exp')
ids = set((root / 'eligible-common.txt').read_text().splitlines())
with open('topics-qrels/queries.tsv', newline='', encoding='utf-8') as f:
    rows = [row for row in csv.reader(f, delimiter='\t') if row[0] in ids]
assert {row[0] for row in rows} == ids, '题表缺少指定 query_id'
for name, selected in [('selected-common.tsv', rows), ('smoke-common.tsv', rows[:3])]:
    with (root / name).open('w', newline='', encoding='utf-8') as f:
        csv.writer(f, delimiter='\t').writerows(selected)
    print(name, len(selected))
PY
```

## 5. 怎样运行与核对结果？

先用 3 题、单线程检查工具和轨迹；端点、模型与密钥由实际服务提供。下面使用现有 8B dense 索引；全量实验替换题表及输出目录。API 异常也保存为 error。核对每道计划题的 run 与评估结果；续跑会跳过已有 query_id，包括失败记录，重试或改配置须换目录。

先完成依赖安装（`uv sync`，包含相邻项目的 editable 依赖）；将下面端点和模型替换成实际服务。鉴权密钥预先放入环境变量，不写入命令或文档。当前命令读取 `OPENAI_API_KEY`；可替换为 `--api-key-env YOUR_KEY_ENV`。

```bash
.venv/bin/python search_agent/custom_agent.py \
  --model YOUR_MODEL \
  --base-url http://127.0.0.1:8000/v1 \
  --api-key-env OPENAI_API_KEY \
  --searcher-type custom --ranking-searcher faiss \
  --index-path 'indexes/qwen3-embedding-8b/corpus.shard*.pkl' \
  --model-name Qwen/Qwen3-Embedding-8B --normalize \
  --corpus-data-dir ../HTML-to-MD/data \
  --document-type turndown --document-profile default-v1 \
  --query docs/pre-exp/smoke-common.tsv \
  --query-template QUERY_TEMPLATE \
  --num-threads 1 --k 5 --snippet-max-tokens 512 \
  --max_tokens 20000 --max-iterations 100 \
  --output-dir runs/custom/turndown-smoke
```

Jina 对照组替换以下参数，其余保持一致：

```text
--document-type jina --document-profile jina-reader@15bad24f884f
--output-dir runs/custom/jina-smoke
```

全量运行将 `--query` 改为 `docs/pre-exp/selected-common.tsv`，输出分别改为 `runs/custom/turndown-common`、`runs/custom/jina-common`。

评估沿用仓库脚本（会加载 Qwen3-32B judge，需相应 GPU 资源）：

```bash
.venv/bin/python scripts_evaluation/evaluate_run.py \
  --input_dir runs/custom/turndown-smoke --tensor_parallel_size 1
```

轨迹及评估口径见 [trajectory-evaluation.md](trajectory-evaluation.md)。本次未调用模型或运行 judge。

## 6. 以后增加独立正文工具改哪里？

在 `SearchToolHandler.get_tool_definitions()` 声明新工具名和参数，在 `execute_tool()` 分派到 searcher 新方法；该方法再调用 SDK 读取对应 type/profile。同步修改提示里的工具名。当前示例每组固定一个正文版本，便于比较；新增工具无需改动逐轮 Chat Completions 循环。

离线验证：`.venv/bin/python -m unittest discover -s tests -p 'test_custom_experiment.py' -v`，11 个测试通过；未验证真实端点、GPU 检索或 judge 运行。
