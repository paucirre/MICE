# analysis_manager.py
#
# El "Director" sobre la Responses API.
#
# La version anterior usaba la Assistants API (client.beta.threads.*), que
# OpenAI retiro el 26 de agosto de 2026. Las instrucciones del Assistant vivian
# en el dashboard de OpenAI y se perdieron; estan reconstruidas aqui a partir
# del contrato real de salida, que esta fijado por dashboard.html y por el
# generador de PDF de api.py.
#
# El flujo es deterministico en tres pasos, sin bucle abierto:
#   1. El Director propone los temas de investigacion (tool call forzada).
#   2. El equipo de investigacion los resuelve.
#   3. El Director redacta el informe final con esquema JSON estricto.

import asyncio
import json

from agents import gen_trace_id, trace

from config import DIRECTOR_MODEL, openai_client
from logging_config import logger
from research_team import ResearchTeamManager

DIRECTOR_INSTRUCTIONS = """\
Eres el director de analisis de ImpactSport, una herramienta que recomienda \
ciudades espanolas para celebrar eventos deportivos.

Recibes los datos de un evento y produces un informe comparativo de sedes.

Tu metodo:
1. Primero pides investigacion mediante la herramienta run_multi_agent_research, \
con entre 4 y 6 temas concretos y complementarios. Los temas deben cubrir: \
precios hoteleros (ADR) en las fechas y ciudades candidatas, infraestructura \
deportiva disponible para esa disciplina, tendencias de patrocinio del sector, \
impacto economico de eventos comparables ya celebrados, y sostenibilidad o \
legado social.
2. Con los resultados, eliges una ciudad recomendada y exactamente dos \
alternativas, y rellenas todos los indicadores.

Reglas que no puedes romper:
- Apoya cada cifra en lo que diga la investigacion. Si la investigacion da el \
impacto de un evento concreto ya celebrado, NO lo copies como prediccion de \
este evento: es otro evento, con otro tamano y otras fechas. Usalo solo como \
referencia de orden de magnitud y ajustalo al numero de asistentes de este.
- direct_impact_eur es el gasto que traen a la ciudad los visitantes de fuera. \
No cuentes el gasto de los residentes locales: es consumo desplazado, no \
impacto nuevo.
- license_increase_proj es un PORCENTAJE de incremento de licencias federativas \
(la interfaz le anade el simbolo %). Es un efecto pequeno y mal documentado: \
manten el valor por debajo de 15 salvo que la investigacion respalde otra cosa.
- budget_fit_percent es el porcentaje del presupuesto declarado que consumiria \
el evento en esa ciudad.
- No inventes el campo roi_est: ponlo a 0. El sistema lo calcula despues \
dividiendo el impacto entre el presupuesto, para que no pueda contradecirse.
- En sources pon entre 4 y 8 nombres de medios o instituciones citados en la \
investigacion, como texto plano corto (por ejemplo "INE" o "Cushman & Wakefield").
- Escribe siempre en espanol.
"""

TOOL_INVESTIGACION = {
    "type": "function",
    "name": "run_multi_agent_research",
    "description": (
        "Lanza al equipo de investigacion sobre una lista de temas y devuelve "
        "un informe consolidado con fuentes citadas."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "topics": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Entre 4 y 6 temas de investigacion concretos.",
            }
        },
        "required": ["topics"],
        "additionalProperties": False,
    },
}


def _ciudad_schema() -> dict:
    numero = {"type": "number"}
    return {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "main_venue": {"type": "string"},
            "kpi_main": {
                "type": "object",
                "properties": {
                    "roi_est": numero,
                    "legacy_score": numero,
                    "sponsorship_potential": numero,
                    "sea_impact_score": numero,
                },
                "required": [
                    "roi_est",
                    "legacy_score",
                    "sponsorship_potential",
                    "sea_impact_score",
                ],
                "additionalProperties": False,
            },
            "kpi_economic": {
                "type": "object",
                "properties": {
                    "adr_eur": numero,
                    "budget_fit_percent": numero,
                    "direct_impact_eur": numero,
                },
                "required": ["adr_eur", "budget_fit_percent", "direct_impact_eur"],
                "additionalProperties": False,
            },
            "kpi_legacy": {
                "type": "object",
                "properties": {
                    "license_increase_proj": numero,
                    "infra_score": numero,
                    "community_engagement": numero,
                },
                "required": [
                    "license_increase_proj",
                    "infra_score",
                    "community_engagement",
                ],
                "additionalProperties": False,
            },
            "kpi_sponsorship": {
                "type": "object",
                "properties": {
                    "media_value_eur": numero,
                    "top_sectors": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["media_value_eur", "top_sectors"],
                "additionalProperties": False,
            },
            "kpi_sea": {
                "type": "object",
                "properties": {
                    "social": numero,
                    "economic": numero,
                    "environmental": numero,
                },
                "required": ["social", "economic", "environmental"],
                "additionalProperties": False,
            },
        },
        "required": [
            "name",
            "main_venue",
            "kpi_main",
            "kpi_economic",
            "kpi_legacy",
            "kpi_sponsorship",
            "kpi_sea",
        ],
        "additionalProperties": False,
    }


