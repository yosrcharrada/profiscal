using Neo4j.Driver;
using FiscalPlatform.Models;

namespace FiscalPlatform.Services;

/// <summary>
/// Wraps Neo4j queries for knowledge base stats and chunk retrieval.
/// </summary>
public class Neo4jService : IDisposable
{
    private readonly IDriver _driver;
    private readonly string _db;
    private readonly ILogger<Neo4jService> _logger;

    public Neo4jService(IConfiguration config, ILogger<Neo4jService> logger)
    {
        _logger = logger;
        var uri  = config["Neo4j:Uri"]      ?? "neo4j://127.0.0.1:7687";
        var user = config["Neo4j:Username"] ?? "neo4j";
        var pass = config["Neo4j:Password"] ?? "neo4j";
        _db      = config["Neo4j:Database"] ?? "neo4j";
        _driver  = GraphDatabase.Driver(uri, AuthTokens.Basic(user, pass));
    }

    public async Task<bool> IsAliveAsync()
    {
        try
        {
            await using var session = _driver.AsyncSession(o => o.WithDatabase(_db));
            await session.RunAsync("RETURN 1");
            return true;
        }
        catch { return false; }
    }

    public async Task<KnowledgeBaseStats> GetStatsAsync()
    {
        var stats = new KnowledgeBaseStats();
        try
        {
            await using var session = _driver.AsyncSession(o => o.WithDatabase(_db));

            stats.TotalChunks    = await ScalarAsync<long>(session, "MATCH (c:Chunk) RETURN count(c) AS n");
            stats.TotalEntities  = await ScalarAsync<long>(session, "MATCH (e:Entity) RETURN count(e) AS n");
            stats.TotalRelations = await ScalarAsync<long>(session, "MATCH ()-[r]->() RETURN count(r) AS n");

            stats.LoisCount        = await ScalarAsync<long>(session, "MATCH (c:Chunk) WHERE c.doc_name CONTAINS 'loi' OR c.doc_name CONTAINS 'finances' RETURN count(c) AS n");
            stats.NotesCount       = await ScalarAsync<long>(session, "MATCH (c:Chunk) WHERE c.doc_name CONTAINS 'note' RETURN count(c) AS n");
            stats.CodesCount       = await ScalarAsync<long>(session, "MATCH (c:Chunk) WHERE c.doc_name CONTAINS 'code' OR c.doc_name CONTAINS 'recueil' RETURN count(c) AS n");
            stats.ConventionsCount = await ScalarAsync<long>(session, "MATCH (c:Chunk) WHERE c.doc_name CONTAINS 'convention' RETURN count(c) AS n");

            stats.TextChunks  = await ScalarAsync<long>(session, "MATCH (c:Chunk {chunk_type:'text'}) RETURN count(c) AS n");
            stats.TableChunks = await ScalarAsync<long>(session, "MATCH (c:Chunk) WHERE c.chunk_type STARTS WITH 'table' RETURN count(c) AS n");

            // Check if GNN embeddings exist
            stats.GnnActive = await ScalarAsync<long>(session, "MATCH (c:Chunk) WHERE c.gnn_embedding IS NOT NULL RETURN count(c) AS n") > 0;
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Neo4j stats query failed");
        }
        return stats;
    }

    /// <summary>
    /// Vector similarity search using pre-computed embeddings stored in Neo4j.
    /// Falls back to text search when no embedding index is present.
    /// </summary>
    public async Task<List<SourceChunk>> VectorSearchAsync(float[] queryEmbedding, int topK = 8)
    {
        var chunks = new List<SourceChunk>();
        try
        {
            await using var session = _driver.AsyncSession(o => o.WithDatabase(_db));
            var embList = queryEmbedding.Select(f => (double)f).ToList();

            // Try GNN index first, then fall back to text embedding index
            string cypher;
            try
            {
                cypher = @"
                    CALL db.index.vector.queryNodes('chunk_gnn_embeddings', $topK, $emb)
                    YIELD node AS c, score
                    RETURN c.doc_name AS doc_name, c.page_num AS page_num,
                           c.text AS text, c.chunk_type AS chunk_type,
                           c.article_ref AS article_ref, score
                    ORDER BY score DESC";
                var result = await session.RunAsync(cypher, new { topK, emb = embList });
                chunks = await MapChunks(result);
            }
            catch
            {
                cypher = @"
                    CALL db.index.vector.queryNodes('chunk_embeddings', $topK, $emb)
                    YIELD node AS c, score
                    RETURN c.doc_name AS doc_name, c.page_num AS page_num,
                           c.text AS text, c.chunk_type AS chunk_type,
                           c.article_ref AS article_ref, score
                    ORDER BY score DESC";
                var result = await session.RunAsync(cypher, new { topK, emb = embList });
                chunks = await MapChunks(result);
            }
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Vector search failed, falling back to keyword search");
        }
        return chunks;
    }

