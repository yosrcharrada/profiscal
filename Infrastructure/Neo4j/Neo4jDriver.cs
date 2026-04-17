using Neo4j.Driver;

namespace FiscalPlatform.Infrastructure.Neo4j;

public sealed class Neo4jDriver : IDisposable
{
    public IDriver Driver { get; }
    public string Database { get; }

    public Neo4jDriver(IConfiguration config)
    {
        var uri = config["Neo4j:Uri"] ?? "neo4j://127.0.0.1:7687";
        var user = config["Neo4j:Username"] ?? "neo4j";
        var pass = config["Neo4j:Password"] ?? "neo4j";

        Database = config["Neo4j:Database"] ?? "neo4j";
        Driver = GraphDatabase.Driver(uri, AuthTokens.Basic(user, pass));
    }

    public void Dispose() => Driver.Dispose();
}
