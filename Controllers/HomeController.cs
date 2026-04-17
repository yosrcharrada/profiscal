using Microsoft.AspNetCore.Mvc;

namespace FiscalPlatform.Controllers;

public class HomeController : Controller
{
    public IActionResult Index() => View();
}
