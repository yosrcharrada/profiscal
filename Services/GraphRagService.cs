using System.Text;
using System.Text.Json;
using FiscalPlatform.Models;

namespace FiscalPlatform.Services;

/// <summary>
/// Orchestrates the full GraphRAG pipeline:
///   1. Embed query (HuggingFace / Ollama)
///   2. Vector search in Neo4j (GNN embeddings preferred)
///   3. Graph expansion via entity mentions
///   4. Deduplicate + rank
///   5. Generate answer via LLM (Ollama or Gemini)
/// </summary>
public class GraphRagService
{
    private readonly Neo4jService _neo4j;
    private readonly HttpClient   _http;
    private readonly IConfiguration _config;
    private readonly ILogger<GraphRagService> _logger;

    private readonly string _llmProvider;
    private readonly string _llmModel;
    private readonly string _ollamaHost;

    public GraphRagService(Neo4jService neo4j, IHttpClientFactory factory,
                           IConfiguration config, ILogger<GraphRagService> logger)
    {
        _neo4j       = neo4j;
        _http        = factory.CreateClient();
        _config      = config;
        _logger      = logger;
        _llmProvider = config["Llm:Provider"] ?? "ollama";
        _llmModel    = config["Llm:Model"]    ?? "phi3:mini";
        _ollamaHost  = config["Llm:OllamaHost"] ?? "http://localhost:11434";
    }

    // ── Public entry point ────────────────────────────────────────────────────

    public async Task<ChatResponse> AnswerAsync(ChatRequest req)
    {
        var sw = System.Diagnostics.Stopwatch.StartNew();
        var question = req.Question.Trim();

        // Step 1 — try embedding
        float[]? embedding = null;
        string method = "keyword";
        try
        {
            embedding = await EmbedAsync(question);
            method = "vector";
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Embedding failed, falling back to keyword");
        }

        // Step 2 — retrieve chunks
        List<SourceChunk> chunks;
        if (embedding != null)
        {
            var vectorChunks = await _neo4j.VectorSearchAsync(embedding, topK: 8);
            var entities     = ExtractKeywords(question);
            var graphChunks  = await _neo4j.GraphExpandAsync(entities, topK: 6);
            chunks = MergeAndRank(vectorChunks, graphChunks);
            if (graphChunks.Any()) method = "vector+graph";
        }
        else
        {
            chunks = await _neo4j.KeywordFallbackAsync(question, topK: 10);
        }

        // Step 3 — build context + generate answer
        var context = BuildContext(chunks);
        var answer  = await GenerateAnswerAsync(question, context, req.History);

        sw.Stop();
        return new ChatResponse
        {
            Answer          = answer,
            Sources         = chunks.Take(10).ToList(),
            Method          = method,
            ElapsedMs       = sw.Elapsed.TotalMilliseconds,
            ChunksRetrieved = chunks.Count,
        };
    }

    // ── Embedding ─────────────────────────────────────────────────────────────

    private async Task<float[]> EmbedAsync(string text)
    {
        // Call local Ollama embedding endpoint
        var payload = JsonSerializer.Serialize(new { model = "nomic-embed-text", prompt = text });
        var resp = await _http.PostAsync(
            $"{_ollamaHost}/api/embeddings",
            new StringContent(payload, Encoding.UTF8, "application/json"));
        resp.EnsureSuccessStatusCode();
        var body = await resp.Content.ReadAsStringAsync();
        var doc  = JsonDocument.Parse(body);
        var arr  = doc.RootElement.GetProperty("embedding").EnumerateArray()
                      .Select(x => x.GetSingle()).ToArray();
        return arr;
    }

    // ── Keyword extraction (simple, no NLP dep) ───────────────────────────────

