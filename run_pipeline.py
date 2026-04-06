"""
run_pipeline.py — Full ingestion pipeline with checkpoint support.

    python run_pipeline.py           # resumes from where it stopped
    python run_pipeline.py --force   # ignores checkpoints, restarts everything
"""
import sys
from document_processor    import process_all
from elasticsearch_indexer import connect, ensure_index, index_all, print_stats

force = "--force" in sys.argv

print("\n" + "="*60)
print("  STEP 1 — Document Processing")
print("="*60)
process_all(force=force)

print("\n" + "="*60)
print("  STEP 2 — Elasticsearch Indexing")
print("="*60)
es = connect()
ensure_index(es, force=force)
index_all(es, force=force)
print_stats(es)

print("All done! Run:  streamlit run app.py")
