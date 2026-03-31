namespace FiscalPlatform.Models;

// ── Search Engine Models ────────────────────────────────────────────────────

public class SearchRequest
{
    public string Query { get; set; } = "";
    public string DocType { get; set; } = "all";
    public string ChunkType { get; set; } = "all";
    public int Size { get; set; } = 50;
    public int YearMin { get; set; } = 2000;
    public int YearMax { get; set; } = 2030;
}

public class SearchResponse
{
    public List<SearchHit> Hits { get; set; } = new();
    public int Total { get; set; }
    public double ElapsedMs { get; set; }
    public double MaxScore { get; set; }
    public List<AggBucket> DocTypeBuckets { get; set; } = new();
    public List<AggBucket> ChunkTypeBuckets { get; set; } = new();
}

public class SearchHit
{
    public string Id { get; set; } = "";
    public double Score { get; set; }
    public string Content { get; set; } = "";
    public string Filename { get; set; } = "";
    public string ArticleNumber { get; set; } = "";
    public string SectionTitle { get; set; } = "";
    public string ChunkType { get; set; } = "";
    public string DocumentType { get; set; } = "";
    public int? PageNumber { get; set; }
    public string Highlight { get; set; } = "";
}

public class AggBucket
{
    public string Key { get; set; } = "";
    public long Count { get; set; }
}

// ── Chatbot / GraphRAG Models ───────────────────────────────────────────────

public class ChatRequest
{
    public string Question { get; set; } = "";
    public List<ChatMessage> History { get; set; } = new();
}

public class ChatMessage
{
    public string Role { get; set; } = "user"; // "user" | "assistant"
    public string Content { get; set; } = "";
}

public class ChatResponse
{
    public string Answer { get; set; } = "";
    public List<SourceChunk> Sources { get; set; } = new();
    public string Method { get; set; } = "";
    public double ElapsedMs { get; set; }
    public int ChunksRetrieved { get; set; }
}

public class SourceChunk
{
    public string DocName { get; set; } = "";
    public int PageNum { get; set; }
    public string Text { get; set; } = "";
    public string ChunkType { get; set; } = "";
    public string ArticleRef { get; set; } = "";
    public double Score { get; set; }
    public string Category { get; set; } = ""; // loi, note, code, convention
}

// ── Stats Models ────────────────────────────────────────────────────────────

public class KnowledgeBaseStats
{
    public long TotalChunks { get; set; }
    public long TotalEntities { get; set; }
    public long TotalRelations { get; set; }
    public long LoisCount { get; set; }
    public long NotesCount { get; set; }
    public long CodesCount { get; set; }
    public long ConventionsCount { get; set; }
    public long TextChunks { get; set; }
    public long TableChunks { get; set; }
    public bool GnnActive { get; set; }
    public long EsChunks { get; set; }
}
