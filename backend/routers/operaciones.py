import json
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_, func
from core.database import get_db
from core.auth import get_current_user
from models.models import (
    Venta, Producto, Servicio, Vehiculo, Cliente,
    CoeficienteFinanciacion, IngresoTaller, MovimientoCliente
)

router = APIRouter(prefix="/api/v1/operaciones", tags=["operaciones"])


@router.get("/dashboard/metricas")
def dashboard_metricas(
    fecha_desde: str = None,
    fecha_hasta: str = None,
    db: Session = Depends(get_db)
):
    from datetime import datetime, timedelta
    
    hoy = datetime.now().date()
    
    if fecha_desde:
        desde = datetime.strptime(fecha_desde, "%Y-%m-%d").date()
    else:
        desde = hoy - timedelta(days=30)
    
    if fecha_hasta:
        hasta = datetime.strptime(fecha_hasta, "%Y-%m-%d").date()
    else:
        hasta = hoy
    
    # Ventas en rango (solo ventas, no cotizaciones)
    ventas = db.query(Venta).filter(
        Venta.es_cotizacion == False,
        func.date(Venta.fecha_creacion) >= desde,
        func.date(Venta.fecha_creacion) <= hasta
    ).all()
    
    # Cotizaciones en rango
    cotizaciones = db.query(Venta).filter(
        Venta.es_cotizacion == True,
        func.date(Venta.fecha_creacion) >= desde,
        func.date(Venta.fecha_creacion) <= hasta
    ).all()
    
    # Compras en rango
    from models.models import CompraProveedor
    compras = db.query(CompraProveedor).filter(
        func.date(CompraProveedor.fecha) >= desde,
        func.date(CompraProveedor.fecha) <= hasta
    ).all()
    
    # Totales ventas
    total_ventas = sum(v.total_venta or 0 for v in ventas)
    costo_ventas = 0
    productos_vendidos = {}
    categorias_vendidas = {}
    
    for v in ventas:
        items = json.loads(v.items) if v.items else []
        for item in items:
            ref_id = item.get("referencia_id")
            desc = item.get("descripcion", "Sin nombre")
            cant = item.get("cantidad", 0)
            precio = item.get("precio_final", 0)
            tipo = item.get("tipo", "")
            
            productos_vendidos[desc] = productos_vendidos.get(desc, {"cantidad": 0, "monto": 0, "tipo": tipo})
            productos_vendidos[desc]["cantidad"] += cant
            productos_vendidos[desc]["monto"] += precio * cant
            
            if ref_id and str(ref_id).isdigit() and tipo == "producto":
                prod = db.query(Producto).filter(Producto.id == int(ref_id)).first()
                if prod:
                    costo_ventas += (prod.precio_costo or 0) * cant
                    cat = prod.categoria or "Servicios"
                    categorias_vendidas[cat] = categorias_vendidas.get(cat, 0) + precio * cant
            elif tipo == "servicio":
                cat = "Servicios"
                categorias_vendidas[cat] = categorias_vendidas.get(cat, 0) + precio * cant
            elif tipo == "libre":
                cat = "Items Varios"
                categorias_vendidas[cat] = categorias_vendidas.get(cat, 0) + precio * cant
    
    # Totales compras
    total_compras = sum(c.total or 0 for c in compras)
    
    # Ganancia bruta
    ganancia = total_ventas - costo_ventas
    
    # Ranking productos más vendidos (por cantidad)
    top_vendidos = sorted(productos_vendidos.items(), key=lambda x: x[1]["cantidad"], reverse=True)[:10]
    
    # Ranking productos más vendidos (por monto)
    top_monto = sorted(productos_vendidos.items(), key=lambda x: x[1]["monto"], reverse=True)[:10]
    
    # Compras más frecuentes (artículos más comprados)
    productos_comprados = {}
    for c in compras:
        items_c = json.loads(c.items) if c.items else []
        for item in items_c:
            desc = item.get("descripcion", "Sin nombre")
            cant = item.get("cantidad", 0)
            productos_comprados[desc] = productos_comprados.get(desc, 0) + cant
    
    top_comprados = sorted(productos_comprados.items(), key=lambda x: x[1], reverse=True)[:10]
    
    # Ventas por día
    ventas_por_dia = {}
    delta = (hasta - desde).days + 1
    for i in range(delta):
        dia = desde + timedelta(days=i)
        ventas_por_dia[dia.strftime("%Y-%m-%d")] = {"dia": dia.strftime("%d/%m"), "ventas": 0, "monto": 0}
    
    for v in ventas:
        if v.fecha_creacion:
            dia_key = v.fecha_creacion.strftime("%Y-%m-%d")
            if dia_key in ventas_por_dia:
                ventas_por_dia[dia_key]["ventas"] += 1
                ventas_por_dia[dia_key]["monto"] += v.total_venta or 0
    
    ventas_por_dia_lista = list(ventas_por_dia.values())
    
    # Clientes nuevos en rango
    clientes_nuevos = db.query(Cliente).filter(
        func.date(Cliente.fecha_creacion) >= desde,
        func.date(Cliente.fecha_creacion) <= hasta
    ).count()
    
    # Top clientes por compras
    clientes_compras = {}
    for v in ventas:
        nombre = v.cliente_nombre or "Anónimo"
        clientes_compras[nombre] = clientes_compras.get(nombre, 0) + (v.total_venta or 0)
    
    top_clientes = sorted(clientes_compras.items(), key=lambda x: x[1], reverse=True)[:5]
    
    # Métodos de pago
    metodos_pago = {}
    for v in ventas:
        metodo = v.metodo_pago or "No especificado"
        metodos_pago[metodo] = metodos_pago.get(metodo, 0) + (v.total_venta or 0)
    
    # Stock bajo
    stock_bajo = db.query(Producto).filter(
        Producto.stock_real != None,
        Producto.stock_real <= 5,
        Producto.activo == True
    ).count()
    
    # Deuda total
    deuda_total = sum(v.monto_debe or 0 for v in db.query(Venta).filter(Venta.monto_debe > 0).all())
    
    # Resumen mensual (si el rango es mayor a 7 días)
    resumen_mensual = []
    if delta > 7:
        meses = {}
        for v in ventas:
            if v.fecha_creacion:
                mes_key = v.fecha_creacion.strftime("%Y-%m")
                if mes_key not in meses:
                    meses[mes_key] = {"mes": mes_key, "ventas": 0, "monto": 0}
                meses[mes_key]["ventas"] += 1
                meses[mes_key]["monto"] += v.total_venta or 0
        resumen_mensual = sorted(meses.values(), key=lambda x: x["mes"])[:12]
    
    return {
        "periodo": {"desde": desde.isoformat(), "hasta": hasta.isoformat()},
        "ventas": {"cantidad": len(ventas), "total": total_ventas, "ticket_promedio": total_ventas / len(ventas) if ventas else 0, "cotizaciones": len(cotizaciones)},
        "compras": {"cantidad": len(compras), "total": total_compras},
        "ganancia": {"bruta": ganancia, "margen": (ganancia / total_ventas * 100) if total_ventas > 0 else 0},
        "stock_bajo": stock_bajo,
        "deuda_total": deuda_total,
        "clientes_nuevos": clientes_nuevos,
        "ventas_por_dia": ventas_por_dia_lista,
        "resumen_mensual": resumen_mensual,
        "top_vendidos": [{"nombre": p[0], "cantidad": p[1]["cantidad"], "monto": p[1]["monto"], "tipo": p[1].get("tipo", "producto")} for p in top_vendidos],
        "top_monto": [{"nombre": p[0], "cantidad": p[1]["cantidad"], "monto": p[1]["monto"], "tipo": p[1].get("tipo", "producto")} for p in top_monto],
        "top_comprados": [{"nombre": p[0], "cantidad": p[1]} for p in top_comprados],
        "categorias": [{"nombre": c[0], "monto": c[1]} for c in sorted(categorias_vendidas.items(), key=lambda x: x[1], reverse=True)],
        "top_clientes": [{"nombre": c[0], "monto": c[1]} for c in top_clientes],
        "metodos_pago": [{"metodo": m[0], "monto": m[1]} for m in sorted(metodos_pago.items(), key=lambda x: x[1], reverse=True)],
    }


