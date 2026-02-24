from fastapi import FastAPI

from app.routers import admin, ask, auth, connectors, health, slack, ui
from app.runtime import ensure_supported_python

ensure_supported_python()

app = FastAPI(title='multi-persona-rag-api', version='0.1.0')

app.include_router(health.router)
app.include_router(ask.router)
app.include_router(slack.router)
app.include_router(auth.router)
app.include_router(connectors.router)
app.include_router(admin.router)
app.include_router(ui.router)
