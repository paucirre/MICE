# Usamos una imagen oficial de Python ligera
FROM python:3.12-slim

# Establecemos el directorio de trabajo dentro del contenedor
WORKDIR /app

# Copiamos primero el archivo de requisitos para aprovechar el cache de Docker
COPY requirements.txt requirements.txt

# Instalamos las dependencias del proyecto
RUN pip install --no-cache-dir -r requirements.txt

# Copiamos el resto del código del proyecto al contenedor
COPY . .

# Exponemos el puerto 8000, que es donde Uvicorn se ejecutará
EXPOSE 8000

# El comando que se ejecutará cuando el contenedor se inicie
# Usamos --host 0.0.0.0 para que la app sea accesible desde fuera del contenedor
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]