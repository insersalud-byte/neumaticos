from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from core.database import get_db
from models.models import Producto, Categoria

router = APIRouter(prefix="/api/v1/articulos", tags=["articulos"])

# ── RUTAS ESPECÍFICAS (antes de las con parámetros) ──

@router.get("")
def listar_articulos(
    buscar: str = "",
    categoria: str = "",
    db: Session = Depends(get_db)
):
    q = db.query(Producto).filter(Producto.activo == True)
    
    if buscar:
        terms = buscar.strip().split()
        for term in terms:
            pattern = f"%{term}%"
            q = q.filter(
                (Producto.descripcion.ilike(pattern)) |
                (Producto.marca.ilike(pattern)) |
                (Producto.codigo.ilike(pattern))
            )
    
    if categoria:
        q = q.filter(Producto.categoria == categoria)
    
    articulos = q.order_by(Producto.descripcion).all()
    
    return {
        "data": [
            {
                "id": a.id,
                "codigo": a.codigo or "",
                "descripcion": a.descripcion,
                "marca": a.marca or "",
                "categoria": a.categoria or "",
                "precio_costo": a.precio_costo or 0,
                "precio_venta": a.precio_venta_final or 0,
                "stock_real": a.stock_real or 0,
                "stock_local": a.stock_local or 0,
                "activo": a.activo,
            }
            for a in articulos
        ]
    }


