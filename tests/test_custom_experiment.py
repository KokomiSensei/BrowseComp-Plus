"""Offline integration checks; run with unittest discover, without model/network calls."""

import copy
import json
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from html_to_md import db
from html_to_md.errors import ArtifactFailed
from html_to_md.object_store import ObjectStore

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "search_agent"))
sys.path.insert(0, str(ROOT))

from search_agent import custom_agent as agent
from searcher.searchers import custom_searcher as searcher_module

SECRET = "ORIGINAL_RANKER_BODY_MUST_NEVER_REACH_AGENT"


def make_corpus(root):
    """Build a real SDK store, including absent, blank and corrupt artifacts."""
    connection = db.initialize(root)
    connection.execute("INSERT INTO corpora(id,name) VALUES(1,'test')")
    connection.execute(
        "INSERT INTO profiles(id,type,name,config_json,config_hash) "
        "VALUES(1,'dataset','original-v1','{}','fixture')"
    )
    store = ObjectStore(root)
    for ordinal, (docid, text) in enumerate(
        [("1", "LOCAL SDK BODY"), ("2", "   \n"), ("3", None), ("4", "corrupt body")]
    ):
        document_id = ordinal + 1
        connection.execute(
            "INSERT INTO documents(id,corpus_id,docid,ordinal,url) VALUES(?,1,?,?,?)",
            (document_id, docid, ordinal, f"https://example.test/{docid}"),
        )
        if text is None:
            continue
        obj = store.put(text.encode())
        cursor = connection.execute(
            "INSERT INTO objects(sha256,relative_path,codec,raw_size,compressed_size) "
            "VALUES(?,?,?,?,?)",
            (obj.sha256, str(obj.relative_path), obj.codec, obj.raw_size, obj.compressed_size),
        )
        connection.execute(
            "INSERT INTO artifacts(document_id,profile_id,object_id,mime_type) "
            "VALUES(?,1,?,'text/plain')",
            (document_id, cursor.lastrowid),
        )
        if docid == "4":
            store.path_for(obj.sha256).write_bytes(b"invalid zstd payload")
    connection.commit()
    connection.close()


class FakeRanker:
    @classmethod
    def parse_args(cls, parser):
        parser.add_argument("--index-path", default="offline")

    def __init__(self, args=None):
        self.calls = []

    def search(self, query, k):
        self.calls.append((query, k))
        return [
            {"docid": docid, "score": score, "text": SECRET, "snippet": SECRET}
            for docid, score in [("1", 9.5), ("3", 8.0), ("2", 7.0), ("4", 6.0)]
        ][:k]

    def get_document(self, docid):
        raise AssertionError("Original ranker full-text access is forbidden")


class FakeMessage:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls

    def model_dump(self):
        result = {"role": "assistant", "content": self.content}
        if self.tool_calls:
            result["tool_calls"] = [
                {"id": call.id, "type": "function", "function": vars(call.function)}
                for call in self.tool_calls
            ]
        return result


def completion(content=None, tool=None, finish_reason="stop", tokens=3):
    calls = None
    if tool:
        name, arguments = tool
        calls = [SimpleNamespace(id="call-1", function=SimpleNamespace(
            name=name, arguments=json.dumps(arguments))) ]
    return SimpleNamespace(
        choices=[SimpleNamespace(message=FakeMessage(content, calls), finish_reason=finish_reason)],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=tokens, total_tokens=10 + tokens),
    )


class FakeClient:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.requests = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.requests.append(copy.deepcopy(kwargs))
        reply = next(self.replies)
        if isinstance(reply, Exception):
            raise reply
        return reply


class CustomExperimentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        make_corpus(self.root)
        args = SimpleNamespace(
            corpus_data_dir=self.root, corpus_name="test", document_type="dataset",
            document_profile="original-v1", ranking_searcher="bm25",
        )
        with patch.object(searcher_module, "_ranking_class", return_value=FakeRanker):
            self.searcher = searcher_module.CustomSearcher(args)
        self.handler = agent.SearchToolHandler(self.searcher, snippet_max_tokens=-1, k=3)

    def run_loop(self, client, **overrides):
        kwargs = dict(query="Offline question", model="fake-model", max_tokens=30,
                      tool_handler=self.handler, max_iterations=3)
        kwargs.update(overrides)
        return agent.run_conversation_with_tools(client, **kwargs)

    def persist(self, results, usage, reason):
        out = self.root / "runs"
        agent._persist_response(
            str(out), model="fake-model", query_id="769", system_prompt=None,
            max_tokens=30, normalized_results=results, cumulative_usage=usage,
            finish_reason=reason,
        )
        return json.loads(next(out.glob("run_*.json")).read_text())

    def test_search_preserves_rank_and_scores_without_original_body(self):
        results = json.loads(self.handler.execute_tool("search", {"query": "needle"}))
        self.assertEqual(self.searcher.ranking_searcher.calls, [("needle", 3)])
        self.assertEqual([row["docid"] for row in results], ["1", "3", "2"])
        self.assertEqual([row["score"] for row in results], [9.5, 8.0, 7.0])
        self.assertEqual(results[0]["snippet"], "LOCAL SDK BODY")
        self.assertNotIn(SECRET, json.dumps(results))
        self.assertEqual(results[1]["error"]["code"], "artifact_unavailable")
        self.assertEqual(results[2]["error"]["code"], "empty_document")

    def test_faiss_backend_never_loads_original_corpus(self):
        module = ModuleType("searcher.searchers.faiss_searcher")

        class FakeFaissSearcher:
            def __init__(self, args):
                self._load_dataset()

            def _load_dataset(self):
                raise AssertionError("Original corpus loading is forbidden")

            @classmethod
            def parse_args(cls, parser):
                parser.add_argument("--index-path", required=True)
                parser.add_argument("--model-name", required=True)

        module.FaissSearcher = FakeFaissSearcher
        import argparse
        argv = ["custom_agent.py", "--ranking-searcher", "faiss",
                "--index-path", "offline-index", "--model-name", "offline-model"]
        with patch.dict(sys.modules, {module.__name__: module}), patch.object(sys, "argv", argv):
            parser = argparse.ArgumentParser()
            searcher_module.CustomSearcher.parse_args(parser)
            args = parser.parse_args()
            ranker = searcher_module._ranking_class(args.ranking_searcher)(args)
        self.assertEqual(ranker.docid_to_text, {})
        self.assertEqual(args.index_path, "offline-index")
        self.assertEqual(args.model_name, "offline-model")

    def test_document_errors_are_explicit_and_never_fall_back(self):
        for docid, code in [("2", "empty_document"), ("3", "artifact_unavailable"),
                            ("4", "storage_corruption"), ("missing", "document_not_found")]:
            with self.subTest(docid=docid):
                result = json.loads(self.handler.execute_tool("get_document", {"docid": docid}))
                self.assertEqual(result["error"]["code"], code)
                self.assertEqual(result["text"], "")
                self.assertNotIn(SECRET, json.dumps(result))

    def test_threaded_real_sdk_reads_are_sqlite_safe(self):
        with ThreadPoolExecutor(max_workers=6) as executor:
            results = list(executor.map(self.searcher.get_document, ["1"] * 24))
        self.assertTrue(all(result["text"] == "LOCAL SDK BODY" for result in results))

    def test_sdk_failed_artifact_is_exposed(self):
        with patch.object(searcher_module.Corpus, "read_text", side_effect=ArtifactFailed("conversion failed")):
            result = self.searcher.get_document("1")
        self.assertEqual(result["error"]["code"], "artifact_failed")
        self.assertEqual(result["text"], "")

    def test_tool_then_answer_records_rollout_and_cumulative_usage(self):
        first = completion(tool=("search", {"query": "needle"}), finish_reason="tool_calls")
        second = completion(content="Exact Answer: local answer [1]", tokens=5)
        first.usage.completion_tokens_details = SimpleNamespace(reasoning_tokens=1)
        second.usage.completion_tokens_details = SimpleNamespace(reasoning_tokens=2)
        client = FakeClient([first, second])
        results, usage, reason = self.run_loop(client)
        self.assertEqual(reason, "stop")
        self.assertEqual(client.requests[1]["max_tokens"], 27)
        tool_message = next(msg for msg in client.requests[1]["messages"] if msg["role"] == "tool")
        self.assertIn("LOCAL SDK BODY", tool_message["content"])
        self.assertNotIn(SECRET, tool_message["content"])
        run = self.persist(results, usage, reason)
        self.assertEqual(run["status"], "completed")
        self.assertEqual(run["query_id"], "769")
        self.assertEqual(run["tool_call_counts"], {"search": 1})
        self.assertEqual(set(run["retrieved_docids"]), {"1", "2", "3"})
        self.assertEqual(run["result"][-1]["type"], "output_text")
        self.assertEqual(run["usage"]["input_tokens"], 20)
        self.assertEqual(run["usage"]["output_tokens"], 8)
        self.assertEqual(run["usage"]["included_reasoning_tokens"], 3)

    def test_iteration_and_token_exhaustion_are_not_completed(self):
        for budget, iterations in [(30, 1), (3, 3)]:
            with self.subTest(budget=budget, iterations=iterations):
                client = FakeClient([completion(tool=("search", {"query": "needle"}),
                                               finish_reason="tool_calls")])
                results, usage, reason = self.run_loop(client, max_tokens=budget,
                                                       max_iterations=iterations)
                run = self.persist(results, usage, reason)
                self.assertNotEqual(run["status"], "completed")
                self.assertEqual(len(client.requests), 1)

    def test_empty_stop_is_not_completed(self):
        results, usage, reason = self.run_loop(FakeClient([completion(content="")]))
        self.assertNotEqual(self.persist(results, usage, reason)["status"], "completed")

    def test_provider_stop_with_tool_calls_still_executes_tools(self):
        # Atria reports stop together with tool_calls rather than tool_calls.
        client = FakeClient([
            completion(tool=("get_document", {"docid": "1"}), finish_reason="stop"),
            completion(content="Exact Answer: local answer"),
        ])
        results, usage, reason = self.run_loop(client)
        self.assertEqual(len(client.requests), 2)
        tool_message = next(msg for msg in client.requests[1]["messages"] if msg["role"] == "tool")
        self.assertIn("LOCAL SDK BODY", tool_message["content"])
        self.assertEqual(self.persist(results, usage, reason)["status"], "completed")

    def test_length_limit_is_not_completed(self):
        results, usage, reason = self.run_loop(FakeClient([
            completion(content="unfinished answer", finish_reason="length")]))
        self.assertNotEqual(self.persist(results, usage, reason)["status"], "completed")

    def test_batch_api_failure_is_saved_including_threaded_runner(self):
        for threads in (1, 2):
            with self.subTest(threads=threads):
                tsv = self.root / "questions.tsv"
                tsv.write_text("769\tOffline question\n")
                output = self.root / f"failed-{threads}"
                args = SimpleNamespace(
                    output_dir=str(output), model="fake-model", max_tokens=30,
                    system=None, query_template="QUERY_TEMPLATE", temperature=None,
                    top_p=None, max_iterations=3, num_threads=threads,
                )
                client = FakeClient([RuntimeError("offline API failure")])
                agent._process_tsv_dataset(str(tsv), client, args, self.handler)
                run = json.loads(next(output.glob("run_*.json")).read_text())
                self.assertEqual(run["query_id"], "769")
                self.assertEqual(run["status"], "error")
                self.assertEqual(run["result"], [])

    def test_cli_routes_endpoint_to_chat_completions(self):
        client = FakeClient([completion(content="offline answer")])
        args = ["custom_agent.py", "--query", "offline question", "--model", "my-model",
                "--base-url", "http://offline.test/v1", "--api-key-env", "TEST_AGENT_KEY",
                "--ranking-searcher", "bm25", "--corpus-data-dir", str(self.root),
                "--corpus-name", "test", "--document-type", "dataset",
                "--document-profile", "original-v1", "--snippet-max-tokens", "-1",
                "--output-dir", str(self.root / "cli-runs")]
        with patch.object(sys, "argv", args), \
             patch.dict("os.environ", {"TEST_AGENT_KEY": "offline-key"}), \
             patch.object(searcher_module, "_ranking_class", return_value=FakeRanker), \
             patch.object(agent, "OpenAI", return_value=client) as client_factory:
            agent.main()
        client_factory.assert_called_once_with(api_key="offline-key", base_url="http://offline.test/v1")
        self.assertEqual(client.requests[0]["model"], "my-model")
        self.assertEqual({tool["function"]["name"] for tool in client.requests[0]["tools"]},
                         {"search", "get_document"})
        run = json.loads(next((self.root / "cli-runs").glob("run_*.json")).read_text())
        self.assertEqual(run["metadata"]["base_url"], "http://offline.test/v1")
        self.assertNotIn("offline-key", json.dumps(run))


if __name__ == "__main__":
    unittest.main()
