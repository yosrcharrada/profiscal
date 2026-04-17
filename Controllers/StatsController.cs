using FiscalPlatform.Application.Queries;
using MediatR;
using Microsoft.AspNetCore.Mvc;

namespace FiscalPlatform.Controllers;

[ApiController]
[Route("api/stats")]
public class StatsController(IMediator mediator) : ControllerBase
{
    [HttpGet]
    public async Task<IActionResult> GetStats()
    {
        var result = await mediator.Send(new GetKnowledgeBaseStatsQuery());
        return Ok(result);
    }
}
