from fastapi import HTTPException, Depends
from core.security import get_user_role, has_permission

def require_permission(permission: str):
    def checker(user: str = Depends()):
        if not has_permission(user, permission):
            raise HTTPException(status_code=403, detail="Permission denied")
        return user
    return checker 