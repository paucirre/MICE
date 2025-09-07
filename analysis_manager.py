# analysis_manager.py

import json
import asyncio
from config import openai_client, ASSISTANT_ID
from research_team import ResearchTeamManager
from agents import trace, gen_trace_id

class AnalysisManager:
    def __init__(self):
        self.client = openai_client
        self.assistant_id = ASSISTANT_ID
        self.research_team = ResearchTeamManager()
        self.available_functions = {
            "run_multi_agent_research": self.research_team.run,
        }

    async def run(self, event_data: dict, update_queue: asyncio.Queue):
        trace_id = gen_trace_id()
        with trace("Análisis de Evento Deportivo", trace_id=trace_id):
            await update_queue.put(json.dumps({"type": "status", "content": f"📊 Ver traza en vivo: https://platform.openai.com/traces/trace?trace_id={trace_id}"}))
            await update_queue.put(json.dumps({"type": "status", "content": "🚀 Iniciando nuevo análisis de evento..."}))
            
            thread = await self.client.beta.threads.create()
            initial_prompt = f"Por favor, analiza el siguiente evento y genera el informe JSON correspondiente. Datos del evento: {json.dumps(event_data, indent=2)}"
            await self.client.beta.threads.messages.create(thread_id=thread.id, role="user", content=initial_prompt)
            run = await self.client.beta.threads.runs.create(thread_id=thread.id, assistant_id=self.assistant_id)

            while run.status != 'completed':
                run = await self.client.beta.threads.runs.retrieve(thread_id=thread.id, run_id=run.id)
                await update_queue.put(json.dumps({"type": "status", "content": f"🤖 Estado del Director: {run.status}"}))

                if run.status == 'requires_action':
                    tool_outputs = []
                    for tool_call in run.required_action.submit_tool_outputs.tool_calls:
                        function_name = tool_call.function.name
                        function_args = json.loads(tool_call.function.arguments)
                        if function_name in self.available_functions:
                            function_to_call = self.available_functions[function_name]
                            # Le pasamos la cola al equipo de investigación
                            output = await function_to_call(**function_args, update_queue=update_queue)
                            tool_outputs.append({"tool_call_id": tool_call.id, "output": output})
                    
                    run = await self.client.beta.threads.runs.submit_tool_outputs(thread_id=thread.id, run_id=run.id, tool_outputs=tool_outputs)
                await asyncio.sleep(1)

            if run.status == 'completed':
                await update_queue.put(json.dumps({"type": "status", "content": "✅ Análisis completado. Generando JSON final..."}))
                messages = await self.client.beta.threads.messages.list(thread_id=thread.id)
                final_response = messages.data[0].content[0].text.value
                try:
                    json_string = final_response.split('```json\n')[1].split('\n```')[0]
                    json_output = json.loads(json_string)
                    # Enviamos el resultado final a la cola
                    await update_queue.put(json.dumps({"type": "final_result", "content": json_output}))
                except Exception as e:
                    await update_queue.put(json.dumps({"type": "error", "content": f"Error al parsear JSON final: {e}"}))
            else:
                await update_queue.put(json.dumps({"type": "error", "content": f"El análisis falló. Estado final: {run.status}"}))
            
            # Señal de fin de stream
            await update_queue.put("END_OF_STREAM")