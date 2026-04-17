using FiscalPlatform.Application.DTOs;
using FiscalPlatform.Domain.Entities;

namespace FiscalPlatform.Application.Mappers;

public static class SearchResultMapper
{
    public static SearchResultDto ToDto(SearchResult result) => new()
    {
        Hits = result.Chunks.Select(ChunkMapper.ToDto).ToList(),
        Total = result.Total,
        ElapsedMs = result.ElapsedMs,
        MaxScore = result.MaxScore,
        DocTypeBuckets = result.DocTypeBuckets.Select(b => new AggBucketDto { Key = b.Key, Count = b.Count }).ToList(),
        ChunkTypeBuckets = result.ChunkTypeBuckets.Select(b => new AggBucketDto { Key = b.Key, Count = b.Count }).ToList()
    };
}
