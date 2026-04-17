using Azure;
using Azure.AI.OpenAI;
using FiscalPlatform.Application.DTOs;

namespace FiscalPlatform.Infrastructure.LLM;

public sealed class AzureOpenAiService
{
    private readonly string _model;
    private readonly string _apiKey;
    private readonly string _endpoint;

    public AzureOpenAiService()
    {
        _model = Environment.GetEnvironmentVariable("LLM_MODEL") ?? "gpt-4o";
        _apiKey = Environment.GetEnvironmentVariable("OPENAI_API_KEY") ?? string.Empty;
        _endpoint = Environment.GetEnvironmentVariable("OPENAI_ENDPOINT") ?? string.Empty;
    }

    public async Task<string> GetAnswerAsync(string question, string context, List<ChatMessageDto> history)
    {
        var client = new OpenAIClient(new Uri(_endpoint), new AzureKeyCredential(_apiKey));
        var messages = new List<ChatRequestMessage>
        {
            new ChatRequestSystemMessage(@"Tu es un expert en fiscalité tunisienne.
Analyse d'abord la question, puis utilise les extraits fournis pour retrouver
les passages les plus pertinents.

SI les sources fournies NE mentionnent PAS directement la réponse :
- utilise le raisonnement fiscal logique,
- combine les indices présents dans les textes,
- recherche les termes proches ou notions équivalentes,
- propose la réponse la PLUS probable et EXPLIQUE pourquoi.

NE réponds 'les sources ne traitent pas du sujet' que si VRAIMENT
aucun élément n’est exploitable.

Structure toujours ta réponse ainsi :
1️. Ce que disent les sources
2️. Analyse et interprétation
3️. Réponse finale
4. Références exactes aux extraits utilisés")
        };

        foreach (var h in history.TakeLast(4))
        {
            if (h.Role == "assistant")
                messages.Add(new ChatRequestAssistantMessage(h.Content));
            else
                messages.Add(new ChatRequestUserMessage(h.Content));
        }

        messages.Add(new ChatRequestUserMessage($"Sources:\n{context}\n\nQuestion: {question}"));

        var options = new ChatCompletionsOptions { Temperature = 0 };
        foreach (var message in messages)
            options.Messages.Add(message);

        options.DeploymentName = _model;

        var response = await client.GetChatCompletionsAsync(options);
        return response.Value.Choices[0].Message.Content;
    }
}
