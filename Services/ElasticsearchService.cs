using System.Text;
using System.Text.Json;
using FiscalPlatform.Models;

namespace FiscalPlatform.Services;

/// <summary>
/// Wraps Elasticsearch calls: BM25 + fuzzy search with highlighting,
/// mirroring the Python app.py logic.
/// </summary>
public class ElasticsearchService
{
    private readonly HttpClient _http;
    private readonly string _host;
    private readonly string _index;
    private readonly ILogger<ElasticsearchService> _logger;

    public ElasticsearchService(IConfiguration config, IHttpClientFactory factory, ILogger<ElasticsearchService> logger)
    {
        _host   = config["Elasticsearch:Host"]  ?? "http://localhost:9200";
        _index  = config["Elasticsearch:Index"] ?? "tunisian_legal";
        _http   = factory.CreateClient();
        _logger = logger;
    }

    // ── Health / count ────────────────────────────────────────────────────────

    public async Task<bool> IsAliveAsync()
    {
        try
        {
            var resp = await _http.GetAsync($"{_host}/_cluster/health?timeout=3s");
            return resp.IsSuccessStatusCode;
        }
        catch { return false; }
    }

    public async Task<long> CountAsync()
    {
        try
        {
            var resp = await _http.GetAsync($"{_host}/{_index}/_count");
            var body = await resp.Content.ReadAsStringAsync();
            var doc  = JsonDocument.Parse(body);
            return doc.RootElement.GetProperty("count").GetInt64();
        }
        catch { return 0; }
    }

    // ── Main search ───────────────────────────────────────────────────────────

    public async Task<SearchResponse> SearchAsync(SearchRequest req)
    {
        var sw = System.Diagnostics.Stopwatch.StartNew();

        var query = BuildQuery(req);
        var json  = JsonSerializer.Serialize(query);
        var content = new StringContent(json, Encoding.UTF8, "application/json");

        var resp = await _http.PostAsync($"{_host}/{_index}/_search", content);
        var body = await resp.Content.ReadAsStringAsync();
        sw.Stop();

        return ParseResponse(body, sw.Elapsed.TotalMilliseconds);
    }

    // ── Query DSL builder (mirrors Python do_search) ─────────────────────────

    private object BuildQuery(SearchRequest req)
    {
        var q = req.Query;
        var filters = new List<object>();

        if (req.DocType != "all")
            filters.Add(new { term = new { document_type = req.DocType } });
        if (req.ChunkType != "all")
            filters.Add(new { term = new { chunk_type = req.ChunkType } });

        object boolQuery;
        if (filters.Count > 0)
        {
            boolQuery = new
            {
                @bool = new
                {
                    must = BuildMultiMatch(q),
                    filter = filters
                }
            };
        }
        else
        {
            boolQuery = new { @bool = new { must = BuildMultiMatch(q) } };
        }

        return new
        {
            size = req.Size,
            query = boolQuery,
            highlight = new
            {
                fields = new
                {
                    content         = new { number_of_fragments = 3, fragment_size = 200, pre_tags = new[] { "<em>" }, post_tags = new[] { "</em>" } },
                    article_number  = new { number_of_fragments = 1 },
                    section_title   = new { number_of_fragments = 1 }
                }
            },
            aggs = new
            {
                doc_types   = new { terms = new { field = "document_type", size = 10 } },
                chunk_types = new { terms = new { field = "chunk_type",    size = 20 } }
            },
            _source = new[] { "content", "filename", "article_number", "section_title",
                              "chunk_type", "document_type", "page_number", "chunk_id" }
        };
    }

    private object BuildMultiMatch(string q)
    {
        return new object[]
        {
            new
            {
                multi_match = new
                {
                    query    = q,
                    fields   = new[] { "content^3", "article_number^2", "section_title^1.5", "filename" },
                    type     = "best_fields",
                    fuzziness = "AUTO",
                    operator  = "or"
                }
            }
        };
    }

    // ── Response parser ───────────────────────────────────────────────────────

    private SearchResponse ParseResponse(string body, double elapsedMs)
    {
        var result = new SearchResponse { ElapsedMs = elapsedMs };
        try
        {
            var doc   = JsonDocument.Parse(body);
            var hits  = doc.RootElement.GetProperty("hits");
            result.Total    = hits.GetProperty("total").GetProperty("value").GetInt32();
            result.MaxScore = hits.TryGetProperty("max_score", out var ms) && ms.ValueKind == JsonValueKind.Number
                ? ms.GetDouble() : 1.0;

            foreach (var h in hits.GetProperty("hits").EnumerateArray())
            {
                var src = h.GetProperty("_source");
                var hit = new SearchHit
                {
                    Id            = h.GetProperty("_id").GetString() ?? "",
                    Score         = h.GetProperty("_score").GetDouble(),
                    Content       = GetStr(src, "content"),
                    Filename      = GetStr(src, "filename"),
                    ArticleNumber = GetStr(src, "article_number"),
                    SectionTitle  = GetStr(src, "section_title"),
                    ChunkType     = GetStr(src, "chunk_type"),
                    DocumentType  = GetStr(src, "document_type"),
                    PageNumber    = src.TryGetProperty("page_number", out var pn) && pn.ValueKind == JsonValueKind.Number
                        ? pn.GetInt32() : null,
                };

                // Highlight
                if (h.TryGetProperty("highlight", out var hl))
                {
                    var parts = new List<string>();
                    if (hl.TryGetProperty("content", out var c))
                        foreach (var f in c.EnumerateArray()) parts.Add(f.GetString() ?? "");
                    hit.Highlight = string.Join(" … ", parts);
                }
                if (string.IsNullOrEmpty(hit.Highlight))
                    hit.Highlight = hit.Content.Length > 300 ? hit.Content[..300] + "…" : hit.Content;

                result.Hits.Add(hit);
            }

            // Aggregations
            if (doc.RootElement.TryGetProperty("aggregations", out var aggs))
            {
                if (aggs.TryGetProperty("doc_types", out var dt))
                    foreach (var b in dt.GetProperty("buckets").EnumerateArray())
                        result.DocTypeBuckets.Add(new AggBucket { Key = b.GetProperty("key").GetString()!, Count = b.GetProperty("doc_count").GetInt64() });
                if (aggs.TryGetProperty("chunk_types", out var ct))
                    foreach (var b in ct.GetProperty("buckets").EnumerateArray())
                        result.ChunkTypeBuckets.Add(new AggBucket { Key = b.GetProperty("key").GetString()!, Count = b.GetProperty("doc_count").GetInt64() });
            }
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Failed to parse ES response");
        }
        return result;
    }

    private static string GetStr(JsonElement el, string key)
        => el.TryGetProperty(key, out var v) && v.ValueKind == JsonValueKind.String ? v.GetString() ?? "" : "";
}
