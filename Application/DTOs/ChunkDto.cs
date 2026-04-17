namespace FiscalPlatform.Application.DTOs;

public sealed class ChunkDto
{
    public string Id { get; init; } = string.Empty;
    public double Score { get; init; }
    public string Content { get; init; } = string.Empty;
    public string Filename { get; init; } = string.Empty;
    public string ArticleNumber { get; init; } = string.Empty;
    public string SectionTitle { get; init; } = string.Empty;
    public string ChunkType { get; init; } = string.Empty;
    public string DocumentType { get; init; } = string.Empty;
    public int? PageNumber { get; init; }
    public string Highlight { get; init; } = string.Empty;
}
