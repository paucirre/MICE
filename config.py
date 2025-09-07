import os
from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ASSISTANT_ID = os.getenv("OPENAI_ASSISTANT_ID")

openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY, max_retries=2)
RESEARCH_MODEL = "gpt-4o-mini"