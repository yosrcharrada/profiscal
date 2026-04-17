using FiscalPlatform.Domain.Repositories;

namespace FiscalPlatform.Infrastructure.Elasticsearch;

public sealed class ElasticsearchHealthRepository(ElasticsearchClient client) : IHealthRepository
{
    public Task<bool> IsHealthyAsync() => client.IsHealthyAsync();
}
