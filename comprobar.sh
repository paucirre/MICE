#!/usr/bin/env bash
#
# Comprobacion previa a la demo.
#
# Ejecuta esto DESPUES de desplegar y ANTES de ponerte delante de un cliente.
# Verifica que el servicio responde, que la contrasena protege de verdad y que
# un analisis completo llega hasta el final.
#
#   ./comprobar.sh https://tu-backend.easypanel.host tu-contrasena
#
# El analisis real tarda entre uno y tres minutos: es normal que se quede un
# rato en silencio mientras los agentes buscan.

set -uo pipefail

BASE="${1:-}"
PASS="${2:-}"

if [ -z "$BASE" ] || [ -z "$PASS" ]; then
  echo "Uso: ./comprobar.sh <url-del-backend> <contrasena>"
  exit 2
fi

BASE="${BASE%/}"
FALLOS=0

ok()    { printf '  \033[32mOK\033[0m    %s\n' "$1"; }
fallo() { printf '  \033[31mFALLA\033[0m %s\n' "$1"; FALLOS=$((FALLOS+1)); }
paso()  { printf '\n\033[1m%s\033[0m\n' "$1"; }

paso "1. El servicio responde"
CODIGO=$(curl -s -o /dev/null -w '%{http_code}' -m 20 "$BASE/healthz")
if [ "$CODIGO" = "200" ]; then
  ok "healthz responde 200"
else
  fallo "healthz responde $CODIGO (si es 000, el contenedor no esta arriba)"
  echo
  # Confusion habitual: pasar la URL del frontend en vez de la del backend.
  if curl -s -m 20 "$BASE" | grep -qi '<html\|<!doctype'; then
    echo "Esa URL devuelve HTML: parece el FRONTEND, no el backend."
    echo "Necesitas la URL del servicio en EasyPanel, del tipo:"
    echo "  https://<algo>.easypanel.host"
    echo "No la de utopi.es, que solo sirve ficheros estaticos."
  else
    echo "Sin servicio no tiene sentido seguir. Revisa los logs en EasyPanel:"
    echo "si falta DEMO_PASSWORD o SESSION_SECRET, el arranque se bloquea aposta."
  fi
  exit 1
fi

paso "2. La contrasena protege de verdad"
CODIGO=$(curl -s -o /dev/null -w '%{http_code}' -m 20 -X POST "$BASE/login" \
  -H 'Content-Type: application/json' -d '{"password":"contrasena-que-no-es"}')
[ "$CODIGO" = "401" ] && ok "una contrasena incorrecta recibe 401" \
                      || fallo "una contrasena incorrecta recibe $CODIGO, deberia ser 401"

CODIGO=$(curl -s -o /dev/null -w '%{http_code}' -m 30 \
  "$BASE/analyze-stream?event_data_json=%7B%7D")
[ "$CODIGO" = "401" ] && ok "sin token no se puede lanzar un analisis" \
                      || fallo "sin token el analisis devuelve $CODIGO, deberia ser 401"

paso "3. La contrasena buena abre sesion"
RESPUESTA=$(curl -s -m 20 -X POST "$BASE/login" \
  -H 'Content-Type: application/json' -d "{\"password\":$(printf '%s' "$PASS" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')}")
TOKEN=$(printf '%s' "$RESPUESTA" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("token",""))' 2>/dev/null)

if [ -n "$TOKEN" ]; then
  ok "sesion abierta"
else
  fallo "no se pudo abrir sesion. Respuesta del servidor: $RESPUESTA"
  echo
  if printf '%s' "$RESPUESTA" | grep -qi 'not found'; then
    echo "El endpoint /login no existe: lo que hay desplegado es el codigo viejo."
    echo "Haz merge de la rama fix/responses-api y pulsa Implementar en EasyPanel."
  else
    echo "Comprueba que DEMO_PASSWORD en EasyPanel coincide con la que has pasado."
  fi
  exit 1
fi

paso "4. Un analisis completo de principio a fin"
echo "  (esto tarda entre uno y tres minutos, es normal)"

DATOS=$(python3 -c '
import json, urllib.parse
print(urllib.parse.quote(json.dumps({
    "sportType": "Running / Maratón",
    "eventLevel": "Amateur / Popular",
    "mainFocus": "Participativo / Masivo",
    "startDate": "2026-10-24",
    "endDate": "2026-10-24",
    "attendeesMin": 5000,
    "attendeesMax": 10000,
    "budget": 70000,
    "location": "",
    "requirements": "",
})))')

SALIDA=$(curl -s -N -m 420 \
  "$BASE/analyze-stream?event_data_json=$DATOS&token=$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))" "$TOKEN")")

if printf '%s' "$SALIDA" | grep -q '"type": *"final_result"'; then
  ok "el analisis llego hasta el informe final"

  # La invariante que la v1 rompia: el ROI tiene que ser el impacto entre el
  # presupuesto. Si esto falla, no ensenes las cifras a nadie.
  printf '%s' "$SALIDA" | python3 - <<'PY'
import json, sys
texto = sys.stdin.read()
informe = None
for linea in texto.splitlines():
    if linea.startswith("data: "):
        try:
            m = json.loads(linea[6:])
        except Exception:
            continue
        if m.get("type") == "final_result":
            informe = m["content"]
if not informe:
    sys.exit(0)

presupuesto = 70000
rec = informe.get("recommendations", {})
ciudades = [rec.get("recommended")] + list(rec.get("alternatives") or [])
malas = []
for c in ciudades:
    if not c:
        continue
    impacto = (c.get("kpi_economic") or {}).get("direct_impact_eur")
    roi = (c.get("kpi_main") or {}).get("roi_est")
    if not isinstance(impacto, (int, float)) or not isinstance(roi, (int, float)):
        continue
    if abs(roi - round(impacto / presupuesto, 1)) > 0.15:
        malas.append(f"{c.get('name')}: ROI {roi}x pero impacto/presupuesto = {impacto/presupuesto:.1f}x")

if malas:
    print("  \033[31mFALLA\033[0m el ROI no cuadra con el impacto:")
    for m in malas:
        print("          " + m)
else:
    print("  \033[32mOK\033[0m    el ROI cuadra con el impacto en todas las ciudades")
    print(f"  \033[32mOK\033[0m    ciudad recomendada: {(rec.get('recommended') or {}).get('name','?')}")
PY
elif printf '%s' "$SALIDA" | grep -q '"type": *"error"'; then
  fallo "el servidor devolvio un error:"
  printf '%s' "$SALIDA" | grep '"type": *"error"' | tail -1 | sed 's/^/          /'
else
  fallo "el analisis no termino. Ultimas lineas recibidas:"
  printf '%s' "$SALIDA" | tail -5 | sed 's/^/          /'
fi

paso "Resultado"
if [ "$FALLOS" -eq 0 ]; then
  printf '  \033[32mTodo listo para la demo.\033[0m\n\n'
  exit 0
else
  printf '  \033[31m%s comprobacion(es) fallida(s).\033[0m Mira DEPLOY.md, seccion "Si algo falla".\n\n' "$FALLOS"
  exit 1
fi
