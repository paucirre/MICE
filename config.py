import os

from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY, max_retries=2)

# Los modelos se leen del entorno para poder cambiarlos en EasyPanel sin
# volver a desplegar codigo. Agosto de 2026 retiro la Assistants API y la
# familia gpt-4o; si vuelve a pasar, esto se arregla con una variable.
DIRECTOR_MODEL = os.getenv("DIRECTOR_MODEL", "gpt-5.6-terra")
RESEARCH_MODEL = os.getenv("RESEARCH_MODEL", "gpt-5.6-luna")

# Contrasena de acceso a la demo. Sin ella el servicio no arranca: dejarlo
# abierto significa que cualquiera con la URL consume tokens de tu cuenta.
DEMO_PASSWORD = os.getenv("DEMO_PASSWORD")
SESSION_SECRET = os.getenv("SESSION_SECRET")

# Origenes permitidos, separados por comas.
ALLOWED_ORIGINS = [
    o.strip()
    for o in os.getenv("ALLOWED_ORIGINS", "https://utopi.es").split(",")
    if o.strip()
]

# Analisis permitidos por sesion y hora.
RATE_LIMIT_POR_HORA = int(os.getenv("RATE_LIMIT_POR_HORA", "10"))
