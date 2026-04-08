import io
import json
import os
import sys
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from core.database import get_db
from models.models import Venta, Cliente, MovimientoCuenta, Proveedor, CompraProveedor, MovimientoProveedor

router = APIRouter(prefix="/api/v1/reportes", tags=["reportes"])

def get_base_path():
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        internal_dir = os.path.join(exe_dir, '_internal')
        if os.path.isdir(internal_dir):
            return internal_dir
        return exe_dir
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Logo embebido como base64 para garantizar disponibilidad en Vercel
try:
    from routers._logo_b64 import LOGO_B64 as _LOGO_B64
    import base64 as _b64
    _logo_bytes = _b64.b64decode(_LOGO_B64)
    LOGO_IO = io.BytesIO(_logo_bytes)
except Exception:
    LOGO_IO = None
EMPRESA_INFO = {
    "nombre": "GIORDA NEUMÁTICOS",
    "direccion": "Emilio Carafa 2154",
    "telefono": "3515893288",
    "whatsapp": "35123500349",
    "email": "giordaneumaticos@hotmail.com",
}


def _header_empresa(tipo_doc="FACTURA"):
    elements = []

    if LOGO_IO:
        try:
            LOGO_IO.seek(0)
            logo = Image(LOGO_IO, width=35*mm, height=35*mm)
            elements.append(logo)
            elements.append(Spacer(1, 8*mm))
        except:
            elements.append(Spacer(1, 15*mm))
    else:
        elements.append(Spacer(1, 15*mm))

    factura_style = ParagraphStyle("Factura", fontSize=28, fontName="Helvetica-Bold", textColor=colors.HexColor("#1e3a5f"), alignment=1)
    sin_fiscal_style = ParagraphStyle("SinFiscal", fontSize=9, textColor=colors.HexColor("#888888"), alignment=1)
    nombre_style = ParagraphStyle("Nombre", fontSize=16, fontName="Helvetica-Bold", textColor=colors.HexColor("#1e3a5f"), alignment=1)
    datos_style = ParagraphStyle("Datos", fontSize=10, textColor=colors.HexColor("#444444"), leading=14, alignment=1)

    elements.append(Paragraph(tipo_doc, factura_style))
    elements.append(Spacer(1, 4*mm))
    elements.append(Paragraph("*** SIN VALOR FISCAL ***", sin_fiscal_style))
    elements.append(Spacer(1, 8*mm))
    elements.append(Paragraph("GIORDA NEUMATICOS", nombre_style))
    elements.append(Spacer(1, 3*mm))
    elements.append(Paragraph(f"Direccion: {EMPRESA_INFO['direccion']}", datos_style))
    elements.append(Paragraph(f"Tel: {EMPRESA_INFO['telefono']} | WhatsApp: {EMPRESA_INFO['whatsapp']}", datos_style))
    elements.append(Paragraph(f"Email: {EMPRESA_INFO['email']}", datos_style))
    elements.append(Spacer(1, 10*mm))
    
    return elements


