namespace FiscalPlatform.Application.DTOs;

public sealed class SearchResultDto
{
    public List<ChunkDto> Hits { get; init; } = [];
    public int Total { get; init; }
    public double ElapsedMs { get; init; }
    public double MaxScore { get; init; }
    public List<AggBucketDto> DocTypeBuckets { get; init; } = [];
    public List<AggBucketDto> ChunkTypeBuckets { get; init; } = [];
}
