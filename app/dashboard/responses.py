def login_error_html(error: Exception) -> str:
    return f"<h2>Erro ao iniciar login</h2><p>{error}</p><a href='/'>Voltar</a>"


def oauth_error_html(error: Exception, redirect_uri: str) -> str:
    return f"""
    <h2>Erro na autenticação</h2>
    <p><strong>{type(error).__name__}:</strong> {error}</p>
    <p>Verifique se <code>{redirect_uri}</code>
    está cadastrado como URI autorizada no
    <a href='https://console.cloud.google.com/apis/credentials' target='_blank'>Google Cloud Console</a>.</p>
    <a href='/'>Tentar novamente</a>
    """


def dashboard_error_html(error: Exception, traceback_str: str) -> str:
    return f"""
    <!DOCTYPE html><html><head>
    <meta charset='UTF-8'>
    <title>Erro — StayIQ</title>
    <style>
        body {{ font-family: sans-serif; padding: 40px; max-width: 700px; margin: auto }}
        pre  {{ background: #f3f4f6; padding: 16px; border-radius: 8px; overflow: auto; font-size: 13px }}
        a    {{ color: #4F46E5 }}
    </style>
    </head><body>
    <h2>⚠️ Erro ao carregar o dashboard</h2>
    <p><strong>{type(error).__name__}:</strong> {error}</p>
    <pre>{traceback_str}</pre>
    <p><a href='/logout'>Sair</a> · <a href='/dashboard'>Tentar novamente</a></p>
    </body></html>
    """
