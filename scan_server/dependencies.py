from fastapi import HTTPException, Header
from config import settings

def verify_key(secret_key: str = Header()):
    if secret_key != settings.secret_key:
        raise HTTPException(status_code=403, detail="Invalid secrete key")