"""관리자 인증 경계 · 외부 포트 없이 게이트웨이가 검증한 헤더만 수신"""
from fastapi import HTTPException, Request

ADMIN_USER_HEADER = "X-Admin-User"


def require_admin(request: Request) -> None:
    admin_user = request.headers.get(ADMIN_USER_HEADER, "").strip()
    if not admin_user:
        raise HTTPException(status_code=403, detail="관리자 권한 필요")
    request.state.admin_user = admin_user
