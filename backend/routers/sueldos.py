from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from core.database import get_db
from models.models import Empleado, SueldoEmpleado, AdelantoEmpleado

router = APIRouter(prefix="/api/v1/sueldos", tags=["sueldos"])


@router.get("/empleados")
def listar_empleados(db: Session = Depends(get_db)):
    empleados = db.query(Empleado).filter(Empleado.activo == True).order_by(Empleado.nombre).all()
    return [{"id": e.id, "nombre": e.nombre, "telefono": e.telefono} for e in empleados]


@router.post("/empleados")
def crear_empleado(data: dict, db: Session = Depends(get_db)):
    emp = Empleado(
        nombre=data.get("nombre", ""),
        telefono=data.get("telefono", ""),
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return {"id": emp.id, "message": "Empleado creado"}


@router.put("/empleados/{empleado_id}")
def editar_empleado(empleado_id: int, data: dict, db: Session = Depends(get_db)):
    emp = db.query(Empleado).filter(Empleado.id == empleado_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Empleado no encontrado")
    emp.nombre = data.get("nombre", emp.nombre)
    emp.telefono = data.get("telefono", emp.telefono)
    emp.activo = data.get("activo", emp.activo)
    db.commit()
    return {"message": "Empleado actualizado"}


@router.get("/sueldos")
def listar_sueldos(mes: int = None, anio: int = None, db: Session = Depends(get_db)):
    hoy = datetime.now()
    if not mes:
        mes = hoy.month
    if not anio:
        anio = hoy.year
    
    sueldo_records = db.query(SueldoEmpleado).filter(
        SueldoEmpleado.mes == mes,
        SueldoEmpleado.anio == anio
    ).all()
    
    empleados = db.query(Empleado).filter(Empleado.activo == True).all()
    
    result = []
    for emp in empleados:
        sueldo = next((s for s in sueldo_records if s.empleado_id == emp.id), None)
        adelantos = db.query(AdelantoEmpleado).filter(
            AdelantoEmpleado.empleado_id == emp.id,
            AdelantoEmpleado.mes == mes,
            AdelantoEmpleado.anio == anio
        ).all()
        
        if sueldo:
            result.append({
                "empleado_id": emp.id,
                "nombre": emp.nombre,
                "monto_sueldo": sueldo.monto_sueldo,
                "total_adelantos": sueldo.total_adelantos,
                "saldo": sueldo.saldo,
                "pagado": sueldo.pagado,
                "adelantos": [{"id": a.id, "monto": a.monto, "descripcion": a.descripcion, "fecha": a.fecha.isoformat() if a.fecha else None} for a in adelantos]
            })
        else:
            result.append({
                "empleado_id": emp.id,
                "nombre": emp.nombre,
                "monto_sueldo": 0,
                "total_adelantos": 0,
                "saldo": 0,
                "pagado": False,
                "adelantos": []
            })
    
    return result


@router.post("/sueldos")
def guardar_sueldo(data: dict, db: Session = Depends(get_db)):
    hoy = datetime.now()
    empleado_id = data.get("empleado_id")
    mes = data.get("mes", hoy.month)
    anio = data.get("anio", hoy.year)
    monto_sueldo = data.get("monto_sueldo", 0)
    
    sueldo = db.query(SueldoEmpleado).filter(
        SueldoEmpleado.empleado_id == empleado_id,
        SueldoEmpleado.mes == mes,
        SueldoEmpleado.anio == anio
    ).first()
    
    adelantos_total = sum(a.monto for a in db.query(AdelantoEmpleado).filter(
        AdelantoEmpleado.empleado_id == empleado_id,
        AdelantoEmpleado.mes == mes,
        AdelantoEmpleado.anio == anio
    ).all())
    
    if sueldo:
        sueldo.monto_sueldo = monto_sueldo
        sueldo.total_adelantos = adelantos_total
        sueldo.saldo = monto_sueldo - adelantos_total
    else:
        sueldo = SueldoEmpleado(
            empleado_id=empleado_id,
            mes=mes,
            anio=anio,
            monto_sueldo=monto_sueldo,
            total_adelantos=adelantos_total,
            saldo=monto_sueldo - adelantos_total
        )
        db.add(sueldo)
    
    db.commit()
    return {"message": "Sueldo guardado"}


@router.post("/adelantos")
def agregar_adelanto(data: dict, db: Session = Depends(get_db)):
    hoy = datetime.now()
    empleado_id = data.get("empleado_id")
    monto = data.get("monto", 0)
    descripcion = data.get("descripcion", "")
    mes = data.get("mes", hoy.month)
    anio = data.get("anio", hoy.year)
    
    adelantos = AdelantoEmpleado(
        empleado_id=empleado_id,
        mes=mes,
        anio=anio,
        monto=monto,
        descripcion=descripcion
    )
    db.add(adelantos)
    
    sueldo = db.query(SueldoEmpleado).filter(
        SueldoEmpleado.empleado_id == empleado_id,
        SueldoEmpleado.mes == mes,
        SueldoEmpleado.anio == anio
    ).first()
    
    if sueldo:
        sueldo.total_adelantos += monto
        sueldo.saldo = sueldo.monto_sueldo - sueldo.total_adelantos
    else:
        sueldo = SueldoEmpleado(
            empleado_id=empleado_id,
            mes=mes,
            anio=anio,
            monto_sueldo=0,
            total_adelantos=monto,
            saldo=-monto
        )
        db.add(sueldo)
    
    db.commit()
    return {"message": "Adelanto registrado"}


@router.delete("/adelantos/{adelanto_id}")
def eliminar_adelanto(adelanto_id: int, db: Session = Depends(get_db)):
    adelantos = db.query(AdelantoEmpleado).filter(AdelantoEmpleado.id == adelanto_id).first()
    if not adelantos:
        raise HTTPException(status_code=404, detail="Adelanto no encontrado")
    
    sueldo = db.query(SueldoEmpleado).filter(
        SueldoEmpleado.empleado_id == adelantos.empleado_id,
        SueldoEmpleado.mes == adelantos.mes,
        SueldoEmpleado.anio == adelantos.anio
    ).first()
    
    if sueldo:
        sueldo.total_adelantos -= adelantos.monto
        sueldo.saldo = sueldo.monto_sueldo - sueldo.total_adelantos
    
    db.delete(adelantos)
    db.commit()
    return {"message": "Adelanto eliminado"}


@router.get("/historial/{empleado_id}")
def historial_empleado(empleado_id: int, db: Session = Depends(get_db)):
    sueldo_records = db.query(SueldoEmpleado).filter(
        SueldoEmpleado.empleado_id == empleado_id
    ).order_by(SueldoEmpleado.anio.desc(), SueldoEmpleado.mes.desc()).all()
    
    result = []
    for s in sueldo_records:
        adelantos = db.query(AdelantoEmpleado).filter(
            AdelantoEmpleado.empleado_id == empleado_id,
            AdelantoEmpleado.mes == s.mes,
            AdelantoEmpleado.anio == s.anio
        ).all()
        result.append({
            "mes": s.mes,
            "anio": s.anio,
            "monto_sueldo": s.monto_sueldo,
            "total_adelantos": s.total_adelantos,
            "saldo": s.saldo,
            "pagado": s.pagado,
            "adelantos": [{"id": a.id, "monto": a.monto, "descripcion": a.descripcion} for a in adelantos]
        })
    
    return result
