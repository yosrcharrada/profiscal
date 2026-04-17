using System.Text;

namespace FiscalPlatform.Infrastructure.Elasticsearch;

public sealed class ElasticsearchClient
{
    private readonly HttpClient _http;
    private readonly string _host;
    private readonly string _index;

    public ElasticsearchClient(IConfiguration config, IHttpClientFactory factory)
    {
        _host = config["Elasticsearch:Host"] ?? "http://localhost:9200";
        _index = config["Elasticsearch:Index"] ?? "tunisian_legal";
        _http = factory.CreateClient();
    }

    public async Task<bool> IsHealthyAsync()
    {
        try
        {
            var resp = await _http.GetAsync($"{_host}/_cluster/health?timeout=3s");
            return resp.IsSuccessStatusCode;
        }
        catch
        {
            return false;
        }
    }

    public async Task<string> SearchAsync(string payload)
    {
        try
        {
            var content = new StringContent(payload, Encoding.UTF8, "application/json");
            var response = await _http.PostAsync($"{_host}/{_index}/_search", content);
            return await response.Content.ReadAsStringAsync();
        }
        catch
        {
            return "{}";
        }
    }

    public async Task<string> CountAsync()
    {
        try
        {
            var response = await _http.GetAsync($"{_host}/{_index}/_count");
            return await response.Content.ReadAsStringAsync();
        }
        catch
        {
            return "{\"count\":0}";
        }
    }
}
