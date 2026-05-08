"""
API pública para el asistente de WhatsApp.

Endpoint único optimizado: devuelve catálogo + servicios + info de empresa
en un formato que el LLM puede leer directamente.

Sin auth (lectura pública). Si querés restringirlo, agregá un header X-Bot-Key
y validalo contra una variable de entorno.
"""
from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session
from sqlalchemy import or_
from core.database import get_db
from models.models import Producto, Servicio
import os

router = APIRouter(prefix="/api/v1/bot", tags=["bot"])

EMPRESA = {
    "nombre": "Giorda Neumáticos",
    "direccion": "Caraffa 2154, Córdoba Capital",
    "telefono": "+54 9 351 235 0349",
    "horario": "Lunes a Sábado 8:30 a 13:00 / 16:00 a 20:00",
    "web": "https://giordaneumaticos.com.ar",
    "turnos": "https://giordaneumaticos.com.ar/turnos",
    "metodos_pago": "Efectivo, débito, crédito en cuotas, Mercado Pago",
}


def _verify_key(x_bot_key: str | None) -> bool:
    """Si BOT_API_KEY está seteada en env, exige el header. Si no, deja pasar."""
    expected = os.environ.get("BOT_API_KEY")
    if not expected:
        return True
    return x_bot_key == expected


@router.get("/catalogo")
def catalogo_json(
    buscar: str = Query("", description="Filtra productos por marca/modelo/medida"),
    solo_con_stock: bool = Query(True),
    limite: int = Query(80, le=200),
    db: Session = Depends(get_db),
):
    """JSON estructurado con todo lo que el bot necesita."""
    q = db.query(Producto).filter(Producto.activo == True, Producto.publicar_web == True)
    if solo_con_stock:
        q = q.filter(Producto.stock_real > 0)
    if buscar:
        terms = buscar.strip().split()
        for t in terms:
            like = f"%{t}%"
            q = q.filter(
                or_(
                    Producto.marca.ilike(like),
                    Producto.modelo.ilike(like),
                    Producto.medida.ilike(like),
                    Producto.descripcion.ilike(like),
                    Producto.categoria.ilike(like),
                )
            )

    productos = q.limit(limite).all()
    servicios = db.query(Servicio).filter(Servicio.activo == True).all()

    return {
        "empresa": EMPRESA,
        "productos": [
            {
                "id": p.id,
                "marca": p.marca,
                "modelo": p.modelo,
                "medida": p.medida,
                "descripcion": p.descripcion,
                "categoria": p.categoria,
                "tipo": p.tipo,
                "precio_contado": round(p.precio_venta_contado or p.precio_venta_final or 0),
                "precio_lista": round(p.precio_venta_final or 0),
                "precio_6_cuotas": round(p.precio_cuota_6 or 0),
                "precio_12_cuotas": round(p.precio_cuota_12 or 0),
                "stock": p.stock_real,
            }
            for p in productos
        ],
        "servicios": [
            {"nombre": s.nombre, "precio": round(s.precio_sugerido or 0), "descripcion": s.descripcion}
            for s in servicios
        ],
        "total_productos": len(productos),
        "total_servicios": len(servicios),
    }


@router.get("/contexto", response_class=PlainTextResponse)
def contexto_texto(
    buscar: str = Query("", description="Filtra productos por marca/modelo/medida"),
    limite: int = Query(60, le=200),
    db: Session = Depends(get_db),
):
    """
    Devuelve el catálogo como TEXTO plano formateado, ideal para inyectar
    directamente en el prompt del modelo (es lo que el bot consume).
    """
    q = db.query(Producto).filter(
        Producto.activo == True,
        Producto.publicar_web == True,
        Producto.stock_real > 0,
    )
    if buscar:
        terms = buscar.strip().split()
        for t in terms:
            like = f"%{t}%"
            q = q.filter(
                or_(
                    Producto.marca.ilike(like),
                    Producto.modelo.ilike(like),
                    Producto.medida.ilike(like),
                )
            )

    productos = q.limit(limite).all()
    servicios = db.query(Servicio).filter(Servicio.activo == True).all()

    lines: list[str] = []
    lines.append(f"# {EMPRESA['nombre']}")
    lines.append(f"📍 {EMPRESA['direccion']}")
    lines.append(f"📞 {EMPRESA['telefono']}")
    lines.append(f"🕐 {EMPRESA['horario']}")
    lines.append(f"🌐 {EMPRESA['web']}")
    lines.append(f"💳 {EMPRESA['metodos_pago']}")
    lines.append("")

    if servicios:
        lines.append("## Servicios")
        lines.append("| Servicio | Precio |")
        lines.append("|---|---|")
        for s in servicios:
            precio = f"${round(s.precio_sugerido or 0):,}".replace(",", ".")
            lines.append(f"| {s.nombre} | {precio} |")
        lines.append("")

    if productos:
        lines.append("## Productos disponibles (con stock)")
        lines.append("| Marca | Modelo | Medida | Precio contado | 6 cuotas | 12 cuotas | Stock |")
        lines.append("|---|---|---|---|---|---|---|")
        for p in productos:
            pc = round(p.precio_venta_contado or p.precio_venta_final or 0)
            p6 = round(p.precio_cuota_6 or 0)
            p12 = round(p.precio_cuota_12 or 0)
            fmt = lambda n: f"${n:,}".replace(",", ".") if n else "—"
            lines.append(
                f"| {p.marca or '—'} | {p.modelo or '—'} | {p.medida or '—'} | "
                f"{fmt(pc)} | {fmt(p6)} | {fmt(p12)} | {p.stock_real} |"
            )
        lines.append("")

    if not productos and buscar:
        lines.append(f"_Sin resultados para: '{buscar}'_")

    lines.append("---")
    lines.append(f"Para sacar turno: {EMPRESA['turnos']}")

    return "\n".join(lines)


@router.get("/buscar")
def buscar_producto(
    q: str = Query(..., min_length=2, description="Término a buscar"),
    db: Session = Depends(get_db),
):
    """Búsqueda específica para que el bot consulte productos puntuales."""
    terms = q.strip().split()
    query = db.query(Producto).filter(
        Producto.activo == True, Producto.publicar_web == True
    )
    for t in terms:
        like = f"%{t}%"
        query = query.filter(
            or_(
                Producto.marca.ilike(like),
                Producto.modelo.ilike(like),
                Producto.medida.ilike(like),
                Producto.descripcion.ilike(like),
            )
        )
    resultados = query.limit(20).all()
    return {
        "consulta": q,
        "encontrados": len(resultados),
        "productos": [
            {
                "marca": p.marca,
                "modelo": p.modelo,
                "medida": p.medida,
                "descripcion": p.descripcion,
                "precio_contado": round(p.precio_venta_contado or p.precio_venta_final or 0),
                "precio_6_cuotas": round(p.precio_cuota_6 or 0),
                "precio_12_cuotas": round(p.precio_cuota_12 or 0),
                "stock": p.stock_real,
                "disponible": p.stock_real > 0,
            }
            for p in resultados
        ],
    }


@router.get("/empresa")
def info_empresa():
    """Datos básicos de la empresa para el bot."""
    return EMPRESA
