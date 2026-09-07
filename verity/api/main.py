from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from verity.graph.repository import pool
from verity.api.routes import clients, companies, people, relationships, briefs, monitoring


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Warm the DB pool on startup
    await pool()
    yield


app = FastAPI(
    title="Verity",
    description="Private intelligence system for professional firms.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten per firm deployment
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(clients.router, prefix="/clients", tags=["Clients"])
app.include_router(companies.router, prefix="/companies", tags=["Companies"])
app.include_router(people.router, prefix="/people", tags=["People"])
app.include_router(relationships.router, prefix="/relationships", tags=["Relationships"])
app.include_router(briefs.router, prefix="/briefs", tags=["Briefs"])
app.include_router(monitoring.router, prefix="/monitoring", tags=["Monitoring"])


@app.get("/health")
async def health():
    return {"status": "ok", "service": "verity"}
