using FiscalPlatform.Application.DTOs;
using MediatR;

namespace FiscalPlatform.Application.Queries;

public sealed record ChatQuery(string Question, List<ChatMessageDto> History) : IRequest<ChatResponseDto>;
