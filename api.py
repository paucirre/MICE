from fastapi import FastAPI, Request, Query
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from analysis_manager import AnalysisManager
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import json
from playwright.async_api import async_playwright

# --- Modelo de Datos (sin cambios) ---
class EventInput(BaseModel):
    sportType: str
    eventLevel: str
    mainFocus: str
    startDate: str
    endDate: str
    attendeesMin: int
    attendeesMax: int | None = None
    budget: int
    location: str
    requirements: str | None = None

app = FastAPI()

# --- CORS Middleware (sin cambios) ---
origins = ["*"] # Puedes restringir esto a tu dominio en producción
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


@app.get("/", include_in_schema=False)
async def root():
    return {"status": "ok"}

@app.get("/healthz", include_in_schema=False)
async def healthz():
    return {"health": "ok"}

async def run_analysis_in_background(event_data: dict, queue: asyncio.Queue):
    manager = AnalysisManager()
    try:
        await manager.run(event_data, queue)
    except Exception as e:
        error_message = {"type": "error", "content": f"Ha ocurrido un error fatal: {e}"}
        await queue.put(json.dumps(error_message))
    finally:
        await queue.put("END_OF_STREAM")

@app.get("/analyze-stream")
async def analyze_event_stream(request: Request, event_data_json: str = Query(...)):
    try:
        event_data_dict = json.loads(event_data_json)
        event_data = EventInput.model_validate(event_data_dict)
    except Exception as e:
        return {"error": f"Datos de entrada inválidos: {e}"}
    
    async def event_generator():
        queue = asyncio.Queue()
        asyncio.create_task(run_analysis_in_background(event_data.model_dump(), queue))
        while True:
            if await request.is_disconnected(): break
            try:
                message = await asyncio.wait_for(queue.get(), timeout=20.0)
                if message == "END_OF_STREAM": break
                yield f"data: {message}\n\n"
            except asyncio.TimeoutError:
                yield ": heartbeat\n\n"
            
    return StreamingResponse(event_generator(), media_type="text/event-stream")

# --- LÓGICA DE GENERACIÓN DE PDF (ACTUALIZADA) ---

def _format_currency(value):
    if not isinstance(value, (int, float)): return "N/A"
    return f"{value:,.0f} €".replace(",", ".")

def _generate_kpi_table(city_data):
    kpis = {
        "ROI Estimado": f"{city_data.get('kpi_main', {}).get('roi_est', 'N/A')}x",
        "Impacto Directo (€)": _format_currency(city_data.get('kpi_economic', {}).get('direct_impact_eur')),
        "Puntuación Legado": f"{city_data.get('kpi_main', {}).get('legacy_score', 'N/A')} / 10",
        "Potencial Patrocinio": f"{city_data.get('kpi_main', {}).get('sponsorship_potential', 'N/A')} / 10",
        "ADR Hotel (€)": _format_currency(city_data.get('kpi_economic', {}).get('adr_eur')),
        "Media Value (€)": _format_currency(city_data.get('kpi_sponsorship', {}).get('media_value_eur')),
        "Impacto SEA": f"{city_data.get('kpi_main', {}).get('sea_impact_score', 'N/A')} / 100",
        "Ajuste Presupuesto": f"{city_data.get('kpi_economic', {}).get('budget_fit_percent', 'N/A')}%"
    }
    rows_html = ""
    kpi_items = list(kpis.items())
    for i in range(0, len(kpi_items), 2):
        rows_html += "<tr>"
        label1, value1 = kpi_items[i]
        rows_html += f"<th>{label1}</th><td>{value1}</td>"
        if i + 1 < len(kpi_items):
            label2, value2 = kpi_items[i+1]
            rows_html += f"<th>{label2}</th><td>{value2}</td>"
        else:
            rows_html += "<th></th><td></td>"
        rows_html += "</tr>"
    return rows_html

def _generate_city_html(city_data, is_recommended=False):
    badge = '<span class="badge">⭐ RECOMENDADO</span>' if is_recommended else ''
    return f"""
    <div class="card">
        <div class="card-header">
            <h3>{city_data.get('name', 'N/A')} {badge}</h3>
            <p class="venue">📍 {city_data.get('main_venue', 'N/A')}</p>
        </div>
        <div class="card-body">
            <h4>Indicadores Clave de Rendimiento (KPIs)</h4>
            <table class="kpi-table">{_generate_kpi_table(city_data)}</table>
        </div>
    </div>
    """

# api.py (reemplaza solo esta función)

# api.py (reemplaza las dos últimas funciones)

