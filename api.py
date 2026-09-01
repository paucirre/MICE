from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from analysis_manager import AnalysisManager
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import json
from playwright.async_api import async_playwright

import auth
from config import ALLOWED_ORIGINS, DIRECTOR_MODEL, RESEARCH_MODEL
from logging_config import logger

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

class LoginInput(BaseModel):
    password: str


# Falla al importar si el servicio quedaria abierto. Preferimos que EasyPanel
# muestre el contenedor caido a que arranque sin contrasena.
auth.comprobar_configuracion()

app = FastAPI()

# CORS restringido. Antes era ["*"], que junto con la ausencia de auth permitia
# a cualquiera lanzar analisis contra esta API desde cualquier pagina.
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def exigir_token(x_demo_token: str = Header(default="")) -> str:
    """Para endpoints normales, donde si se pueden enviar cabeceras."""
    if not auth.token_valido(x_demo_token):
        raise HTTPException(status_code=401, detail="Sesion no valida o caducada.")
    return x_demo_token


@app.get("/", include_in_schema=False)
async def root():
    return {"status": "ok"}

@app.get("/healthz", include_in_schema=False)
async def healthz():
    return {"health": "ok"}

@app.post("/login")
async def login(datos: LoginInput):
    if not auth.password_correcta(datos.password):
        raise HTTPException(status_code=401, detail="Contrasena incorrecta.")
    return {"token": auth.crear_token()}

def _explicar_error(e: Exception) -> str:
    """Convierte los fallos opacos de la API en algo accionable.

    La v1 murio mostrando "Ha ocurrido un error fatal: Error code: 404" y no
    habia forma de saber que OpenAI habia apagado la Assistants API. Un 404 de
    esta API significa casi siempre que un modelo o un endpoint ya no existe.
    """
    texto = str(e)
    if "404" in texto or "not found" in texto.lower():
        return (
            "El servidor de OpenAI respondio 404. Casi siempre significa que el "
            "modelo configurado ya no existe. Revisa las variables de entorno "
            f"DIRECTOR_MODEL ({DIRECTOR_MODEL}) y RESEARCH_MODEL ({RESEARCH_MODEL}) "
            f"contra la lista de modelos vigentes. Detalle: {texto}"
        )
    if "401" in texto or "api key" in texto.lower():
        return (
            "OpenAI rechazo la clave (401). Revisa la variable OPENAI_API_KEY. "
            f"Detalle: {texto}"
        )
    if "429" in texto:
        return (
            "OpenAI ha limitado el ritmo o la cuenta no tiene saldo (429). "
            f"Detalle: {texto}"
        )
    return f"Ha ocurrido un error fatal: {texto}"


async def run_analysis_in_background(event_data: dict, queue: asyncio.Queue):
    manager = AnalysisManager()
    try:
        await manager.run(event_data, queue)
    except Exception as e:
        logger.error("El analisis fallo", extra={"error": str(e), "input": event_data})
        await queue.put(json.dumps({"type": "error", "content": _explicar_error(e)}))
    finally:
        await queue.put("END_OF_STREAM")

