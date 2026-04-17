using FiscalPlatform.Domain.ValueObjects;

namespace FiscalPlatform.Domain.Entities;

public sealed class SearchFilters
{
    public DocumentType DocType { get; init; } = DocumentType.From("all");
    public ChunkType ChunkType { get; init; } = ChunkType.From("all");
    public int Size { get; init; } = 50;
    public int YearMin { get; init; } = 2000;
    public int YearMax { get; init; } = 2030;
}
