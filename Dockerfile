# OPTIONNEL — à utiliser seulement si ton service Render est en mode « Docker ».
# Ajoute ffmpeg (téléchargement musique) et LibreOffice (Word/Excel/PowerPoint -> PDF).
# Attention : LibreOffice est lourd, il demande une offre Render avec assez de RAM.
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
      ffmpeg libreoffice-writer libreoffice-calc libreoffice-impress \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

CMD gunicorn server:app --bind 0.0.0.0:${PORT:-10000} --workers 1 --threads 4 --timeout 120
