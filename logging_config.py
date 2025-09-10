# logging_config.py

import logging
from logtail import LogtailHandler
import os
from dotenv import load_dotenv

load_dotenv()

# Obtenemos el token desde las variables de entorno
handler = LogtailHandler(source_token=os.getenv("LOGTAIL_SOURCE_TOKEN"))

# Creamos un logger llamado 'mice_logger'
logger = logging.getLogger('mice_logger')
logger.setLevel(logging.INFO)

# Si no tiene ya un handler (para evitar duplicados), se lo añadimos
if not logger.handlers:
    logger.addHandler(handler)