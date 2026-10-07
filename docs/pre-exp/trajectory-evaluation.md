# 轨迹采集与评估

调查日期：2026-10-06；只读检查，未调用 API。每问正文不超过 200 字，来源另列。

## 1. 轨迹记录什么，loop 有何区别？

每题结束写 `run_<时间>.json`：配置、题号、状态、工具次数、检索 docid，及顺序排列的 reasoning/tool_call/output_text；工具项含名称、参数、返回值。OpenAI/GLM/OSS 在本地逐轮调用；Qwen 用 Qwen-Agent，Gemini 用 SDK，OpenAI/Anthropic MCP 用远端工具循环。轨迹经过标准化，并非完整请求日志。

来源：[OpenAI 记录](../../search_agent/openai_client.py#L295)、[Qwen loop](../../search_agent/qwen_client.py#L217)、[Gemini](../../search_agent/gemini_client.py#L60)、[远端 MCP](../../search_agent/openai_client_with_mcp.py#L223)。

## 2. 预算、失败记录和续跑可靠吗？

OpenAI/GLM 按累计输出预算；OSS 每轮预算，纯 reasoning 分支不增加轮数。token 统计不统一。轨迹只在题末保存；续跑凭已有 query_id 跳题，失败记录也跳过，不能题内恢复。OpenAI 请求异常不落盘，工具异常反馈模型但错误详情未保存。建议用独立目录重跑失败题，避免重复计分。

来源：[OpenAI 预算/错误](../../search_agent/openai_client.py#L193)、[OSS loop](../../search_agent/oss_client.py#L148)、[续跑](../../search_agent/openai_client.py#L413)。

## 3. judge 如何评分与配置端点？

只评分 completed 且末项是非空答案的轨迹；judge 比较参考答案语义，不核验正文。`evaluate_run.py` 用 vLLM 本地加载 Qwen3-32B。`evaluate_with_openai.py` 默认 gpt-4.1，用 OPENAI_API_KEY；无端点参数，本地 SDK 支持 OPENAI_BASE_URL。API 评估另计费，无 judge 用量记录。

来源：[答案选择](../../scripts_evaluation/evaluate_run.py#L517)、[本地 judge](../../scripts_evaluation/evaluate_run.py#L469)、[API judge](../../scripts_evaluation/evaluate_with_openai.py#L444)；本地 SDK `openai/_client.py:150`。

## 4. Accuracy 的分母是什么？

分母是实际进入 all_results 的评估文件数，含缓存、不完整回答和 judge 解析失败；不是计划题数，也不按 query_id 去重。损坏 JSON、无参考答案、judge 调用异常被跳过，可能抬高 Accuracy。报告应另列计划数、落盘数、评估数和失败数，并保证每题一个 run。

来源：[加载/过滤](../../scripts_evaluation/evaluate_run.py#L499)、[judge 异常](../../scripts_evaluation/evaluate_run.py#L593)、[Accuracy](../../scripts_evaluation/evaluate_run.py#L704)。

## 5. Retrieval Recall 衡量什么？

每题为「累计返回的去重 docid ∩ evidence」/ evidence 数，再对题平均。通用提取器仅扫描名称含 search/retrieval 的工具；get_document 正文读取不计入。默认只用 qrel_evidence，不用 qrel_golds，所以 Recall 不代表读到正文或可回答。缺 evidence 会除零，需预检。

来源：[docid 提取](../../search_agent/utils.py#L6)、[recall](../../scripts_evaluation/evaluate_run.py#L524)、[题间平均](../../scripts_evaluation/evaluate_run.py#L695)。

## 6. 引用指标怎样计算？

从答案的 `[数字]`、`【数字】` 及列表提取去重 docid，与 evidence 比较 precision/recall。覆盖率以所有评估为分母；平均引用数、引用 precision/recall 仅对有引用的回答计算。它不核验正文是否支持句子，非数字自定义 ID 不适配。

来源：[引用解析/计算](../../scripts_evaluation/evaluate_run.py#L225)、[汇总分母](../../scripts_evaluation/evaluate_with_openai.py#L695)。

## 7. 评估产物、缓存和校准有哪些局限？

输出逐题 `*_eval.json`、`evaluation_summary.json`、`detailed_judge_results.csv`；引用汇总打印到终端。默认复用缓存，`--force` 重评；缓存不校验配置变化，应另设目录。Qwen 默认随机采样。置信度不足 100 条时校准误差写 0；实现还跳过最后分箱，不能据此作可靠校准结论。

来源：[缓存](../../scripts_evaluation/evaluate_run.py#L499)、[产物](../../scripts_evaluation/evaluate_run.py#L785)、[校准阈值](../../scripts_evaluation/evaluate_run.py#L687)、[分箱循环](../../scripts_evaluation/evaluate_run.py#L163)。

评估命令（需本地 GPU 与模型，未执行）：

```bash
.venv/bin/python scripts_evaluation/evaluate_run.py \
  --input_dir runs/pre-exp/CONFIG_NAME \
  --eval_dir evals/pre-exp/CONFIG_NAME \
  --tensor_parallel_size 1 --temperature 0
```

评估会镜像 `runs/` 后的路径；上述结果实际落在 `evals/pre-exp/CONFIG_NAME/pre-exp/CONFIG_NAME/`。若希望结果位于 `evals/pre-exp/CONFIG_NAME/`，将 `--eval_dir` 改为 `evals`。

本地 judge 命令示例（需准备 GPU、模型与已完成的 run；本次未执行）：

```bash
.venv/bin/python scripts_evaluation/evaluate_run.py \
  --input_dir runs/pre-exp/CONFIG_NAME \
  --eval_dir evals/pre-exp \
  --tensor_parallel_size 1 --temperature 0
```

评估目录会镜像输入路径，实际保存位置以启动输出为准；换 judge 或数据配置时更换 `--eval_dir`。
