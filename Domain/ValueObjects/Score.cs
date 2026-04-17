namespace FiscalPlatform.Domain.ValueObjects;

public readonly record struct Score(double Value) : IComparable<Score>
{
    public int CompareTo(Score other) => Value.CompareTo(other.Value);

    public bool IsHighRelevance(double threshold = 1.0) => Value >= threshold;

    public static implicit operator double(Score score) => score.Value;
}
