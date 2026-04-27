"""
test_neo4j.py
Diagnostic script to identify Neo4j schema and data issues.

Run this to:
1. Verify Neo4j connection
2. Check database structure
3. Test actual chunk content
4. Debug why queries return 0 results
"""

import os
from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

NEO4J_URI = os.getenv("NEO4J_URI", "neo4j://127.0.0.1:7687")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "fiscal")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "neo4j")

print("=" * 80)
print("🔍 NEO4J DIAGNOSTIC SCRIPT")
print("=" * 80)
print(f"\n📍 Configuration:")
print(f"   URI:      {NEO4J_URI}")
print(f"   Database: {NEO4J_DATABASE}")
print(f"   Username: {NEO4J_USERNAME}")

# ─────────────────────────────────────────────────────────────────────────────
# Step 1: Test Connection
# ─────────────────────────────────────────────────────────────────────────────

print("\n" + "─" * 80)
print("Step 1️⃣ : Testing Neo4j Connection")
print("─" * 80)

try:
    driver = GraphDatabase.driver(
        NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD)
    )
    with driver.session(database=NEO4J_DATABASE) as session:
        session.run("RETURN 1")
    print("✅ Neo4j connection successful!")
except Exception as e:
    print(f"❌ Connection failed: {e}")
    print("   Check NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD")
    exit(1)

# ─────────────────────────────────────────────────────────────────────────────
# Step 2: Check Database Contents
# ─────────────────────────────────────────────────────────────────────────────

print("\n" + "─" * 80)
print("Step 2️⃣ : Checking Database Contents")
print("─" * 80)

with driver.session(database=NEO4J_DATABASE) as session:
    # Count nodes by label
    result = session.run("""
        MATCH (n)
        RETURN labels(n) AS labels, count(*) AS count
        ORDER BY count DESC
    """)
    
    print("\n📊 Nodes by label:")
    total_nodes = 0
    for row in result:
        label = row['labels'][0] if row['labels'] else '(no label)'
        count = row['count']
        total_nodes += count
        print(f"   • [{label}]: {count}")
    
    print(f"\n   Total nodes: {total_nodes}")

# ─────────────────────────────────────────────────────────────────────────────
# Step 3: Inspect One Chunk Node (Print All Properties)
# ─────────────────────────────────────────────────────────────────────────────

print("\n" + "─" * 80)
print("Step 3️⃣ : Inspecting a Single Chunk Node (All Properties)")
print("─" * 80)

with driver.session(database=NEO4J_DATABASE) as session:
    result = session.run("""
        MATCH (c:Chunk)
        RETURN c
        LIMIT 1
    """)
    
    rows = list(result)
    if rows:
        chunk = rows[0]['c']
        print("\n🔹 First Chunk Node Properties:")
        print(f"   Keys: {list(chunk.keys())}\n")
        
        for key, value in chunk.items():
            # Show first 200 chars of long values
            if isinstance(value, str) and len(value) > 200:
                display_value = value[:200] + "... [TRUNCATED]"
            else:
                display_value = repr(value)
            print(f"   • {key}: {display_value}")
    else:
        print("❌ No Chunk nodes found!")
        exit(1)

# ─────────────────────────────────────────────────────────────────────────────
# Step 4: Test Search in Different Properties
# ─────────────────────────────────────────────────────────────────────────────

print("\n" + "─" * 80)
print("Step 4️⃣ : Testing Search in Different Properties")
print("─" * 80)

# Keywords to test
test_keywords = ["tva", "retenue", "article", "impot", "taxe"]

with driver.session(database=NEO4J_DATABASE) as session:
    # Test each property
    properties_to_test = ["data", "text", "article_ref", "section_title", "doc_name"]
    
    for prop in properties_to_test:
        print(f"\n🔹 Searching in property: '{prop}'")
        
        for keyword in test_keywords[:2]:  # Test first 2 keywords only
            try:
                result = session.run(f"""
                    MATCH (c:Chunk)
                    WHERE toLower(c.{prop}) CONTAINS toLower('{keyword}')
                    RETURN count(c) AS matches
                """)
                
                row = result.single()
                matches = row['matches'] if row else 0
                status = "✅" if matches > 0 else "❌"
                print(f"   {status} '{keyword}' in {prop}: {matches} matches")
            except Exception as e:
                print(f"   ❌ Error testing {prop}: {e}")

# ─────────────────────────────────────────────────────────────────────────────
# Step 5: Sample Data from 'data' Property
# ─────────────────────────────────────────────────────────────────────────────

print("\n" + "─" * 80)
print("Step 5️⃣ : Sampling 'data' Property Content (First 500 chars)")
print("─" * 80)

with driver.session(database=NEO4J_DATABASE) as session:
    result = session.run("""
        MATCH (c:Chunk)
        WHERE c.data IS NOT NULL
        RETURN c.doc_name, c.data[0..500] AS sample
        LIMIT 3
    """)
    
    print()
    for i, row in enumerate(result, 1):
        doc = row['doc_name']
        sample = row['sample']
        print(f"🔹 Chunk {i} from {doc}:")
        print(f"   {repr(sample)}\n")