@app.get("/analyze-stream")
async def analyze_event_stream(
    request: Request,
    event_data_json: str = Query(...),
    token: str = Query(default=""),
):
    # El token viaja por query string y no por cabecera porque EventSource no
    # permite cabeceras personalizadas. Es un token de sesion de 8 horas, no un
    # dato personal, pero queda en los logs del proxy: asumido para la demo, y
    # resuelto en la v2 con cookie de sesion.
    if not auth.token_valido(token):
        raise HTTPException(status_code=401, detail="Sesion no valida o caducada.")
    if not auth.dentro_del_limite(token):
        raise HTTPException(
            status_code=429,
            detail="Has alcanzado el limite de analisis por hora de esta sesion.",
        )

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
                text-align: center; padding: 20px; margin-bottom: 15px;
            }}
            .header h1 {{ color: #fff; font-size: 24px; margin: 0 0 10px 0; }}
            .header p {{ color: var(--accent-green); font-size: 16px; margin: 0; font-weight: 600; }}
            .card {{
                background-color: var(--card-bg); border: 1px solid var(--border-color);
                border-radius: 12px;
                margin-bottom: 20px;
                page-break-inside: avoid;
                margin-top: 20px; /* <-- CAMBIO: Añadido margen superior a todas las cajas */
            }}
            .header + .card {{
                margin-top: 0; /* <-- CAMBIO: Eliminamos el margen superior solo a la primera caja después del header */
            }}
            .card-header {{
                padding: 12px 15px; /* <-- CAMBIO: Reducido el padding vertical */
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
async def generate_pdf_endpoint(data: dict, _token: str = Depends(exigir_token)):
    # Autenticado tambien: cada llamada arranca un Chromium y renderiza datos
    # que vienen del cliente. Abierto, es a la vez un consumo de recursos
    # gratuito y una inyeccion de HTML arbitrario en un navegador headless.
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


# --- LÓGICA DE GENERACIÓN DE PDF PARA "IA MICE"  ---

def _generate_mice_kpi_html(kpi_data):
    """Genera el HTML para los KPIs del informe MICE."""
    kpis = {
        "ROI Estimado": f"{kpi_data.get('roi_est', 'N/A')}x",
        "ADR Hotel (€)": _format_currency(kpi_data.get('adr_eur')),
        "Capacidad Venue": f"{kpi_data.get('venue_capacity', 'N/A')}",
        "Huella CO₂ (kg)": f"{kpi_data.get('co2_kg', 'N/A')}"
    }
    return "".join([f'<div><span>{label}:</span> <strong>{value}</strong></div>' for label, value in kpis.items()])

def _generate_mice_city_html(city_data, is_recommended=False):
    """Genera el bloque HTML para una ciudad del informe MICE."""
    title = "🏆 Sede Recomendada" if is_recommended else "🏙️ Sede Alternativa"
    badge_color = "#48bb78" if is_recommended else "#ed8936"
    
    return f"""
    <div class="card">
        <div class="card-header" style="background-color: {badge_color};">
            {title}: {city_data.get('name', 'N/A')}
        </div>
        <div class="card-body">
            <p class="venue">📍 {city_data.get('logistics', {}).get('main_venue', 'N/A')}</p>
            <div class="kpi-block">
                {_generate_mice_kpi_html(city_data.get('kpi', {}))}
            </div>
        </div>
    </div>
    """

def generate_html_for_mice_pdf(data: dict) -> str:
    """
    Genera un string HTML auto-contenido y estilizado para el informe de IA MICE.
    """
    event = data.get('event', {})
    recommendations = data.get('recommendations', {})
    recommended_city = recommendations.get('recommended')
    alternative_cities = recommendations.get('alternatives', [])
    alternatives_html = "".join([_generate_mice_city_html(city) for city in alternative_cities])

    html_content = f"""
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <link href="https://fonts.googleapis.com/css2?family=Segoe+UI:wght@400;600;700&display=swap" rel="stylesheet">
        <style>
            @page {{ margin: 0; }}
            *, *::before, *::after {{ box-sizing: border-box; }}
            html, body {{
                margin: 0; padding: 0; width: 100%;
                background-color: #f0f2f5 !important;
                -webkit-print-color-adjust: exact !important;
                print-color-adjust: exact !important;
            }}
            body {{ font-family: 'Segoe UI', sans-serif; color: #2d3748; }}
            .report-container {{ width: 100%; max-width: 800px; margin: auto; padding: 40px; }}
            .header {{
                text-align: center; padding-bottom: 20px;
                border-bottom: 3px solid #667eea; margin-bottom: 30px;
            }}
            .header h1 {{ color: #667eea; font-size: 28px; margin: 0; }}
            .card {{
                background-color: #fff; border: 1px solid #e2e8f0; border-radius: 12px;
                margin-bottom: 25px; page-break-inside: avoid; overflow: hidden;
                box-shadow: 0 10px 25px rgba(0,0,0,0.05);
            }}
            .card-header {{
                color: white; padding: 15px 20px; font-size: 18px; font-weight: 600;
                background: linear-gradient(135deg, #667eea, #764ba2);
            }}
            .card-body {{ padding: 20px; }}
            .card-body h3 {{ font-size: 16px; margin: 0 0 15px 0; border-bottom: 1px solid #e2e8f0; padding-bottom: 10px; }}
            .summary-text {{ font-size: 14px; line-height: 1.6; color: #4a5568; }}
            .venue {{ font-weight: 600; color: #667eea; margin-bottom: 15px; }}
            .kpi-block div {{
                display: flex; justify-content: space-between;
                padding: 8px 0; border-bottom: 1px solid #f7fafc;
                font-size: 14px;
            }}
            .kpi-block div:last-child {{ border-bottom: none; }}
            .kpi-block div span {{ color: #718096; }}
        </style>
    </head>
    <body>
        <div class="report-container">
            <div class="header"><h1>📊 Informe de Recomendaciones IA MICE</h1></div>
            <div class="card">
                <div class="card-header" style="background: #fff; color: #2d3748;"><h3>📝 Resumen Ejecutivo</h3></div>
                <div class="card-body"><p class="summary-text">{data.get('summary', 'No disponible.')}</p></div>
            </div>
            {_generate_mice_city_html(recommended_city, is_recommended=True) if recommended_city else ''}
            {alternatives_html}
        </div>
    </body>
    </html>
    """
    return html_content

@app.post("/generate-pdf-mice")
async def generate_mice_pdf_endpoint(data: dict, _token: str = Depends(exigir_token)):
    html_content = generate_html_for_mice_pdf(data)
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.set_content(html_content)
        await page.emulate_media(media="print")
        
        pdf_bytes = await page.pdf(
            format="A4",
            print_background=True,
            margin={"top": "0.5in", "bottom": "0.5in", "left": "0.5in", "right": "0.5in"}
        )
        await browser.close()
    return Response(content=pdf_bytes, media_type="application/pdf")