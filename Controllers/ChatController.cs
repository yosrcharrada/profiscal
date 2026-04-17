using FiscalPlatform.Application.DTOs;
using FiscalPlatform.Application.Queries;
using FiscalPlatform.Infrastructure.Neo4j;
using FiscalPlatform.Models;
using MediatR;
using Microsoft.AspNetCore.Mvc;

namespace FiscalPlatform.Controllers;

[ApiController]
[Route("api/chat")]
public class ChatController(IMediator mediator, Neo4jHealthRepository healthRepository) : ControllerBase
{
    [HttpPost]
    public async Task<IActionResult> Chat([FromBody] ChatRequest req)
    {
        if (string.IsNullOrWhiteSpace(req.Question))
            return BadRequest(new { error = "Question is required" });

        var query = new ChatQuery(
            req.Question,
            req.History.Select(h => new ChatMessageDto { Role = h.Role, Content = h.Content }).ToList());

        var result = await mediator.Send(query);
        return Ok(result);
    }

    [HttpGet("health")]
    public async Task<IActionResult> Health()
    {
        var alive = await healthRepository.IsHealthyAsync();
        return Ok(new { alive });
    }
}
