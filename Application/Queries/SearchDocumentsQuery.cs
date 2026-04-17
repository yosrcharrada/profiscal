using FiscalPlatform.Application.DTOs;
using MediatR;

namespace FiscalPlatform.Application.Queries;

public sealed record SearchDocumentsQuery(
    string Query,
    string DocType,
    string ChunkType,
    int Size,
    int YearMin,
    int YearMax) : IRequest<SearchResultDto>;
