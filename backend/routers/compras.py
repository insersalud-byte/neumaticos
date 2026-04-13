from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from core.database import get_db
from models.models import Proveedor, CompraProveedor, MovimientoProveedor, Producto
import os
import sys
import tempfile
import json

router = APIRouter(prefix="/api/v1/compras", tags=["compras"])

def get_base_path():
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        internal_dir = os.path.join(exe_dir, '_internal')
        if os.path.isdir(internal_dir):
            return internal_dir
        return exe_dir
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if os.environ.get("VERCEL") == "1":
    UPLOAD_DIR = "/tmp/uploads"
else:
    UPLOAD_DIR = os.path.join(get_base_path(), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


# ── PROVEEDORES ──────────────────────────────────────────────

@router.get("/proveedores")
def listar_proveedores(solo_con_deuda: bool = False, db: Session = Depends(get_db)):
    q = db.query(Proveedor).filter(Proveedor.activo == True)
    if solo_con_deuda:
        q = q.filter(Proveedor.saldo_deudor > 0)
    proveedores = q.order_by(Proveedor.nombre).all()
    return {
        "data": [
            {
                "id": p.id,
                "nombre": p.nombre,
                "telefono": p.telefono or "",
                "email": p.email or "",
                "cuit": p.cuit or "",
                "direccion": p.direccion or "",
                "saldo_deudor": p.saldo_deudor or 0,
            }
            for p in proveedores
        ]
    }


@router.post("/proveedores")
def crear_proveedor(data: dict, db: Session = Depends(get_db)):
    p = Proveedor(
        nombre=data.get("nombre", ""),
        telefono=data.get("telefono", ""),
        email=data.get("email", ""),
        cuit=data.get("cuit", ""),
        direccion=data.get("direccion", ""),
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return {"id": p.id, "message": "Proveedor creado"}


@router.put("/proveedores/{prov_id}")
def editar_proveedor(prov_id: int, data: dict, db: Session = Depends(get_db)):
    p = db.query(Proveedor).filter(Proveedor.id == prov_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Proveedor no encontrado")
    for key in ["nombre", "telefono", "email", "cuit", "direccion"]:
        if key in data:
            setattr(p, key, data[key])
    db.commit()
    return {"message": "Proveedor actualizado"}


@router.post("/importar-proveedores-lote")
def importar_proveedores_lote(data: dict, db: Session = Depends(get_db)):
    """Lee proveedores.xlsx del servidor en lotes para evitar timeout."""
    import openpyxl, re

    offset = int(data.get("offset", 0))
    limit = int(data.get("limit", 50))

    base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    posibles = [
        os.path.join(base, "frontend", "admin", "catalogos", "proveedores.xlsx"),
        os.path.join(base, "proveedores.xlsx"),
    ]
    ruta = next((p for p in posibles if os.path.exists(p)), None)
    if not ruta:
        raise HTTPException(status_code=404, detail="proveedores.xlsx no encontrado")

    wb = openpyxl.load_workbook(ruta, read_only=True, data_only=True)
    ws = wb.active
    all_rows = list(ws.iter_rows(values_only=True))
    wb.close()

    total = len(all_rows) - 1  # sin header
    lote = all_rows[1 + offset: 1 + offset + limit]

    creados = 0
    actualizados = 0

    for row in lote:
        cuit_raw = str(row[0] or "").strip()
        nombre = str(row[1] or "").strip()
        correo = str(row[2] or "").strip()
        tel_raw = str(row[3] or "").strip()
        contacto1 = str(row[4] or "").strip() if len(row) > 4 else ""
        contacto2 = str(row[5] or "").strip() if len(row) > 5 else ""

        if not nombre or nombre == "None":
            continue

        # Limpiar CUIT: solo dígitos
        cuit = re.sub(r"\D", "", cuit_raw)[:11] if cuit_raw and cuit_raw != "None" else ""
        # Limpiar teléfono
        telefono = re.sub(r"\D", "", tel_raw)[:15] if tel_raw and tel_raw != "None" else ""
        email = correo if correo and "@" in correo else ""
        # Contacto secundario como observación adicional
        obs = " / ".join(filter(None, [contacto1, contacto2]))

        # Upsert por CUIT primero, luego por nombre
        existente = None
        if cuit:
            existente = db.query(Proveedor).filter(Proveedor.cuit == cuit).first()
        if not existente:
            from sqlalchemy import text as _text
            existente = db.query(Proveedor).filter(
                _text("LOWER(nombre) = LOWER(:n)")
            ).params(n=nombre).first()

        if existente:
            if cuit: existente.cuit = cuit
            if telefono: existente.telefono = telefono
            if email: existente.email = email
            actualizados += 1
        else:
            db.add(Proveedor(
                nombre=nombre,
                cuit=cuit,
                telefono=telefono,
                email=email,
                direccion=obs,
                activo=True,
            ))
            creados += 1

    db.commit()
    return {"ok": True, "creados": creados, "actualizados": actualizados,
            "total": total, "procesados": offset + len(lote), "fin": offset + len(lote) >= total}


# ── COMPRAS MANUALES ─────────────────────────────────────────

@router.post("/registrar")
def registrar_compra(data: dict, db: Session = Depends(get_db)):
    """Carga manual de compra a proveedor"""
    import json

    proveedor_id = data.get("proveedor_id")
    proveedor_nombre = data.get("proveedor_nombre", "")
    metodo_pago = data.get("metodo_pago", "efectivo")
    items = data.get("items", [])
    total = data.get("total", 0)
    numero_factura = data.get("numero_factura", "")
    observaciones = data.get("observaciones", "")

    # Buscar o crear proveedor
    if not proveedor_id and proveedor_nombre:
        prov = db.query(Proveedor).filter(Proveedor.nombre == proveedor_nombre).first()
        if not prov:
            prov = Proveedor(nombre=proveedor_nombre)
            db.add(prov)
            db.flush()
        proveedor_id = prov.id
    elif proveedor_id:
        prov = db.query(Proveedor).filter(Proveedor.id == proveedor_id).first()
        if not prov:
            raise HTTPException(status_code=404, detail="Proveedor no encontrado")
    else:
        raise HTTPException(status_code=400, detail="Debe indicar proveedor")

    # Calcular total si no viene
    if not total and items:
        total = sum((it.get("cantidad", 1) * it.get("costo_unitario", 0)) for it in items)

    # Crear compra
    compra = CompraProveedor(
        proveedor_id=proveedor_id,
        descripcion=data.get("descripcion", ""),
        numero_factura=numero_factura,
        items=json.dumps(items),
        total=total,
        metodo_pago=metodo_pago,
        pagado=total if metodo_pago != "cuenta_corriente" else 0,
        observaciones=observaciones,
    )
    db.add(compra)
    db.flush()

    # Registrar movimiento cargo
    mov = MovimientoProveedor(
        proveedor_id=proveedor_id,
        tipo="cargo",
        monto=total,
        descripcion=f"Compra #{compra.id} - {numero_factura or 'S/F'}",
        metodo_pago=metodo_pago,
        compra_id=compra.id,
    )
    db.add(mov)

    # Si es cuenta corriente, aumentar saldo deudor
    if metodo_pago == "cuenta_corriente":
        prov.saldo_deudor = (prov.saldo_deudor or 0) + total
    else:
        # Si paga en efectivo/cheque, registrar pago automático
        mov_pago = MovimientoProveedor(
            proveedor_id=proveedor_id,
            tipo="pago",
            monto=total,
            descripcion=f"Pago compra #{compra.id} ({metodo_pago})",
            metodo_pago=metodo_pago,
            numero_cheque=data.get("numero_cheque", ""),
            compra_id=compra.id,
        )
        db.add(mov_pago)

    # Actualizar stock de productos si se identifican
    for it in items:
        cant = it.get("cantidad", 1)
        costo = it.get("costo_unitario", 0)
        desc = it.get("descripcion", "")
        # Intentar encontrar producto por descripción
        if desc:
            producto = db.query(Producto).filter(
                Producto.descripcion.ilike(f"%{desc}%")
            ).first()
            if producto:
                producto.stock_real = (producto.stock_real or 0) + cant
                producto.stock_local = (producto.stock_local or 0) + cant
                if costo > 0:
                    producto.precio_costo = costo
                    producto.costo_base = costo

    db.commit()
    return {
        "compra_id": compra.id,
        "proveedor_id": proveedor_id,
        "total": total,
        "metodo_pago": metodo_pago,
        "message": "Compra registrada",
    }


@router.get("/historial")
def historial_compras(proveedor_id: int = 0, limit: int = 50, db: Session = Depends(get_db)):
    import json
    q = db.query(CompraProveedor)
    if proveedor_id:
        q = q.filter(CompraProveedor.proveedor_id == proveedor_id)
    compras = q.order_by(CompraProveedor.fecha.desc()).limit(limit).all()

    result = []
    for c in compras:
        prov = db.query(Proveedor).filter(Proveedor.id == c.proveedor_id).first()
        result.append({
            "id": c.id,
            "proveedor_id": c.proveedor_id,
            "proveedor_nombre": prov.nombre if prov else "",
            "fecha": c.fecha.isoformat() if c.fecha else None,
            "descripcion": c.descripcion,
            "numero_factura": c.numero_factura,
            "items": json.loads(c.items) if c.items else [],
            "total": c.total,
            "metodo_pago": c.metodo_pago,
            "pagado": c.pagado,
            "pendiente": max(0, (c.total or 0) - (c.pagado or 0)),
            "observaciones": c.observaciones,
        })
    return {"data": result}


# ── CUENTA CORRIENTE PROVEEDORES ─────────────────────────────

@router.get("/proveedores/{prov_id}/movimientos")
def movimientos_proveedor(prov_id: int, db: Session = Depends(get_db)):
    prov = db.query(Proveedor).filter(Proveedor.id == prov_id).first()
    if not prov:
        raise HTTPException(status_code=404, detail="Proveedor no encontrado")

    movs = (
        db.query(MovimientoProveedor)
        .filter(MovimientoProveedor.proveedor_id == prov_id)
        .order_by(MovimientoProveedor.fecha.desc())
        .limit(100)
        .all()
    )

    return {
        "proveedor": {
            "id": prov.id,
            "nombre": prov.nombre,
            "telefono": prov.telefono or "",
            "cuit": prov.cuit or "",
            "saldo_deudor": prov.saldo_deudor or 0,
        },
        "movimientos": [
            {
                "id": m.id,
                "tipo": m.tipo,
                "monto": m.monto,
                "descripcion": m.descripcion,
                "metodo_pago": m.metodo_pago or "",
                "numero_cheque": m.numero_cheque or "",
                "fecha": m.fecha.isoformat() if m.fecha else None,
                "compra_id": m.compra_id,
            }
            for m in movs
        ],
    }


@router.post("/proveedores/{prov_id}/pagar")
def pagar_proveedor(prov_id: int, data: dict, db: Session = Depends(get_db)):
    """Pago parcial o total a proveedor"""
    prov = db.query(Proveedor).filter(Proveedor.id == prov_id).first()
    if not prov:
        raise HTTPException(status_code=404, detail="Proveedor no encontrado")

    monto = data.get("monto", 0)
    metodo = data.get("metodo_pago", "efectivo")
    observaciones = data.get("observaciones", "")
    numero_cheque = data.get("numero_cheque", "")

    if monto <= 0:
        raise HTTPException(status_code=400, detail="Monto inválido")

    # Registrar movimiento pago
    mov = MovimientoProveedor(
        proveedor_id=prov_id,
        tipo="pago",
        monto=monto,
        descripcion=observaciones or f"Pago {metodo}",
        metodo_pago=metodo,
        numero_cheque=numero_cheque,
    )
    db.add(mov)

    # Actualizar saldo
    prov.saldo_deudor = max(0, (prov.saldo_deudor or 0) - monto)

    # Actualizar compras pendientes (distribuir pago)
    compras_pendientes = (
        db.query(CompraProveedor)
        .filter(
            CompraProveedor.proveedor_id == prov_id,
            CompraProveedor.metodo_pago == "cuenta_corriente",
        )
        .all()
    )
    restante = monto
    for c in compras_pendientes:
        pendiente = max(0, (c.total or 0) - (c.pagado or 0))
        if pendiente > 0 and restante > 0:
            abono = min(pendiente, restante)
            c.pagado = (c.pagado or 0) + abono
            restante -= abono

    db.commit()
    return {
        "message": "Pago registrado",
        "nuevo_saldo": prov.saldo_deudor,
    }


@router.get("/proveedores/{prov_id}/facturas-impagas")
def facturas_impagas_proveedor(prov_id: int, db: Session = Depends(get_db)):
    import json as _json
    prov = db.query(Proveedor).filter(Proveedor.id == prov_id).first()
    if not prov:
        raise HTTPException(status_code=404, detail="Proveedor no encontrado")

    compras = (
        db.query(CompraProveedor)
        .filter(CompraProveedor.proveedor_id == prov_id)
        .order_by(CompraProveedor.fecha.desc())
        .all()
    )
    impagas = []
    for c in compras:
        pendiente = max(0, (c.total or 0) - (c.pagado or 0))
        if pendiente > 0:
            impagas.append({
                "id": c.id,
                "fecha": c.fecha.isoformat() if c.fecha else None,
                "numero_factura": c.numero_factura or f"Compra #{c.id}",
                "total": c.total,
                "pagado": c.pagado,
                "pendiente": pendiente,
                "metodo_pago": c.metodo_pago,
            })
    return {
        "proveedor": {"id": prov.id, "nombre": prov.nombre, "saldo_deudor": prov.saldo_deudor or 0},
        "facturas_impagas": impagas,
        "total_impago": sum(f["pendiente"] for f in impagas),
    }


# ── IMPORTAR FACTURA PDF CON IA ──────────────────────────────

@router.post("/importar-factura")
async def importar_factura(
    file: UploadFile = File(...),
    proveedor_id: int = None,
    db: Session = Depends(get_db)
):
    """Importa factura PDF y procesa automáticamente"""
    from core.factura_ia import extraer_texto_pdf, parsear_factura_ia
    
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Solo se permiten archivos PDF")
    
    with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name
    
    try:
        texto = extraer_texto_pdf(tmp_path)
        if not texto.strip():
            return JSONResponse(
                status_code=422,
                content={"error": "No se pudo extraer texto del PDF"}
            )
        
        datos = parsear_factura_ia(texto)
        
        proveedor_nombre = datos.get("proveedor", "")
        if not proveedor_nombre:
            return JSONResponse(
                status_code=422,
                content={"error": "No se pudo identificar el proveedor"}
            )
        
        if not proveedor_id:
            prov = db.query(Proveedor).filter(
                Proveedor.nombre.ilike(f"%{proveedor_nombre}%")
            ).first()
            if not prov:
                prov = Proveedor(nombre=proveedor_nombre)
                db.add(prov)
                db.flush()
            proveedor_id = prov.id
        else:
            prov = db.query(Proveedor).filter(Proveedor.id == proveedor_id).first()
        
        items = datos.get("items", [])
        total = datos.get("total", 0)
        if not total and items:
            total = sum(it.get("cantidad", 1) * it.get("costo_unitario", 0) for it in items)
        
        metodo = datos.get("metodo_pago", "efectivo")
        
        compra = CompraProveedor(
            proveedor_id=proveedor_id,
            descripcion=f"Importado de PDF - {datos.get('numero_factura', '')}",
            numero_factura=datos.get("numero_factura", ""),
            items=json.dumps(items),
            total=total,
            metodo_pago=metodo,
            pagado=total if metodo != "cuenta_corriente" else 0,
            observaciones=f"Importado automáticamente el {datos.get('fecha', '')}"
        )
        db.add(compra)
        db.flush()
        
        mov = MovimientoProveedor(
            proveedor_id=proveedor_id,
            tipo="cargo",
            monto=total,
            descripcion=f"Compra #{compra.id} - {datos.get('numero_factura', 'S/F')}",
            metodo_pago=metodo,
            compra_id=compra.id,
        )
        db.add(mov)
        
        if metodo == "cuenta_corriente":
            prov.saldo_deudor = (prov.saldo_deudor or 0) + total
        
        actualizados = 0
        for it in items:
            cant = it.get("cantidad", 1)
            costo = it.get("costo_unitario", 0)
            desc = it.get("descripcion", "")
            
            if desc and costo > 0:
                producto = db.query(Producto).filter(
                    Producto.descripcion.ilike(f"%{desc}%")
                ).first()
                
                if producto:
                    producto.stock_real = (producto.stock_real or 0) + cant
                    producto.stock_local = (producto.stock_local or 0) + cant
                    producto.precio_costo = costo
                    producto.costo_base = costo
                    producto.precio_venta_contado = costo
                    producto.precio_venta_final = costo
                    actualizados += 1
        
        db.commit()
        
        return {
            "success": True,
            "compra_id": compra.id,
            "proveedor_id": proveedor_id,
            "proveedor_nombre": prov.nombre,
            "numero_factura": datos.get("numero_factura", ""),
            "total": total,
            "items_encontrados": len(items),
            "items_actualizados_stock": actualizados,
            "metodo_pago": metodo,
            "datos_extraidos": datos,
            "message": f"Factura importada. {actualizados} productos actualizados en stock."
        }
        
    except Exception as e:
        db.rollback()
        return JSONResponse(
            status_code=500,
            content={"error": f"Error procesando factura: {str(e)}"}
        )
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


@router.post("/importar-factura-validar")
async def validar_factura(
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """Solo extrae datos del PDF sin guardar"""
    from core.factura_ia import extraer_texto_pdf, parsear_factura_ia
    
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Solo se permiten archivos PDF")
    
    with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name
    
    try:
        texto = extraer_texto_pdf(tmp_path)
        datos = parsear_factura_ia(texto)
        
        proveedores = db.query(Proveedor).filter(Proveedor.activo == True).all()
        proveedores_match = [
            p for p in proveedores 
            if datos.get("proveedor", "").upper() in p.nombre.upper() or p.nombre.upper() in datos.get("proveedor", "").upper()
        ]
        
        return {
            "success": True,
            "datos": datos,
            "proveedores_match": [{"id": p.id, "nombre": p.nombre} for p in proveedores_match],
            "texto_preview": texto[:500] + "..." if len(texto) > 500 else texto
        }
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