@router.post("")
def crear_articulo(data: dict, db: Session = Depends(get_db)):
    precio_costo = data.get("precio_costo", 0)
    precio_venta = data.get("precio_venta", 0)
    
    a = Producto(
        codigo=data.get("codigo", ""),
        descripcion=data.get("descripcion", ""),
        marca=data.get("marca", ""),
        categoria=data.get("categoria", ""),
        proveedor=data.get("proveedor", ""),
        precio_costo=precio_costo,
        precio_venta_contado=precio_venta,
        precio_venta_final=precio_venta,
        costo_base=precio_costo,
        stock_real=data.get("stock_real", 0),
        stock_local=data.get("stock_local", 0),
        activo=True,
        publicar_web=data.get("publicar_web", True),
        foto_base64=data.get("foto_base64", ""),
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return {"id": a.id, "message": "Artículo creado"}


@router.post("/importar-excel")
def importar_excel(data: dict, db: Session = Depends(get_db)):
    articulos = data.get("articulos", [])
    opc_stock = data.get("opc_stock", "todos")
    opc_existente = data.get("opc_existente", "actualizar")
    ganancia_default = data.get("ganancia_default", 30)

    # Alias de columnas: variantes → clave interna
    ALIAS = {
        # código
        "codigo": "codigo", "code": "codigo", "cod": "codigo", "ref": "codigo",
        "referencia": "codigo", "sku": "codigo",
        # descripción
        "descripcion": "descripcion", "descripcion_del_producto": "descripcion",
        "descripcion_producto": "descripcion", "nombre": "descripcion",
        "nombre_del_articulo": "descripcion", "nombre_del_producto": "descripcion",
        "nombre_articulo": "descripcion", "nombre_producto": "descripcion",
        "articulo": "descripcion", "articulos": "descripcion",
        "description": "descripcion", "item": "descripcion",
        "producto": "descripcion", "productos": "descripcion",
        "denominacion": "descripcion", "detalle": "descripcion",
        "concepto": "descripcion", "especificacion": "descripcion",
        # precio costo
        "precio_compra": "precio_costo", "precio_costo": "precio_costo",
        "precio_de_compra": "precio_costo", "precio_de_costo": "precio_costo",
        "costo": "precio_costo", "costo_unitario": "precio_costo",
        "precio": "precio_costo", "precio_unitario": "precio_costo",
        "precio_unit": "precio_costo", "p_costo": "precio_costo",
        "p_compra": "precio_costo", "valor": "precio_costo",
        # margen
        "ganancia_porcentaje": "margen", "ganancia": "margen",
        "margen": "margen", "utilidad": "margen", "porcentaje": "margen",
        "porc": "margen", "markup": "margen",
        # stock
        "stock": "stock", "cantidad": "stock", "cant": "stock",
        "existencia": "stock", "existencias": "stock",
        "stock_actual": "stock", "cantidad_en_stock": "stock",
        "inventario": "stock", "qty": "stock",
        # marca
        "marca": "marca", "brand": "marca", "fabricante": "marca",
        # categoría
        "categoria": "categoria", "rubro": "categoria",
        "tipo": "categoria", "familia": "categoria",
        "linea": "categoria", "grupo": "categoria", "seccion": "categoria",
        # modelo / proveedor
        "modelo": "modelo", "model": "modelo", "version": "modelo",
        "proveedor": "proveedor", "supplier": "proveedor", "distribuidor": "proveedor",
    }

    import unicodedata

    def normalize_key(k):
        k = str(k).strip().lower()
        k = unicodedata.normalize("NFD", k)
        k = "".join(c for c in k if unicodedata.category(c) != "Mn")
        k = k.replace(" ", "_")
        return ALIAS.get(k, k)

    def g(art_norm, *keys, default=""):
        for k in keys:
            if k in art_norm and art_norm[k] not in (None, ""):
                return art_norm[k]
        return default

    nuevos = 0
    actualizados = 0
    omitidos = 0
    sin_categoria = 0
    errores = []
    primer_row_claves = []  # para diagnóstico

    for raw in articulos:
        try:
            # Normalizar claves del row
            art = {normalize_key(k): v for k, v in raw.items()}

            if not primer_row_claves:
                primer_row_claves = list(art.keys())

            def to_str(val):
                """Convierte valor (incluido float tipo 12345.0) a string limpio."""
                if val is None or val == "":
                    return ""
                try:
                    f = float(val)
                    return str(int(f)) if f == int(f) else str(f)
                except (ValueError, TypeError):
                    return str(val).strip()

            codigo = to_str(g(art, "codigo", default=""))
            descripcion = str(g(art, "descripcion", default="")).strip()
            marca = str(g(art, "marca", default="")).strip()
            categoria_raw = str(g(art, "categoria", default="")).strip()
            modelo = str(g(art, "modelo", default="")).strip()

            # Saltar filas sin nombre ni código
            if not descripcion and not codigo:
                omitidos += 1
                continue

            if not categoria_raw:
                sin_categoria += 1

            precio_costo = float(g(art, "precio_costo", default=0) or 0)
            margen = float(g(art, "margen", default=ganancia_default) or ganancia_default)
            precio_venta = precio_costo * (1 + margen / 100)
            stock_val = float(g(art, "stock", default=0) or 0)

            # Auto-crear categoría y usar nombre CANÓNICO de la BD
            # Normalizar: quitar espacios extra y capitalizar para evitar duplicados
            categoria_raw_norm = " ".join(categoria_raw.split()).title() if categoria_raw else ""
            categoria = categoria_raw_norm
            if categoria_raw_norm:
                cat_obj = db.query(Categoria).filter(
                    func.lower(func.trim(Categoria.nombre)) == categoria_raw_norm.lower()
                ).first()
                if not cat_obj:
                    cat_obj = Categoria(nombre=categoria_raw_norm)
                    db.add(cat_obj)
                    db.flush()
                categoria = cat_obj.nombre  # nombre exacto de la BD

            # Buscar existente
            existente = None
            if codigo:
                existente = db.query(Producto).filter(Producto.codigo == codigo).first()
            if not existente and descripcion:
                existente = db.query(Producto).filter(
                    func.lower(Producto.descripcion) == descripcion.lower()
                ).first()

            if existente:
                if opc_existente == "actualizar":
                    if descripcion:
                        existente.descripcion = descripcion
                    if marca:
                        existente.marca = marca
                    existente.precio_costo = precio_costo
                    existente.costo_base = precio_costo
                    existente.precio_venta_contado = precio_venta
                    existente.precio_venta_final = precio_venta
                    if categoria:
                        existente.categoria = categoria
                    if opc_stock != "no_actualizar":
                        existente.stock_real = stock_val
                        existente.stock_local = stock_val
                    existente.activo = True  # reactivar si estaba borrado
                    actualizados += 1
            else:
                nuevo = Producto(
                    codigo=codigo,
                    descripcion=descripcion,
                    marca=marca,
                    modelo=modelo,
                    categoria=categoria,
                    precio_costo=precio_costo,
                    costo_base=precio_costo,
                    precio_venta_contado=precio_venta,
                    precio_venta_final=precio_venta,
                    stock_real=stock_val,
                    stock_local=stock_val,
                    activo=True,
                )
                db.add(nuevo)
                nuevos += 1
        except Exception as e:
            errores.append(str(e))

    db.commit()
    return {
        "nuevos": nuevos,
        "actualizados": actualizados,
        "omitidos": omitidos,
        "sin_categoria": sin_categoria,
        "columnas_detectadas": primer_row_claves,
        "errores": errores,
    }


@router.get("/debug-categorias")
def debug_categorias(db: Session = Depends(get_db)):
    """Muestra los valores reales de categoria en Producto."""
    rows = (
        db.query(Producto.categoria, func.count(Producto.id))
        .filter(Producto.activo == True)
        .group_by(Producto.categoria)
        .order_by(func.count(Producto.id).desc())
        .all()
    )
    cats_bd = [c.nombre for c in db.query(Categoria).all()]
    return {
        "categorias_en_productos": [{"valor": r[0] or "(vacío)", "count": r[1]} for r in rows],
        "categorias_en_tabla": cats_bd,
    }


@router.post("/normalizar-categorias")
def normalizar_categorias(db: Session = Depends(get_db)):
    """Unifica Producto.categoria con el nombre canónico de Categoria (case-insensitive)."""
    categorias = db.query(Categoria).all()
    cat_map = {c.nombre.strip().lower(): c.nombre for c in categorias}
    productos = db.query(Producto).filter(
        Producto.categoria != None, Producto.categoria != ""
    ).all()
    actualizados = 0
    for p in productos:
        key = (p.categoria or "").strip().lower()
        if key in cat_map and p.categoria != cat_map[key]:
            p.categoria = cat_map[key]
            actualizados += 1
    db.commit()
    return {"normalizados": actualizados}


@router.post("/deduplicar-categorias")
def deduplicar_categorias(db: Session = Depends(get_db)):
    """Unifica categorías duplicadas (mismo nombre ignorando mayúsculas/espacios).
    Conserva la de menor id y reasigna todos los productos a ella."""
    todas = db.query(Categoria).order_by(Categoria.id).all()

    # Agrupar por nombre normalizado
    grupos: dict[str, list] = {}
    for cat in todas:
        key = cat.nombre.strip().lower()
        grupos.setdefault(key, []).append(cat)

    cats_eliminadas = 0
    productos_reasignados = 0

    for key, grupo in grupos.items():
        if len(grupo) <= 1:
            continue
        # Conservar la categoría con menor id (la más antigua)
        canonical = grupo[0]
        duplicados = grupo[1:]

        for dup in duplicados:
            # Reasignar productos del duplicado al canonical
            prods = db.query(Producto).filter(Producto.categoria == dup.nombre).all()
            for p in prods:
                p.categoria = canonical.nombre
                productos_reasignados += 1
            db.delete(dup)
            cats_eliminadas += 1

    db.commit()
    return {
        "categorias_eliminadas": cats_eliminadas,
        "productos_reasignados": productos_reasignados,
    }


@router.get("/marcas")
def listar_marcas(db: Session = Depends(get_db)):
    rows = (
        db.query(Producto.marca)
        .filter(Producto.activo == True)
        .filter(Producto.marca != None)
        .filter(Producto.marca != "")
        .distinct()
        .order_by(Producto.marca)
        .all()
    )
    return [r[0] for r in rows]


@router.delete("/limpiar-vacios")
def limpiar_articulos_vacios(db: Session = Depends(get_db)):
    """Elimina definitivamente artículos sin descripción ni código."""
    arts = db.query(Producto).filter(
        ((Producto.descripcion == None) | (Producto.descripcion == "")) &
        ((Producto.codigo == None) | (Producto.codigo == ""))
    ).all()
    count = len(arts)
    for a in arts:
        db.delete(a)
    db.commit()
    return {"eliminados": count}


@router.delete("/por-categoria")
def borrado_masivo_categoria(data: dict, db: Session = Depends(get_db)):
    """Elimina (soft-delete) todos los artículos de una categoría."""
    categoria = data.get("categoria", "").strip()
    if not categoria:
        raise HTTPException(status_code=400, detail="Falta la categoría")
    count = db.query(Producto).filter(Producto.categoria == categoria).update({"activo": False})
    db.commit()
    return {"eliminados": count, "categoria": categoria}


# ── CATEGORÍAS ──

categorias_cache = {}

@router.get("/categorias")
def listar_categorias(db: Session = Depends(get_db)):
    # Conteo usando lower(trim()) en la BD para evitar problemas de casing/espacios
    raw_counts = (
        db.query(
            func.lower(func.trim(Producto.categoria)),
            func.count(Producto.id)
        )
        .filter(Producto.activo == True)
        .filter(Producto.categoria != None)
        .filter(Producto.categoria != "")
        .group_by(func.lower(func.trim(Producto.categoria)))
        .all()
    )
    counts = {cat_key: cnt for cat_key, cnt in raw_counts if cat_key}

    categorias = db.query(Categoria).order_by(Categoria.nombre).all()
    return [
        {
            "id": c.id,
            "nombre": c.nombre,
            "descripcion": c.descripcion or "",
            "articulos_count": counts.get(c.nombre.strip().lower(), 0),
        }
        for c in categorias
    ]


@router.post("/categorias")
def crear_categoria(data: dict, db: Session = Depends(get_db)):
    nombre = " ".join(data.get("nombre", "").strip().split()).title()
    if not nombre:
        raise HTTPException(status_code=400, detail="El nombre es requerido")

    existente = db.query(Categoria).filter(
        func.lower(func.trim(Categoria.nombre)) == nombre.lower()
    ).first()
    if existente:
        raise HTTPException(status_code=400, detail="Ya existe una categoría con ese nombre")
    
    cat = Categoria(
        nombre=nombre,
        descripcion=data.get("descripcion", "")
    )
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return {"id": cat.id, "nombre": cat.nombre, "descripcion": cat.descripcion}


@router.put("/categorias/{categoria_id}")
def actualizar_categoria(categoria_id: int, data: dict, db: Session = Depends(get_db)):
    cat = db.query(Categoria).filter(Categoria.id == categoria_id).first()
    if not cat:
        raise HTTPException(status_code=404, detail="Categoría no encontrada")
    
    nombre = data.get("nombre", "").strip()
    if nombre and nombre != cat.nombre:
        existente = db.query(Categoria).filter(Categoria.nombre.ilike(nombre), Categoria.id != categoria_id).first()
        if existente:
            raise HTTPException(status_code=400, detail="Ya existe una categoría con ese nombre")
        cat.nombre = nombre
    
    cat.descripcion = data.get("descripcion", cat.descripcion)
    db.commit()
    return {"id": cat.id, "nombre": cat.nombre, "descripcion": cat.descripcion}


@router.delete("/categorias/{categoria_id}")
def eliminar_categoria(categoria_id: int, db: Session = Depends(get_db)):
    cat = db.query(Categoria).filter(Categoria.id == categoria_id).first()
    if not cat:
        raise HTTPException(status_code=404, detail="Categoría no encontrada")
    db.delete(cat)
    db.commit()
    return {"message": "Categoría eliminada"}


# ── RUTAS CON PARÁMETROS (al final) ──

@router.get("/{articulo_id}")
def get_articulo(articulo_id: int, db: Session = Depends(get_db)):
    a = db.query(Producto).filter(Producto.id == articulo_id).first()
    if not a:
        raise HTTPException(status_code=404, detail="Artículo no encontrado")
    return {
        "id": a.id,
        "codigo": a.codigo or "",
        "descripcion": a.descripcion,
        "marca": a.marca or "",
        "categoria": a.categoria or "",
        "proveedor": a.proveedor or "",
        "precio_costo": a.precio_costo or 0,
        "precio_venta": a.precio_venta_final or 0,
        "precio_venta_contado": a.precio_venta_contado or 0,
        "precio_venta_final": a.precio_venta_final or 0,
        "stock_real": a.stock_real or 0,
        "stock_local": a.stock_local or 0,
        "activo": a.activo,
        "publicar_web": a.publicar_web,
        "foto_url": a.foto_base64 if a.foto_base64 else "",
    }


@router.put("/{articulo_id}")
def actualizar_articulo(articulo_id: int, data: dict, db: Session = Depends(get_db)):
    a = db.query(Producto).filter(Producto.id == articulo_id).first()
    if not a:
        raise HTTPException(status_code=404, detail="Artículo no encontrado")
    
    if "codigo" in data:
        a.codigo = data["codigo"]
    if "descripcion" in data:
        a.descripcion = data["descripcion"]
    if "marca" in data:
        a.marca = data["marca"]
    if "categoria" in data:
        a.categoria = data["categoria"]
    if "proveedor" in data:
        a.proveedor = data["proveedor"]
    if "precio_costo" in data:
        a.precio_costo = data["precio_costo"]
        a.costo_base = data["precio_costo"]
    if "precio_venta" in data:
        a.precio_venta_contado = data["precio_venta"]
        a.precio_venta_final = data["precio_venta"]
    if "stock_real" in data:
        a.stock_real = data["stock_real"]
    if "stock_local" in data:
        a.stock_local = data["stock_local"]
    if "publicar_web" in data:
        a.publicar_web = data["publicar_web"]
    if "foto_base64" in data:
        a.foto_base64 = data["foto_base64"]
    
    db.commit()
    return {"message": "Artículo actualizado"}


@router.delete("/{articulo_id}")
def eliminar_articulo(articulo_id: int, db: Session = Depends(get_db)):
    a = db.query(Producto).filter(Producto.id == articulo_id).first()
    if not a:
        raise HTTPException(status_code=404, detail="Artículo no encontrado")
    a.activo = False
    db.commit()
    return {"message": "Artículo eliminado"}


@router.post("/actualizar-margen-marca")
def actualizar_margen_marca(data: dict, db: Session = Depends(get_db)):
    """Actualiza margen y recalcula precio_venta_final para todos los productos de una marca."""
    marca = (data.get("marca") or "").strip()
    margen = float(data.get("margen") or 0)
    if not marca:
        raise HTTPException(status_code=400, detail="Falta la marca")

    productos = db.query(Producto).filter(
        Producto.activo == True,
        Producto.marca.ilike(f"%{marca}%")
    ).all()

    if not productos:
        return {"message": f"No se encontraron productos de la marca '{marca}'", "actualizados": 0}

    for p in productos:
        p.margen_ganancia = margen
        if p.precio_costo and p.precio_costo > 0:
            nuevo_precio = round(p.precio_costo * (1 + margen / 100), 2)
            p.precio_venta_final = nuevo_precio
            p.precio_venta_contado = nuevo_precio

    db.commit()
    return {"message": f"{len(productos)} productos de '{marca}' actualizados con margen {margen}%", "actualizados": len(productos)}