@router.get("/presupuesto/{venta_id}")
def generar_presupuesto_pdf(venta_id: int, db: Session = Depends(get_db)):
    venta = db.query(Venta).filter(Venta.id == venta_id).first()
    if not venta:
        raise HTTPException(status_code=404, detail="Operación no encontrada")

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=15*mm, bottomMargin=20*mm, leftMargin=15*mm, rightMargin=15*mm)
    elements = []

    info_style = ParagraphStyle("Info", parent=getSampleStyleSheet()["Normal"], fontSize=10, spaceAfter=4)
    label_style = ParagraphStyle("Label", parent=info_style, textColor=colors.HexColor("#666666"))
    value_style = ParagraphStyle("Value", parent=info_style, textColor=colors.black, fontName="Helvetica-Bold")

    tipo = "COTIZACIÓN" if venta.es_cotizacion else "FACTURA"
    elements.extend(_header_empresa(tipo_doc=tipo))
    tipo_style = ParagraphStyle("Tipo", fontSize=14, fontName="Helvetica-Bold", textColor=colors.HexColor("#1e3a5f"), spaceAfter=8)
    elements.append(Paragraph(f"{tipo} N° {venta.id}", tipo_style))
    elements.append(Spacer(1, 3*mm))

    header_data = [
        [Paragraph("<b>DATOS DEL CLIENTE</b>", ParagraphStyle("H", fontSize=9, textColor=colors.HexColor("#999999")))],
    ]
    cliente_table = Table(header_data, colWidths=[180*mm])
    cliente_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f3f4f6")),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("ROUNDEDCORNERS", [4]),
    ]))
    elements.append(cliente_table)

    cliente_data = [
        [Paragraph("Cliente:", label_style), Paragraph(venta.cliente_nombre or "Consumidor Final", value_style)],
        [Paragraph("Teléfono:", label_style), Paragraph(venta.cliente_telefono or "-", info_style)],
        [Paragraph("Vehículo:", label_style), Paragraph(f"{venta.vehiculo_patente or '-'} {venta.vehiculo_modelo or ''}" + (f" | {venta.kilometraje:,} km" if venta.kilometraje else ""), value_style)],
        [Paragraph("Fecha:", label_style), Paragraph(venta.fecha_creacion.strftime("%d/%m/%Y %H:%M") if venta.fecha_creacion else "-", info_style)],
    ]
    cliente_table2 = Table(cliente_data, colWidths=[40*mm, 140*mm])
    cliente_table2.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.append(cliente_table2)
    elements.append(Spacer(1, 8*mm))

    items = json.loads(venta.items) if venta.items else []
    table_data = [["CANT.", "DESCRIPCIÓN", "P. UNIT.", "SUBTOTAL"]]
    for item in items:
        cant = item.get("cantidad", 1)
        desc = item.get("descripcion", "")
        precio = item.get("precio_final", 0)
        sub = cant * precio
        table_data.append([str(cant), desc, f"$ {precio:,.0f}", f"$ {sub:,.0f}"])

    table_data.append(["", "", "TOTAL:", f"$ {venta.total_venta:,.0f}"])

    col_widths = [25*mm, 105*mm, 30*mm, 30*mm]
    table = Table(table_data, colWidths=col_widths)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e3a5f")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -2), 0.5, colors.HexColor("#e5e7eb")),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#1e3a5f")),
        ("TEXTCOLOR", (0, -1), (-1, -1), colors.white),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, -1), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    elements.append(table)

    if venta.observaciones:
        elements.append(Spacer(1, 10*mm))
        elements.append(Paragraph(f"<b>Observaciones:</b> {venta.observaciones}", info_style))

    doc.build(elements)
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename=presupuesto_{venta_id}.pdf"},
    )


