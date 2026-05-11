import re
import unicodedata
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, or_
from core.database import get_db
from models.models import Producto, Categoria

router = APIRouter(prefix="/api/v1/articulos", tags=["articulos"])


# ─────────────────────────────────────────────────────────────────────────────
# ANTI-DUPLICADOS: helpers compartidos por crear, importar Excel y bot
# ─────────────────────────────────────────────────────────────────────────────

def _normalizar_texto(s: str) -> str:
    """Normaliza un string para comparación: lowercase, sin tildes, espacios colapsados."""
    if not s:
        return ""
    s = unicodedata.normalize("NFD", str(s))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.lower().strip()
    s = " ".join(s.split())
    return s


def _normalizar_medida(s: str) -> str:
    """175/65 R14 → 17565R14 (canonical sin separadores) para comparar."""
    if not s:
        return ""
    return re.sub(r'[^0-9a-zA-Z]', '', str(s).upper())


def buscar_producto_existente(db: Session, codigo="", descripcion="", marca="", modelo="", medida=""):
    """
    Busca productos existentes que coincidan total o parcialmente.

    Devuelve dict:
      - exacto:     producto que matchea por codigo, descripcion exacta, o marca+modelo+medida
      - candidatos: lista de productos que parcialmente coinciden (misma medida+marca, etc.)

    Si hay un exacto, candidatos viene vacío. Si no hay exacto, candidatos puede tener varios.
    """
    codigo = (codigo or "").strip()
    desc_norm = _normalizar_texto(descripcion)
    marca_norm = _normalizar_texto(marca)
    modelo_norm = _normalizar_texto(modelo)
    medida_norm = _normalizar_medida(medida)

    # 1. Match exacto por código
    if codigo:
        ex = db.query(Producto).filter(
            Producto.activo == True,
            Producto.codigo == codigo,
        ).first()
        if ex:
            return {"exacto": ex, "candidatos": []}

    # 2. Match exacto por descripción normalizada
    if desc_norm:
        candidatos_desc = db.query(Producto).filter(Producto.activo == True).all()
        for p in candidatos_desc:
            if _normalizar_texto(p.descripcion) == desc_norm:
                return {"exacto": p, "candidatos": []}

    # 3. Match exacto por marca+modelo+medida (los 3 con valor)
    if marca_norm and modelo_norm and medida_norm:
        candidatos_mmm = db.query(Producto).filter(Producto.activo == True).all()
        for p in candidatos_mmm:
            if (_normalizar_texto(p.marca) == marca_norm and
                _normalizar_texto(p.modelo) == modelo_norm and
                _normalizar_medida(p.medida) == medida_norm):
                return {"exacto": p, "candidatos": []}

    # 4. Candidatos parciales: misma marca+medida (mismo modelo o no)
    candidatos = []
    if marca_norm and medida_norm:
        for p in db.query(Producto).filter(Producto.activo == True).all():
            p_marca = _normalizar_texto(p.marca)
            p_medida = _normalizar_medida(p.medida)
            if p_marca == marca_norm and p_medida == medida_norm:
                candidatos.append(p)
    elif medida_norm and desc_norm:
        # Sin marca: matchear descripcion que contenga la medida y comparte palabras
        palabras_desc = set(desc_norm.split())
        for p in db.query(Producto).filter(Producto.activo == True).all():
            if _normalizar_medida(p.medida) == medida_norm:
                palabras_p = set(_normalizar_texto(p.descripcion).split())
                comunes = palabras_desc & palabras_p
                if len(comunes) >= 2:
                    candidatos.append(p)

    return {"exacto": None, "candidatos": candidatos[:10]}


