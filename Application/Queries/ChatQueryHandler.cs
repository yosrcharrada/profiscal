using System.Text;
using FiscalPlatform.Application.DTOs;
using FiscalPlatform.Application.Mappers;
using FiscalPlatform.Domain.Repositories;
using FiscalPlatform.Infrastructure.LLM;
using MediatR;

namespace FiscalPlatform.Application.Queries;

public sealed class ChatQueryHandler(
    IKnowledgeGraphRepository knowledgeGraphRepository,
    AzureOpenAiService azureOpenAiService)
    : IRequestHandler<ChatQuery, ChatResponseDto>
{
    public async Task<ChatResponseDto> Handle(ChatQuery request, CancellationToken cancellationToken)
    {
        var sw = System.Diagnostics.Stopwatch.StartNew();

        var chunks = await knowledgeGraphRepository.KeywordFallbackAsync(request.Question.Trim(), topK: 10);
        var context = BuildContext(chunks);

        var answer = await azureOpenAiService.GetAnswerAsync(request.Question.Trim(), context, request.History);

        sw.Stop();

        return new ChatResponseDto
        {
            Answer = answer,
            Sources = chunks.Take(10).Select(ChunkMapper.ToDto).ToList(),
            Method = "keyword",
            ElapsedMs = sw.Elapsed.TotalMilliseconds,
            ChunksRetrieved = chunks.Count
        };
    }

    private static string BuildContext(List<Domain.Entities.SourceChunk> chunks)
    {
        var sb = new StringBuilder();

        for (var i = 0; i < Math.Min(chunks.Count, 8); i++)
        {
            var c = chunks[i];
            sb.AppendLine($"[Source {i + 1}: {c.DocName}, p.{c.PageNum}]");
            sb.AppendLine(c.Text.Length > 600 ? c.Text[..600] + "…" : c.Text);
            sb.AppendLine();
        }

        return sb.ToString();
    }
}
