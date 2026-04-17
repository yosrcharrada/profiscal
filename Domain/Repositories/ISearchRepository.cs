using FiscalPlatform.Domain.Entities;

namespace FiscalPlatform.Domain.Repositories;

public interface ISearchRepository
{
    Task<SearchResult> SearchAsync(string query, SearchFilters filters);
    Task<long> CountAsync();
}
