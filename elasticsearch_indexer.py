"""
================================================================================
ELASTICSEARCH INDEXER — Tunisian Legal Documents
================================================================================
Reads JSON files from processed_documents/ and indexes chunks into Elasticsearch.

CHECKPOINT SYSTEM:
  Tracks which JSON files have already been indexed.
  On restart, already-indexed documents are skipped.
  Only new or failed documents are re-indexed.

  Checkpoint file: processed_documents/_index_progress.json

Run:
    python elasticsearch_indexer.py
    python elasticsearch_indexer.py --force   # re-index everything
================================================================================
"""

import json
import os
import time
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

try:
    from elasticsearch import Elasticsearch, helpers
except ImportError:
    raise SystemExit("Run: pip install elasticsearch==8.13.0")

ES_HOST       = os.getenv("ES_HOST",       "http://localhost:9200")
ES_INDEX      = os.getenv("ES_INDEX",      "tunisian_legal")
PROCESSED_DIR = os.getenv("PROCESSED_DIR", "./processed_documents")

INDEX_CHECKPOINT = "_index_progress.json"   # inside PROCESSED_DIR


# ═════════════════════════════════════════════════════════════════════════════
# INDEX MAPPING
# ═════════════════════════════════════════════════════════════════════════════

INDEX_SETTINGS = {
    "settings": {
        "number_of_shards":   1,
        "number_of_replicas": 0,
        "analysis": {
            "analyzer": {
                "legal_analyzer": {
                    "type":      "custom",
                    "tokenizer": "standard",
                    "filter":    ["lowercase", "asciifolding"]
                    # asciifolding: é→e, à→a, ç→c
                    # so "penalite" finds "pénalité"
                }
            }
        },
        "index": {
            "similarity": {
                "legal_bm25": {
                    "type": "BM25",
                    "k1":   1.5,   # higher = more reward for term frequency
                    "b":    0.6    # lower = less length normalisation
                }
            }
        }
    },
    "mappings": {
        "properties": {
            "content":          {"type": "text",    "analyzer": "legal_analyzer",
                                 "similarity": "legal_bm25",
                                 "term_vector": "with_positions_offsets"},
            "filename":         {"type": "text",    "analyzer": "legal_analyzer",
                                 "fields": {"keyword": {"type": "keyword"}}},
            "article_number":   {"type": "text",    "analyzer": "legal_analyzer",
                                 "fields": {"keyword": {"type": "keyword"}}},
            "section_title":    {"type": "text",    "analyzer": "legal_analyzer"},
            "subsection_title": {"type": "text",    "analyzer": "legal_analyzer"},
            "chunk_type":       {"type": "keyword"},
            "document_type":    {"type": "keyword"},
            "chunk_id":         {"type": "keyword"},
            "document_id":      {"type": "keyword"},
            "section_number":   {"type": "keyword"},
            "subsection_letter":{"type": "keyword"},
            "page_number":      {"type": "integer"},
            "part":             {"type": "integer"},
        }
    }
}


# ═════════════════════════════════════════════════════════════════════════════
# INDEXING CHECKPOINT
# ═════════════════════════════════════════════════════════════════════════════

