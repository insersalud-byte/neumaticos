import json
import io
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import inspect, text
from core.database import get_db, engine

router = APIRouter(prefix="/api/v1/backup", tags=["backup"])


def _export_all_tables(db: Session) -> dict:
    inspector = inspect(engine)
    table_names = inspector.get_table_names()
    dump = {}
    for table in table_names:
        rows = db.execute(text(f'SELECT * FROM "{table}"')).mappings().all()
        dump[table] = [dict(r) for r in rows]
    return dump


@router.get("/descargar")
def descargar_backup(db: Session = Depends(get_db)):
    """Descarga un backup completo en JSON."""
    try:
        dump = _export_all_tables(db)
        fecha = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"giorda_backup_{fecha}.json"
        content = json.dumps(dump, ensure_ascii=False, indent=2, default=str)
        return StreamingResponse(
            io.BytesIO(content.encode("utf-8")),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/crear")
def crear_backup(db: Session = Depends(get_db)):
    """Genera backup y lo retorna como JSON descargable."""
    try:
        dump = _export_all_tables(db)
        fecha = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"giorda_backup_{fecha}.json"
        content = json.dumps(dump, ensure_ascii=False, default=str)
        return StreamingResponse(
            io.BytesIO(content.encode("utf-8")),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/listar")
def listar_backups():
    """Con PostgreSQL/Vercel no hay archivos locales."""
    return []


@router.post("/restaurar")
async def restaurar_backup(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """
    Restaura la base desde un archivo .json generado por este sistema.
    Hace INSERT ... ON CONFLICT DO NOTHING para no duplicar registros existentes.
    """
    try:
        raw = await file.read()
        dump: dict = json.loads(raw.decode("utf-8"))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Archivo inválido: {e}")

    errors = []
    for table, rows in dump.items():
        if not rows:
            continue
        try:
            cols = list(rows[0].keys())
            cols_quoted = ", ".join(f'"{c}"' for c in cols)
            placeholders = ", ".join(f":{c}" for c in cols)
            sql = text(
                f'INSERT INTO "{table}" ({cols_quoted}) VALUES ({placeholders}) '
                f'ON CONFLICT DO NOTHING'
            )
            for row in rows:
                db.execute(sql, row)
        except Exception as e:
            errors.append(f"{table}: {e}")

    db.commit()
    return {"ok": True, "mensaje": "Restauración completada", "errores": errors}
