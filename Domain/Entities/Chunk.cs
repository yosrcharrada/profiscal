using FiscalPlatform.Domain.ValueObjects;

namespace FiscalPlatform.Domain.Entities;

public sealed class Chunk
{
    public ChunkId ChunkId { get; init; }
    public string DocumentId { get; init; } = string.Empty;
    public string Filename { get; init; } = string.Empty;
    public string Content { get; init; } = string.Empty;
    public string ArticleNumber { get; init; } = string.Empty;
    public string SectionTitle { get; init; } = string.Empty;
    public int? PageNumber { get; init; }
    public DocumentType DocumentType { get; init; } = DocumentType.From("loi");
    public ChunkType ChunkType { get; init; } = ChunkType.From("text");
    public Score Score { get; init; }
    public string Highlight { get; init; } = string.Empty;

    public bool IsHighRelevance(double threshold = 1.0) => Score.IsHighRelevance(threshold);

    public string GetCategoryLabel() => DocumentType.Value;
}
