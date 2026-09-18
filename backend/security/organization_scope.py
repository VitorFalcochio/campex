from __future__ import annotations

import hmac
from dataclasses import dataclass

from fastapi import HTTPException, status


@dataclass(frozen=True)
class OrganizationScope:
    organization_id: str
    authenticated: bool
    source: str


def resolve_organization_scope(
    settings,
    *,
    authorization: str | None = None,
    organization_token: str | None = None,
    requested_organization_id: str | None = None,
) -> OrganizationScope:
    token = organization_token or _bearer_token(authorization)
    token_map = settings.intelligence_organization_tokens or {}
    allowed = settings.intelligence_allowed_organization_ids or [
        settings.intelligence_default_organization_id
    ]

    if token_map:
        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Organization token is required.",
            )
        organization_id = _organization_for_token(token_map, token)
        if organization_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid organization token.",
            )
        if requested_organization_id and requested_organization_id != organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Organization token does not allow the requested organization.",
            )
        if organization_id not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Organization is not allowed.",
            )
        return OrganizationScope(
            organization_id=organization_id,
            authenticated=True,
            source="organization_token",
        )

    organization_id = requested_organization_id or settings.intelligence_default_organization_id
    if organization_id not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization is not allowed.",
        )
    return OrganizationScope(
        organization_id=organization_id,
        authenticated=False,
        source="development_default" if not requested_organization_id else "development_header",
    )


def _organization_for_token(token_map: dict[str, str], token: str) -> str | None:
    for organization_id, expected_token in token_map.items():
        if hmac.compare_digest(token, expected_token):
            return organization_id
    return None


def _bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer" or not value:
        return None
    return value.strip()