@router.get("")
def listar_operaciones(db: Session = Depends(get_db)):
    ventas = db.query(Venta).order_by(Venta.fecha_creacion.desc()).limit(100).all()
    result = []
    for v in ventas:
        result.append({
            "id": v.id,
            "fecha_creacion": v.fecha_creacion.isoformat() if v.fecha_creacion else None,
            "cliente_nombre": v.cliente_nombre,
            "cliente_telefono": v.cliente_telefono,
            "vehiculo_patente": v.vehiculo_patente,
            "vehiculo_modelo": v.vehiculo_modelo,
            "es_cotizacion": v.es_cotizacion,
            "items": json.loads(v.items) if v.items else [],
            "total_venta": v.total_venta,
            "metodo_pago": v.metodo_pago,
            "monto_abonado": v.monto_abonado,
            "monto_debe": v.monto_debe,
        })
    return result



@router.get("/admin/inventario")
def buscar_inventario(query: str = "", limit: int = 50, page: int = 1,
                      unidad_negocio_id: int = 28, buscar: str = "",
                      db: Session = Depends(get_db)):
    search = query or buscar
    q = db.query(Producto).filter(Producto.activo == True)
    if search:
        terms = search.strip().split()
        for term in terms:
            pattern = f"%{term}%"
            q = q.filter(
                or_(
                    Producto.marca.ilike(pattern),
                    Producto.modelo.ilike(pattern),
                    Producto.descripcion.ilike(pattern),
                    Producto.medida.ilike(pattern),
                )
            )
    total = q.count()
    total_pages = max(1, (total + limit - 1) // limit)
    offset = (page - 1) * limit
    productos = q.offset(offset).limit(limit).all()
    return {
        "data": [
            {
                "id": p.id, "marca": p.marca, "modelo": p.modelo,
                "descripcion": p.descripcion, "medida": p.medida,
                "precio_costo": p.precio_costo, "costo_base": p.costo_base,
                "margen_ganancia": p.margen_ganancia,
                "precio_venta_final": p.precio_venta_final,
                "precio_venta_contado": p.precio_venta_contado or p.precio_venta_final,
                "precio_cuota_6": p.precio_cuota_6,
                "precio_cuota_12": p.precio_cuota_12,
                "stock_real": p.stock_real, "stock_local": p.stock_local,
                "precio_venta": p.precio_venta_final or p.precio_venta_contado,
                "stock": p.stock_real or p.stock_local,
            }
            for p in productos
        ],
        "total": total,
        "total_pages": total_pages,
        "page": page,
    }


@router.post("/admin/inventario")
def crear_producto(data: dict, db: Session = Depends(get_db)):
    p = Producto(
        marca=data.get("marca", ""),
        modelo=data.get("modelo", ""),
        descripcion=data.get("descripcion", ""),
        precio_costo=data.get("precio_costo", 0),
        precio_venta_final=data.get("precio_venta_final", 0),
        stock_real=data.get("stock_real", 0),
        activo=True,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return {"id": p.id, "message": "Producto creado"}


@router.put("/admin/inventario/{producto_id}")
def editar_producto(producto_id: int, data: dict, db: Session = Depends(get_db)):
    p = db.query(Producto).filter(Producto.id == producto_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    for key in ["marca", "modelo", "descripcion", "precio_costo", "precio_venta_final", "stock_real"]:
        if key in data:
            setattr(p, key, data[key])
    db.commit()
    return {"message": "Producto actualizado"}


@router.get("/servicios/buscar")
def buscar_servicios(q: str = "", termino: str = "", db: Session = Depends(get_db)):
    search = q or termino
    query = db.query(Servicio)
    if search:
        query = query.filter(Servicio.nombre.ilike(f"%{search}%"))
    servicios = query.all()
    return [
        {"id": s.id, "nombre": s.nombre, "descripcion": s.descripcion or "",
         "precio_sugerido": s.precio_sugerido or 0, "precio": s.precio_sugerido or 0}
        for s in servicios
    ]


@router.get("/servicios")
def listar_servicios(db: Session = Depends(get_db)):
    servicios = db.query(Servicio).all()
    return [
        {"id": s.id, "nombre": s.nombre, "descripcion": s.descripcion or "",
         "precio_sugerido": s.precio_sugerido or 0}
        for s in servicios
    ]


@router.post("/servicios")
def crear_servicio(data: dict, db: Session = Depends(get_db)):
    s = Servicio(
        nombre=data.get("nombre", ""),
        descripcion=data.get("descripcion", ""),
        precio_sugerido=data.get("precio_sugerido", 0),
        activo=True,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return {"id": s.id, "message": "Servicio creado"}


@router.put("/servicios/{servicio_id}")
def editar_servicio(servicio_id: int, data: dict, db: Session = Depends(get_db)):
    s = db.query(Servicio).filter(Servicio.id == servicio_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Servicio no encontrado")
    for key in ["nombre", "descripcion", "precio_sugerido"]:
        if key in data:
            setattr(s, key, data[key])
    db.commit()
    return {"message": "Servicio actualizado"}


@router.delete("/servicios/{servicio_id}")
def eliminar_servicio(servicio_id: int, db: Session = Depends(get_db)):
    s = db.query(Servicio).filter(Servicio.id == servicio_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Servicio no encontrado")
    db.delete(s)
    db.commit()
    return {"message": "Servicio eliminado"}


@router.post("/admin/inventario/crear-producto")
def crear_producto_nuevo(data: dict, db: Session = Depends(get_db)):
    costo = data.get("costo_base", 0)
    margen = data.get("margen_ganancia", 0)
    venta = data.get("precio_venta_contado", 0) or round(costo * (1 + margen / 100))
    ancho = data.get("ancho", "")
    perfil = data.get("perfil", "")
    rodado = data.get("rodado", "")
    medida = f"{ancho}/{perfil}R{rodado}" if ancho and perfil and rodado else ""

    p = Producto(
        marca=data.get("marca", ""),
        modelo=data.get("modelo", ""),
        descripcion=data.get("descripcion", ""),
        medida=medida,
        sku=data.get("sku", ""),
        tipo=data.get("tipo", "neumatico"),
        costo_base=costo,
        precio_costo=costo,
        margen_ganancia=margen,
        precio_venta_contado=venta,
        precio_venta_final=venta,
        stock_local=data.get("stock_local", 0),
        stock_real=data.get("stock_local", 0),
        activo=True,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return {"id": p.id, "message": "Producto creado"}


@router.put("/admin/producto/{producto_id}")
def editar_producto_por_id(producto_id: int, data: dict, db: Session = Depends(get_db)):
    p = db.query(Producto).filter(Producto.id == producto_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    for key in ["costo_base", "margen_ganancia", "stock_local", "precio_venta_contado"]:
        if key in data:
            setattr(p, key, data[key])
    if "costo_base" in data or "margen_ganancia" in data:
        costo = data.get("costo_base", p.costo_base) or 0
        margen = data.get("margen_ganancia", p.margen_ganancia) or 0
        precio = round(costo * (1 + margen / 100))
        p.precio_venta_contado = precio
        p.precio_venta_final = precio
        p.precio_costo = costo
    if "stock_local" in data:
        p.stock_real = data["stock_local"]
    db.commit()
    return {"message": "Producto actualizado"}


@router.get("/admin/finanzas/resumen")
def resumen_finanzas(db: Session = Depends(get_db)):
    from sqlalchemy import func as sqlfunc
    ventas = db.query(Venta).filter(Venta.es_cotizacion == False).all()
    total = sum(v.total_venta or 0 for v in ventas)
    taller_total = sum((v.total_venta or 0) for v in ventas if v.enviar_a_taller)
    web_total = total - taller_total
    count = len(ventas)
    ticket = total / count if count > 0 else 0
    return {
        "ingresos_total": total,
        "ingresos_web": web_total,
        "ingresos_taller": taller_total,
        "ticket_promedio": ticket,
        "operaciones_totales": count,
    }


@router.get("/vehiculos/buscar")
def buscar_vehiculo(q: str = "", patente: str = "", db: Session = Depends(get_db)):
    search = q or patente
    if not search:
        return []
    search = search.upper()
    
    resultados = []
    
    # Buscar en tabla de vehículos
    vehiculos = db.query(Vehiculo).filter(
        Vehiculo.patente.ilike(f"%{search}%")
    ).limit(10).all()
    for v in vehiculos:
        resultados.append({
            "id": v.id,
            "patente": v.patente,
            "modelo": v.modelo,
            "cliente_nombre": v.cliente_nombre or ""
        })
    
    # Buscar en ingresos del taller (para patentes ya registradas)
    ingresos = db.query(IngresoTaller).filter(
        IngresoTaller.vehiculo_patente.ilike(f"%{search}%")
    ).limit(10).all()
    for i in ingresos:
        existe = any(r["patente"] == i.vehiculo_patente for r in resultados)
        if not existe:
            resultados.append({
                "id": i.id,
                "patente": i.vehiculo_patente,
                "modelo": i.vehiculo_modelo,
                "cliente_nombre": i.cliente_nombre or ""
            })
    
    return resultados[:10]


@router.get("/cotizaciones/pendientes")
def cotizaciones_pendientes(db: Session = Depends(get_db)):
    cots = db.query(Venta).filter(Venta.es_cotizacion == True).order_by(Venta.fecha_creacion.desc()).limit(50).all()
    return [
        {
            "id": c.id,
            "fecha_creacion": c.fecha_creacion.isoformat() if c.fecha_creacion else None,
            "cliente_nombre": c.cliente_nombre,
            "cliente_telefono": c.cliente_telefono,
            "vehiculo_patente": c.vehiculo_patente,
            "vehiculo_modelo": c.vehiculo_modelo,
            "total_venta": c.total_venta,
            "items": json.loads(c.items) if c.items else [],
            "datos_cliente_snapshot": json.loads(c.datos_cliente_snapshot) if c.datos_cliente_snapshot else {},
        }
        for c in cots
    ]


@router.post("/cotizaciones/{cot_id}/convertir")
def convertir_cotizacion(cot_id: int, db: Session = Depends(get_db)):
    cot = db.query(Venta).filter(Venta.id == cot_id).first()
    if not cot:
        raise HTTPException(status_code=404, detail="Cotización no encontrada")
    cot.es_cotizacion = False
    cot.monto_abonado = cot.total_venta
    cot.monto_debe = 0
    db.commit()
    return {
        "message": "Venta confirmada",
        "venta_id": cot.id,
        "cliente_nombre": cot.cliente_nombre,
        "vehiculo_patente": cot.vehiculo_patente,
        "vehiculo_modelo": cot.vehiculo_modelo,
        "observaciones": cot.observaciones,
        "items": json.loads(cot.items) if cot.items else []
    }


@router.post("/venta-mostrador")
def venta_mostrador(data: dict, db: Session = Depends(get_db)):
    items = data.get("items", [])
    subtotal = sum((i.get("cantidad", 0) * i.get("precio_final", 0)) for i in items)
    bonificacion = data.get("monto_bonificacion", 0)
    base = max(0, subtotal - bonificacion)
    iva = data.get("alicuota_iva", 0)
    total = base * (1 + iva)

    coef_id = data.get("coeficiente_id")
    if coef_id:
        coef = db.query(CoeficienteFinanciacion).filter(CoeficienteFinanciacion.id == coef_id).first()
        if coef:
            total *= coef.coeficiente

    abonado = data.get("monto_abonado", 0)
    debe = max(0, total - abonado)

    # Buscar o crear cliente
    cliente_id = data.get("cliente_id")
    cliente_nombre = data.get("cliente_nombre", "").strip()
    cliente_telefono = data.get("cliente_telefono", "").strip()
    
    if not cliente_id:
        if cliente_nombre:
            # Buscar por nombre (case-insensitive)
            cliente = db.query(Cliente).filter(func.lower(Cliente.nombre) == func.lower(cliente_nombre)).first()
            if not cliente and cliente_telefono:
                # Buscar por teléfono
                cliente = db.query(Cliente).filter(Cliente.telefono == cliente_telefono).first()
            if not cliente:
                # Crear nuevo cliente
                cliente = Cliente(nombre=cliente_nombre, telefono=cliente_telefono, activo=True)
                db.add(cliente)
                db.flush()
            else:
                # Actualizar datos existentes
                if cliente_nombre and cliente.nombre != cliente_nombre:
                    cliente.nombre = cliente_nombre
                if cliente_telefono:
                    cliente.telefono = cliente_telefono
                cliente.activo = True
            cliente_id = cliente.id
        elif cliente_telefono:
            # Solo teléfono, buscar o crear
            cliente = db.query(Cliente).filter(Cliente.telefono == cliente_telefono).first()
            if not cliente:
                cliente = Cliente(nombre="Cliente", telefono=cliente_telefono, activo=True)
                db.add(cliente)
                db.flush()
            cliente_id = cliente.id

    # Buscar o crear vehículo
    vehiculo_id = data.get("vehiculo_id")
    patente = data.get("patente", "").strip().upper()
    modelo = data.get("modelo_vehiculo", "").strip()
    
    if not vehiculo_id and patente:
        vehiculo = db.query(Vehiculo).filter(Vehiculo.patente == patente).first()
        if not vehiculo:
            vehiculo = Vehiculo(
                patente=patente,
                modelo=modelo,
                cliente_id=cliente_id,
                activo=True
            )
            db.add(vehiculo)
            db.flush()
        else:
            # Actualizar datos del vehículo
            if modelo:
                vehiculo.modelo = modelo
            if cliente_id:
                vehiculo.cliente_id = cliente_id
            vehiculo.activo = True
        vehiculo_id = vehiculo.id

    # Si es update de cotización existente
    cot_original_id = data.get("cotizacion_original_id")
    if cot_original_id:
        venta = db.query(Venta).filter(Venta.id == cot_original_id).first()
        if venta:
            venta.cliente_id = cliente_id
            venta.cliente_nombre = cliente_nombre
            venta.cliente_telefono = cliente_telefono
            venta.vehiculo_patente = patente
            venta.vehiculo_modelo = data.get("modelo_vehiculo", "")
            venta.vehiculo_id = vehiculo_id
            venta.kilometraje = data.get("kilometraje", 0)
            venta.es_cotizacion = data.get("es_cotizacion", False)
            venta.items = json.dumps(items)
            venta.subtotal_neto = subtotal
            venta.monto_bonificacion = bonificacion
            venta.alicuota_iva = iva
            venta.total_venta = total
            venta.metodo_pago = data.get("metodo_pago", "Efectivo")
            venta.coeficiente_id = coef_id
            venta.monto_abonado = abonado
            venta.monto_debe = debe
            venta.enviar_a_taller = data.get("enviar_a_taller", False)
            venta.observaciones = data.get("observaciones", "")
            venta.datos_cliente_snapshot = json.dumps({"nombre": cliente_nombre, "telefono": cliente_telefono})
            db.commit()
            return {"venta_id": venta.id, "cliente_id": cliente_id, "vehiculo_id": vehiculo_id}

    snapshot = json.dumps({"nombre": cliente_nombre, "telefono": cliente_telefono})
    venta = Venta(
        cliente_id=cliente_id,
        cliente_nombre=cliente_nombre,
        cliente_telefono=cliente_telefono,
        vehiculo_patente=patente,
        vehiculo_modelo=data.get("modelo_vehiculo", ""),
        vehiculo_id=vehiculo_id,
        kilometraje=data.get("kilometraje", 0),
        es_cotizacion=data.get("es_cotizacion", False),
        cotizacion_original_id=cot_original_id,
        items=json.dumps(items),
        subtotal_neto=subtotal,
        monto_bonificacion=bonificacion,
        alicuota_iva=iva,
        total_venta=total,
        metodo_pago=data.get("metodo_pago", "Efectivo"),
        coeficiente_id=coef_id,
        monto_abonado=abonado,
        monto_debe=debe,
        enviar_a_taller=data.get("enviar_a_taller", False),
        observaciones=data.get("observaciones", ""),
        datos_cliente_snapshot=snapshot,
    )
    db.add(venta)
    db.flush()

    # Descontar stock solo si NO es cotización
    es_cotizacion = data.get("es_cotizacion", False)
    if not es_cotizacion:
        for item in items:
            producto_id = item.get("producto_id")
            cantidad = item.get("cantidad", 0)
            if producto_id and cantidad > 0:
                producto = db.query(Producto).filter(Producto.id == producto_id).first()
                if producto:
                    producto.stock_real = max(0, (producto.stock_real or 0) - cantidad)

    # Extraer metodo_pago para uso posterior
    metodo_pago = data.get("metodo_pago", "Efectivo")

    # Enviar a taller si corresponde
    if data.get("enviar_a_taller"):
        ingreso = IngresoTaller(
            vehiculo_modelo=data.get("modelo_vehiculo", ""),
            vehiculo_patente=patente,
            cliente_nombre=cliente_nombre,
            estado="ADENTRO",
            venta_ref_id=venta.id,
        )
        db.add(ingreso)

    db.commit()
    
    # Registrar en cuenta corriente si es a crédito
    if debe > 0 and cliente_id and metodo_pago == "cuenta_corriente":
        cliente = db.query(Cliente).filter(Cliente.id == cliente_id).first()
        if cliente:
            cliente.saldo_deudor = (cliente.saldo_deudor or 0) + debe
            mov = MovimientoCliente(
                cliente_id=cliente_id,
                tipo="credito",
                monto=debe,
                descripcion=f"Venta #{venta.id} - Saldo pendiente",
                metodo_pago=metodo_pago,
                venta_id=venta.id,
            )
            db.add(mov)
            db.commit()
    
    return {"venta_id": venta.id, "cliente_id": cliente_id, "vehiculo_id": vehiculo_id}


@router.post("")
def crear_operacion(data: dict, db: Session = Depends(get_db)):
    """Crear cotización / venta desde el POS (POST /api/v1/operaciones)"""
    items = data.get("items", [])
    if isinstance(items, str):
        items = json.loads(items) if items else []
    subtotal = sum((i.get("cantidad", 0) * i.get("precio_final", 0)) for i in items)
    bonificacion = data.get("monto_bonificacion", 0)
    base = max(0, subtotal - bonificacion)
    iva = data.get("alicuota_iva", 0)
    total = base * (1 + iva)

    coef_id = data.get("coeficiente_id")
    if coef_id:
        coef = db.query(CoeficienteFinanciacion).filter(CoeficienteFinanciacion.id == coef_id).first()
        if coef:
            total *= coef.coeficiente

    abonado = data.get("monto_abonado", 0)
    debe = max(0, total - abonado)

    cliente_id = data.get("cliente_id")
    cliente_nombre = data.get("cliente_nombre", "").strip()
    cliente_telefono = data.get("cliente_telefono", "").strip()
    
    if not cliente_id:
        if cliente_nombre:
            cliente = db.query(Cliente).filter(func.lower(Cliente.nombre) == func.lower(cliente_nombre)).first()
            if not cliente and cliente_telefono:
                cliente = db.query(Cliente).filter(Cliente.telefono == cliente_telefono).first()
            if not cliente:
                cliente = Cliente(nombre=cliente_nombre, telefono=cliente_telefono, activo=True)
                db.add(cliente)
                db.flush()
            else:
                if cliente_nombre and cliente.nombre != cliente_nombre:
                    cliente.nombre = cliente_nombre
                if cliente_telefono:
                    cliente.telefono = cliente_telefono
                cliente.activo = True
            cliente_id = cliente.id
        elif cliente_telefono:
            cliente = db.query(Cliente).filter(Cliente.telefono == cliente_telefono).first()
            if not cliente:
                cliente = Cliente(nombre="Cliente", telefono=cliente_telefono, activo=True)
                db.add(cliente)
                db.flush()
            cliente_id = cliente.id

    vehiculo_id = data.get("vehiculo_id")
    patente = data.get("patente", "").strip().upper()
    modelo = data.get("modelo_vehiculo", "").strip()
    
    if not vehiculo_id and patente:
        vehiculo = db.query(Vehiculo).filter(Vehiculo.patente == patente).first()
        if not vehiculo:
            vehiculo = Vehiculo(patente=patente, modelo=modelo, cliente_id=cliente_id, activo=True)
            db.add(vehiculo)
            db.flush()
        else:
            if modelo:
                vehiculo.modelo = modelo
            if cliente_id:
                vehiculo.cliente_id = cliente_id
            vehiculo.activo = True
        vehiculo_id = vehiculo.id

    snapshot = json.dumps({"nombre": cliente_nombre, "telefono": cliente_telefono})
    venta = Venta(
        cliente_id=cliente_id,
        cliente_nombre=cliente_nombre,
        cliente_telefono=cliente_telefono,
        vehiculo_patente=patente,
        vehiculo_modelo=data.get("modelo_vehiculo", ""),
        vehiculo_id=vehiculo_id,
        kilometraje=data.get("kilometraje", 0),
        es_cotizacion=data.get("es_cotizacion", True),
        items=json.dumps(items),
        subtotal_neto=subtotal,
        monto_bonificacion=bonificacion,
        alicuota_iva=iva,
        total_venta=total,
        metodo_pago=data.get("metodo_pago", "Efectivo"),
        coeficiente_id=coef_id,
        monto_abonado=abonado,
        monto_debe=debe,
        enviar_a_taller=data.get("enviar_a_taller", False),
        observaciones=data.get("observaciones", ""),
        datos_cliente_snapshot=snapshot,
    )
    db.add(venta)
    db.commit()
    db.refresh(venta)
    
    # Registrar en cuenta corriente si es a crédito
    metodo_pago = data.get("metodo_pago", "Efectivo")
    if debe > 0 and cliente_id and metodo_pago == "cuenta_corriente":
        cliente = db.query(Cliente).filter(Cliente.id == cliente_id).first()
        if cliente:
            cliente.saldo_deudor = (cliente.saldo_deudor or 0) + debe
            mov = MovimientoCliente(
                cliente_id=cliente_id,
                tipo="credito",
                monto=debe,
                descripcion=f"Venta #{venta.id} - Saldo pendiente",
                metodo_pago=metodo_pago,
                venta_id=venta.id,
            )
            db.add(mov)
            db.commit()
    
    return {"venta_id": venta.id, "message": "Operación creada"}


@router.delete("/{venta_id}")
def eliminar_venta(venta_id: int, db: Session = Depends(get_db)):
    """Eliminar venta/cotización y revertir stock si corresponde"""
    venta = db.query(Venta).filter(Venta.id == venta_id).first()
    if not venta:
        raise HTTPException(status_code=404, detail="Venta no encontrada")
    
    es_cotizacion_original = venta.es_cotizacion
    
    if not es_cotizacion_original:
        items = json.loads(venta.items) if venta.items else []
        for item in items:
            producto_id = item.get("producto_id")
            cantidad = item.get("cantidad", 0)
            if producto_id and cantidad > 0:
                producto = db.query(Producto).filter(Producto.id == producto_id).first()
                if producto:
                    producto.stock_real = (producto.stock_real or 0) + cantidad
    
    db.delete(venta)
    db.commit()
    return {"message": "Venta eliminada"}


@router.get("/{venta_id}")
def obtener_venta(venta_id: int, db: Session = Depends(get_db)):
    venta = db.query(Venta).filter(Venta.id == venta_id).first()
    if not venta:
        raise HTTPException(status_code=404, detail="Operación no encontrada")
    return {
        "id": venta.id,
        "fecha_creacion": venta.fecha_creacion.isoformat() if venta.fecha_creacion else None,
        "cliente_nombre": venta.cliente_nombre,
        "cliente_telefono": venta.cliente_telefono,
        "vehiculo_patente": venta.vehiculo_patente,
        "vehiculo_modelo": venta.vehiculo_modelo,
        "es_cotizacion": venta.es_cotizacion,
        "items": json.loads(venta.items) if venta.items else [],
        "total_venta": venta.total_venta,
        "metodo_pago": venta.metodo_pago,
        "monto_abonado": venta.monto_abonado,
        "monto_debe": venta.monto_debe,
        "observaciones": venta.observaciones,
        "enviar_a_taller": venta.enviar_a_taller,
    }

