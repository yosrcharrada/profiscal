"""
GraphRAG Builder v2 — COMPLETE
=======================================
Pipeline:
  1. Extract raw chunks from PDFs (with OCR + table extraction)
  2. Context-aware legal chunking (article/section boundaries)
  3. Embed chunks + extract typed entities + save to Neo4j
  4. Create SAME_PAGE relationships
  5. Train GNN + store GNN embeddings
"""

import os
import sys
import json
import time
from pathlib import Path
from dotenv import load_dotenv
import warnings

warnings.filterwarnings('ignore')
load_dotenv()

from llama_index.core import Settings
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from neo4j import GraphDatabase

from config import get_config
from pdf_table_extractor import FiscalDocumentLoader
from legal_chunker import LegalDocumentChunker
from code_chunker import CodeDocumentChunker
from convention_chunker import ConventionDocumentChunker

cfg = get_config()

print("=" * 70)
print("🇹🇳 TUNISIAN FISCALITY GRAPHRAG — v2 (CONTEXT-AWARE + GNN)")
print("=" * 70)

# ── AI Models ─────────────────────────────────────────────────────────────────
print("\n🤖 Setting up AI models...")

if cfg["llm_provider"] == "ollama":
    from llama_index.llms.ollama import Ollama
    llm = Ollama(model=cfg["llm_model"], request_timeout=120.0, temperature=0.1)
    print(f"   Testing Ollama {cfg['llm_model']}...")
    test = llm.complete("Say OK")
    print(f"   Response: {test.text.strip()}")
else:
    from llama_index.llms.gemini import Gemini
    import google.generativeai as genai
    genai.configure(api_key=os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))
    llm = Gemini(model=cfg["llm_model"], temperature=0.1)

embed_model = HuggingFaceEmbedding(
    model_name=cfg["embedding_model"], cache_folder="./model_cache"
)
Settings.llm = llm
Settings.embed_model = embed_model
print(f"✅ LLM: {cfg['llm_provider']}/{cfg['llm_model']}")

# ── Neo4j ─────────────────────────────────────────────────────────────────────
print(f"\n🗄️  Connecting to Neo4j ({cfg['neo4j_database']})...")
driver = GraphDatabase.driver(
    cfg["neo4j_uri"], auth=(cfg["neo4j_username"], cfg["neo4j_password"])
)
with driver.session(database=cfg["neo4j_database"]) as session:
    session.run("RETURN 1").single()
print("✅ Connected!")

clear = input("\n🗑️  Clear existing data? (y/N): ").strip().lower()
if clear == 'y':
    with driver.session(database=cfg["neo4j_database"]) as session:
        session.run("MATCH (n) DETACH DELETE n")
    print("✅ Cleared!")

# ============================================================================
# STEP 1: Extract raw chunks from PDFs
# ============================================================================
print("\n" + "=" * 70)
print("📚 Step 1: Extracting PDFs...")
print("=" * 70)

CACHE_FILE = "extracted_chunks_cache.json"

if Path(CACHE_FILE).exists():
    print(f"   ⚡ Loading from cache: {CACHE_FILE}")
    with open(CACHE_FILE, 'r', encoding='utf-8') as f:
        raw_chunks = json.load(f)
    print(f"   ✅ {len(raw_chunks)} chunks loaded from cache")
else:
    print("   Running full extraction (first time only — may take a while)...")
    loader = FiscalDocumentLoader(cfg["docs_path"])
    raw_chunks = loader.load_all_chunks()
    loader.save_extraction_report(raw_chunks)
    with open(CACHE_FILE, 'w', encoding='utf-8') as f:
        json.dump(raw_chunks, f, ensure_ascii=False, indent=2)
    print(f"   ✅ Saved to cache: {CACHE_FILE}")

text_n = sum(1 for c in raw_chunks if c['chunk_type'] == 'text')
tbl_md = sum(1 for c in raw_chunks if c['chunk_type'] == 'table_markdown')
tbl_pr = sum(1 for c in raw_chunks if c['chunk_type'] == 'table_prose')
print(f"   Raw: {len(raw_chunks)} total — text:{text_n}  table_md:{tbl_md}  table_prose:{tbl_pr}")

# ============================================================================
# STEP 2: Context-aware legal chunking
# ============================================================================
print("\n" + "=" * 70)
print("✂️  Step 2: Context-aware legal chunking...")
print("=" * 70)


# Detect document type from filename
def detect_doc_type(doc_name: str) -> str:
    """Detect document type from filename."""
    doc_name_lower = doc_name.lower()
    if 'code' in doc_name_lower:
        return 'code'
    elif 'convention' in doc_name_lower:
        return 'convention'
    elif 'note' in doc_name_lower:
        return 'note'
    else:
        return 'loi'

doc_type = detect_doc_type(raw_chunks[0]['doc_name'])

if doc_type == 'code':
    chunker = CodeDocumentChunker(
        max_chunk_size=cfg["chunk_size"],
        chunk_overlap=cfg["chunk_overlap"],
    )
    print(f"   📖 Using CodeDocumentChunker")
