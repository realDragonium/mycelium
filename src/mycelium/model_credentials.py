"""Local credential discovery shared by model-backed features."""


def claude_configuration_error() -> str | None:
    from anthropic import Anthropic, AnthropicError

    # SDK discovery includes tokens, profiles and federation. Constructing a
    # client resolves configuration locally; credentials are fetched on request.
    try:
        with Anthropic() as client:
            if client.api_key or client.auth_token or client.credentials:
                return None
    except (AnthropicError, ValueError, OSError):
        return "Check the server's Anthropic credential configuration."
    return "Configure Anthropic credentials on the server."
