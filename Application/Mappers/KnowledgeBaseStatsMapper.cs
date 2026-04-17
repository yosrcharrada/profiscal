using FiscalPlatform.Application.DTOs;
using FiscalPlatform.Domain.Entities;

namespace FiscalPlatform.Application.Mappers;

public static class KnowledgeBaseStatsMapper
{
    public static KnowledgeBaseStatsDto ToDto(KnowledgeBaseStats stats) => new()
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
        EsChunks = stats.EsChunks
    };
}
