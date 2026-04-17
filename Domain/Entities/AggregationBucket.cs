namespace FiscalPlatform.Domain.Entities;

public sealed class AggregationBucket
{
    public string Key { get; init; } = string.Empty;
    public long Count { get; init; }
}
