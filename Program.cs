using FiscalPlatform.Services;
using DotNetEnv;

var builder = WebApplication.CreateBuilder(args);
Env.Load();

builder.WebHost.UseUrls("http://localhost:8080");

builder.Services.AddControllersWithViews();
builder.Services.AddHttpClient();

// Register services
builder.Services.AddSingleton<ElasticsearchService>();
builder.Services.AddSingleton<Neo4jService>();
builder.Services.AddSingleton<GraphRagService>();

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
