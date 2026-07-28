"""FastAPI 애플리케이션 부트스트랩."""

import logging
import os

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import llm_client
from routers import evaluate, followup, personas, questions, report, slides

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Presentation Sparring API")

FRONTEND_ORIGIN = os.getenv(
    "FRONTEND_ORIGIN",
    "http://localhost:5173",
)
_EXTRA_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "EXTRA_ORIGINS",
        "",
    ).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        FRONTEND_ORIGIN,
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        *_EXTRA_ORIGINS,
    ],
    allow_origin_regex=(
        r"https://.*\.(netlify\.app|onrender\.com)"
    ),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "provider": llm_client.PROVIDER,
    }


app.include_router(slides.router)
app.include_router(personas.router)
app.include_router(questions.router)
app.include_router(evaluate.router)
app.include_router(followup.router)
app.include_router(report.router)
