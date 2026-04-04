from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from core.database import get_db
from core.auth import verify_password, create_access_token
from models.models import Usuario

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/token")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(Usuario).filter(Usuario.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Credenciales incorrectas")
    token = create_access_token({"sub": user.username, "nombre": user.nombre, "rol": user.rol})
    response = JSONResponse(content={"access_token": token, "token_type": "bearer", "nombre": user.nombre, "rol": user.rol})
    response.set_cookie(key="becubical_session", value=token, httponly=False, samesite="lax", path="/")
    return response
