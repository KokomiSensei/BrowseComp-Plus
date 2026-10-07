# 本地数据与筛题

统计时间：2026-10-06；采用逐行 JSONL 与 SQLite `mode=ro` 查询，未运行模型或抓取网页。

## 1. BrowseComp-Plus 在本地有哪些数据？

本地解密 JSONL、查询 TSV 均为830题。字段有 `query_id/query/answer` 和 `evidence_docs/gold_docs/negative_docs`；文档项含 `docid/text/url`。缓存语料为100,195篇。证据标注5,064条，gold标注2,407条，均覆盖830题；本地全部gold均属于对应evidence。

| 文件/资源 | 本地统计 |
| --- | --- |
| `data/browsecomp_plus_decrypted.jsonl` | 830题；约2.0 GiB |
| `topics-qrels/queries.tsv` | 830行，无表头，`query_id\tquery` |
| `topics-qrels/qrel_evidence.txt` | 5,064条；5,040个不同docid |
| `topics-qrels/qrel_golds.txt` | 2,407条；2,398个不同docid |
| Hugging Face corpus缓存 | train 100,195行，7个Arrow分片 |
| `indexes/qwen3-embedding-8b/` | 4个pickle向量分片，约1.6 GiB；尚未反序列化核对索引ID；无本地BM25索引 |

来源：[官方数据集](https://huggingface.co/datasets/Tevatron/browsecomp-plus)、[解密脚本](../../scripts_build_index/decrypt_dataset.py)、本地文件流式统计；语料缓存revision为 `b27b02bc3e45511b8b82a13e6f90ce761df726f6`。

## 2. 找到了什么本地正文数据库？

相邻 `../HTML-to-MD/data/metadata.sqlite3` 是候选正文库，尚未由用户确认。SQLite存docid、profile、artifact和质量元数据，正文在`objects/`的zstd对象。100,195个document含1个无效占位；dataset正文100,194篇，缺`10395`，导致题`525`不满足完整证据覆盖。

| 类型 | 完整profile名称 | artifact数 | 非空正文数 | E∪G全覆盖题数 |
| --- | --- | ---: | ---: | ---: |
| dataset | original-v1 | 100,194 | 100,194 | 829 |
| html | original-v1 | 97,893 | 97,893 | 662 |
| turndown | default-v1 | 97,870 | 97,830 | 650 |
| jina | jina-reader@15bad24f884f | 96,846 | 96,846 | 575 |
| jina | default-v1 | 1 | 1 | 0 |
| html | jina-reader@d8f93edfe608 | 2,463 | 2,463 | 112 |
| turndown与主要jina交集 | 上述两个profile | — | 96,824 | 575 |

其他profile `html/jina-reader@f9a92acf9bc9`、`jina/jina-reader@d9cf25b0b021` 尚无artifact；未发现llm profile或artifact。不要以类型默认profile代替已生成的主要jina profile。

来源：[相邻项目读取API](../../../HTML-to-MD/src/html_to_md/corpus.py)、[数据库结构](../../../HTML-to-MD/src/html_to_md/db.py)、候选库只读SQL统计。无效占位为`__html_to_md_invalid_row_1492__`，导入失败原因是URL不是绝对HTTP(S)地址。

## 3. 怎样筛出正文子集覆盖的问题？

每个工具固定type/profile，取有artifact且`raw_size>0`的docid集合S；比较多个工具时用交集。对每题取qrels的E∪G，仅保留非空且完全包含于S的题，再与用户指定qid取交集。使用qrels筛选，问题正文只从查询TSV读取，答案与标注正文不得传给agent。

已生成仅含qid的清单：[dataset 829题](eligible-dataset.txt)、[turndown 650题](eligible-turndown.txt)、[主要jina 575题](eligible-jina.txt)、[共同575题](eligible-common.txt)。[逐题缺失docid表](question-coverage.tsv)空单元格表示覆盖完整；列名`common`指turndown与主要jina交集。

## 4. 完整覆盖能保证题目可解吗？

不能。上述清单只验证标注docid有非空artifact，未逐个验证对象可读或答案保留。重抓页面可能变化、受阻或转换漏内容；原始html中4,371条被标记blocked，仍有成功artifact。正式实验应检查相关对象可读、过滤阻断页并抽查证据；仅覆盖一个gold不能保证多步问题可解。

## 5. 如何从候选库按docid读取正文？

用相邻项目的只读SDK：`Corpus.open(data_dir)`后调用`read_text(docid, type=..., profile=...)`，返回文本并保留原docid。`common_docids([ResourceSpec(...)])`可求profile交集，但未排除空正文。缺文档、未生成和失败分别有异常，工具应明确返回错误并记录type/profile。

来源：[Corpus读取实现](../../../HTML-to-MD/src/html_to_md/corpus.py)。SDK读取对象时验证解压及内容哈希；本次覆盖表仅查元数据，正式筛题可用SDK复核相关正文。

## 6. 统计如何复现？

只读连接候选库，将`documents→artifacts→profiles→objects`关联，按type/name筛选且`raw_size>0`，获得S。逐行读取两个qrels的第一、三列，按qid合并文档集合并检查其是否为S子集。清单仅存qid；实验前按选定profile重新统计，固定数据库快照与语料revision。
