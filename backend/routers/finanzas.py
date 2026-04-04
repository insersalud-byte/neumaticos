from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from core.database import get_db
from models.models import CoeficienteFinanciacion

router = APIRouter(prefix="/api/v1/finanzas", tags=["finanzas"])


@router.get("/coeficientes/{unidad_id}")
def listar_coeficientes(unidad_id: int, db: Session = Depends(get_db)):
    coefs = db.query(CoeficienteFinanciacion).filter(
        CoeficienteFinanciacion.unidad_negocio_id == unidad_id
    ).all()
    return [
        {
            "id": c.id, "nombre": c.nombre, "proveedor": c.proveedor or "",
            "cuotas": c.cuotas, "coeficiente": c.coeficiente,
            "activo": c.activo if c.activo is not None else True,
            "unidad_negocio_id": c.unidad_negocio_id,
        }
        for c in coefs
    ]


@router.post("/coeficientes")
def crear_coeficiente(data: dict, db: Session = Depends(get_db)):
    c = CoeficienteFinanciacion(
        nombre=data.get("nombre") or f"{data.get('proveedor', '')} {data.get('cuotas', '')}c",
        proveedor=data.get("proveedor", ""),
        cuotas=data.get("cuotas", 1),
        coeficiente=data.get("coeficiente", 1.0),
        unidad_negocio_id=data.get("unidad_negocio_id", 28),
        activo=data.get("activo", True),
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return {"id": c.id, "message": "Plan creado"}


@router.put("/coeficientes/{coef_id}")
def editar_coeficiente(coef_id: int, data: dict, db: Session = Depends(get_db)):
    c = db.query(CoeficienteFinanciacion).filter(CoeficienteFinanciacion.id == coef_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Plan no encontrado")
    for key in ["nombre", "proveedor", "cuotas", "coeficiente", "activo"]:
        if key in data:
            setattr(c, key, data[key])
    db.commit()
    return {"message": "Plan actualizado"}


@router.delete("/coeficientes/{coef_id}")
def eliminar_coeficiente(coef_id: int, db: Session = Depends(get_db)):
    c = db.query(CoeficienteFinanciacion).filter(CoeficienteFinanciacion.id == coef_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Plan no encontrado")
    db.delete(c)
    db.commit()
    return {"message": "Plan eliminado"}


@router.patch("/coeficientes/{coef_id}/toggle")
def toggle_coeficiente(coef_id: int, db: Session = Depends(get_db)):
    c = db.query(CoeficienteFinanciacion).filter(CoeficienteFinanciacion.id == coef_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Plan no encontrado")
    c.activo = not c.activo
    db.commit()
    return {"message": "Estado cambiado", "activo": c.activo}
