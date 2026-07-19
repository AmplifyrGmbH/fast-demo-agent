from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="FastDemo Builder API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8003",
        "https://demo.amplifyr-digital.ch",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

from routers import builds, dashboard  # noqa: E402
app.include_router(builds.router)
app.include_router(dashboard.router)


@app.on_event("startup")
async def startup():
    from database import create_tables
    await create_tables()


@app.get("/health")
async def health():
    return {"status": "ok"}
