namespace FiscalPlatform.Domain.Entities;

public sealed class KnowledgeBaseStats
{
    public long TotalChunks { get; init; }
    public long TotalEntities { get; init; }
    public long TotalRelations { get; init; }
    public long LoisCount { get; init; }
    public long NotesCount { get; init; }
    public long CodesCount { get; init; }
    public long ConventionsCount { get; init; }
    public long TextChunks { get; init; }
    public long TableChunks { get; init; }
    public bool GnnActive { get; init; }
    public long EsChunks { get; init; }
}
