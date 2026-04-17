namespace FiscalPlatform.Domain.ValueObjects;

public readonly record struct ChunkId
{
    public string Value { get; }

    public ChunkId(string value)
    {
        if (string.IsNullOrWhiteSpace(value))
            throw new ArgumentException("ChunkId cannot be empty", nameof(value));
        Value = value;
    }

    public override string ToString() => Value;
}
