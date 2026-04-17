using FiscalPlatform.Application.DTOs;
using FiscalPlatform.Application.Mappers;
using FiscalPlatform.Domain.Entities;
using FiscalPlatform.Domain.Repositories;
using FiscalPlatform.Domain.ValueObjects;
using MediatR;

namespace FiscalPlatform.Application.Queries;

public sealed class SearchDocumentsQueryHandler(ISearchRepository searchRepository)
    : IRequestHandler<SearchDocumentsQuery, SearchResultDto>
{
    public async Task<SearchResultDto> Handle(SearchDocumentsQuery request, CancellationToken cancellationToken)
    {
        var filters = new SearchFilters
        {
            DocType = DocumentType.From(request.DocType),
            ChunkType = ChunkType.From(request.ChunkType),
            Size = request.Size,
            YearMin = request.YearMin,
            YearMax = request.YearMax
        };

        var domainResult = await searchRepository.SearchAsync(request.Query, filters);
        return SearchResultMapper.ToDto(domainResult);
    }
}
