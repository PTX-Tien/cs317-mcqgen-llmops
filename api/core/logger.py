import structlog, logging, uuid
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request

def setup_logging():
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
    )
    logging.basicConfig(level=logging.INFO)

log = structlog.get_logger()

class CorrelationIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        cid = request.headers.get("X-Correlation-ID", str(uuid.uuid4())[:8])
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            cid=cid,
            path=str(request.url.path),
            method=request.method,
        )
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = cid
        return response