    private static List<string> ExtractKeywords(string text)
    {
        var stop = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            "le","la","les","de","du","des","un","une","que","qui","quoi","quel",
            "quelle","quels","quelles","en","au","aux","et","ou","mais","donc",
            "or","ni","car","par","pour","sur","sous","dans","avec","sans","est",
            "sont","a","ont","se","ne","pas","plus","comment","quand","où","ce",
            "si","tout","très","bien","aussi","même","autre","autres","il","elle",
            "ils","elles","nous","vous","je","tu","mon","ma","mes","son","sa","ses",
            "leur","leurs","quoi","dont","quel","taux","applicable","tunisie","tunisien"
        };
        return text.Split(new[] {' ',',','.','?','!',';',':','\n','\r'},
                StringSplitOptions.RemoveEmptyEntries)
            .Where(w => w.Length > 3 && !stop.Contains(w))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .Take(8)
            .ToList();
    }

    // ── Merge & deduplicate retrieved chunks ──────────────────────────────────

    private static List<SourceChunk> MergeAndRank(List<SourceChunk> vec, List<SourceChunk> graph)
    {
        var seen = new HashSet<string>();
        var all  = new List<SourceChunk>();
        foreach (var c in vec.Concat(graph))
        {
            var key = $"{c.DocName}_{c.PageNum}_{c.Text[..Math.Min(40, c.Text.Length)]}";
            if (seen.Add(key)) all.Add(c);
        }
        return all.OrderByDescending(c => c.Score).ToList();
    }

    // ── Context builder ───────────────────────────────────────────────────────

    private static string BuildContext(List<SourceChunk> chunks)
    {
        var sb = new StringBuilder();
        for (int i = 0; i < Math.Min(chunks.Count, 8); i++)
        {
            var c = chunks[i];
            var ref_ = !string.IsNullOrEmpty(c.ArticleRef) ? $" [{c.ArticleRef}]" : "";
            sb.AppendLine($"[Source {i+1}: {c.DocName}, page {c.PageNum}{ref_}]");
            sb.AppendLine(c.Text.Length > 600 ? c.Text[..600] + "…" : c.Text);
            sb.AppendLine();
        }
        return sb.ToString();
    }

    // ── LLM call ──────────────────────────────────────────────────────────────

    private async Task<string> GenerateAnswerAsync(string question, string context,
                                                    List<ChatMessage> history)
    {
        var systemPrompt = @"Tu es un expert en fiscalité tunisienne. 
Tu réponds aux questions basées UNIQUEMENT sur les sources fournies.
Si une information n'est pas dans les sources, dis-le clairement.
Réponds en français de manière structurée et précise.
Cite les articles de loi et les références spécifiques quand disponibles.";

        var userMessage = $@"Voici les sources pertinentes :

{context}

Question : {question}

Réponds de manière précise en te basant sur ces sources.";

        if (_llmProvider == "ollama")
            return await CallOllamaAsync(systemPrompt, userMessage, history);

        // Fallback — structured response without LLM
        return BuildFallbackAnswer(question, context);
    }

    private async Task<string> CallOllamaAsync(string system, string user,
                                                List<ChatMessage> history)
    {
        var messages = new List<object> { new { role = "system", content = system } };
        foreach (var h in history.TakeLast(4))
            messages.Add(new { role = h.Role, content = h.Content });
        messages.Add(new { role = "user", content = user });

        var payload = JsonSerializer.Serialize(new
        {
            model    = _llmModel,
            messages,
            stream   = false,
            options  = new { temperature = 0.1, num_predict = 1024 }
        });

        try
        {
            var resp = await _http.PostAsync(
                $"{_ollamaHost}/api/chat",
                new StringContent(payload, Encoding.UTF8, "application/json"));
            var body = await resp.Content.ReadAsStringAsync();
            var doc  = JsonDocument.Parse(body);
            return doc.RootElement
                      .GetProperty("message")
                      .GetProperty("content")
                      .GetString() ?? "Réponse indisponible.";
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Ollama call failed");
            return BuildFallbackAnswer("", "");
        }
    }

    private static string BuildFallbackAnswer(string question, string context)
    {
        if (string.IsNullOrEmpty(context))
            return "⚠️ Le service LLM est indisponible et aucune source n'a été trouvée pour cette question.";

        return $"📋 **Sources trouvées :**\n\n{context}\n\n" +
               "_Le service LLM (Ollama) est indisponible. Les sources brutes sont affichées ci-dessus._";
    }
}
