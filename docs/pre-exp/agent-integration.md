# Agent 与工具接入

调查范围：仓库现有实现；未调用模型 API、未修改实验代码。未发现适用的 `AGENTS.md`。

## 1. 怎样配置端点并复用预定义 loop？

先确认端点协议。Responses 用 OpenAI/OSS loop；Chat Completions 可复用 GLM loop，需参数化其硬编码端点与密钥；Qwen 路线已有 `--model-server` 和 MCP，但密钥固定为 `EMPTY`。不要将“OpenAI 兼容”直接等同于支持 Responses。loop 均可保留。

依据：[Responses loop](../../search_agent/openai_client.py#L171)、[OSS 端点及固定密钥](../../search_agent/oss_client.py#L508)、[GLM loop](../../search_agent/glm_zai_client.py#L112)、[GLM 固定端点](../../search_agent/glm_zai_client.py#L463)、[Qwen 配置](../../search_agent/qwen_client.py#L24)。

## 2. 怎样加入多个 docid 正文工具，保留自带排序？

单一正文工具可实现 `CustomSearcher`，将 `search` 委托给 BM25/FAISS，仅替换 `get_document`。多个独立工具需扩展客户端 handler 的定义与分派；或在本地 MCP 服务注册多个正文工具，再用 Qwen 客户端发现。现有 CLI 只提供可选的 `get_document`，不是任意工具插件配置。

依据：[自定义接口](../../searcher/searchers/custom_searcher.py#L13)、[工具定义与分派](../../search_agent/openai_client.py#L40)、[MCP 注册](../../searcher/tools.py#L8)、[Qwen MCP](../../search_agent/qwen_client.py#L43)。返回格式以实现为准：检索候选 `{"docid","score","text"}`，正文 `{"docid","text"}`；基类注释中的 `snippet` 与实际实现不一致。

## 3. 怎样保证正文子集实验不被完整数据绕过？

只替换正文工具不够：自带 `search` 会从完整索引或语料读取正文并输出摘要。建议保留排序和 docid，但摘要仅由本地正文生成；缺失正文返回明确不可用状态。若过滤候选或扩大召回补足 top-k，会改变检索条件，应固定并记录规则。所有正文工具须使用一致的可用文档集合。

依据：[BM25 返回正文](../../searcher/searchers/bm25_searcher.py#L43)、[FAISS 载入语料](../../searcher/searchers/faiss_searcher.py#L208)、[FAISS 返回正文](../../searcher/searchers/faiss_searcher.py#L281)、[摘要输出](../../searcher/tools.py#L34)。`--snippet-max-tokens -1` 会输出完整正文，不能用于阻断泄漏。

## 4. 怎样指定一系列问题并开始测试？

从原始题表按 query_id 导出无表头的两列 TSV（ID、问题），以 `--query 子集.tsv` 运行；没有直接的 ID 列表参数。正文实验启用 `--get-document`，并选择 `QUERY_TEMPLATE`，默认提示只要求搜索。每个配置使用独立输出目录；续跑按已有 query_id 跳过，连不完整结果也会跳过。

依据：[TSV 读取与续跑](../../search_agent/openai_client.py#L394)、[正文开关](../../search_agent/openai_client.py#L585)、[提示模板](../../search_agent/prompts.py#L1)。多个新工具应同步调整提示中的名称及描述，保留 `Exact Answer` 等回答格式。

现有 Qwen 接口示例（仅展示参数，多个正文工具及摘要适配尚未实现）：

```bash
.venv/bin/python searcher/mcp_server.py \
  --searcher-type bm25 --index-path /path/to/bm25 \
  --get-document --transport streamable-http --port 8080

.venv/bin/python search_agent/qwen_client.py \
  --model MODEL_NAME --model-server http://MODEL_HOST:8000/v1 \
  --mcp-url http://127.0.0.1:8080/mcp \
  --query docs/pre-exp/selected-queries.tsv \
  --query-template QUERY_TEMPLATE --output-dir runs/pre-exp/CONFIG_NAME
```

题表、索引及端点为待配置项。本地没有 BM25 索引，当前 shell 也找不到 Java；上述 BM25 示例需先准备索引及 Java 21。多工具及摘要适配完成后可沿用客户端命令；认证端点需先修改固定密钥。
