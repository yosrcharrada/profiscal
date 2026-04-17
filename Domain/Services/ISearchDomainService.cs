using FiscalPlatform.Domain.Entities;

namespace FiscalPlatform.Domain.Services;

public interface ISearchDomainService
{
    SearchResult Rank(SearchResult result);
}
