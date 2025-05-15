from fastapi import APIRouter
from pydantic import BaseModel
from core.llm import knowledge_query, generate_remediation

router = APIRouter()

class KnowledgeRequest(BaseModel):
    question: str

class RemediationRequest(BaseModel):
    issue: str
    service: str
    server: str

@router.post("/knowledge-query")
async def knowledge(req: KnowledgeRequest):
    answer = await knowledge_query(req.question)
    return {"answer": answer}

@router.post("/remediation")
async def remediation(req: RemediationRequest):
    plan = await generate_remediation(req.issue, req.service, req.server)
    return {"remediation_plan": plan} 