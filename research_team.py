# research_team.py (VERSIÓN FINAL Y CORREGIDA)

import asyncio
import json
from pydantic import BaseModel, Field
from logging_config import logger 
from config import openai_client, RESEARCH_MODEL
from agents import Agent, WebSearchTool, ModelSettings, Runner

# --- Clases Pydantic (Sin cambios) ---
class WebSearchQuery(BaseModel):
    query: str = Field(description="El término de búsqueda optimizado para un motor de búsqueda web.")

class WebSearchPlan(BaseModel):
    searches: list[WebSearchQuery] = Field(description="Una lista de 5 a 10 búsquedas web específicas para realizar.")

# --- Agente 1: Planificador (Sin cambios) ---
async def planner_agent(topic: str, update_queue: asyncio.Queue):
    await update_queue.put(json.dumps({"type": "status", "phase": "planning", "content": f"🧠 Planificador: Creando plan para '{topic}'..."}))
    response = await openai_client.chat.completions.create(
        model=RESEARCH_MODEL,
        messages=[{"role": "system", "content": "Eres un asistente de investigación experto. Dado un tema, genera un plan de exactamente 5 búsquedas web específicas y detalladas para recopilar la información más relevante."}, {"role": "user", "content": f"Tema de investigación: {topic}"}],
        tools=[{"type": "function", "function": {"name": "generate_search_plan", "description": "Genera el plan de búsqueda estructurado.", "parameters": WebSearchPlan.model_json_schema()}}],
        tool_choice={"type": "function", "function": {"name": "generate_search_plan"}},
    )
    tool_call = response.choices[0].message.tool_calls[0]
    function_args = json.loads(tool_call.function.arguments)
    await update_queue.put(json.dumps({"type": "status", "phase": "planning_complete", "content": f"✅ Plan creado con {len(function_args.get('searches', []))} búsquedas."}))
    return WebSearchPlan(**function_args)

# --- Agente 2: Investigador (Definición sin cambios) ---
INSTRUCTIONS = (
    "Eres un asistente de investigación. Dado un término de búsqueda, buscas en la web ese término y "
    "produce un resumen conciso de los resultados. El resumen debe tener 2-3 párrafos y menos de 300 "
    "palabras. Captura los puntos principales. Escribe de manera concisa, no es necesario tener frases completas o buena "
    "gramática. Esto será consumido por alguien que sintetiza un informe, por lo que es vital que captures la "
    "esencia y ignores cualquier fluff. No incluyas ningún comentario adicional más que el resumen en sí."
)
search_agent = Agent( name="Agente de búsqueda", instructions=INSTRUCTIONS, tools=[WebSearchTool(search_context_size="medium")], model="gpt-4o-mini", model_settings=ModelSettings(tool_choice="required"), )

# --- Orquestador del Equipo de Investigación (LÓGICA CORREGIDA) ---
class ResearchTeamManager:
    async def run_search(self, query: str, update_queue: asyncio.Queue) -> str:
        await update_queue.put(json.dumps({"type": "status", "phase": "research", "content": f"🔍 Investigando: '{query[:60]}...'", "progress": ""}))
        try:
            result = await Runner.run(search_agent, query)
            summary = str(result.final_output)
            log_data = {"query": query, "summary": summary}
            logger.info("Resumen de Investigador generado", extra=log_data)
            await update_queue.put(json.dumps({"type": "status", "phase": "research", "content": f"📄 Resumen generado para: '{query[:60]}...'", "progress": ""}))
            return summary
        except Exception as e:
            error_message = f"⚠️ Error en la búsqueda para '{query}': {e}"
            logger.error(error_message)
            await update_queue.put(json.dumps({"type": "status", "phase": "error", "content": error_message}))
            return f"No se pudieron obtener resultados para la búsqueda: {query}"

    async def run(self, topics: list[str], update_queue: asyncio.Queue) -> str:
        # 1. Se crea una lista vacía para guardar los informes de cada tema.
        topic_reports = []

        # 2. Se itera sobre cada tema y se procesa de forma AISLADA.
        for topic in topics:
            plan = await planner_agent(topic, update_queue)
            
            search_tasks = [self.run_search(item.query, update_queue) for item in plan.searches]
            search_summaries = await asyncio.gather(*search_tasks)
            
            # 3. Se unen los resúmenes para ESTE TEMA ÚNICAMENTE.
            final_summary_for_topic = "\n\n".join(search_summaries)
            
            # 4. Se crea el informe completo para este tema y se AÑADE a la lista.
            #    La lista 'topic_reports' ahora contiene un nuevo informe completo.
            report_for_topic = f"## Informe de Investigación sobre: {topic}\n\n{final_summary_for_topic}"
            topic_reports.append(report_for_topic)

        # 5. UNA VEZ TERMINADO EL BUCLE, se unen todos los informes de la lista.
        #    Esto se hace una única vez, al final.
        consolidated_report = "\n\n---\n\n".join(topic_reports)
        
        # 6. Se imprime el informe consolidado final en la consola una única vez.
        print("\n" + "#"*60)
        print("📝 INFORME CONSOLIDADO FINAL ENVIADO AL DIRECTOR (ASSISTANT)")
        print(consolidated_report)
        print("#"*60 + "\n")
        
        return consolidated_report