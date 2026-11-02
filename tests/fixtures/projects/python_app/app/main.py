"""Sample app for scanner tests. Not a real service."""

import os

from fastapi import FastAPI

app = FastAPI()
SECRET_KEY = os.environ["SECRET_KEY"]
LOG_LEVEL = os.getenv("LOG_LEVEL", "info")
# os.getenv("ONLY_IN_A_COMMENT") must not be reported.
