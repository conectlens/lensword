"""Read-only capability discovery for LensWord's versioned MCP boundary."""
from fastapi import APIRouter
from app.application.mcp.contracts import capabilities

router = APIRouter(prefix="/api/v1/mcp", tags=["mcp"])

@router.get("/capabilities")
def get_capabilities() -> dict:
    return capabilities()
