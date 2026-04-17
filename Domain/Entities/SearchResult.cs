namespace FiscalPlatform.Domain.Entities;

public sealed class SearchResult
{
    public List<Chunk> Chunks { get; init; } = [];
    public int Total { get; init; }
    public double ElapsedMs { get; init; }
    public double MaxScore { get; init; }
    public List<AggregationBucket> DocTypeBuckets { get; init; } = [];
    public List<AggregationBucket> ChunkTypeBuckets { get; init; } = [];
}