ESQUEMA_INFORME = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "event": {
            "type": "object",
            "properties": {
                "sportType": {"type": "string"},
                "eventLevel": {"type": "string"},
                "mainFocus": {"type": "string"},
                "attendees": {"type": "string"},
                "budget_eur": {"type": "number"},
            },
            "required": [
                "sportType",
                "eventLevel",
                "mainFocus",
                "attendees",
                "budget_eur",
            ],
            "additionalProperties": False,
        },
        "recommendations": {
            "type": "object",
            "properties": {
                "recommended": _ciudad_schema(),
                "alternatives": {"type": "array", "items": _ciudad_schema()},
            },
            "required": ["recommended", "alternatives"],
            "additionalProperties": False,
        },
        "sources": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "event", "recommendations", "sources"],
    "additionalProperties": False,
}


class AnalysisManager:
    def __init__(self):
        self.client = openai_client
        self.research_team = ResearchTeamManager()

    async def run(self, event_data: dict, update_queue: asyncio.Queue):
        trace_id = gen_trace_id()
        with trace("Analisis de Evento Deportivo", trace_id=trace_id):
            await self._status(update_queue, "Iniciando nuevo analisis de evento...")

            prompt = (
                "Analiza el siguiente evento y genera el informe correspondiente. "
                f"Datos del evento:\n{json.dumps(event_data, indent=2, ensure_ascii=False)}"
            )
            conversacion = [
                {"role": "system", "content": DIRECTOR_INSTRUCTIONS},
                {"role": "user", "content": prompt},
            ]

            topics = await self._pedir_temas(conversacion, update_queue)
            informe = await self.research_team.run(topics, update_queue)

            await self._status(update_queue, "Redactando el informe final...")
            datos = await self._redactar(conversacion, topics, informe)

            datos = _derivar_roi(datos, event_data.get("budget", 0))

            logger.info(
                "Analisis de evento completado con exito",
                extra={"input": event_data, "output": datos},
            )
            await update_queue.put(
                json.dumps({"type": "final_result", "content": datos})
            )
            await update_queue.put("END_OF_STREAM")

    async def _status(self, queue: asyncio.Queue, texto: str):
        await queue.put(json.dumps({"type": "status", "content": texto}))

    async def _pedir_temas(self, conversacion: list, queue: asyncio.Queue) -> list[str]:
        """Paso 1: el Director decide que hay que investigar."""
        await self._status(queue, "El Director esta planificando la investigacion...")

        respuesta = await self.client.responses.create(
            model=DIRECTOR_MODEL,
            input=conversacion,
            tools=[TOOL_INVESTIGACION],
            tool_choice={"type": "function", "name": "run_multi_agent_research"},
        )

        for item in respuesta.output:
            if getattr(item, "type", None) == "function_call":
                topics = json.loads(item.arguments).get("topics", [])
                if topics:
                    await self._status(
                        queue, f"Plan trazado: {len(topics)} lineas de investigacion."
                    )
                    return topics

        raise RuntimeError(
            "El Director no propuso ningun tema de investigacion. "
            f"Salida recibida: {respuesta.output!r}"
        )

    async def _redactar(
        self, conversacion: list, topics: list[str], informe: str
    ) -> dict:
        """Paso 3: el informe final, con esquema estricto."""
        entrada = conversacion + [
            {
                "role": "user",
                "content": (
                    "Estos son los resultados de la investigacion que pediste sobre "
                    f"{', '.join(topics)}.\n\n{informe}\n\n"
                    "Redacta ahora el informe final siguiendo tus reglas."
                ),
            }
        ]

        respuesta = await self.client.responses.create(
            model=DIRECTOR_MODEL,
            input=entrada,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "informe_impactsport",
                    "schema": ESQUEMA_INFORME,
                    "strict": True,
                }
            },
        )
        return json.loads(respuesta.output_text)


def _derivar_roi(datos: dict, presupuesto: float) -> dict:
    """Calcula el ROI en codigo en vez de aceptar el que diga el modelo.

    La v1 emitio un informe con presupuesto 70.000 EUR, impacto 1.500.000 EUR y
    un ROI declarado de 4,5x, cuando la division da 21,4x. Derivarlo aqui hace
    imposible esa contradiccion. Es un parche sobre una arquitectura que sigue
    generando el resto de cifras con un modelo de lenguaje: el arreglo de fondo
    es la v2.
    """
    if not presupuesto:
        return datos

    recomendaciones = datos.get("recommendations", {})
    ciudades = [recomendaciones.get("recommended")] + list(
        recomendaciones.get("alternatives", [])
    )

    for ciudad in ciudades:
        if not ciudad:
            continue
        impacto = ciudad.get("kpi_economic", {}).get("direct_impact_eur")
        if isinstance(impacto, (int, float)) and impacto > 0:
            ciudad.setdefault("kpi_main", {})["roi_est"] = round(
                impacto / presupuesto, 1
            )

    return datos
