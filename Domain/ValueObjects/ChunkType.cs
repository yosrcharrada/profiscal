namespace FiscalPlatform.Domain.ValueObjects;

public readonly record struct ChunkType
{
    public string Value { get; }

    public ChunkType(string value)
    {
        Value = string.IsNullOrWhiteSpace(value) ? "all" : value.ToLowerInvariant();
    }

    public bool IsAll => Value == "all";

    public static ChunkType From(string? value) => new(value ?? "all");

    public override string ToString() => Value;
}
