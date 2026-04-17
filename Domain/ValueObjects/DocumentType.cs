namespace FiscalPlatform.Domain.ValueObjects;

public readonly record struct DocumentType
{
    public static readonly string[] Supported = ["loi", "note_commune", "code", "convention", "all"];

    public string Value { get; }

    public DocumentType(string value)
    {
        Value = string.IsNullOrWhiteSpace(value) ? "loi" : value.ToLowerInvariant();
    }

    public bool IsAll => Value == "all";

    public static DocumentType From(string? value) => new(value ?? "all");

    public override string ToString() => Value;
}
