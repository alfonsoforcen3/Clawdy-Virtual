namespace Clawdy.Windows.Core;

/// <summary>Pure allowlist. Availability and actual OS launch are separate capabilities.</summary>
public static class LaunchPolicy
{
    public static string? Destination(CardAction action, Func<string, bool> hasProtocol, string terminal)
    {
        if (action.Kind == "chat")
        {
            var uri = action.Target;
            if (action.Provider != "codex" || uri is null || !uri.IsAbsoluteUri || uri.Scheme != "codex"
                || uri.Host != "threads" || uri.Query.Length != 0 || uri.Fragment.Length != 0
                || uri.UserInfo.Length != 0 || !uri.IsDefaultPort) return null;
            var id = uri.AbsolutePath.Length > 1 ? uri.AbsolutePath[1..] : null;
            if (!CardAction.IsThreadId(id) || !hasProtocol("codex")) return null;
            return "codex://threads/" + id;
        }
        if (action.Kind != "app" || action.Target is not null) return null;
        if (action.Provider is "codex" or "cursor") return hasProtocol(action.Provider) ? action.Provider + "://" : null;
        if (action.Provider is "claude" or "gemini") return terminal;
        return null;
    }
}
