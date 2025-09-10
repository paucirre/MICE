# analysis_manager.py (VERSIÓN FINAL Y MÁS ROBUSTA)

import json
import asyncio
from config import openai_client, ASSISTANT_ID
from research_team import ResearchTeamManager
from agents import trace, gen_trace_id
from logging_config import logger

class AnalysisManager:
    def __init__(self):
        self.client = openai_client
        self.assistant_id = ASSISTANT_ID
        self.research_team = ResearchTeamManager()
        self.available_functions = { "run_multi_agent_research": self.research_team.run }

    async def run(self, event_data: dict, update_queue: asyncio.Queue):
        trace_id = gen_trace_id()
        with trace("Análisis de Evento Deportivo", trace_id=trace_id):
            await update_queue.put(json.dumps({"type": "status", "content": f"📊 Ver traza en vivo: [https://platform.openai.com/traces/trace?trace_id=](https://platform.openai.com/traces/trace?trace_id=){trace_id}"}))
            await update_queue.put(json.dumps({"type": "status", "content": "🚀 Iniciando nuevo análisis de evento..."}))
            
            thread = await self.client.beta.threads.create()
            initial_prompt = f"Por favor, analiza el siguiente evento y genera el informe JSON correspondiente. Datos del evento: {json.dumps(event_data, indent=2)}"
            
            # --- DEBUGGING: Entrada al Asistente (con flush=True) ---
            print("\n" + "="*50, flush=True)
            print("📥 ENVIANDO AL DIRECTOR (ASSISTANT):", flush=True)
            print(initial_prompt, flush=True)
            print("="*50 + "\n", flush=True)
            # ---------------------------------------------------------

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
                            output = await function_to_call(**function_args, update_queue=update_queue)
                            tool_outputs.append({"tool_call_id": tool_call.id, "output": output})
                    
                    run = await self.client.beta.threads.runs.submit_tool_outputs(thread_id=thread.id, run_id=run.id, tool_outputs=tool_outputs)
                await asyncio.sleep(1)

            if run.status == 'completed':
                await update_queue.put(json.dumps({"type": "status", "content": "✅ Análisis completado. Generando JSON final..."}))
                messages = await self.client.beta.threads.messages.list(thread_id=thread.id)
                final_response = messages.data[0].content[0].text.value
                
                # --- LÓGICA DE PARSEO DE JSON MEJORADA ---
                try:
                    json_output = None
                    # Primero, intenta parsear la respuesta directamente
                    try:
                        json_output = json.loads(final_response)
                    except json.JSONDecodeError:
                        # Si falla, intenta extraerlo de un bloque de código markdown
                        print("Respuesta no es JSON puro, intentando extraer de markdown...", flush=True)
                        json_string = final_response.split('```json\n')[1].split('\n```')[0]
                        json_output = json.loads(json_string)

                    # --- DEBUGGING: Salida del Asistente (con flush=True) ---
                    print("\n" + "="*50, flush=True)
                    print("📤 RESPUESTA RECIBIDA DEL DIRECTOR (ASSISTANT):", flush=True)
                    print(json.dumps(json_output, indent=2, ensure_ascii=False), flush=True)
                    print("="*50 + "\n", flush=True)
                    # ------------------------------------------------------------
                    
                    log_data = {"input": event_data, "output": json_output}
                    logger.info("Análisis de evento completado con éxito", extra=log_data)
                    
                    await update_queue.put(json.dumps({"type": "final_result", "content": json_output}))

                except Exception as e:
                    logger.error("Error al parsear el JSON final del Assistant", extra={"raw_response": final_response, "error": str(e)})
                    await update_queue.put(json.dumps({"type": "error", "content": f"Error al parsear JSON final: {e}"}))
            else:
                logger.error(f"El Run del Assistant falló", extra={"run_status": run.status, "event_data": event_data})
                await update_queue.put(json.dumps({"type": "error", "content": f"El análisis falló. Estado final: {run.status}"}))
            
            await update_queue.put("END_OF_STREAM")