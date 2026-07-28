"""평가 이후 꼬리질문 전용 라우터."""

from fastapi import APIRouter

from schemas import FollowupRequest, FollowupResponse
from services.evaluation_service import generate_followup

router = APIRouter(prefix="/api")


@router.post("/followup", response_model=FollowupResponse)
def followup(req: FollowupRequest) -> FollowupResponse:
    return generate_followup(req)
