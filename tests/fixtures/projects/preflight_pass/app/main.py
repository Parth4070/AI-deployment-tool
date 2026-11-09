"""Sample app where every preflight check passes. Not a real service."""

import os

from fastapi import FastAPI

app = FastAPI()
DATABASE_URL = os.environ["DATABASE_URL"]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
