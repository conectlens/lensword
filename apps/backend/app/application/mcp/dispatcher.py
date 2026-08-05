from collections.abc import Callable
from typing import Any
from inspect import isawaitable

from app.application.mcp.contracts import TOOL_CONTRACTS, ToolContract


class UnknownMCPToolError(ValueError): pass
class UnboundMCPToolError(RuntimeError): pass


class MCPDispatcher:
    """Adapter-facing dispatcher that admits only registered contract names.

    Handlers are application-use-case adapters, injected by the transport
    composition root. This keeps MCP transport code from reaching a repository.
    """
    def __init__(self, handlers: dict[str, Callable[[int, dict[str, Any]], dict[str, Any]]]):
        self.handlers = handlers
        self.contracts = {contract.name: contract for contract in TOOL_CONTRACTS}

    def contract_for(self, name: str) -> ToolContract:
        try: return self.contracts[name]
        except KeyError as exc: raise UnknownMCPToolError(name) from exc

    def dispatch(self, user_id: int, name: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.contract_for(name)
        handler = self.handlers.get(name)
        if handler is None: raise UnboundMCPToolError(name)
        return handler(user_id, payload)

    async def dispatch_async(self, user_id: int, name: str, payload: dict[str, Any]) -> dict[str, Any]:
        result = self.dispatch(user_id, name, payload)
        return await result if isawaitable(result) else result
