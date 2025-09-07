# api.py (VERSIÓN FINAL Y CORRECTA)

from fastapi import FastAPI, Request, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from analysis_manager import AnalysisManager
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import json

class EventInput(BaseModel):
    sportType: str; eventLevel: str; mainFocus: str; startDate: str; endDate: str; attendeesMin: int; attendeesMax: int | None = None; budget: int; location: str; requirements: str | None = None

app = FastAPI()

origins = ["*"]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

async def run_analysis_in_background(event_data: dict, queue: asyncio.Queue):
    manager = AnalysisManager()
    try:
        await manager.run(event_data, queue)
    except Exception as e:
        error_message = {"type": "error", "content": f"Ha ocurrido un error fatal: {e}"}
        await queue.put(json.dumps(error_message))
    finally:
        await queue.put("END_OF_STREAM")

# CAMBIO 1: El decorador ahora es @app.get
@app.get("/analyze-stream")
async def analyze_event_stream(request: Request, event_data_json: str = Query(...)):
    # CAMBIO 2: La función ahora recibe el JSON como un string desde la URL
    
    # Validamos los datos recibidos
    try:
        event_data_dict = json.loads(event_data_json)
        event_data = EventInput.model_validate(event_data_dict)
    except Exception as e:
        return {"error": f"Datos de entrada inválidos: {e}"}

    async def event_generator():
        queue = asyncio.Queue()
        asyncio.create_task(run_analysis_in_background(event_data.model_dump(), queue))
        while True:
            message = await queue.get()
            if await request.is_disconnected():
                print("Cliente desconectado.")
                break
            if message == "END_OF_STREAM":
                print("Fin del stream.")
                break
            yield f"data: {message}\n\n"
            
    return StreamingResponse(event_generator(), media_type="text/event-stream")