elif doc_type == 'convention':
    chunker = ConventionDocumentChunker(
        max_chunk_size=cfg["chunk_size"],
        chunk_overlap=cfg["chunk_overlap"],
    )
    print(f"   📖 Using ConventionDocumentChunker")
else:
    chunker = LegalDocumentChunker(
        max_chunk_size=cfg["chunk_size"],
        fallback_chunk_size=1024,
        chunk_overlap=cfg["chunk_overlap"],
    )
    print(f"   📖 Using LegalDocumentChunker (Loi/Note)")

final_chunks = chunker.chunk_document(raw_chunks)

text_n = sum(1 for c in final_chunks if c['chunk_type'] == 'text')
tbl_n = sum(1 for c in final_chunks if c['chunk_type'] != 'text')
with_ref = sum(1 for c in final_chunks if c.get('article_ref'))
print(f"✅ {len(final_chunks)} chunks — text:{text_n}  tables:{tbl_n}  with article ref:{with_ref}")
# ============================================================================
# STEP 3: Embed + typed entity extraction + save to Neo4j
# ============================================================================
print("\n" + "=" * 70)
print("🏗️  Step 3: Embed → extract typed entities → save to Neo4j...")
print("=" * 70)
print("   💡 Data saved after EACH chunk — safe to Ctrl+C anytime")

VALID_TYPES = {'article', 'tax', 'rate', 'threshold', 'organization', 'law', 'concept', 'exemption', 'article_reference', 'cross_reference', 'tax_concept'}
VALID_RELS = {'REFERENCES', 'DEFINES_RATE', 'APPLIES_TO', 'EXEMPTS', 'MODIFIES'}

# ── Check which chunks already exist (for resume support) ────────────────
existing_ids = set()
with driver.session(database=cfg["neo4j_database"]) as session:
    result = session.run("MATCH (c:Chunk) RETURN c.id AS id")
    existing_ids = {r['id'] for r in result}

if existing_ids:
    print(f"   ⚡ Found {len(existing_ids)} chunks already in Neo4j — will skip them")
else:
    print("   Starting fresh build")

total_saved = 0
total_entities = 0
skipped = 0
start_time = time.time()

for idx, chunk in enumerate(final_chunks, 1):
    chunk_text = chunk['text']
    chunk_type = chunk['chunk_type']
    doc_name = chunk['doc_name']
    page_num = chunk.get('page_num', 0)
    article_ref = chunk.get('article_ref', '')
    section_title = chunk.get('section_title', '')
    chunk_id = f"{doc_name}_p{page_num}_{chunk_type}_{idx}"

###modification## again  14800
    # ── FAST SKIP: jump past already-processed region ────────────────
    if idx <= 14990 and chunk_id not in existing_ids:        # FAST SKIP
        continue                                               # FAST SKIP


    # ── RESUME: skip if already saved ────────────────────────────────
    if chunk_id in existing_ids:
        skipped += 1
        if skipped % 50 == 0:
            print(f"   ⏭️  Skipped {skipped} already-saved chunks...")
        continue

    try:
        label = article_ref[:20] if article_ref else ''
        print(f"   [{idx}/{len(final_chunks)}] {chunk_type:15s} p{page_num} {label}: ",
              end="", flush=True)

        # ── Embed ────────────────────────────────────────────────────────
        embed_text = chunk_text
        if chunk_type == 'table_markdown':
            prose_match = next((
                c for c in final_chunks
                if c['chunk_type'] == 'table_prose'
                and c.get('page_num') == page_num
                and c.get('table_index') == chunk.get('table_index')
            ), None)
            if prose_match:
                embed_text = prose_match['text']

        print("embed...", end="", flush=True)
        embedding = embed_model.get_text_embedding(embed_text)

        # ── Extract entities from chunk metadata (NO LLM!) ──────────────────
        print("entities...", end="", flush=True)

        entities = []

        # Get pre-extracted entities from chunker (regex-based)
        chunk_entities = chunk.get('entities', {})
        chunk_thresholds = chunk.get('thresholds', [])
        chunk_cross_refs = chunk.get('cross_references', [])

        # Add tax concepts
        for concept in chunk_entities.get('tax_concepts', []):
            entities.append((concept, 'tax_concept'))

        # Add article references
        for article_ref_text in chunk_entities.get('article_references', []):
            entities.append((article_ref_text, 'article_reference'))

        # Add cross-references
        for cross_ref in chunk_cross_refs:
            entities.append((cross_ref[:100], 'cross_reference'))

        # Add thresholds as entities
        for threshold in chunk_thresholds[:5]:
            threshold_text = f"{threshold['value']} {threshold['full_text']}"
            entities.append((threshold_text, 'threshold'))

        # Deduplicate and limit
        entities = list(set(entities))[:15]

        # ── Save to Neo4j ────────────────────────────────────────────────
        print("saving...", end="", flush=True)

        with driver.session(database=cfg["neo4j_database"]) as session:
            # Create chunk node
            session.run("""
                CREATE (c:Chunk {
                    id:             $chunk_id,
                    text:           $text,
                    doc_name:       $doc_name,
                    page_num:       $page_num,
                    chunk_type:     $chunk_type,
                    doc_type:       $doc_type,
                    article_ref:    $article_ref,
                    section_title:  $section_title,
                    embedding:      $embedding,
                    created_at:     datetime()
                })
            """, {
                'chunk_id': chunk_id,
                'text': chunk_text[:5000],
                'doc_name': doc_name,
                'page_num': page_num,
                'chunk_type': chunk_type,
                'doc_type': chunk.get('doc_type', 'loi'),
                'article_ref': article_ref,
                'section_title': section_title,
                'embedding': embedding,
            })

            # Create vector index on first new chunk saved
            if total_saved == 0 and skipped == 0:
                try:
                    session.run("""
                        CREATE VECTOR INDEX chunk_embeddings IF NOT EXISTS
                        FOR (c:Chunk) ON (c.embedding)
                        OPTIONS {indexConfig: {
                          `vector.dimensions`: 768,
                          `vector.similarity_function`: 'cosine'
                        }}
                    """)
                except Exception:
                    pass

            # Create typed entity nodes + MENTIONED_IN relationships
            for name, etype in entities:
                if name:
                    session.run("""
                        MERGE (e:Entity {name: $name})
                        ON CREATE SET e.type = $etype
                        WITH e
                        MATCH (c:Chunk {id: $chunk_id})
                        MERGE (e)-[:MENTIONED_IN]->(c)
                    """, {'name': name, 'etype': etype, 'chunk_id': chunk_id})

        total_saved += 1
        total_entities += len(entities)
        print(f"✅ ({len(entities)} entities)")

    except Exception as e:
        print(f"❌ {e}")
        continue

    time.sleep(0.5)

