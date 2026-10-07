"""Existing ranking backends with document text from a local Corpus profile."""

import argparse
import logging
from pathlib import Path
from typing import Any

from html_to_md.corpus import Corpus
from html_to_md.models import ResourceSpec
from html_to_md.errors import (
    ArtifactFailed,
    ArtifactUnavailable,
    DocumentNotFound,
    StorageCorruption,
)

from .base import BaseSearcher
logger = logging.getLogger(__name__)

def _ranking_class(ranking_searcher: str):
    if ranking_searcher == "bm25":
        from .bm25_searcher import BM25Searcher

        return BM25Searcher
    if ranking_searcher == "faiss":
        from .faiss_searcher import FaissSearcher

        class RankingOnlyFaissSearcher(FaissSearcher):
            def _load_dataset(self) -> None:
                # FAISS needs lookup IDs for ranking; never load original text.
                self.docid_to_text = {}

        return RankingOnlyFaissSearcher
    raise ValueError(f"Unknown ranking searcher: {ranking_searcher}")


class CustomSearcher(BaseSearcher):
    @classmethod
    def parse_args(cls, parser):
        parser.add_argument(
            "--ranking-searcher",
            choices=["bm25", "faiss"],
            default="faiss",
            help="Existing backend used only for ranking (default: faiss).",
        )
        parser.add_argument(
            "--corpus-data-dir",
            type=Path,
            default=Path("../HTML-to-MD/data"),
            help="Local html-to-md data directory (default: ../HTML-to-MD/data).",
        )
        parser.add_argument(
            "--document-type",
            default="turndown",
            help="Corpus artifact type to read (default: turndown).",
        )
        parser.add_argument(
            "--document-profile",
            default="default-v1",
            help="Exact Corpus profile to read (default: default-v1).",
        )
        parser.add_argument(
            "--corpus-name",
            default=None,
            help="Corpus name; required if the data directory has multiple corpora.",
        )

        # Inspect backend selection independently of the caller's required options.
        selector = argparse.ArgumentParser(add_help=False)
        selector.add_argument(
            "--ranking-searcher", choices=["bm25", "faiss"], default="faiss"
        )
        selected, _ = selector.parse_known_args()
        _ranking_class(selected.ranking_searcher).parse_args(parser)

    def __init__(self, args):
        self.args = args
        self.data_dir = args.corpus_data_dir
        self.document_type = args.document_type
        self.document_profile = args.document_profile
        self.corpus_name = args.corpus_name
        if not self.document_type or not self.document_profile:
            raise ValueError("Document type and profile must be nonempty")
        # No connection is retained: threaded agent clients share this searcher.
        with Corpus.open(self.data_dir, corpus=self.corpus_name) as corpus:
            if not corpus.common_docids([ResourceSpec(self.document_type, self.document_profile)]):
                raise ValueError(
                    f"No artifacts for {self.document_type}/{self.document_profile} "
                    f"in corpus {corpus.name!r}"
                )
        self.ranking_searcher = _ranking_class(args.ranking_searcher)(args)

    def search(self, query: str, k: int = 10) -> list[dict[str, Any]]:
        logger.info(f"CustomSearcher: search({query!r}, k={k})")
        results = []
        for candidate in self.ranking_searcher.search(query, k):
            # Copy only ranking metadata; original backend text is never returned.
            document = self.get_document(str(candidate["docid"]))
            if "score" in candidate:
                document["score"] = candidate["score"]
            results.append(document)
        return results

    def get_document(self, docid: str) -> dict[str, Any]:
        # TODO: Add logging for errors when error occurs
        document = {
            "docid": str(docid),
            "text": "",
            "type": self.document_type,
            "profile": self.document_profile,
        }
        try:
            with Corpus.open(self.data_dir, corpus=self.corpus_name) as corpus:
                text = corpus.read_text(
                    str(docid),
                    type=self.document_type,
                    profile=self.document_profile,
                )
        except (DocumentNotFound, ArtifactFailed, ArtifactUnavailable, StorageCorruption) as exc:
            # ArtifactFailed subclasses ArtifactUnavailable, so check it first.
            codes = (
                (DocumentNotFound, "document_not_found"),
                (ArtifactFailed, "artifact_failed"),
                (ArtifactUnavailable, "artifact_unavailable"),
                (StorageCorruption, "storage_corruption"),
            )
            code = next(code for error_type, code in codes if isinstance(exc, error_type))
            document["error"] = {"code": code, "message": str(exc)}
            logger.error({"docid": docid, "error": document["error"]})
            return document

        if not text.strip():
            document["error"] = {
                "code": "empty_document",
                "message": "The selected document artifact contains no text.",
            }
        else:
            document["text"] = text
        return document

    @property
    def search_type(self) -> str:
        return "custom"

    def search_description(self, k: int = 10) -> str:
        return (
            f"Return top-{k} documents in the existing retriever's ranking order. "
            f"Snippets use local {self.document_type}/{self.document_profile} text. "
            "An error with an empty snippet means this document cannot be read; "
            "it is not replaced by another candidate."
        )

    def get_document_description(self) -> str:
        return (
            f"Read a full document by docid from local "
            f"{self.document_type}/{self.document_profile}. "
            "Returns an explicit error if unavailable, empty or corrupt."
        )
