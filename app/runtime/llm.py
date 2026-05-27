from langchain_groq import ChatGroq
from app.core.config import get_settings

settings = get_settings()

def get_llm():
    return ChatGroq(
        api_key=settings.groq_api_key,
        model=settings.default_model,
        temperature=0.2,
    )