using FiscalPlatform.Domain.Repositories;

namespace FiscalPlatform.Infrastructure.Neo4j;

public sealed class Neo4jHealthRepository(Neo4jDriver neo4jDriver) : IHealthRepository
{
    public async Task<bool> IsHealthyAsync()
    {
        try
        {
            await using var session = neo4jDriver.Driver.AsyncSession(o => o.WithDatabase(neo4jDriver.Database));
            await session.RunAsync("RETURN 1");
            return true;
        }
        catch
        {
            return false;
        }
    }
}
