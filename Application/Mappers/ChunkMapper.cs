using FiscalPlatform.Application.DTOs;
using FiscalPlatform.Domain.Entities;

namespace FiscalPlatform.Application.Mappers;

public static class ChunkMapper
{
    public static ChunkDto ToDto(Chunk chunk) => new()
    {
        Id = chunk.ChunkId.Value,
        Score = chunk.Score,
        Content = chunk.Content,
        Filename = chunk.Filename,
        ArticleNumber = chunk.ArticleNumber,
        SectionTitle = chunk.SectionTitle,
        ChunkType = chunk.ChunkType.Value,
        DocumentType = chunk.DocumentType.Value,
        PageNumber = chunk.PageNumber,
        Highlight = chunk.Highlight
    };

    public static SourceChunkDto ToDto(SourceChunk chunk) => new()
    {
        DocName = chunk.DocName,
        PageNum = chunk.PageNum,
        Text = chunk.Text,
        ChunkType = chunk.ChunkType,
        ArticleRef = chunk.ArticleRef,
        Score = chunk.Score,
        Category = chunk.Category
    };
}
