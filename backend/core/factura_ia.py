import pdfplumber
import re
import json
import os

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

PROMPT_FACTURA = """Eres un asistente que extrae datos de facturas de proveedores de neumáticos. 
Del siguiente texto de factura, extrae en JSON con esta estructura exacta:
{
  "proveedor": "nombre del proveedor",
  "numero_factura": "número de factura",
  "fecha": "fecha en formato YYYY-MM-DD",
  "total": "monto total como número",
  "metodo_pago": "efectivo, cheque, transferencia o cuenta_corriente",
  "items": [
    {"descripcion": "nombre del producto", "cantidad": número, "costo_unitario": número}
  ]
}
Solo devuelve el JSON, sin texto adicional.
"""


def extraer_texto_pdf(pdf_path: str) -> str:
    texto = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                texto += t + "\n"
    return texto


def parsear_factura_ia(texto_factura: str) -> dict:
    if not OPENAI_API_KEY:
        return parsear_factura_regex(texto_factura)
    
    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": PROMPT_FACTURA},
                {"role": "user", "content": texto_factura[:4000]}
            ],
            temperature=0
        )
        result = response.choices[0].message.content.strip()
        if result.startswith("```json"):
            result = result[7:]
        if result.startswith("```"):
            result = result[3:]
        if result.endswith("```"):
            result = result[:-3]
        return json.loads(result.strip())
    except Exception as e:
        print(f"Error IA: {e}")
        return parsear_factura_regex(texto_factura)


def parsear_factura_regex(texto: str) -> dict:
    texto = texto.upper()
    
    proveedor_match = re.search(r'(?:RAZÓN SOCIAL|SUPPLIER|PROVEEDOR)[:\s]*([A-ZÁÉÍÓÚÑ\s]+?)(?:\n|FACTURA)', texto)
    proveedor = proveedor_match.group(1).strip()[:100] if proveedor_match else "Proveedor"
    
    nro_match = re.search(r'(?:FACTURA|NRO|NÚMERO|N\.)[:\s]*([A-Z]?[\d\-]+)', texto)
    numero = nro_match.group(1).strip() if nro_match else ""
    
    fecha_match = re.search(r'(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})', texto)
    if fecha_match:
        d, m, a = fecha_match.groups()
        a = a if len(a) == 4 else f"20{a}" if int(a) < 50 else f"19{a}"
        fecha = f"{a}-{int(m):02d}-{int(d):02d}"
    else:
        from datetime import date
        fecha = date.today().isoformat()
    
    total_match = re.search(r'(?:TOTAL|IMPORTE TOTAL)[:\s]*\$?\s*([\d.,]+)', texto)
    total = float(total_match.group(1).replace(",", ".").replace(".", "").replace(",", ".")) if total_match else 0
    
    pago_match = re.search(r'(?:FORMA\s+DE\s+PAGO|PAGO)[:\s]*([A-ZÁÉÍÓÚÑ]+)', texto)
    if pago_match:
        pago_text = pago_match.group(1).upper()
        if "CTA CTE" in pago_text or "CORRIENTE" in pago_text:
            metodo = "cuenta_corriente"
        elif "TRANSF" in pago_text:
            metodo = "transferencia"
        elif "CHEQU" in pago_text:
            metodo = "cheque"
        else:
            metodo = "efectivo"
    else:
        metodo = "efectivo"
    
    items = []
    lines = texto.split('\n')
    for line in lines:
        qty_match = re.search(r'(\d+)\s*(?:X|UN|UNID|UNIDADES?|U\.?)\s*\$?\s*([\d.,]+)', line)
        price_match = re.search(r'\$?\s*([\d.,]+)\s*(?:X|UN|UNID)', line)
        
        if qty_match or price_match:
            desc = re.sub(r'[\d.,\s$]+', '', line).strip()
            if len(desc) > 3:
                cantidad = int(qty_match.group(1)) if qty_match else 1
                precio = float((qty_match.group(2) or price_match.group(1) or "0").replace(",", "."))
                items.append({
                    "descripcion": desc[:100],
                    "cantidad": cantidad,
                    "costo_unitario": precio
                })
    
    return {
        "proveedor": proveedor,
        "numero_factura": numero,
        "fecha": fecha,
        "total": total,
        "metodo_pago": metodo,
        "items": items[:20]
    }
