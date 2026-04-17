using FiscalPlatform.Domain.Entities;

namespace FiscalPlatform.Domain.Services;

public interface IChatOrchestrationService
{
    string BuildContext(List<SourceChunk> chunks);
}
