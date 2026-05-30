from langchain_groq import ChatGroq
from app.core.config import get_settings

settings = get_settings()


def get_llm(model: str = "") -> ChatGroq:
    """
    Return a ChatGroq LLM instance.

    Args:
        model: Optional Groq model name (e.g. 'llama-3.3-70b-versatile').
               Falls back to settings.default_model when empty or not provided.
    """
    return ChatGroq(
        api_key=settings.groq_api_key,
        model=model.strip() or settings.default_model,
        temperature=0.2,
    )