def generate_html_for_pdf(data: dict) -> str:
    event = data.get('event', {})
    recommendations = data.get('recommendations', {})
    recommended_city = recommendations.get('recommended')
    alternative_cities = recommendations.get('alternatives', [])
    alternatives_html = "".join([_generate_city_html(city) for city in alternative_cities])

    html_content = f"""
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;600;700&display=swap" rel="stylesheet">
        <style>
            :root {{
                --bg-dark: #1a1d24; --card-bg: #2c303a; --border-color: #4a5568;
                --text-primary: #e2e8f0; --text-secondary: #94a3b8;
                --accent-green: #10B981; --accent-blue: #3B82F6;
            }}
            @page {{ margin: 0; }}
            *, *::before, *::after {{ box-sizing: border-box; }}
            html, body {{
                margin: 0; padding: 0; width: 100%; min-height: 100%;
                background-color: var(--bg-dark) !important;
                -webkit-print-color-adjust: exact !important;
                print-color-adjust: exact !important;
            }}
            body {{ font-family: 'Montserrat', sans-serif; color: var(--text-primary); }}
            
            .report-container {{
                width: 100%;
                max-width: 800px;
                margin: auto;
                padding: 25px; /* <-- CAMBIO: Reducido de 30px a 25px */
            }}
            .header {{
                background-color: var(--card-bg); border: 1px solid var(--border-color); border-radius: 12px;
                text-align: center; padding: 25px; margin-bottom: 25px;
            }}
            .header h1 {{ color: #fff; font-size: 26px; margin: 0 0 10px 0; }}
            .header p {{ color: var(--accent-green); font-size: 16px; margin: 0; font-weight: 600; }}
            .card {{
                background-color: var(--card-bg); border: 1px solid var(--border-color);
                border-radius: 12px;
                margin-bottom: 25px;
                page-break-inside: avoid;
                margin-top: 25px; /* <-- CAMBIO: Añadido margen superior a todas las cajas */
            }}
            .header + .card {{
                margin-top: 0; /* <-- CAMBIO: Eliminamos el margen superior solo a la primera caja después del header */
            }}
            .card-header {{
                padding: 15px 20px; /* <-- CAMBIO: Reducido el padding vertical */
                border-bottom: 1px solid var(--border-color);
            }}
            .card-header h3 {{ font-size: 20px; color: #fff; margin: 0; display: inline-block; }}
            .card-header .venue {{ font-size: 13px; color: var(--accent-blue); margin: 5px 0 0 0; }}
            .badge {{
                display: inline-block; background-color: var(--accent-green); color: #fff;
                padding: 4px 10px; border-radius: 20px; font-size: 11px; font-weight: 600;
                margin-left: 10px; vertical-align: middle;
            }}
            .card-body {{
                padding: 15px 20px; /* <-- CAMBIO: Reducido el padding vertical */
            }}
            .card-body h4 {{ font-size: 15px; color: #fff; margin: 0 0 12px 0; border-bottom: 1px solid var(--border-color); padding-bottom: 8px; }}
            .summary-text {{ font-size: 13px; line-height: 1.6; color: var(--text-secondary); }}
            .kpi-table {{ width: 100%; border-collapse: collapse; }}
            .kpi-table th, .kpi-table td {{ padding: 8px; text-align: left; border-bottom: 1px solid var(--border-color); font-size: 13px; }}
            .kpi-table th {{ color: var(--text-secondary); font-weight: 400; width: 25%; }}
            .kpi-table td {{ color: #fff; font-weight: 600; width: 25%; }}
        </style>
    </head>
    <body>
        <div class="report-container">
            <div class="header">
                <h1>Informe de Potencial para Eventos Deportivos</h1>
                
            </div>
            <div class="card">
                <div class="card-header"><h3>📝 Resumen Ejecutivo</h3></div>
                <div class="card-body"><p class="summary-text">{data.get('summary', 'No disponible.')}</p></div>
            </div>
            {_generate_city_html(recommended_city, is_recommended=True) if recommended_city else ''}
            {alternatives_html}
        </div>
    </body>
    </html>
    """
    return html_content

@app.post("/generate-pdf")
async def generate_pdf_endpoint(data: dict):
    html_content = generate_html_for_pdf(data)
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.set_content(html_content)
        await page.emulate_media(media="print")
        
        pdf_bytes = await page.pdf(
            format="A4",
            print_background=True,
            # 3. Aplicamos el margen 0 también aquí para máxima seguridad
            margin={"top": "0px", "bottom": "0px", "left": "0px", "right": "0px"}
        )
        
        await browser.close()
    return Response(content=pdf_bytes, media_type="application/pdf")