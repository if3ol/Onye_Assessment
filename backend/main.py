from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse

from backend.config import settings
from backend.routers import reconcile, validate

app = FastAPI(
    title="EHR Clinical Data Reconciliation Engine",
    description="AI-powered reconciliation of conflicting patient records across EHR systems.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

#  CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)

#  Routers
app.include_router(reconcile.router)
app.include_router(validate.router)

#  Global error handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal error occurred. Please try again."},
    )

#  Health check
@app.get("/health", tags=["System"])
async def health():
    return {"status": "ok"}

#  Serve frontend — injects API key server-side
@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    with open("frontend/index.html", "r") as f:
        html = f.read()
    html = html.replace("'__API_KEY__'", f"'{settings.app_api_key}'")
    return HTMLResponse(content=html)