using FiscalPlatform.Application.Queries;
using FiscalPlatform.Domain.Repositories;
using FiscalPlatform.Infrastructure.Elasticsearch;
using FiscalPlatform.Models;
using MediatR;
using Microsoft.AspNetCore.Mvc;

namespace FiscalPlatform.Controllers;

[ApiController]
[Route("api/search")]
public class SearchController(IMediator mediator, ISearchRepository searchRepository, ElasticsearchHealthRepository healthRepository)
    : ControllerBase
{
    [HttpPost]
    public async Task<IActionResult> Search([FromBody] SearchRequest req)
    {
        if (string.IsNullOrWhiteSpace(req.Query))
            return BadRequest(new { error = "Query is required" });

        var query = new SearchDocumentsQuery(
            req.Query,
            req.DocType,
            req.ChunkType,
            req.Size,
            req.YearMin,
            req.YearMax);

        var result = await mediator.Send(query);
        return Ok(result);
    }

    [HttpGet("health")]
    public async Task<IActionResult> Health()
    {
        var alive = await healthRepository.IsHealthyAsync();
        var count = alive ? await searchRepository.CountAsync() : 0;
        return Ok(new { alive, count });
    }
}
