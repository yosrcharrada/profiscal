using FiscalPlatform.Application.DTOs;
using MediatR;

namespace FiscalPlatform.Application.Queries;

public sealed record GetKnowledgeBaseStatsQuery : IRequest<KnowledgeBaseStatsDto>;