def aplicar_actualizacion_parcial(producto: Producto, datos: dict, modo: str = "modificar_campos"):
    """
    Aplica datos a un producto existente.
      - modo='modificar_campos': solo actualiza precio_costo, precio_venta, stock,
        margen_ganancia, proveedor (los campos de "negocio"). No toca descripcion/marca/modelo/medida.
      - modo='sobrescribir': actualiza todos los campos provistos.
    """
    if modo == "sobrescribir":
        if "descripcion" in datos and datos["descripcion"]: producto.descripcion = datos["descripcion"]
        if "marca" in datos and datos["marca"]: producto.marca = datos["marca"]
        if "modelo" in datos and datos["modelo"]: producto.modelo = datos["modelo"]
        if "medida" in datos and datos["medida"]: producto.medida = datos["medida"]
        if "categoria" in datos and datos["categoria"]: producto.categoria = datos["categoria"]
        if "codigo" in datos and datos["codigo"]: producto.codigo = datos["codigo"]
    # Campos comerciales (siempre se actualizan si vienen)
    for campo in ("precio_costo", "costo_base", "precio_venta_contado", "precio_venta_final",
                  "precio_cuota_6", "precio_cuota_12", "margen_ganancia", "proveedor",
                  "stock_real", "stock_local"):
        if campo in datos and datos[campo] is not None:
            setattr(producto, campo, datos[campo])
    producto.activo = True


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
    """
    Crea un artículo CON DETECCIÓN DE DUPLICADOS.

    Si ya existe uno con mismo código/descripcion/marca+modelo+medida:
      - Sin flag → devuelve 409 con info del existente y candidatos
      - Con flag 'modo_duplicado'='sobrescribir' → actualiza todos los campos
      - Con flag 'modo_duplicado'='modificar' → solo actualiza precio/stock/costo/margen
      - Con flag 'modo_duplicado'='crear_igual' → crea un nuevo registro forzado
    """
    precio_costo = data.get("precio_costo", 0)
    precio_venta = data.get("precio_venta", 0)
    modo_duplicado = data.get("modo_duplicado", "")  # 'sobrescribir' | 'modificar' | 'crear_igual'

    busq = buscar_producto_existente(
        db,
        codigo=data.get("codigo", ""),
        descripcion=data.get("descripcion", ""),
        marca=data.get("marca", ""),
        modelo=data.get("modelo", ""),
        medida=data.get("medida", ""),
    )

    # Caso 1: hay match exacto y NO se eligió cómo manejarlo → 409
    if busq["exacto"] and modo_duplicado not in ("sobrescribir", "modificar", "crear_igual"):
        ex = busq["exacto"]
        return _respuesta_conflicto([ex], data, exacto=True)

    # Caso 2: hay candidatos parciales y NO se eligió → preguntar
    if not busq["exacto"] and busq["candidatos"] and modo_duplicado not in ("sobrescribir", "modificar", "crear_igual"):
        return _respuesta_conflicto(busq["candidatos"], data, exacto=False)

    # Caso 3: actualizar el match exacto
    if busq["exacto"] and modo_duplicado in ("sobrescribir", "modificar"):
        modo = "sobrescribir" if modo_duplicado == "sobrescribir" else "modificar_campos"
        datos_norm = dict(data)
        datos_norm["precio_venta_contado"] = precio_venta
        datos_norm["precio_venta_final"] = precio_venta
        datos_norm["costo_base"] = precio_costo
        aplicar_actualizacion_parcial(busq["exacto"], datos_norm, modo=modo)
        db.commit()
        db.refresh(busq["exacto"])
        return {"id": busq["exacto"].id, "message": f"Artículo existente actualizado ({modo_duplicado})", "accion": "actualizado"}

    # Caso 4: crear nuevo (no hay duplicado, o user eligió 'crear_igual')
    a = Producto(
        codigo=data.get("codigo", ""),
        descripcion=data.get("descripcion", ""),
        marca=data.get("marca", ""),
        modelo=data.get("modelo", ""),
        medida=data.get("medida", ""),
        categoria=data.get("categoria", ""),
        proveedor=data.get("proveedor", ""),
        precio_costo=precio_costo,
        precio_venta_contado=precio_venta,
        precio_venta_final=precio_venta,
        costo_base=precio_costo,
        margen_ganancia=data.get("margen_ganancia", 0),
        stock_real=data.get("stock_real", 0),
        stock_local=data.get("stock_local", 0),
        activo=True,
        publicar_web=data.get("publicar_web", True),
        foto_base64=data.get("foto_base64", ""),
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return {"id": a.id, "message": "Artículo creado", "accion": "creado"}


def _respuesta_conflicto(candidatos, data_ingresada, exacto=False):
    """Construye respuesta 409 con candidatos para que el frontend pregunte qué hacer."""
    payload = {
        "requiere_confirmacion": True,
        "tipo": "duplicado_exacto" if exacto else "duplicado_sospechoso",
        "mensaje": (
            "Ya existe un producto idéntico. ¿Querés sobrescribirlo o solo modificar precio/stock?"
            if exacto else
            "Encontré productos similares. ¿Es alguno de estos o creo uno nuevo?"
        ),
        "data_ingresada": data_ingresada,
        "candidatos": [
            {
                "id": p.id,
                "codigo": p.codigo,
                "descripcion": p.descripcion,
                "marca": p.marca,
                "modelo": p.modelo,
                "medida": p.medida,
                "precio_contado": int(p.precio_venta_contado or 0),
                "stock_real": p.stock_real or 0,
                "categoria": p.categoria,
            }
            for p in candidatos
        ],
        "opciones": {
            "sobrescribir": "Reemplaza todos los datos del existente con los nuevos",
            "modificar": "Solo actualiza precio/stock/costo/ganancia, mantiene marca/modelo/medida",
            "crear_igual": "Crea un nuevo registro aparte (no recomendado)",
        },
    }
    return payload


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

            # Anti-duplicados: usar helper centralizado
            busq = buscar_producto_existente(
                db, codigo=codigo, descripcion=descripcion, marca=marca, modelo=modelo
            )
            existente = busq["exacto"]

            if existente:
                # Hay match exacto → actualizar según opc_existente
                if opc_existente == "actualizar":
                    # Sobrescribir todo (legacy)
                    if descripcion: existente.descripcion = descripcion
                    if marca: existente.marca = marca
                    if modelo: existente.modelo = modelo
                    existente.precio_costo = precio_costo
                    existente.costo_base = precio_costo
                    existente.precio_venta_contado = precio_venta
                    existente.precio_venta_final = precio_venta
                    existente.margen_ganancia = margen
                    if categoria: existente.categoria = categoria
                    if opc_stock != "no_actualizar":
                        existente.stock_real = stock_val
                        existente.stock_local = stock_val
                    existente.activo = True
                    actualizados += 1
                elif opc_existente == "modificar":
                    # Solo actualizar precio/stock/costo/margen, no toca descripcion/marca/modelo
                    existente.precio_costo = precio_costo
                    existente.costo_base = precio_costo
                    existente.precio_venta_contado = precio_venta
                    existente.precio_venta_final = precio_venta
                    existente.margen_ganancia = margen
                    if opc_stock != "no_actualizar":
                        existente.stock_real = stock_val
                        existente.stock_local = stock_val
                    existente.activo = True
                    actualizados += 1
                elif opc_existente == "omitir":
                    omitidos += 1
            elif busq["candidatos"]:
                # Coincidencia parcial → omitir y dejar para revisión manual
                omitidos += 1
                errores.append({
                    "fila": descripcion or codigo,
                    "motivo": "Posible duplicado parcial — revisar manualmente",
                    "candidatos": [
                        {"id": p.id, "descripcion": p.descripcion, "marca": p.marca, "modelo": p.modelo, "medida": p.medida}
                        for p in busq["candidatos"][:3]
                    ],
                })
            else:
                # No hay duplicado → crear nuevo
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
                    margen_ganancia=margen,
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


@router.post("/recategorizar-por-marca-real")
def recategorizar_por_marca_real(
    aplicar: bool = False,
    db: Session = Depends(get_db),
):
    """
    Recorre TODOS los productos activos y corrige la marca/categoria según patrones
    detectados en la descripcion. Útil después de imports masivos donde se asignó
    una marca/categoria equivocada.
    """
    import re as _re

    # Mapeo descripción → (marca_canónica, categoría_canónica)
    # IMPORTANTE: el orden es crítico. Lo más específico va primero.
    # 1. PASTILLAS/REPUESTOS van PRIMERO para que no caigan en reglas de neumáticos.
    # 2. Marcas con patrones únicos antes que marcas con palabras genéricas.
    REGLAS = [
        # ── Repuestos (no neumáticos) ──
        (_re.compile(r"\bPASTILLAS?\b", _re.IGNORECASE), None, "pastillas de freno"),
        (_re.compile(r"\bFRASLE\b", _re.IGNORECASE), "Frasle", "pastillas de freno"),

        # ── Goodyear (incluido Cargo Marathon) ──
        (_re.compile(r"\bGOODYEAR\b|\bASSURANCE\b|\bASSU\b|\bEFFICIENTGRIP\b|\bEAGLE\s*F1\b|\bWRANGLER\b|\bWRL\.?\b|\bFORTERA\b|\bFORTITUDE\b|\bOPTILIFE\b|\bDURAPLUS\b|\bEXCELLENCE\b|\bCARGO\s*MARATHON\b|\bMARATHON\s+\d\b", _re.IGNORECASE), "Goodyear", "Goodyear"),
        (_re.compile(r"\bKELLY\b|\bK\.?\s*EDGE\b", _re.IGNORECASE), "Kelly", "Goodyear"),

        # ── Marcas Ofertas (todas son submarcas/proveedores de ofertas especiales) ──
        (_re.compile(r"\bSPORTACTIVE\b|\bSAVERO\b|\bADVTURO\b|\bCHAMPIRO\b|\bGT\s*RADIAL\b", _re.IGNORECASE), "GT RADIAL", "Ofertas"),
        (_re.compile(r"\bGITICOMFORT\b|\bGITI4X4\b|\bGITI\b|\bXCURSION\b|\bCOMFORT\s*F\d\b", _re.IGNORECASE), "Giti", "Ofertas"),
        (_re.compile(r"\bWANLI\b|\bSA302\b|\bSP026\b|\bSL106\b|\bSP022\b|\bE01\s*RFID\b", _re.IGNORECASE), "Wanli", "Ofertas"),
        (_re.compile(r"\bSUNNY\b|\bNP226\b", _re.IGNORECASE), "Sunny", "Ofertas"),
        (_re.compile(r"\bMAXMILER\b", _re.IGNORECASE), "Maxmiler", "Ofertas"),

        # ── Marcas Neumáticos (estándar) ──
        (_re.compile(r"\bLINGLONG\b|\bGREENMAX\b", _re.IGNORECASE), "Linglong", "Neumaticos"),
        (_re.compile(r"\bHABILEAD\b|\bH202\b|\bH206\b|\bS801\b|\bRS01\b", _re.IGNORECASE), "Habilead", "Neumaticos"),
        (_re.compile(r"\bYOKOHAMA\b|\bGEOLANDAR\b|\bES32\b|\bES32A\b", _re.IGNORECASE), "Yokohama", "Neumaticos"),
        (_re.compile(r"\bPIRELLI\b|\bSCORPN\b|\bSCORPION\b|\bP400\b|\bP1cint\b|\bF\.?ENGY\b|\bF\.?EVO\b|\bCINTURATO\b|\bFORMULA\s+EVO\b|\bS-ATR\b|\bS-MTR\b|\bS-HT\b|\bS-VERD\b|\bS-VEAS\b", _re.IGNORECASE), "Pirelli", "Neumaticos"),
        (_re.compile(r"\bHANKOOK\b|\bKINERGY\b", _re.IGNORECASE), "Hankook", "Neumaticos"),
        (_re.compile(r"\bNEXEN\b|\bN['’]?FERA\b", _re.IGNORECASE), "Nexen", "Neumaticos"),
        (_re.compile(r"\bBRIDGESTONE\b|\bDUELER\b|\bECOPIA\b", _re.IGNORECASE), "Bridgestone", "Neumaticos"),
        (_re.compile(r"\bFATE\b|\bAR-?360\b", _re.IGNORECASE), "Fate", "Neumaticos"),
        (_re.compile(r"\bMICHELIN\b", _re.IGNORECASE), "Michelin", "Neumaticos"),
        (_re.compile(r"\bCONTINENTAL\b", _re.IGNORECASE), "Continental", "Neumaticos"),
        (_re.compile(r"\bDUNLOP\b", _re.IGNORECASE), "Dunlop", "Neumaticos"),
        (_re.compile(r"\bFIRESTONE\b|\bF600\b", _re.IGNORECASE), "Firestone", "Neumaticos"),
        (_re.compile(r"\bXBRI\b|\bFASTWAY\b|\bSPORT\+\b|\bBRUTUS\b|\bFORZA\b|\bECOLOGY\b|\bFASTDRIVE\b", _re.IGNORECASE), "Xbri", "Neumaticos"),
        (_re.compile(r"\bSUNSET\b|\bVENTTURA\b|\bOVER\s*CARGO\b", _re.IGNORECASE), "Sunset", "Neumaticos"),
        # Durable solo si menciona "DURABLE" explícito o tiene patrón DR0X/DC0X específico
        (_re.compile(r"\bDURABLE\b|\bDR01\b|\bDC01\b|\bCARGO\s*\d\b", _re.IGNORECASE), "Durable", "Neumaticos"),
    ]

    productos = db.query(Producto).filter(Producto.activo == True).all()
    cambios = []
    actualizados = 0

    for p in productos:
        desc = p.descripcion or ""
        marca_actual = (p.marca or "").strip()
        cat_actual = (p.categoria or "").strip()

        # Buscar primera regla que matchee
        marca_nueva = None
        cat_nueva = None
        for regex, marca_r, cat_r in REGLAS:
            if regex.search(desc):
                marca_nueva = marca_r if marca_r else marca_actual
                cat_nueva = cat_r
                break

        if not cat_nueva:
            continue

        cambio_marca = (marca_nueva and marca_nueva.lower() != marca_actual.lower()) if marca_nueva else False
        cambio_cat = cat_nueva.lower() != cat_actual.lower()

        if not (cambio_marca or cambio_cat):
            continue

        cambios.append({
            "id": p.id, "descripcion": desc[:60],
            "marca": {"antes": marca_actual, "despues": marca_nueva} if cambio_marca else None,
            "categoria": {"antes": cat_actual, "despues": cat_nueva} if cambio_cat else None,
        })

        if aplicar:
            if cambio_marca:
                p.marca = marca_nueva
            if cambio_cat:
                # Asegurar que la categoria exista en la tabla
                cat = db.query(Categoria).filter(func.lower(Categoria.nombre) == cat_nueva.lower()).first()
                if not cat:
                    cat = Categoria(nombre=cat_nueva)
                    db.add(cat)
                    db.flush()
                p.categoria = cat.nombre
            actualizados += 1

    if aplicar:
        db.commit()

    return {
        "modo": "aplicado" if aplicar else "dry-run (pasá ?aplicar=true para ejecutar)",
        "productos_recorridos": len(productos),
        "productos_a_corregir": len(cambios),
        "actualizados": actualizados,
        "muestra": cambios[:20],
    }


@router.post("/deduplicar-productos")
def deduplicar_productos(
    aplicar: bool = False,
    db: Session = Depends(get_db),
):
    """
    Encuentra productos duplicados y los unifica.

    Criterio de duplicado: misma descripcion (normalizada: lowercase + sin espacios extras)
    O misma combinación marca+modelo+medida cuando los 3 están cargados.

    Estrategia de unificación:
    - Conserva el producto con menor id (el más antiguo)
    - Suma el stock de los duplicados al producto canónico
    - Los duplicados quedan desactivados (activo=False)

    Modo dry-run por defecto: pasá ?aplicar=true para ejecutar los cambios.
    """
    productos_activos = db.query(Producto).filter(Producto.activo == True).order_by(Producto.id).all()

    def norm_desc(s: str) -> str:
        return " ".join((s or "").strip().lower().split())

    grupos: dict[str, list] = {}
    for p in productos_activos:
        keys = []
        if p.descripcion:
            keys.append(f"desc::{norm_desc(p.descripcion)}")
        if p.marca and p.modelo and p.medida:
            mmm = f"{p.marca.strip().lower()}|{p.modelo.strip().lower()}|{p.medida.strip().lower()}"
            keys.append(f"mmm::{mmm}")
        for k in keys:
            grupos.setdefault(k, []).append(p)

    duplicados_detectados = []
    productos_eliminados = 0
    stock_reasignado = 0
    productos_ya_procesados = set()

    for key, grupo in grupos.items():
        if len(grupo) <= 1:
            continue
        # Filtrar productos ya procesados en otro grupo (cross-key duplicates)
        grupo_filtrado = [p for p in grupo if p.id not in productos_ya_procesados]
        if len(grupo_filtrado) <= 1:
            continue

        canonical = grupo_filtrado[0]
        duplicados = grupo_filtrado[1:]
        info_grupo = {
            "key": key,
            "canonical_id": canonical.id,
            "canonical_descripcion": canonical.descripcion,
            "duplicados": [],
        }

        for dup in duplicados:
            info_grupo["duplicados"].append({
                "id": dup.id,
                "descripcion": dup.descripcion,
                "stock_movido": dup.stock_real or 0,
            })
            if aplicar:
                canonical.stock_real = (canonical.stock_real or 0) + (dup.stock_real or 0)
                stock_reasignado += dup.stock_real or 0
                dup.activo = False
                productos_eliminados += 1
            productos_ya_procesados.add(dup.id)
        productos_ya_procesados.add(canonical.id)
        duplicados_detectados.append(info_grupo)

    if aplicar:
        db.commit()

    return {
        "modo": "aplicado" if aplicar else "dry-run (pasá ?aplicar=true para ejecutar)",
        "grupos_con_duplicados": len(duplicados_detectados),
        "productos_eliminados": productos_eliminados,
        "stock_reasignado": stock_reasignado,
        "detalle": duplicados_detectados,
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
