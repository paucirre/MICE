# research_team.py

import asyncio
import json
from pydantic import BaseModel, Field
from config import openai_client, RESEARCH_MODEL
from agents import Agent, WebSearchTool, ModelSettings, Runner

# --- Clases Pydantic (Sin cambios) ---
class WebSearchQuery(BaseModel):
    query: str = Field(description="El término de búsqueda optimizado para un motor de búsqueda web.")

class WebSearchPlan(BaseModel):
    searches: list[WebSearchQuery] = Field(description="Una lista de 5 a 10 búsquedas web específicas para realizar.")

# --- Agente 1: Planificador (Ahora informa a la cola) ---
async def planner_agent(topic: str, update_queue: asyncio.Queue):
    await update_queue.put(json.dumps({"type": "status", "content": f"🧠 Planificador: Creando plan de búsqueda para '{topic}'..."}))
    response = await openai_client.chat.completions.create(
        model=RESEARCH_MODEL,
        messages=[{"role": "system", "content": "Eres un asistente de investigación experto. Dado un tema, genera un plan de exactamente 5 búsquedas web específicas y detalladas para recopilar la información más relevante."}, {"role": "user", "content": f"Tema de investigación: {topic}"}],
        tools=[{"type": "function", "function": {"name": "generate_search_plan", "description": "Genera el plan de búsqueda estructurado.", "parameters": WebSearchPlan.model_json_schema()}}],
        tool_choice={"type": "function", "function": {"name": "generate_search_plan"}},
    )
    tool_call = response.choices[0].message.tool_calls[0]
    function_args = json.loads(tool_call.function.arguments)
    await update_queue.put(json.dumps({"type": "status", "content": f"✅ Planificador: Plan creado con {len(function_args.get('searches', []))} búsquedas."}))
    return WebSearchPlan(**function_args)

# --- Agente 2: Investigador (Definición sin cambios) ---
INSTRUCTIONS = (
    "Eres un asistente de investigación. Dado un término de búsqueda, buscas en la web ese término y produce un resumen conciso de los resultados..." # (mismo texto que antes)
)
search_agent = Agent( name="Agente de búsqueda", instructions=INSTRUCTIONS, tools=[WebSearchTool(search_context_size="medium")], model="gpt-4o-mini", model_settings=ModelSettings(tool_choice="required"), )

# --- Orquestador del Equipo de Investigación (Ahora informa a la cola) ---
class ResearchTeamManager:
    async def run_search(self, query: str, update_queue: asyncio.Queue) -> str:
        await update_queue.put(json.dumps({"type": "status", "content": f"🔍 Investigador: Buscando '{query}'..."}))
        try:
            result = await Runner.run(search_agent, query)
            await update_queue.put(json.dumps({"type": "status", "content": f"📄 Investigador: Resumen generado para '{query}'."}))
            return str(result.final_output)
        except Exception as e:
            error_message = f"⚠️ Error en la búsqueda para '{query}': {e}"
            await update_queue.put(json.dumps({"type": "status", "content": error_message}))
            return f"No se pudieron obtener resultados para la búsqueda: {query}"

    async def run(self, topics: list[str], update_queue: asyncio.Queue) -> str:
        consolidated_report = ""
        for topic in topics:
            consolidated_report += f"\n\n## Informe de Investigación sobre: {topic}\n\n"
            plan = await planner_agent(topic, update_queue)
            search_tasks = [self.run_search(item.query, update_queue) for item in plan.searches]
            search_summaries = await asyncio.gather(*search_tasks)
            final_summary = "\n\n".join(search_summaries)
            consolidated_report += final_summary
        return consolidated_report