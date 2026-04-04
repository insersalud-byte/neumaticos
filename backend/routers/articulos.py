from fastapi import APIRouter, Depends, HTTPException, Query
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
    
    nuevos = 0
    actualizados = 0
    errores = []
    
    for art in articulos:
        try:
            codigo = art.get("codigo", "")
            existente = db.query(Producto).filter(Producto.codigo == codigo).first() if codigo else None
            
            if existente:
                if opc_existente == "actualizar":
                    existente.descripcion = art.get("descripcion", existente.descripcion)
                    existente.marca = art.get("marca", existente.marca)
                    existente.precio_costo = art.get("precio_costo", existente.precio_costo)
                    if art.get("stock"):
                        existente.stock_real = art.get("stock", 0)
                    actualizados += 1
            else:
                nuevo = Producto(
                    codigo=codigo,
                    descripcion=art.get("descripcion", ""),
                    marca=art.get("marca", ""),
                    categoria=art.get("categoria", ""),
                    precio_costo=art.get("precio_costo", 0),
                    precio_venta_contado=art.get("precio_venta", 0),
                    precio_venta_final=art.get("precio_venta", 0),
                    costo_base=art.get("precio_costo", 0),
                    stock_real=art.get("stock", 0),
                    stock_local=art.get("stock", 0),
                    activo=True,
                )
                db.add(nuevo)
                nuevos += 1
        except Exception as e:
            errores.append(str(e))
    
    db.commit()
    return {"nuevos": nuevos, "actualizados": actualizados, "errores": errores}


# ── CATEGORÍAS ──

categorias_cache = {}

@router.get("/categorias")
def listar_categorias(db: Session = Depends(get_db)):
    categorias = db.query(Categoria).order_by(Categoria.nombre).all()
    return [
        {
            "id": c.id,
            "nombre": c.nombre,
            "descripcion": c.descripcion or "",
        }
        for c in categorias
    ]


@router.post("/categorias")
def crear_categoria(data: dict, db: Session = Depends(get_db)):
    nombre = data.get("nombre", "").strip()
    if not nombre:
        raise HTTPException(status_code=400, detail="El nombre es requerido")
    
    existente = db.query(Categoria).filter(Categoria.nombre.ilike(nombre)).first()
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
        a.precio_venta = data["precio_venta"]
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
