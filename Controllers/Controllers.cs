using Microsoft.AspNetCore.Mvc;
using FiscalPlatform.Models;
using FiscalPlatform.Services;

namespace FiscalPlatform.Controllers;

// ── Home / SPA shell ─────────────────────────────────────────────────────────

public class HomeController : Controller
{
    public IActionResult Index() => View();
}

// ── Search API ────────────────────────────────────────────────────────────────

[ApiController]
[Route("api/search")]
public class SearchController : ControllerBase
{
    private readonly ElasticsearchService _es;
    public SearchController(ElasticsearchService es) => _es = es;

    [HttpPost]
    public async Task<IActionResult> Search([FromBody] SearchRequest req)
    {
        if (string.IsNullOrWhiteSpace(req.Query))
            return BadRequest(new { error = "Query is required" });
        var result = await _es.SearchAsync(req);
        return Ok(result);
    }

    [HttpGet("health")]
    public async Task<IActionResult> Health()
    {
        var alive = await _es.IsAliveAsync();
        var count = alive ? await _es.CountAsync() : 0;
        return Ok(new { alive, count });
    }
}

// ── Chat / GraphRAG API ───────────────────────────────────────────────────────

[ApiController]
[Route("api/chat")]
public class ChatController : ControllerBase
{
    private readonly GraphRagService _rag;
    private readonly Neo4jService    _neo4j;

    public ChatController(GraphRagService rag, Neo4jService neo4j)
    {
        _rag   = rag;
        _neo4j = neo4j;
    }

    [HttpPost]
    public async Task<IActionResult> Chat([FromBody] ChatRequest req)
    {
        if (string.IsNullOrWhiteSpace(req.Question))
            return BadRequest(new { error = "Question is required" });
        var result = await _rag.AnswerAsync(req);
        return Ok(result);
    }

    [HttpGet("health")]
    public async Task<IActionResult> Health()
    {
        var alive = await _neo4j.IsAliveAsync();
        return Ok(new { alive });
    }
}

// ── Stats API ─────────────────────────────────────────────────────────────────

[ApiController]
[Route("api/stats")]
public class StatsController : ControllerBase
{
    private readonly Neo4jService         _neo4j;
    private readonly ElasticsearchService _es;

    public StatsController(Neo4jService neo4j, ElasticsearchService es)
    {
        _neo4j = neo4j;
        _es    = es;
    }

    [HttpGet]
    public async Task<IActionResult> GetStats()
    {
        var stats = await _neo4j.GetStatsAsync();
        stats.EsChunks = await _es.CountAsync();
        return Ok(stats);
    }
}