    /// <summary>
    /// Keyword-based graph expansion — finds chunks mentioning entities related to the query.
    /// </summary>
    public async Task<List<SourceChunk>> GraphExpandAsync(List<string> entities, int topK = 6)
    {
        var chunks = new List<SourceChunk>();
        if (!entities.Any()) return chunks;
        try
        {
            await using var session = _driver.AsyncSession(o => o.WithDatabase(_db));
            var cypher = @"
                UNWIND $entities AS name
                MATCH (e:Entity)-[:MENTIONED_IN]->(c:Chunk)
                WHERE toLower(e.name) CONTAINS toLower(name)
                RETURN DISTINCT c.doc_name AS doc_name, c.page_num AS page_num,
                       c.text AS text, c.chunk_type AS chunk_type,
                       c.article_ref AS article_ref, 1.0 AS score
                LIMIT $topK";
            var result = await session.RunAsync(cypher, new { entities, topK });
            chunks = await MapChunks(result);
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Graph expand failed");
        }
        return chunks;
    }

    /// <summary>Full-text keyword fallback when embedding services are unavailable.</summary>
    public async Task<List<SourceChunk>> KeywordFallbackAsync(string query, int topK = 8)
    {
        var chunks = new List<SourceChunk>();
        var keywords = query.ToLower().Split(' ', StringSplitOptions.RemoveEmptyEntries);
        try
        {
            await using var session = _driver.AsyncSession(o => o.WithDatabase(_db));
            var cypher = @"
                MATCH (c:Chunk)
                WHERE ANY(kw IN $keywords WHERE toLower(c.text) CONTAINS kw)
                RETURN c.doc_name AS doc_name, c.page_num AS page_num,
                       c.text AS text, c.chunk_type AS chunk_type,
                       c.article_ref AS article_ref, 0.5 AS score
                LIMIT $topK";
            var result = await session.RunAsync(cypher, new { keywords, topK });
            chunks = await MapChunks(result);
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Keyword fallback failed");
        }
        return chunks;
    }

    private static async Task<List<SourceChunk>> MapChunks(IResultCursor cursor)
    {
        var list = new List<SourceChunk>();
        await foreach (var record in cursor)
        {
            var text = record["text"]?.As<string>() ?? "";
            list.Add(new SourceChunk
            {
                DocName    = record["doc_name"]?.As<string>() ?? "",
                PageNum    = record["page_num"]?.As<int>() ?? 0,
                Text       = text,
                ChunkType  = record["chunk_type"]?.As<string>() ?? "text",
                ArticleRef = record["article_ref"]?.As<string>() ?? "",
                Score      = record["score"]?.As<double>() ?? 0.0,
                Category   = CategorizeDoc(record["doc_name"]?.As<string>() ?? ""),
            });
        }
        return list;
    }

    private static string CategorizeDoc(string name)
    {
        name = name.ToLower();
        if (name.Contains("note")) return "note";
        if (name.Contains("code") || name.Contains("recueil")) return "code";
        if (name.Contains("convention")) return "convention";
        return "loi";
    }

    private static async Task<T> ScalarAsync<T>(IAsyncSession session, string cypher)
    {
        var result = await session.RunAsync(cypher);
        var record = await result.SingleAsync();
        return record["n"].As<T>();
    }

    public void Dispose() => _driver?.Dispose();
}
