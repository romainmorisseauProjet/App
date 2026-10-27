"""
Lancement en local (VS Code / ordinateur).

Démarre le même serveur que sur Render, uniquement sur ton PC (127.0.0.1),
puis l'affiche dans une fenêtre de bureau (pywebview) comme avant. Si
pywebview n'est pas installé, ouvre le navigateur à la place.
Aucun mot de passe en local : le serveur n'est pas accessible depuis l'extérieur.
"""

import os
import threading
import webbrowser


def demarrer():
    os.environ["MON_IA_LOCAL"] = "1"
    import server  # importé après avoir activé le mode local

    from werkzeug.serving import make_server

    # port 0 = le système en choisit un libre, donc pas de conflit avec autre chose
    http = make_server("127.0.0.1", int(os.environ.get("PORT", 0)), server.app, threaded=True)
    url = f"http://127.0.0.1:{http.server_port}"
    fil = threading.Thread(target=http.serve_forever, daemon=True)
    fil.start()
    print("Serveur local :", url)

    try:
        import webview
    except ImportError:
        print("pywebview absent : ouverture dans le navigateur (Ctrl+C pour arrêter).")
        webbrowser.open(url)
        try:
            fil.join()
        except KeyboardInterrupt:
            pass
        return

    webview.create_window(
        "Assistant", url,
        width=1200, height=800, min_size=(800, 560), background_color="#050810",
    )
    webview.start()
    http.shutdown()


if __name__ == "__main__":
    demarrer()
