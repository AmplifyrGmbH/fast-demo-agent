import os
from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse

router = APIRouter(tags=["dashboard"])

STATIC_DIR = os.path.join(os.path.dirname(__file__), "..", "static")


@router.get("/")
async def serve_dashboard():
    index_path = os.path.join(STATIC_DIR, "index.html")
    return FileResponse(index_path)


@router.get("/static/{filename}")
async def serve_static(filename: str):
    file_path = os.path.join(STATIC_DIR, filename)
    if not os.path.exists(file_path):
        return HTMLResponse("Not found", status_code=404)
    return FileResponse(file_path)
