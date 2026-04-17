namespace FiscalPlatform.Domain.Repositories;

public interface IHealthRepository
{
    Task<bool> IsHealthyAsync();
}
