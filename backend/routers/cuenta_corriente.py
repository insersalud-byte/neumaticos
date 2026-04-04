from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from core.database import get_db
from models.models import Cliente, MovimientoCuenta

router = APIRouter(prefix="/api/v1/cuenta-corriente", tags=["cuenta-corriente"])


@router.get("/clientes")
def listar_clientes_cta_cte(solo_con_deuda: bool = True, db: Session = Depends(get_db)):
    q = db.query(Cliente)
    if solo_con_deuda:
        q = q.filter(Cliente.saldo_deudor > 0)
    clientes = q.order_by(Cliente.nombre).all()
    return {
        "data": [
            {
                "id": c.id,
                "nombre": c.nombre,
                "telefono": c.telefono or "",
                "saldo_deudor": c.saldo_deudor or 0,
            }
            for c in clientes
        ]
    }


@router.get("/{cliente_id}/movimientos")
def movimientos_cliente(cliente_id: int, db: Session = Depends(get_db)):
    cliente = db.query(Cliente).filter(Cliente.id == cliente_id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    movs = (
        db.query(MovimientoCuenta)
        .filter(MovimientoCuenta.cliente_id == cliente_id)
        .order_by(MovimientoCuenta.fecha.desc())
        .limit(100)
        .all()
    )

    return {
        "cliente": {
            "id": cliente.id,
            "nombre": cliente.nombre,
            "telefono": cliente.telefono or "",
            "saldo_deudor": cliente.saldo_deudor or 0,
        },
        "movimientos": [
            {
                "id": m.id,
                "tipo": m.tipo,
                "monto": m.monto,
                "descripcion": m.descripcion,
                "metodo_pago": m.metodo_pago or "",
                "fecha": m.fecha.isoformat() if m.fecha else None,
            }
            for m in movs
        ],
    }


@router.post("/pagar")
def registrar_pago(data: dict, db: Session = Depends(get_db)):
    cliente_id = data.get("cliente_id")
    monto = data.get("monto", 0)
    metodo = data.get("metodo_pago", "efectivo")
    observaciones = data.get("observaciones", "")

    if not cliente_id or monto <= 0:
        raise HTTPException(status_code=400, detail="Datos inválidos")

    cliente = db.query(Cliente).filter(Cliente.id == cliente_id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    # Registrar movimiento
    mov = MovimientoCuenta(
        cliente_id=cliente_id,
        tipo="pago",
        monto=monto,
        descripcion=observaciones or f"Pago {metodo}",
        metodo_pago=metodo,
    )
    db.add(mov)

    # Actualizar saldo
    cliente.saldo_deudor = max(0, (cliente.saldo_deudor or 0) - monto)
    db.commit()

    return {
        "message": "Pago registrado",
        "nuevo_saldo": cliente.saldo_deudor,
    }
