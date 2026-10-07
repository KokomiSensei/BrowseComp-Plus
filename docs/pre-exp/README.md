# 信息检索 agent 预实验调查

调查日期：2026-10-06；仓库版本：`b07df59`。仅调查、只读统计；未调用模型、启动服务或运行付费实验。各问答正文均控制在 200 字以内。

## 1. 总体方案是什么？

保留仓库已有 agent loop 和 BM25／FAISS 排序；在工具层接入自有正文库。先固定各正文版本共同可读的 docid，筛选证据齐全的问题，再生成选题 TSV。每种正文版本用独立输出目录，保持模型、提示词、检索参数和题目集合一致。

依据与接入细节：[agent-integration.md](agent-integration.md)、[data-coverage.md](data-coverage.md)。

## 2. 怎样选择 agent 端点和多个正文工具？

先确认端点协议。支持 Responses：沿用 OpenAI／OSS loop，扩展工具定义与分派。支持 Chat Completions：优先评估 Qwen＋MCP 路线，或参数化 GLM 客户端。多正文工具可注册在同一 MCP 服务；若比较正文版本，建议分组运行，每组只开放对应版本工具。

依据：[agent-integration.md](agent-integration.md)。

## 3. 怎样避免子集之外的正文影响实验？

自带 search 会返回索引正文片段，只替换 get_document 不够。保留排序，但让 search 片段也来自当前正文库；无正文时返回明确不可读状态。是否过滤并补足候选会改变检索行为，须提前固定。若返回纯 docid，则同步调整工具说明和提示词。

依据：[工具片段生成](../../searcher/tools.py#L40)、[BM25 返回正文](../../searcher/searchers/bm25_searcher.py#L42)。

## 4. 如何排除本地数据不全的问题？

发现候选库 `../HTML-to-MD/data`：Turndown 与 Jina 共同非空的文档可覆盖 575/830 题。设 S 为各版本共同可读 docid，保守保留证据与 gold 并集完全包含于 S 的题。还需核查对象可读和内容保真；重抓取或转换可能丢失答案，不能保证每题可解。

统计、候选本地库和筛选规则：[data-coverage.md](data-coverage.md)。

## 5. 怎么指定题目并运行测试？

从解密 JSONL 提取选中的原 query_id 与 query，写成无表头的两列 TSV，再传 --query。首轮只选少量题、低并发，确认所有正文工具、轨迹和评估都正常后再扩大。不要用裸 --query 文本做正式评测：其 query_id 为空，无法正常对齐标准答案。

可执行命令与前提：[agent-integration.md](agent-integration.md)。

## 6. 轨迹和评估需要特别核对什么？

检查每道选题都有最终 run 与 eval，失败也计入计划题数；内置 Accuracy 只统计实际处理结果，跳过错误会抬高分数。内置 Recall 统计搜索命中的 evidence 覆盖，不等于正文读取覆盖。保存选题、正文 profile、端点模型、参数和失败清单；改配置时新建目录，避免缓存混用。

记录字段、judge、指标及续跑行为：[trajectory-evaluation.md](trajectory-evaluation.md)。

## 7. 当前还需确定哪些输入？

需要确定正文库位置及各版本 profile、模型端点协议与鉴权、待测题目清单。已添加可配置的 Chat Completions 客户端和 SDK 正文 searcher 示例；正式运行前核对依赖、索引和正文可读性。

实现与命令：[custom-example.md](custom-example.md)（2026-10-07）。

已验证的 Atria 模型端点配置：[atria-endpoint.md](atria-endpoint.md)。

## 分工与来源

三个 sub agent 分别调查工具接入、数据覆盖、轨迹评估；主 agent 核验协议边界、正文可见范围与评估分母，并汇总方案。代码事实以本地版本为准，数据定义另核对官方 [问题数据卡](https://huggingface.co/datasets/Tevatron/browsecomp-plus) 与 [语料数据卡](https://huggingface.co/datasets/Tevatron/browsecomp-plus-corpus)。
