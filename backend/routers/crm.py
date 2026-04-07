from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import or_
from core.database import get_db
from models.models import Cliente

router = APIRouter(prefix="/api/v1/crm", tags=["crm"])


@router.get("/clientes/buscar")
def buscar_clientes(q: str = "", termino: str = "", db: Session = Depends(get_db)):
    search = q or termino
    if len(search) < 2:
        return {"data": []}
    pattern = f"%{search}%"
    clientes = db.query(Cliente).filter(
        or_(
            Cliente.nombre.ilike(pattern),
            Cliente.telefono.ilike(pattern),
            Cliente.dni_cuit.ilike(pattern),
        )
    ).limit(10).all()
    return {
        "data": [
            {"id": c.id, "nombre": c.nombre, "telefono": c.telefono or "", "dni_cuit": c.dni_cuit or ""}
            for c in clientes
        ]
    }


@router.get("/clientes")
def listar_clientes(db: Session = Depends(get_db)):
    clientes = db.query(Cliente).filter(Cliente.activo == True).limit(50).all()
    return {
        "data": [
            {"id": c.id, "nombre": c.nombre, "telefono": c.telefono or "", "dni_cuit": c.dni_cuit or ""}
            for c in clientes
        ]
    }
