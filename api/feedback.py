from fastapi import APIRouter
from pydantic import BaseModel
from core.feedback import submit_feedback

router = APIRouter()

class FeedbackRequest(BaseModel):
    user: str
    query: str
    rating: int
    comments: str = ""

@router.post("/feedback")
def feedback(req: FeedbackRequest):
    submit_feedback(req.user, req.query, req.rating, req.comments)
    return {"status": "ok"} 