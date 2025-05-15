from fastapi import FastAPI, Request, Depends
from pydantic import BaseModel
import asyncio
from core.command import run_command_async
from core.rbac import require_permission
from api.feedback import router as feedback_router
from api.llm import router as llm_router
from api.anomaly import router as anomaly_router

app = FastAPI()

class CommandRequest(BaseModel):
    command: str
    timeout: int = 30
    user: str

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/run-command")
async def run_command(req: CommandRequest, user: str = Depends(require_permission('execute_whitelisted_command'))):
    result = await run_command_async(req.command, req.timeout, req.user)
    return result

app.include_router(feedback_router)
app.include_router(llm_router)
app.include_router(anomaly_router)

# More endpoints for remediation, plugin management, etc. can be added here 