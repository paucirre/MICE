import os

from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv()


def _var(nombre: str, por_defecto: str | None = None) -> str | None:
    """Lee una variable de entorno quitando comillas y espacios sobrantes.

    En EasyPanel y en Docker el valor se toma literal, asi que escribir
    DEMO_PASSWORD="clave" guarda la clave CON las comillas dentro. El sintoma
    es un "Contrasena incorrecta" que no hay forma de entender, o un CORS que
    bloquea todo sin decir por que. Se limpia aqui para que no pueda pasar.
    """
    valor = os.getenv(nombre)
    if valor is None:
        return por_defecto
    valor = valor.strip()
    if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in ("'", '"'):
        valor = valor[1:-1]
    return valor


OPENAI_API_KEY = _var("OPENAI_API_KEY")

openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY, max_retries=2)

# Los modelos se leen del entorno para poder cambiarlos en EasyPanel sin
# volver a desplegar codigo. Agosto de 2026 retiro la Assistants API y la
# familia gpt-4o; si vuelve a pasar, esto se arregla con una variable.
DIRECTOR_MODEL = _var("DIRECTOR_MODEL", "gpt-5.6-terra")
RESEARCH_MODEL = _var("RESEARCH_MODEL", "gpt-5.6-luna")

# Contrasena de acceso a la demo. Sin ella el servicio no arranca: dejarlo
# abierto significa que cualquiera con la URL consume tokens de tu cuenta.
DEMO_PASSWORD = _var("DEMO_PASSWORD")
SESSION_SECRET = _var("SESSION_SECRET")

# Origenes permitidos, separados por comas.
ALLOWED_ORIGINS = [
    o.strip()
    for o in _var("ALLOWED_ORIGINS", "https://utopi.es").split(",")
    if o.strip()
]

# Analisis permitidos por sesion y hora.
RATE_LIMIT_POR_HORA = int(_var("RATE_LIMIT_POR_HORA", "10"))