class IndexTracker:
    """
    Tracks which JSON files have been successfully indexed into Elasticsearch.

    Structure of _index_progress.json:
    {
      "Loi2024_48_processed.json": {
        "status":    "done",
        "chunks":    170,
        "timestamp": "2025-01-17 14:45"
      }
    }
    """

    def __init__(self, output_dir: str):
        self.path = Path(output_dir) / INDEX_CHECKPOINT
        self.data = self._load()

    def _load(self):
        if self.path.exists():
            try:
                with open(self.path, encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _save(self):
        with open(self.path, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def is_done(self, filename: str) -> bool:
        return self.data.get(filename, {}).get("status") == "done"

    def mark_done(self, filename: str, chunk_count: int):
        self.data[filename] = {
            "status":    "done",
            "chunks":    chunk_count,
            "timestamp": time.strftime("%Y-%m-%d %H:%M"),
        }
        self._save()

    def mark_failed(self, filename: str, error: str):
        self.data[filename] = {
            "status":    "failed",
            "error":     str(error)[:200],
            "timestamp": time.strftime("%Y-%m-%d %H:%M"),
        }
        self._save()

    def print_status(self):
        print("\n── Index checkpoint status ───────────────────────────")
        for fn, info in self.data.items():
            icon = "✓" if info["status"] == "done" else "✗"
            extra = f"  ({info.get('chunks','?')} chunks)" if info["status"] == "done" else f"  {info.get('error','')[:50]}"
            print(f"  {icon} {fn}{extra}  [{info.get('timestamp','')}]")
        print("──────────────────────────────────────────────────────\n")


# ═════════════════════════════════════════════════════════════════════════════
# CORE FUNCTIONS
# ═════════════════════════════════════════════════════════════════════════════

def connect() -> Elasticsearch:
    es = Elasticsearch(ES_HOST, request_timeout=30)
    if not es.ping():
        raise SystemExit(
            f"\n✗ Cannot reach Elasticsearch at {ES_HOST}\n"
            "Start it:\n"
            "  docker run -d -p 9200:9200 \\\n"
            "    -e discovery.type=single-node \\\n"
            "    -e xpack.security.enabled=false \\\n"
            "    elasticsearch:8.13.0\n"
        )
    info = es.info()
    print(f"✓ Elasticsearch {info['version']['number']} at {ES_HOST}")
    return es


def ensure_index(es: Elasticsearch, force: bool = False):
    """Create index if it doesn't exist. With --force, delete and recreate."""
    exists = es.indices.exists(index=ES_INDEX)
    if force and exists:
        es.indices.delete(index=ES_INDEX)
        print(f"  Deleted index '{ES_INDEX}' (--force)")
        exists = False
    if not exists:
        es.indices.create(index=ES_INDEX, body=INDEX_SETTINGS)
        print(f"✓ Created index '{ES_INDEX}'")
        print(f"  Analyzer: asciifolding + lowercase | BM25 k1=1.5 b=0.6")
    else:
        print(f"✓ Index '{ES_INDEX}' already exists — adding new documents only")


def index_all(es: Elasticsearch, force: bool = False):
    """
    Index all processed JSON files.
    Skips files already indexed (unless force=True).
    """
    json_files = sorted(Path(PROCESSED_DIR).glob("*_processed.json"))

    if not json_files:
        raise SystemExit(
            f"\n✗ No *_processed.json files in '{PROCESSED_DIR}'\n"
            "Run document_processor.py first."
        )

    tracker = IndexTracker(PROCESSED_DIR)

    print(f"\nIndexing {len(json_files)} document(s) from '{PROCESSED_DIR}' …")
    if tracker.data:
        tracker.print_status()

    skipped = indexed = failed = 0

    for jf in json_files:
        filename = jf.name

        # ── Checkpoint: skip if already indexed ───────────────────────────────
        if not force and tracker.is_done(filename):
            info = tracker.data[filename]
            print(f"  ⏭  SKIP  {filename}"
                  f"  ({info.get('chunks','?')} chunks already in ES)")
            skipped += 1
            continue

        print(f"  ▶  {filename}")

        try:
            with open(jf, encoding='utf-8') as f:
                chunks = json.load(f)

            actions = [
                {
                    "_index":  ES_INDEX,
                    "_id":     c["chunk_id"],
                    "_source": {k: v for k, v in c.items() if v is not None}
                }
                for c in chunks
            ]

            ok, errors = helpers.bulk(es, actions, raise_on_error=False)
            tracker.mark_done(filename, ok)
            indexed += ok

            if errors:
                print(f"      ⚠ {ok} indexed, {len(errors)} errors")
            else:
                print(f"      ✓ {ok} chunks indexed")

        except Exception as e:
            tracker.mark_failed(filename, str(e))
            failed += 1
            print(f"      ✗ FAILED: {e}")

    es.indices.refresh(index=ES_INDEX)
    print(f"\n  This run  : {indexed} chunks indexed,  {skipped} files skipped,"
          f"  {failed} failed")


def print_stats(es: Elasticsearch):
    total = es.count(index=ES_INDEX)["count"]
    agg   = es.search(index=ES_INDEX, body={
        "size": 0,
        "aggs": {
            "by_doc_type":   {"terms": {"field": "document_type"}},
            "by_chunk_type": {"terms": {"field": "chunk_type", "size": 20}}
        }
    })
    print(f"\n── Elasticsearch index stats ────────────────────────")
    print(f"  Total chunks : {total}")
    print("  By doc type  :")
    for b in agg["aggregations"]["by_doc_type"]["buckets"]:
        print(f"    {b['key']}: {b['doc_count']}")
    print("  By chunk type:")
    for b in agg["aggregations"]["by_chunk_type"]["buckets"]:
        print(f"    {b['key']}: {b['doc_count']}")
    print("─────────────────────────────────────────────────────")
    print("\nDone! Run:  streamlit run app.py\n")


# ═════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    force = "--force" in sys.argv

    print("=" * 55)
    print("  ELASTICSEARCH INDEXER — Tunisian Legal Search")
    print("=" * 55)

    es = connect()
    ensure_index(es, force=force)
    index_all(es, force=force)
    print_stats(es)
