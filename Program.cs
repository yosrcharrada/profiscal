using FiscalPlatform.Domain.Repositories;
using FiscalPlatform.Infrastructure.Elasticsearch;
using FiscalPlatform.Infrastructure.LLM;
using FiscalPlatform.Infrastructure.Neo4j;
using MediatR;
using DotNetEnv;

var builder = WebApplication.CreateBuilder(args);
Env.Load();

builder.WebHost.UseUrls("http://localhost:8080");

builder.Services.AddControllersWithViews();
builder.Services.AddHttpClient();

// CQRS handlers
builder.Services.AddMediatR(typeof(Program));

// Infrastructure clients
builder.Services.AddSingleton<ElasticsearchClient>();
builder.Services.AddSingleton<Neo4jDriver>();
builder.Services.AddSingleton<AzureOpenAiService>();

// Domain repositories
builder.Services.AddSingleton<ISearchRepository, ElasticsearchSearchRepository>();
builder.Services.AddSingleton<IKnowledgeGraphRepository, Neo4jKnowledgeGraphRepository>();
builder.Services.AddSingleton<ElasticsearchHealthRepository>();
builder.Services.AddSingleton<Neo4jHealthRepository>();

// CORS for API calls
builder.Services.AddCors(options =>
{
    options.AddDefaultPolicy(policy =>
        policy.AllowAnyOrigin().AllowAnyMethod().AllowAnyHeader());
});

var app = builder.Build();

app.UseStaticFiles();
app.UseRouting();
app.UseCors();

app.MapControllerRoute(
    name: "default",
    pattern: "{controller=Home}/{action=Index}/{id?}");

app.Run();
