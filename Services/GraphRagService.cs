using System.Text;
using FiscalPlatform.Models;
using Azure;
using Azure.AI.OpenAI;
using System.ClientModel;   // REQUIRED

namespace FiscalPlatform.Services;

public class GraphRagService
{
    private readonly Neo4jService _neo4j;
    private readonly ILogger<GraphRagService> _logger;

    private readonly string _model;
    private readonly string _apiKey;
    private readonly string _endpoint;
    private readonly string _apiVersion;

    public GraphRagService(Neo4jService neo4j, ILogger<GraphRagService> logger)
    {
        _neo4j = neo4j;
        _logger = logger;

        _model      = Environment.GetEnvironmentVariable("LLM_MODEL") ?? "gpt-4o";
        _apiKey     = Environment.GetEnvironmentVariable("OPENAI_API_KEY") ?? "";
        _endpoint   = Environment.GetEnvironmentVariable("OPENAI_ENDPOINT") ?? "";
        _apiVersion = Environment.GetEnvironmentVariable("OPENAI_API_VERSION") ?? "2024-02-15-preview";
    }

    // =====================================================================
    // ENTRY POINT
    // =====================================================================
    public async Task<ChatResponse> AnswerAsync(ChatRequest req)
    {
        var sw = System.Diagnostics.Stopwatch.StartNew();
        string q = req.Question.Trim();

        // We use keyword fallback only (no embeddings yet)
        var chunks = await _neo4j.KeywordFallbackAsync(q, topK: 10);

        string ctx = BuildContext(chunks);
        string answer = await CallAzureAsync(q, ctx, req.History);

        sw.Stop();

        return new ChatResponse
        {
            Answer = answer,
            Sources = chunks.Take(10).ToList(),
            Method = "keyword",
            ElapsedMs = sw.Elapsed.TotalMilliseconds,
            ChunksRetrieved = chunks.Count
        };
    }

    // =====================================================================
    // CONTEXT BUILDER
    // =====================================================================
    private static string BuildContext(List<SourceChunk> chunks)
    {
        var sb = new StringBuilder();

        for (int i = 0; i < Math.Min(chunks.Count, 8); i++)
        {
            var c = chunks[i];
            sb.AppendLine($"[Source {i+1}: {c.DocName}, p.{c.PageNum}]");
            sb.AppendLine(c.Text.Length > 600 ? c.Text[..600] + "…" : c.Text);
            sb.AppendLine();
        }

        return sb.ToString();
    }

    // =====================================================================
    // ✅ FABRIC / AZURE OPENAI CLIENT  (MATCHES YOUR PYTHON SCRIPT)
    // =====================================================================
    private async Task<string> CallAzureAsync(string question, string context, List<ChatMessage> history)
    {
        var client = new OpenAIClient(
            new Uri(_endpoint),
            new AzureKeyCredential(_apiKey)
        );

        // ✅ Build Azure messages (NOT your ChatMessage class)
        var messages = new List<ChatRequestMessage>();

        messages.Add(new ChatRequestSystemMessage(
@"Tu es un expert en fiscalité tunisienne.
Analyse d'abord la question, puis utilise les extraits fournis pour retrouver 
les passages les plus pertinents.

SI les sources fournies NE mentionnent PAS directement la réponse :
- utilise le raisonnement fiscal logique,
- combine les indices présents dans les textes,
- recherche les termes proches ou notions équivalentes,
- propose la réponse la PLUS probable et EXPLIQUE pourquoi.

NE réponds 'les sources ne traitent pas du sujet' que si VRAIMENT 
aucun élément n’est exploitable.

Structure toujours ta réponse ainsi :
1️. Ce que disent les sources  
2️. Analyse et interprétation  
3️. Réponse finale  
4. Références exactes aux extraits utilisés"
));

        foreach (var h in history.TakeLast(4))
        {
            if (h.Role == "assistant")
                messages.Add(new ChatRequestAssistantMessage(h.Content));
            else
                messages.Add(new ChatRequestUserMessage(h.Content));
        }

        messages.Add(new ChatRequestUserMessage(
            $"Sources:\n{context}\n\nQuestion: {question}"
        ));

        var opts = new ChatCompletionsOptions()
        {
            Temperature = 0
        };

        foreach (var m in messages)
            opts.Messages.Add(m);

        // ✅ Correct method for Azure.AI.OpenAI beta.15 (NO deploymentId=)
        opts.DeploymentName = _model;   // <-- tell the SDK which deployment to use

        var response = await client.GetChatCompletionsAsync(opts);


        return response.Value.Choices[0].Message.Content;
    }
};