# ─────────────────────────────────────────────────────────────────────────────
# Step 6: Check if 'data' is Empty
# ─────────────────────────────────────────────────────────────────────────────

print("\n" + "─" * 80)
print("Step 6️⃣ : Checking if 'data' Property is Populated")
print("─" * 80)

with driver.session(database=NEO4J_DATABASE) as session:
    result = session.run("""
        MATCH (c:Chunk)
        RETURN 
            count(*) AS total_chunks,
            sum(CASE WHEN c.data IS NULL THEN 1 ELSE 0 END) AS null_count,
            sum(CASE WHEN c.data = '' THEN 1 ELSE 0 END) AS empty_string_count,
            sum(CASE WHEN length(c.data) > 0 THEN 1 ELSE 0 END) AS with_content
    """)
    
    row = result.single()
    print(f"\n📊 Data Property Statistics:")
    print(f"   Total chunks:         {row['total_chunks']}")
    print(f"   NULL (missing):       {row['null_count']}")
    print(f"   Empty strings:        {row['empty_string_count']}")
    print(f"   With content:         {row['with_content']}")

# ─────────────────────────────────────────────────────────────────────────────
# Step 7: Test the Actual Query from create_reports.py
# ─────────────────────────────────────────────────────────────────────────────

print("\n" + "─" * 80)
print("Step 7️⃣ : Testing Actual Query from create_reports.py")
print("─" * 80)

QUERY = """
MATCH (c:Chunk)
WHERE any(t IN $topics
          WHERE toLower(c.data) CONTAINS toLower(t)
             OR toLower(coalesce(c.article_ref,'')) CONTAINS toLower(t)
             OR toLower(coalesce(c.section_title,'')) CONTAINS toLower(t)
             OR toLower(coalesce(c.doc_name,'')) CONTAINS toLower(t))
WITH c,
     reduce(s = 0.0, t IN $topics |
         s + CASE 
            WHEN toLower(c.data) CONTAINS toLower(t) THEN 2.0
            WHEN toLower(c.article_ref) CONTAINS toLower(t) THEN 1.5
            WHEN toLower(c.section_title) CONTAINS toLower(t) THEN 1.0
             WHEN toLower(c.doc_name) CONTAINS toLower(t) THEN 0.5
             ELSE 0.0 
         END
    ) AS score
WHERE score > 0
RETURN c.doc_name     AS doc_name,
    coalesce(c.page_num, 0)        AS page_num,
    coalesce(c.article_ref, '')    AS article_ref,
    coalesce(c.section_title, '')  AS section_title,
    coalesce(c.data, '')           AS text,
    score
ORDER BY score DESC
LIMIT 5
"""

test_topics = ["tva", "retenue", "source"]

with driver.session(database=NEO4J_DATABASE) as session:
    print(f"\n🔹 Testing with topics: {test_topics}")
    
    try:
        result = session.run(QUERY, topics=test_topics)
        rows = list(result)
        
        print(f"\n✅ Query executed successfully!")
        print(f"   Returned {len(rows)} chunks\n")
        
        if rows:
            print("   Results:")
            for i, row in enumerate(rows, 1):
                print(f"\n   [{i}] {row['doc_name']} (p.{row['page_num']}) - Score: {row['score']}")
                print(f"       Article: {row['article_ref']}")
                preview = row['text'][:100] if row['text'] else "(empty)"
                print(f"       Preview: {preview}...")
        else:
            print("   ❌ Query returned 0 results!")
            print("\n   This means:")
            print("   • Topics don't match any chunk content")
            print("   • 'data' property might be empty or NULL")
            print("   • Property names might still be different")
    
    except Exception as e:
        print(f"\n❌ Query execution failed:")
        print(f"   {e}")

driver.close()

# ─────────────────────────────────────────────────────────────────────────────
# Final Summary
# ─────────────────────────────────────────────────────────────────────────────

print("\n" + "=" * 80)
print("📋 DIAGNOSTIC SUMMARY")
print("=" * 80)
print("""
If Step 7 returned 0 results, check:

1. Is 'data' property populated?
   → If NOT, the Chunk nodes were created but data wasn't saved
   → Run build_graphrag.py to populate

2. Does 'data' contain searchable text?
   → Check Step 5 output - does it show actual text content?
   → If empty strings, re-run build_graphrag.py

3. Are the property names correct?
   → Check Step 3 output - which properties exist on Chunk nodes?
   → Update create_reports.py to use correct property names

4. Try simple tests:
   → MATCH (c:Chunk) WHERE c.data CONTAINS 'article' RETURN COUNT(c)
   → Should return > 0

Contact support with output from this script if issues persist!
""")
print("=" * 80)
