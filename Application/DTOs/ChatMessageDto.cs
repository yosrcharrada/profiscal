namespace FiscalPlatform.Application.DTOs;

public sealed class ChatMessageDto
{
    public string Role { get; init; } = "user";
    public string Content { get; init; } = string.Empty;
}
