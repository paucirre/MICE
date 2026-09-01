# auth.py
#
# Control de acceso minimo para la demo.
#
# La v1 estaba abierta: origins=["*"], sin autenticacion y con la URL del
# backend escrita en claro en el index.html publico. Mientras el servicio
# estuvo roto daba igual, porque fallaba antes de gastar un solo token. En
# cuanto vuelve a funcionar, cualquiera con la URL consume tu cuenta.
#
# Token firmado con HMAC, sin estado y sin base de datos: para una demo es
# suficiente y no anade infraestructura. El control de acceso de verdad
# (cuentas, cuotas por usuario, multi-tenant) es la fase 3 de la v2.

import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque

from config import DEMO_PASSWORD, RATE_LIMIT_POR_HORA, SESSION_SECRET

DURACION_SESION_HORAS = 8

_usos: dict[str, deque] = defaultdict(deque)


class ConfiguracionInsegura(RuntimeError):
    pass


def comprobar_configuracion() -> None:
    """Se llama al arrancar. Preferimos no arrancar a arrancar abierto."""
    if not DEMO_PASSWORD:
        raise ConfiguracionInsegura(
            "Falta la variable de entorno DEMO_PASSWORD. Sin ella el servicio "
            "quedaria abierto a Internet y cualquiera podria consumir tus tokens."
        )
    if not SESSION_SECRET or len(SESSION_SECRET) < 32:
        raise ConfiguracionInsegura(
            "Falta SESSION_SECRET o es demasiado corta (minimo 32 caracteres). "
            "Genera una con: python -c \"import secrets; print(secrets.token_hex(32))\""
        )


def password_correcta(entrada: str) -> bool:
    """Comparacion en tiempo constante, para no filtrar la clave por timing."""
    return hmac.compare_digest(entrada or "", DEMO_PASSWORD or "")


def crear_token() -> str:
    expira = int(time.time()) + DURACION_SESION_HORAS * 3600
    sesion = secrets.token_hex(8)
    cuerpo = f"{expira}.{sesion}"
    return f"{cuerpo}.{_firmar(cuerpo)}"


def token_valido(token: str | None) -> bool:
    if not token:
        return False
    try:
        expira_s, sesion, firma = token.split(".")
    except ValueError:
        return False
    if not hmac.compare_digest(firma, _firmar(f"{expira_s}.{sesion}")):
        return False
    try:
        return int(expira_s) > time.time()
    except ValueError:
        return False


def dentro_del_limite(token: str) -> bool:
    """Ventana deslizante de una hora por sesion."""
    ahora = time.time()
    reciente = _usos[token]
    while reciente and ahora - reciente[0] > 3600:
        reciente.popleft()
    if len(reciente) >= RATE_LIMIT_POR_HORA:
        return False
    reciente.append(ahora)
    return True


def _firmar(cuerpo: str) -> str:
    return hmac.new(
        SESSION_SECRET.encode(), cuerpo.encode(), hashlib.sha256
    ).hexdigest()
