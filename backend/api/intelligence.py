from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import BaseModel, Field

from backend.integrations.nemotron import NemotronClient
from backend.services.intelligence.context import build_intelligence_context
from backend.services.intelligence.exceptions import (
    IntelligenceInvalidResponseError,
    IntelligenceNotConfiguredError,
    IntelligenceProviderUnavailableError,
    IntelligenceRateLimitError,
    IntelligenceTimeoutError,
)
from backend.services.intelligence.models import IntelligenceRequest
from backend.services.intelligence.service import CampexIntelligenceService
from backend.security import resolve_organization_scope


router = APIRouter(prefix="/api/v1/intelligence", tags=["intelligence"])


class AskPayload(BaseModel):
    query: str = Field(min_length=1, max_length=1200)


class AskResponse(BaseModel):
    answer: str
    organization_id: str
    model: str | None
    context_summary: dict
    limitations: list[str]


@router.post("/ask", response_model=AskResponse)
def ask_intelligence(
    payload: AskPayload,
    request: Request,
    authorization: str | None = Header(default=None, alias="Authorization"),
    x_campex_organization_token: str | None = Header(default=None, alias="X-CAMPEX-Organization-Token"),
    x_campex_organization_id: str | None = Header(default=None, alias="X-CAMPEX-Organization-Id"),
) -> AskResponse:
    settings = request.app.state.settings
    if not settings.intelligence_enabled:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Intelligence is disabled.")

    scope = resolve_organization_scope(
        settings,
        authorization=authorization,
        organization_token=x_campex_organization_token,
        requested_organization_id=x_campex_organization_id,
    )
    organization_id = scope.organization_id
    context = build_intelligence_context(settings, organization_id)
    service = CampexIntelligenceService(NemotronClient(settings))
    try:
        response = service.ask(
            IntelligenceRequest(
                organization_id=organization_id,
                query=payload.query,
                context=context,
            )
        )
    except IntelligenceNotConfiguredError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except IntelligenceTimeoutError as exc:
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="Intelligence provider timed out.") from exc
    except IntelligenceRateLimitError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Intelligence provider rate limit reached.") from exc
    except (IntelligenceProviderUnavailableError, IntelligenceInvalidResponseError) as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Intelligence provider unavailable.") from exc

    return AskResponse(
        answer=response.answer,
        organization_id=response.organization_id,
        model=response.model,
        context_summary=response.context_summary,
        limitations=response.limitations,
    )
