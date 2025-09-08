# Usamos una imagen oficial de Python ligera
FROM python:3.12-slim

# Establecemos el directorio de trabajo dentro del contenedor
WORKDIR /app

# Copiamos primero el archivo de requisitos
COPY requirements.txt requirements.txt

# INSTALACIÓN MEJORADA:
# Usamos --with-deps para que Playwright instale automáticamente
# las dependencias del sistema operativo Y el navegador Chromium.
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install --with-deps chromium

# Copiamos el resto del código del proyecto
COPY . .

# Exponemos el puerto 8000
EXPOSE 8000

# El comando que se ejecutará cuando el contenedor se inicie
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]