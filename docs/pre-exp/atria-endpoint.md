# Atria 端点配置

## 1. 端点和模型怎样配置？

使用 `https://discovery-api.intern-ai.org.cn/v1`，模型名为 `Atria-Dawn-Preview`。已通过实际鉴权和 Chat Completions 工具循环验证。用户提供的限制为 512k 上下文、64k 输出，尚未独立验证；无需改用 Responses 客户端。

## 2. 密钥与预算怎样设置？

在用户终端设置并导出 `ATRIA_API_KEY`，命令只传 `--api-key-env ATRIA_API_KEY`。普通 `. .env` 不保证导出变量；当前 smoke 脚本已自动用 `set -a` 加载 `.env`。`--max_tokens` 是 loop 的累计输出预算，不设上下文窗口。

在仓库根目录的终端输入密钥；下面命令不会打印密钥：

```bash
read -rsp 'ATRIA_API_KEY: ' ATRIA_API_KEY
export ATRIA_API_KEY
```

## 3. 怎样选题？

从共同覆盖清单选择原 query_id，再从 `queries.tsv` 提取两列题表。下例取前 3 题用于小样本，保留原 ID，不读取答案；正式实验可换成自己的 ID 清单，并检查所用正文版本的覆盖。已有覆盖清单不保证网页正文保留答案。

```bash
.venv/bin/python - <<'PY'
import csv
from pathlib import Path

root = Path('docs/pre-exp')
ids = (root / 'eligible-common.txt').read_text().splitlines()[:3]
with open('topics-qrels/queries.tsv', newline='', encoding='utf-8') as f:
    queries = {qid: question for qid, question in csv.reader(f, delimiter='\t')}
assert all(qid in queries for qid in ids), '题表缺少指定 query_id'
with (root / 'atria-smoke.tsv').open('w', newline='', encoding='utf-8') as f:
    csv.writer(f, delimiter='\t').writerows((qid, queries[qid]) for qid in ids)
print('已生成', len(ids), '题')
PY
```

## 4. 怎样组合 dense 检索与 SDK 正文？

使用已有 FAISS dense 排序，正文通过 SDK 按 docid 读取；固定 type/profile，单线程运行所选题表。每次配置使用独立输出目录，避免续跑跳过旧记录。下例为 Turndown 正文；Jina 对照只替换正文类型、profile 和输出目录。

在依赖、embedding 模型和索引就绪后运行：

```bash
.venv/bin/python search_agent/custom_agent.py \
  --model Atria-Dawn-Preview \
  --base-url https://discovery-api.intern-ai.org.cn/v1 \
  --api-key-env ATRIA_API_KEY \
  --searcher-type custom --ranking-searcher faiss \
  --index-path 'indexes/qwen3-embedding-8b/corpus.shard*.pkl' \
  --model-name Qwen/Qwen3-Embedding-8B --normalize \
  --corpus-data-dir ../HTML-to-MD/data \
  --document-type turndown --document-profile default-v1 \
  --query docs/pre-exp/atria-smoke.tsv \
  --query-template QUERY_TEMPLATE \
  --num-threads 1 --k 5 --snippet-max-tokens 512 \
  --max_tokens 20000 --max-iterations 100 \
  --output-dir runs/custom/atria-turndown-smoke
```

Jina 对照替换：

```text
--document-type jina --document-profile jina-reader@15bad24f884f
--output-dir runs/custom/atria-jina-smoke
```

相关说明：[自定义实验](custom-example.md)、[正文覆盖](data-coverage.md)、[轨迹评估](trajectory-evaluation.md)。本文件未包含密钥。

## 5. 实际验证了什么，需要什么兼容修改？

2026-10-07 用测试文档验证工具调用→执行→回传→最终回答，两轮成功，输出67 token。Atria 的工具响应带 tool_calls，但 finish_reason 为 stop；已修改 custom_agent 按实际调用继续执行，并新增回归测试。12个离线测试通过；未运行正式题目或大上下文测试。

来源：[工具调用判断](../../search_agent/custom_agent.py#L225)、[回归测试](../../tests/test_custom_experiment.py)。密钥仅用于测试进程内存，不保存到配置、轨迹或此文档。

## 6. 失败为何曾返回 shell 成功？

客户端已把 API 异常保存为 `status=error`，但原批处理会吞掉异常、返回0；重跑还会跳过该失败题。现在 smoke 脚本导出 `.env` 并在缺 key 时早停，agent 对失败题返回非零，并将旧失败记录移到 `failed_attempts/` 后重试。

## 7. 如何用远程 API judge？

复制 `evaluate_with_openai.py` 的评分、Recall、引用计算与汇总流程，新增 [Chat Completions 版本](../../scripts_evaluation/evaluate_with_chat_completions.py)。它默认使用 Atria judge；单题校准误差显示“未计算”。本次同一 Atria 模型既生成又评分，结果适合冒烟验证，不宜当独立 judge 对比。

```bash
set -a; source .env; set +a
.venv/bin/python scripts_evaluation/evaluate_with_chat_completions.py \
  --input_dir runs/custom/atria-turndown-smoke \
  --eval_dir evals/pre-exp/atria-remote --temperature 0
```

本次结果：[汇总 JSON](../../evals/pre-exp/atria-remote/custom/atria-turndown-smoke/evaluation_summary.json)、[逐题 judge 记录](../../evals/pre-exp/atria-remote/custom/atria-turndown-smoke/run_20261007T113908987457Z_eval.json)。