if skipped > 0:
    print(f"\n   ⏭️  Skipped {skipped} chunks (already in Neo4j)")
print(f"   ✅ Saved {total_saved} new chunks, {total_entities} entities")
# ============================================================================
# STEP 4: Create SAME_PAGE relationships
# ============================================================================
print("\n" + "=" * 70)
print("🔗 Step 4: Creating SAME_PAGE relationships...")
print("=" * 70)

with driver.session(database=cfg["neo4j_database"]) as session:
    result = session.run("""
        MATCH (c1:Chunk), (c2:Chunk)
        WHERE c1.doc_name = c2.doc_name
          AND c1.page_num = c2.page_num
          AND c1.id < c2.id
        MERGE (c1)-[:SAME_PAGE]->(c2)
        RETURN count(*) AS created
    """)
    same_page_count = result.single()['created']
    print(f"✅ Created {same_page_count} SAME_PAGE relationships")

# ============================================================================
# STEP 5: Train GNN + store embeddings
# ============================================================================
print("\n" + "=" * 70)
print("🧠 Step 5: Training GNN + storing GNN embeddings...")
print("=" * 70)

try:
    from gnn_embeddings import build_gnn_layer
    build_gnn_layer()
except Exception as e:
    print(f"⚠️  GNN training failed: {e}")
    print("   This is optional — vector search still works without GNN")
    import traceback
    traceback.print_exc()

# ============================================================================
# FINAL STATS
# ============================================================================
duration = time.time() - start_time

print("\n" + "=" * 70)
print("✅ BUILD COMPLETE!")
print("=" * 70)

with driver.session(database=cfg["neo4j_database"]) as session:
    chunks_n = session.run("MATCH (c:Chunk) RETURN count(c) as n").single()['n']
    text_n = session.run("MATCH (c:Chunk {chunk_type:'text'}) RETURN count(c) as n").single()['n']
    tbl_n = session.run("MATCH (c:Chunk) WHERE c.chunk_type STARTS WITH 'table' RETURN count(c) as n").single()['n']
    ent_n = session.run("MATCH (e:Entity) RETURN count(e) as n").single()['n']

    rel_result = session.run("""
        MATCH ()-[r]->()
        RETURN type(r) AS rel, count(r) AS n
        ORDER BY n DESC
    """)
    rels = [dict(r) for r in rel_result]

    gnn_n = session.run("MATCH (c:Chunk) WHERE c.gnn_embedding IS NOT NULL RETURN count(c) as n").single()['n']

print(f"\n📊 Final Statistics:")
print(f"   Chunks: {chunks_n} (text: {text_n}, tables: {tbl_n})")
print(f"   Entities: {ent_n}")
print(f"   Relationships:")
for r in rels:
    print(f"      • {r['rel']}: {r['n']}")
print(f"   GNN embeddings: {gnn_n}")
print(f"   Time: {int(duration // 60)}m {int(duration % 60)}s")

driver.close()

print("\n" + "=" * 70)
print("🎉 NEXT STEPS:")
print("=" * 70)
print("   python query_system.py     ← CLI Q&A")
print("   python agent.py            ← ReAct agent")
print("   streamlit run app.py       ← Web UI")
print("=" * 70)