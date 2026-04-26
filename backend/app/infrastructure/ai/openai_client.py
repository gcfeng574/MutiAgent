from langchain_openai import ChatOpenAI

from config.settings import settings


def _resolve_provider(
    preferred_base_url: str | None,
    preferred_api_key: str | None,
    fallback_base_url: str | None,
    fallback_api_key: str | None,
) -> tuple[str, str]:
    if preferred_base_url and preferred_api_key:
        return preferred_base_url, preferred_api_key
    if fallback_base_url and fallback_api_key:
        return fallback_base_url, fallback_api_key
    raise ValueError("No usable LLM provider configuration found.")


def _build_chat_model(
    model_name: str | None,
    preferred_base_url: str | None,
    preferred_api_key: str | None,
    fallback_base_url: str | None,
    fallback_api_key: str | None,
    temperature: float = 0,
) -> ChatOpenAI:
    base_url, api_key = _resolve_provider(
        preferred_base_url=preferred_base_url,
        preferred_api_key=preferred_api_key,
        fallback_base_url=fallback_base_url,
        fallback_api_key=fallback_api_key,
    )

    return ChatOpenAI(
        model=model_name or "",
        base_url=base_url,
        api_key=api_key,
        temperature=temperature,
    )


main_model = _build_chat_model(
    model_name=settings.MAIN_MODEL_NAME,
    preferred_base_url=settings.SF_BASE_URL,
    preferred_api_key=settings.SF_API_KEY,
    fallback_base_url=settings.AL_BAILIAN_BASE_URL,
    fallback_api_key=settings.AL_BAILIAN_API_KEY,
)

sub_model = _build_chat_model(
    model_name=settings.SUB_MODEL_NAME or settings.MAIN_MODEL_NAME,
    preferred_base_url=settings.AL_BAILIAN_BASE_URL,
    preferred_api_key=settings.AL_BAILIAN_API_KEY,
    fallback_base_url=settings.SF_BASE_URL,
    fallback_api_key=settings.SF_API_KEY,
)
