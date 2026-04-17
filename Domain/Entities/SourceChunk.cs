namespace FiscalPlatform.Domain.Entities;

public sealed class SourceChunk
{
    public string DocName { get; init; } = string.Empty;
    public int PageNum { get; init; }
    public string Text { get; init; } = string.Empty;
    public string ChunkType { get; init; } = string.Empty;
    public string ArticleRef { get; init; } = string.Empty;
    public double Score { get; init; }
    public string Category { get; init; } = string.Empty;
}