@router.get("/cierre-taller")
def cierre_taller_pdf(fecha_desde: str = "", fecha_hasta: str = "", db: Session = Depends(get_db)):
    from datetime import datetime
    q = db.query(Venta).filter(Venta.es_cotizacion == False)
    if fecha_desde:
        q = q.filter(Venta.fecha_creacion >= datetime.strptime(fecha_desde, "%Y-%m-%d"))
    if fecha_hasta:
        q = q.filter(Venta.fecha_creacion <= datetime.strptime(fecha_hasta + " 23:59:59", "%Y-%m-%d %H:%M:%S"))
    ventas = q.order_by(Venta.fecha_creacion.desc()).all()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=15*mm, bottomMargin=20*mm, leftMargin=15*mm, rightMargin=15*mm)
    elements = []
    info_style = ParagraphStyle("I", parent=getSampleStyleSheet()["Normal"], fontSize=10, spaceAfter=4)

    elements.extend(_header_empresa())
    elements.append(Paragraph("RESUMEN DE VENTAS", ParagraphStyle("T", fontSize=14, fontName="Helvetica-Bold", textColor=colors.HexColor("#1e3a5f"), spaceAfter=6)))
    elements.append(Paragraph(f"Período: {fecha_desde or 'Inicio'} a {fecha_hasta or 'Hoy'}", info_style))
    elements.append(Spacer(1, 6*mm))

    total_general = sum(v.total_venta or 0 for v in ventas)
    table_data = [["#", "Fecha", "Cliente", "Total"]]
    for v in ventas:
        fecha = v.fecha_creacion.strftime("%d/%m/%Y") if v.fecha_creacion else ""
        table_data.append([str(v.id), fecha, v.cliente_nombre or "", f"$ {v.total_venta:,.0f}"])
    table_data.append(["", "", "TOTAL:", f"$ {total_general:,.0f}"])

    table = Table(table_data, colWidths=[20*mm, 35*mm, 95*mm, 30*mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e3a5f")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (3, 0), (3, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -2), 0.5, colors.HexColor("#e5e7eb")),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#1e3a5f")),
        ("TEXTCOLOR", (0, -1), (-1, -1), colors.white),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    elements.append(table)
    doc.build(elements)
    buffer.seek(0)
    return StreamingResponse(buffer, media_type="application/pdf",
        headers={"Content-Disposition": "inline; filename=cierre_taller.pdf"})


@router.get("/resumen-cuenta/{cliente_id}")
def resumen_cuenta_pdf(cliente_id: int, db: Session = Depends(get_db)):
    cliente = db.query(Cliente).filter(Cliente.id == cliente_id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    movs = db.query(MovimientoCuenta).filter(
        MovimientoCuenta.cliente_id == cliente_id
    ).order_by(MovimientoCuenta.fecha.desc()).limit(100).all()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=15*mm, bottomMargin=20*mm, leftMargin=15*mm, rightMargin=15*mm)
    elements = []
    info_style = ParagraphStyle("I", parent=getSampleStyleSheet()["Normal"], fontSize=10, spaceAfter=4)

    elements.extend(_header_empresa())
    elements.append(Paragraph("ESTADO DE CUENTA", ParagraphStyle("T", fontSize=14, fontName="Helvetica-Bold", textColor=colors.HexColor("#1e3a5f"), spaceAfter=6)))
    elements.append(Paragraph(f"Cliente: {cliente.nombre}", info_style))
    elements.append(Paragraph(f"Saldo Deudor: $ {(cliente.saldo_deudor or 0):,.0f}", info_style))
    elements.append(Spacer(1, 6*mm))

    table_data = [["Fecha", "Tipo", "Descripción", "Monto"]]
    for m in movs:
        fecha = m.fecha.strftime("%d/%m/%Y") if m.fecha else ""
        signo = "-" if m.tipo == "pago" else "+"
        table_data.append([fecha, m.tipo.upper(), m.descripcion or "", f"{signo}$ {m.monto:,.0f}"])

    if len(table_data) > 1:
        table = Table(table_data, colWidths=[30*mm, 25*mm, 85*mm, 30*mm])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dc2626")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ALIGN", (3, 0), (3, -1), "RIGHT"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e5e7eb")),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        elements.append(table)
    else:
        elements.append(Paragraph("Sin movimientos registrados.", info_style))

    doc.build(elements)
    buffer.seek(0)
    return StreamingResponse(buffer, media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename=cuenta_{cliente_id}.pdf"})


@router.get("/resumen-proveedor/{proveedor_id}")
def resumen_proveedor_pdf(proveedor_id: int, db: Session = Depends(get_db)):
    prov = db.query(Proveedor).filter(Proveedor.id == proveedor_id).first()
    if not prov:
        raise HTTPException(status_code=404, detail="Proveedor no encontrado")

    compras = (
        db.query(CompraProveedor)
        .filter(CompraProveedor.proveedor_id == proveedor_id)
        .order_by(CompraProveedor.fecha.desc())
        .all()
    )

    movs = (
        db.query(MovimientoProveedor)
        .filter(MovimientoProveedor.proveedor_id == proveedor_id)
        .order_by(MovimientoProveedor.fecha.desc())
        .limit(100)
        .all()
    )

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=15*mm, bottomMargin=20*mm, leftMargin=15*mm, rightMargin=15*mm)
    elements = []
    info_style = ParagraphStyle("I", parent=getSampleStyleSheet()["Normal"], fontSize=10, spaceAfter=4)

    elements.extend(_header_empresa())
    elements.append(Paragraph("ESTADO DE CUENTA PROVEEDOR", ParagraphStyle("T", fontSize=14, fontName="Helvetica-Bold", textColor=colors.HexColor("#1e3a5f"), spaceAfter=6)))
    elements.append(Paragraph(f"Proveedor: {prov.nombre}", info_style))
    if prov.cuit:
        elements.append(Paragraph(f"CUIT: {prov.cuit}", info_style))
    elements.append(Paragraph(f"Saldo Deudor: $ {(prov.saldo_deudor or 0):,.0f}", info_style))
    elements.append(Spacer(1, 6*mm))

    impagas = [c for c in compras if (c.total or 0) - (c.pagado or 0) > 0]
    if impagas:
        elements.append(Paragraph("<b>FACTURAS IMPAGAS</b>", info_style))
        elements.append(Spacer(1, 3*mm))
        t_data = [["Fecha", "Factura", "Total", "Pagado", "Pendiente"]]
        for c in impagas:
            fecha = c.fecha.strftime("%d/%m/%Y") if c.fecha else ""
            pendiente = max(0, (c.total or 0) - (c.pagado or 0))
            t_data.append([fecha, c.numero_factura or f"#{c.id}", f"$ {c.total:,.0f}", f"$ {(c.pagado or 0):,.0f}", f"$ {pendiente:,.0f}"])
        total_impago = sum(max(0, (c.total or 0) - (c.pagado or 0)) for c in impagas)
        t_data.append(["", "", "", "TOTAL:", f"$ {total_impago:,.0f}"])

        table = Table(t_data, colWidths=[28*mm, 35*mm, 35*mm, 35*mm, 35*mm])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dc2626")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
            ("GRID", (0, 0), (-1, -2), 0.5, colors.HexColor("#e5e7eb")),
            ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#1e3a5f")),
            ("TEXTCOLOR", (0, -1), (-1, -1), colors.white),
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        elements.append(table)
        elements.append(Spacer(1, 8*mm))

    elements.append(Paragraph("<b>MOVIMIENTOS</b>", info_style))
    elements.append(Spacer(1, 3*mm))
    if movs:
        m_data = [["Fecha", "Tipo", "Descripción", "Monto"]]
        for m in movs:
            fecha = m.fecha.strftime("%d/%m/%Y") if m.fecha else ""
            signo = "-" if m.tipo == "pago" else "+"
            m_data.append([fecha, m.tipo.upper(), m.descripcion or "", f"{signo}$ {m.monto:,.0f}"])

        table2 = Table(m_data, colWidths=[30*mm, 25*mm, 85*mm, 30*mm])
        table2.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dc2626")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ALIGN", (3, 0), (3, -1), "RIGHT"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e5e7eb")),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        elements.append(table2)
    else:
        elements.append(Paragraph("Sin movimientos registrados.", info_style))

    doc.build(elements)
    buffer.seek(0)
    return StreamingResponse(buffer, media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename=proveedor_{proveedor_id}.pdf"})


@router.get("/facturas-impagas-cliente/{cliente_id}")
def facturas_impagas_cliente(cliente_id: int, db: Session = Depends(get_db)):
    cliente = db.query(Cliente).filter(Cliente.id == cliente_id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    ventas = (
        db.query(Venta)
        .filter(Venta.cliente_id == cliente_id, Venta.es_cotizacion == False, Venta.monto_debe > 0)
        .order_by(Venta.fecha_creacion.desc())
        .all()
    )
    return {
        "cliente": {"id": cliente.id, "nombre": cliente.nombre, "saldo_deudor": cliente.saldo_deudor or 0},
        "facturas_impagas": [
            {
                "id": v.id,
                "fecha": v.fecha_creacion.isoformat() if v.fecha_creacion else None,
                "descripcion": f"Venta #{v.id}",
                "total": v.total_venta,
                "pagado": v.monto_abonado or 0,
                "pendiente": v.monto_debe or 0,
            }
            for v in ventas
        ],
        "total_impago": sum(v.monto_debe or 0 for v in ventas),
    }
