using FiscalPlatform.Domain.Entities;
using FiscalPlatform.Domain.Repositories;
using Neo4j.Driver;

namespace FiscalPlatform.Infrastructure.Neo4j;

public sealed class Neo4jKnowledgeGraphRepository(
    Neo4jDriver neo4jDriver,
    ILogger<Neo4jKnowledgeGraphRepository> logger) : IKnowledgeGraphRepository
{
    public async Task<List<SourceChunk>> VectorSearchAsync(float[] embedding, int topK)
    {
        var chunks = new List<SourceChunk>();
        try
        {
            await using var session = neo4jDriver.Driver.AsyncSession(o => o.WithDatabase(neo4jDriver.Database));
            var embList = embedding.Select(f => (double)f).ToList();

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
            catch (Exception ex)
            {
                logger.LogInformation(ex, "Falling back to 'chunk_embeddings' vector index");
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
            logger.LogWarning(ex, "Vector search failed");
        }

        return chunks;
    }

    public async Task<List<SourceChunk>> KeywordFallbackAsync(string query, int topK)
    {
        var chunks = new List<SourceChunk>();
        var keywords = query.ToLowerInvariant().Split(' ', StringSplitOptions.RemoveEmptyEntries);

        try
        {
            await using var session = neo4jDriver.Driver.AsyncSession(o => o.WithDatabase(neo4jDriver.Database));
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
            logger.LogWarning(ex, "Keyword fallback failed");
        }

        return chunks;
    }

    public async Task<KnowledgeBaseStats> GetStatsAsync()
    {
        try
        {
            await using var session = neo4jDriver.Driver.AsyncSession(o => o.WithDatabase(neo4jDriver.Database));

            return new KnowledgeBaseStats
            {
                TotalChunks = await ScalarAsync<long>(session, "MATCH (c:Chunk) RETURN count(c) AS n"),
                TotalEntities = await ScalarAsync<long>(session, "MATCH (e:Entity) RETURN count(e) AS n"),
                TotalRelations = await ScalarAsync<long>(session, "MATCH ()-[r]->() RETURN count(r) AS n"),
                LoisCount = await ScalarAsync<long>(session, "MATCH (c:Chunk) WHERE c.doc_name CONTAINS 'loi' OR c.doc_name CONTAINS 'finances' RETURN count(c) AS n"),
                NotesCount = await ScalarAsync<long>(session, "MATCH (c:Chunk) WHERE c.doc_name CONTAINS 'note' RETURN count(c) AS n"),
                CodesCount = await ScalarAsync<long>(session, "MATCH (c:Chunk) WHERE c.doc_name CONTAINS 'code' OR c.doc_name CONTAINS 'recueil' RETURN count(c) AS n"),
                ConventionsCount = await ScalarAsync<long>(session, "MATCH (c:Chunk) WHERE c.doc_name CONTAINS 'convention' RETURN count(c) AS n"),
                TextChunks = await ScalarAsync<long>(session, "MATCH (c:Chunk {chunk_type:'text'}) RETURN count(c) AS n"),
                TableChunks = await ScalarAsync<long>(session, "MATCH (c:Chunk) WHERE c.chunk_type STARTS WITH 'table' RETURN count(c) AS n"),
                GnnActive = await ScalarAsync<long>(session, "MATCH (c:Chunk) WHERE c.gnn_embedding IS NOT NULL RETURN count(c) AS n") > 0
            };
        }
        catch (Exception ex)
        {
            logger.LogWarning(ex, "Neo4j stats query failed");
            return new KnowledgeBaseStats();
        }
    }

    private static async Task<T> ScalarAsync<T>(IAsyncSession session, string cypher)
    {
        var result = await session.RunAsync(cypher);
        var record = await result.SingleAsync();
        return record["n"].As<T>();
    }

    private static async Task<List<SourceChunk>> MapChunks(IResultCursor cursor)
    {
        var list = new List<SourceChunk>();
        await foreach (var record in cursor)
        {
            list.Add(new SourceChunk
            {
                DocName = record["doc_name"]?.As<string>() ?? string.Empty,
                PageNum = record["page_num"]?.As<int>() ?? 0,
                Text = record["text"]?.As<string>() ?? string.Empty,
                ChunkType = record["chunk_type"]?.As<string>() ?? "text",
                ArticleRef = record["article_ref"]?.As<string>() ?? string.Empty,
                Score = record["score"]?.As<double>() ?? 0,
                Category = CategorizeDoc(record["doc_name"]?.As<string>() ?? string.Empty)
            });
        }

        return list;
    }

    private static string CategorizeDoc(string name)
    {
        var normalized = name.ToLowerInvariant();
        if (normalized.Contains("note")) return "note";
        if (normalized.Contains("code") || normalized.Contains("recueil")) return "code";
        if (normalized.Contains("convention")) return "convention";
        return "loi";
    }
}
