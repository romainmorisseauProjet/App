# MON_IA

## En local (VS Code)
    pip install -r requirements.txt
    pip install -r requirements-local.txt     (fenêtre de bureau, facultatif)
    python main.py                            (ou bouton ▶ sur main.py)
Ouvre la fenêtre comme avant, sans mot de passe. Sans pywebview, s'ouvre dans le navigateur.
Dans VS Code : « python server.py » puis Ctrl+Maj+P > « Simple Browser: Show » > http://127.0.0.1:5000

## Sur Render
    Build Command : pip install -r requirements.txt
    Start Command : gunicorn server:app --workers 1 --threads 4 --timeout 120
    Health Check Path : /healthz
    Variables : APP_PASSWORD, SECRET_KEY, DATA_DIR (= point de montage du disque persistant)
