using FiscalPlatform.Domain.Entities;

namespace FiscalPlatform.Domain.Repositories;

public interface IKnowledgeGraphRepository
{
    Task<List<SourceChunk>> VectorSearchAsync(float[] embedding, int topK);
    Task<List<SourceChunk>> KeywordFallbackAsync(string query, int topK);
    Task<KnowledgeBaseStats> GetStatsAsync();
}
