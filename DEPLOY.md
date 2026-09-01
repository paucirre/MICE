# Puesta en marcha para la demo

Del clon a la demo funcionando. Calcula unos 20 minutos, casi todos de espera
del build de Docker.

---

## 1. Variables de entorno

En EasyPanel, servicio `ia-mice-deporte` → **Entorno**. Genera el secreto:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

| Variable | Valor | Obligatoria |
|---|---|---|
| `OPENAI_API_KEY` | tu clave (ya la tienes puesta) | sí |
| `DEMO_PASSWORD` | la contraseña que darás a quien vea la demo | sí |
| `SESSION_SECRET` | lo que imprima el comando de arriba | sí |
| `ALLOWED_ORIGINS` | `https://utopi.es` | no |
| `DIRECTOR_MODEL` | `gpt-5.6-terra` | no |
| `RESEARCH_MODEL` | `gpt-5.6-luna` | no |
| `RATE_LIMIT_POR_HORA` | `10` | no |

**Sin las tres obligatorias el contenedor no arranca.** Es deliberado: prefiero
que veas el servicio caído a que se levante abierto a Internet. Si arrancas y
se cae al momento, mira los logs — el mensaje dice exactamente qué falta.

## 2. Desplegar el backend

```bash
git checkout main
git merge fix/responses-api
git push
```

Y en EasyPanel, **Implementar**. El build tarda porque reinstala Chromium para
Playwright.

## 3. Subir el frontend

A `utopi.es/iamicedeporte/`, sobrescribiendo:

- `index.html` — lleva la pantalla de contraseña
- `dashboard.html` — envía el token al generar el PDF

Si subes el backend y no el frontend, la web se quedará en «Error de conexión»:
estará pidiendo análisis sin token.

## 4. Comprobar antes de la demo

```bash
./comprobar.sh https://multiagente-micedeporte-ia-mice-deporte.gra1ll.easypanel.host TU_CONTRASEÑA
```

Verifica que el servicio responde, que la contraseña protege de verdad, que un
análisis completo llega al final, y que **el ROI cuadra con el impacto** en
todas las ciudades. Tarda entre uno y tres minutos.

Hazlo el día antes, no diez minutos antes.

---

## Si algo falla

| Lo que ves | Qué pasa | Qué haces |
|---|---|---|
| El contenedor no arranca y los logs dicen `ConfiguracionInsegura` | Falta `DEMO_PASSWORD` o `SESSION_SECRET` | Añádelas y vuelve a implementar |
| «El servidor de OpenAI respondió 404… revisa DIRECTOR_MODEL» | El modelo configurado ya no existe | Cambia `DIRECTOR_MODEL` / `RESEARCH_MODEL` por uno vigente. **No hace falta redesplegar código**, solo reiniciar |
| «OpenAI rechazó la clave (401)» | `OPENAI_API_KEY` mal o revocada | Revisa la clave |
| «OpenAI ha limitado el ritmo o la cuenta no tiene saldo (429)» | Sin saldo, o demasiadas peticiones | Recarga saldo o espera |
| «Sesión caducada o límite alcanzado» en la web | Han pasado 8 h, o 10 análisis en una hora | Vuelve a entrar. Si es el límite, sube `RATE_LIMIT_POR_HORA` |
| La web dice «Error de conexión» nada más entrar | Frontend viejo sin token, o `ALLOWED_ORIGINS` no incluye tu dominio | Sube el frontend nuevo y revisa la variable |
| `comprobar.sh` dice «lo que hay desplegado es el código viejo» | El merge no llegó o no pulsaste Implementar | Repite el paso 2 |

**Para cortar el acceso a todo el mundo de golpe:** cambia `SESSION_SECRET`.
Todas las sesiones abiertas caducan al instante.

---

## Qué enseñar y qué no

Esto es la v1 con el apagón reparado. Merece la pena tenerlo claro antes de
ponerte delante de alguien.

**Lo que puedes enseñar sin reservas:** el flujo completo, la investigación en
vivo con fuentes citadas, la comparativa de sedes, el PDF, y la velocidad a la
que produce un informe presentable.

**Lo que no debes presentar como dato:** las cifras. El impacto directo, el ADR,
el valor mediático y las puntuaciones sobre 10 las sigue generando un modelo de
lenguaje, no un cálculo. Le he puesto instrucciones para que no copie el impacto
de eventos ajenos —que es lo que hacía— pero eso es una petición al modelo, no
una garantía.

Lo único que ahora está garantizado es el **ROI**, que se calcula en código
dividiendo impacto entre presupuesto. La versión anterior llegó a emitir 4,5×
sobre 1.500.000 / 70.000 = 21,4×, y `comprobar.sh` vigila que no vuelva a pasar.

Si alguien pregunta de dónde salen los números, la respuesta honesta es que es
un prototipo de producto y que la versión con cifras trazables contra INE, CSD
y AEMET está en construcción. Esa conversación juega a tu favor: es exactamente
lo que te diferencia.

---

## Detalles que quizá necesites

**El token de sesión viaja en la query string** del endpoint de análisis, porque
`EventSource` no admite cabeceras propias. Es un token de 8 horas, no una
contraseña, pero queda en los logs del proxy. En la v2 se resuelve con cookie.

**El límite es por sesión, no por persona.** Si compartes la contraseña con
varios y todos entran a la vez, cada uno abre su propia sesión y tiene sus 10
análisis. El control por usuario es la fase 3 de la v2.

**Los modelos están en variables de entorno** precisamente porque OpenAI retiró
la Assistants API y la familia `gpt-4o` sin previo aviso útil. Si vuelve a
pasar, se arregla cambiando una variable y reiniciando.
