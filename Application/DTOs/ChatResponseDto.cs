namespace FiscalPlatform.Application.DTOs;

public sealed class ChatResponseDto
{
    public string Answer { get; init; } = string.Empty;
    public List<SourceChunkDto> Sources { get; init; } = [];
    public string Method { get; init; } = string.Empty;
    public double ElapsedMs { get; init; }
    public int ChunksRetrieved { get; init; }
}
