using System.Diagnostics;
using System.Text.Json;
using FiscalPlatform.Domain.Entities;
using FiscalPlatform.Domain.Repositories;
using FiscalPlatform.Domain.ValueObjects;

namespace FiscalPlatform.Infrastructure.Elasticsearch;

public sealed class ElasticsearchSearchRepository(
    ElasticsearchClient client,
    ILogger<ElasticsearchSearchRepository> logger) : ISearchRepository
{
    public async Task<SearchResult> SearchAsync(string query, SearchFilters filters)
    {
        var sw = Stopwatch.StartNew();
        var request = BuildQuery(query, filters);
        var body = await client.SearchAsync(JsonSerializer.Serialize(request));
        sw.Stop();

        return ParseResponse(body, sw.Elapsed.TotalMilliseconds);
    }

    public async Task<long> CountAsync()
    {
        try
        {
            var body = await client.CountAsync();
            var doc = JsonDocument.Parse(body);
            return doc.RootElement.GetProperty("count").GetInt64();
        }
        catch
        {
            return 0;
        }
    }

    private static object BuildQuery(string q, SearchFilters filters)
    {
        var esFilters = new List<object>();

        if (!filters.DocType.IsAll)
            esFilters.Add(new { term = new { document_type = filters.DocType.Value } });
        if (!filters.ChunkType.IsAll)
            esFilters.Add(new { term = new { chunk_type = filters.ChunkType.Value } });

        object boolQuery;
        if (esFilters.Count > 0)
        {
            boolQuery = new
            {
                @bool = new
                {
                    must = BuildMultiMatch(q),
                    filter = esFilters
                }
            };
        }
        else
        {
            boolQuery = new { @bool = new { must = BuildMultiMatch(q) } };
        }

        return new
        {
            size = filters.Size,
            query = boolQuery,
            highlight = new
            {
                fields = new
                {
                    content = new { number_of_fragments = 3, fragment_size = 200, pre_tags = new[] { "<em>" }, post_tags = new[] { "</em>" } },
                    article_number = new { number_of_fragments = 1 },
                    section_title = new { number_of_fragments = 1 }
                }
            },
            aggs = new
            {
                doc_types = new { terms = new { field = "document_type", size = 10 } },
                chunk_types = new { terms = new { field = "chunk_type", size = 20 } }
            },
            _source = new[]
            {
                "content", "filename", "article_number", "section_title",
                "chunk_type", "document_type", "page_number", "chunk_id"
            }
        };
    }

    private static object[] BuildMultiMatch(string q) =>
    [
        new
        {
            multi_match = new
            {
                query = q,
                fields = new[] { "content^3", "article_number^2", "section_title^1.5", "filename" },
                type = "best_fields",
                fuzziness = "AUTO",
                @operator = "or"
            }
        }
    ];

    private SearchResult ParseResponse(string body, double elapsedMs)
    {
        var result = new SearchResult { ElapsedMs = elapsedMs };
        try
        {
            var doc = JsonDocument.Parse(body);
            var hits = doc.RootElement.GetProperty("hits");
            var totalProp = hits.GetProperty("total").GetProperty("value").GetInt32();
            var maxScore = hits.TryGetProperty("max_score", out var maxScoreElement) && maxScoreElement.ValueKind == JsonValueKind.Number
                ? maxScoreElement.GetDouble()
                : 1.0;

            var chunks = new List<Chunk>();
            foreach (var h in hits.GetProperty("hits").EnumerateArray())
            {
                var src = h.GetProperty("_source");
                var id = h.GetProperty("_id").GetString() ?? string.Empty;
                var score = h.GetProperty("_score").GetDouble();

                var highlight = string.Empty;
                if (h.TryGetProperty("highlight", out var hl))
                {
                    var parts = new List<string>();
                    if (hl.TryGetProperty("content", out var c))
                    {
                        foreach (var f in c.EnumerateArray())
                            parts.Add(f.GetString() ?? string.Empty);
                    }

                    highlight = string.Join(" … ", parts);
                }

                var content = GetString(src, "content");
                if (string.IsNullOrEmpty(highlight))
                    highlight = content.Length > 300 ? content[..300] + "…" : content;

                chunks.Add(new Chunk
                {
                    ChunkId = new ChunkId(id),
                    DocumentId = GetString(src, "filename"),
                    Filename = GetString(src, "filename"),
                    Content = content,
                    ArticleNumber = GetString(src, "article_number"),
                    SectionTitle = GetString(src, "section_title"),
                    ChunkType = ChunkType.From(GetString(src, "chunk_type")),
                    DocumentType = DocumentType.From(GetString(src, "document_type")),
                    PageNumber = src.TryGetProperty("page_number", out var pn) && pn.ValueKind == JsonValueKind.Number
                        ? pn.GetInt32()
                        : null,
                    Score = new Score(score),
                    Highlight = highlight
                });
            }

            var docBuckets = new List<AggregationBucket>();
            var chunkBuckets = new List<AggregationBucket>();

            if (doc.RootElement.TryGetProperty("aggregations", out var aggs))
            {
                if (aggs.TryGetProperty("doc_types", out var dt))
                {
                    foreach (var b in dt.GetProperty("buckets").EnumerateArray())
                    {
                        docBuckets.Add(new AggregationBucket
                        {
                            Key = b.GetProperty("key").GetString() ?? string.Empty,
                            Count = b.GetProperty("doc_count").GetInt64()
                        });
                    }
                }

                if (aggs.TryGetProperty("chunk_types", out var ct))
                {
                    foreach (var b in ct.GetProperty("buckets").EnumerateArray())
                    {
                        chunkBuckets.Add(new AggregationBucket
                        {
                            Key = b.GetProperty("key").GetString() ?? string.Empty,
                            Count = b.GetProperty("doc_count").GetInt64()
                        });
                    }
                }
            }

            result = new SearchResult
            {
                Chunks = chunks,
                Total = totalProp,
                ElapsedMs = elapsedMs,
                MaxScore = maxScore,
                DocTypeBuckets = docBuckets,
                ChunkTypeBuckets = chunkBuckets
            };
        }
        catch (Exception ex)
        {
            logger.LogError(ex, "Failed to parse Elasticsearch response");
        }

        return result;
    }

    private static string GetString(JsonElement source, string key) =>
        source.TryGetProperty(key, out var value) && value.ValueKind == JsonValueKind.String
            ? value.GetString() ?? string.Empty
            : string.Empty;
}
