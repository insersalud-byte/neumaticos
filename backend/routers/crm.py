from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from core.database import get_db
from models.models import Cliente

router = APIRouter(prefix="/api/v1/crm", tags=["crm"])


@router.get("/clientes/buscar")
def buscar_clientes(q: str = "", termino: str = "", db: Session = Depends(get_db)):
    search = q or termino
    if len(search) < 2:
        return {"data": []}
    clientes = db.query(Cliente).filter(
        Cliente.nombre.ilike(f"%{search}%")
    ).limit(10).all()
    return {
        "data": [
            {"id": c.id, "nombre": c.nombre, "telefono": c.telefono or "", "dni_cuit": c.dni_cuit or ""}
            for c in clientes
        ]
    }
