from datetime import datetime, date
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from core.database import get_db
from models.models import IngresoTaller, Turno, Vehiculo, Cliente

router = APIRouter(prefix="/api/v1/taller", tags=["taller"])


# ── Ingresos ──

@router.get("/ingresos/hoy")
def ingresos_hoy(db: Session = Depends(get_db)):
    hoy = date.today()
    ingresos = db.query(IngresoTaller).filter(
        func.date(IngresoTaller.fecha_ingreso) == hoy
    ).order_by(IngresoTaller.fecha_ingreso.desc()).all()
    return [
        {
            "id": i.id,
            "fecha_ingreso": i.fecha_ingreso.isoformat() if i.fecha_ingreso else None,
            "vehiculo_modelo": i.vehiculo_modelo,
            "vehiculo_patente": i.vehiculo_patente,
            "cliente_nombre": i.cliente_nombre,
            "cliente_telefono": i.cliente_telefono or "",
            "mecanico_nombre": i.mecanico_nombre,
            "estado": i.estado,
            "venta_ref_id": i.venta_ref_id,
            "kilometraje": getattr(i, "kilometraje", 0) or 0,
        }
        for i in ingresos
    ]


@router.post("/ingresos")
def crear_ingreso(data: dict, db: Session = Depends(get_db)):
    km = data.get("kilometraje", 0) or 0
    ingreso = IngresoTaller(
        vehiculo_modelo=data.get("vehiculo_modelo", ""),
        vehiculo_patente=data.get("vehiculo_patente", ""),
        cliente_nombre=data.get("cliente_nombre", ""),
        cliente_telefono=data.get("cliente_telefono", ""),
        mecanico_nombre=data.get("mecanico_nombre", ""),
        estado=data.get("estado", "PENDIENTE"),
        venta_ref_id=data.get("venta_ref_id"),
        kilometraje=km,
    )
    db.add(ingreso)
    db.commit()
    db.refresh(ingreso)
    return {"id": ingreso.id, "message": "Ingreso registrado"}


@router.get("/ingresos/{ingreso_id}/items")
def get_items_ingreso(ingreso_id: int, db: Session = Depends(get_db)):
    ingreso = db.query(IngresoTaller).filter(IngresoTaller.id == ingreso_id).first()
    if not ingreso:
        raise HTTPException(status_code=404, detail="Ingreso no encontrado")
    return {"items": ingreso.items or "[]"}


@router.put("/ingresos/{ingreso_id}/items")
def save_items_ingreso(ingreso_id: int, data: dict, db: Session = Depends(get_db)):
    ingreso = db.query(IngresoTaller).filter(IngresoTaller.id == ingreso_id).first()
    if not ingreso:
        raise HTTPException(status_code=404, detail="Ingreso no encontrado")
    ingreso.items = data.get("items", "[]")
    db.commit()
    return {"message": "Items guardados"}


@router.patch("/ingresos/{ingreso_id}/estado")
def cambiar_estado_ingreso(ingreso_id: int, data: dict, db: Session = Depends(get_db)):
    ingreso = db.query(IngresoTaller).filter(IngresoTaller.id == ingreso_id).first()
    if not ingreso:
        raise HTTPException(status_code=404, detail="Ingreso no encontrado")
    ingreso.estado = data.get("estado", ingreso.estado)
    db.commit()
    return {"message": "Estado actualizado"}


# ── Turnos ──

@router.get("/turnos/hoy")
def turnos_hoy(db: Session = Depends(get_db)):
    hoy = date.today()
    turnos = db.query(Turno).filter(
        func.date(Turno.fecha_hora) >= hoy
    ).order_by(Turno.fecha_hora.asc()).all()
    return [
        {
            "id": t.id,
            "fecha_hora": t.fecha_hora.isoformat() if t.fecha_hora else None,
            "vehiculo_modelo": t.vehiculo_modelo,
            "cliente_nombre": t.cliente_nombre,
            "observaciones": t.observaciones,
            "estado": t.estado,
        }
        for t in turnos
    ]


@router.get("/turnos/{turno_id}")
def get_turno(turno_id: int, db: Session = Depends(get_db)):
    turno = db.query(Turno).filter(Turno.id == turno_id).first()
    if not turno:
        raise HTTPException(status_code=404, detail="Turno no encontrado")
    return {
        "id": turno.id,
        "fecha_hora": turno.fecha_hora.isoformat() if turno.fecha_hora else None,
        "vehiculo_modelo": turno.vehiculo_modelo,
        "cliente_nombre": turno.cliente_nombre,
        "observaciones": turno.observaciones,
        "estado": turno.estado,
    }


@router.post("/turnos")
def crear_turno(data: dict, db: Session = Depends(get_db)):
    fecha_str = data.get("fecha_hora", "")
    try:
        fecha = datetime.fromisoformat(fecha_str)
    except (ValueError, TypeError):
        fecha = datetime.now()
    turno = Turno(
        fecha_hora=fecha,
        vehiculo_modelo=data.get("vehiculo_modelo", ""),
        cliente_nombre=data.get("cliente_nombre", ""),
        observaciones=data.get("observaciones", ""),
        estado=data.get("estado", "CONFIRMADO"),
    )
    db.add(turno)
    db.commit()
    db.refresh(turno)
    return {"id": turno.id, "message": "Turno creado"}


@router.patch("/turnos/{turno_id}/estado")
def cambiar_estado_turno(turno_id: int, data: dict, db: Session = Depends(get_db)):
    turno = db.query(Turno).filter(Turno.id == turno_id).first()
    if not turno:
        raise HTTPException(status_code=404, detail="Turno no encontrado")
    turno.estado = data.get("estado", turno.estado)
    db.commit()
    return {"message": "Estado actualizado"}


@router.delete("/turnos/{turno_id}")
def eliminar_turno(turno_id: int, db: Session = Depends(get_db)):
    turno = db.query(Turno).filter(Turno.id == turno_id).first()
    if not turno:
        raise HTTPException(status_code=404, detail="Turno no encontrado")
    db.delete(turno)
    db.commit()
    return {"message": "Turno eliminado"}
