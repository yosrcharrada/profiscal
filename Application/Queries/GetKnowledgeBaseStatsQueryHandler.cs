using FiscalPlatform.Application.DTOs;
using FiscalPlatform.Application.Mappers;
using FiscalPlatform.Domain.Repositories;
using MediatR;

namespace FiscalPlatform.Application.Queries;

public sealed class GetKnowledgeBaseStatsQueryHandler(
    IKnowledgeGraphRepository knowledgeGraphRepository,
    ISearchRepository searchRepository)
    : IRequestHandler<GetKnowledgeBaseStatsQuery, KnowledgeBaseStatsDto>
{
    public async Task<KnowledgeBaseStatsDto> Handle(GetKnowledgeBaseStatsQuery request, CancellationToken cancellationToken)
    {
        var stats = await knowledgeGraphRepository.GetStatsAsync();
        var esCount = await searchRepository.CountAsync();

        var updated = new Domain.Entities.KnowledgeBaseStats
        {
            TotalChunks = stats.TotalChunks,
            TotalEntities = stats.TotalEntities,
            TotalRelations = stats.TotalRelations,
            LoisCount = stats.LoisCount,
            NotesCount = stats.NotesCount,
            CodesCount = stats.CodesCount,
            ConventionsCount = stats.ConventionsCount,
            TextChunks = stats.TextChunks,
            TableChunks = stats.TableChunks,
            GnnActive = stats.GnnActive,
            EsChunks = esCount
        };

        return KnowledgeBaseStatsMapper.ToDto(updated);
    }
}
