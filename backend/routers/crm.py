from fastapi import APIRouter, Depends, HTTPException
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


@router.post("/clientes")
def crear_cliente(data: dict, db: Session = Depends(get_db)):
    c = Cliente(
        nombre=data.get("nombre", "").strip(),
        telefono=data.get("telefono", "").strip(),
        dni_cuit=data.get("dni_cuit", "").strip(),
        tipo_cliente=data.get("tipo_cliente", "persona"),
        correo=data.get("correo", "").strip(),
        saldo_deudor=0,
        activo=True,
    )
    if not c.nombre:
        raise HTTPException(status_code=400, detail="El nombre es obligatorio")
    db.add(c)
    db.commit()
    db.refresh(c)
    return {"id": c.id, "message": "Cliente creado"}


@router.put("/clientes/{cliente_id}")
def editar_cliente(cliente_id: int, data: dict, db: Session = Depends(get_db)):
    c = db.query(Cliente).filter(Cliente.id == cliente_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    if "nombre" in data:
        c.nombre = data["nombre"].strip()
    if "telefono" in data:
        c.telefono = data["telefono"].strip()
    if "dni_cuit" in data:
        c.dni_cuit = data["dni_cuit"].strip()
    if "tipo_cliente" in data:
        c.tipo_cliente = data["tipo_cliente"]
    if "correo" in data:
        c.correo = data["correo"].strip()
    db.commit()
    return {"message": "Cliente actualizado"}
