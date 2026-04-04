from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional
import os
import sys

router = APIRouter(prefix="/api/v1/backup", tags=["backup"])

def get_base_path():
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        internal_dir = os.path.join(exe_dir, '_internal')
        if os.path.isdir(internal_dir):
            return internal_dir
        return exe_dir
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BASE_PATH = get_base_path()
DB_PATH = os.path.join(BASE_PATH, "giorda.db")
BACKUP_DIR = os.path.join(BASE_PATH, "Backups_GiordaOS")
os.makedirs(BACKUP_DIR, exist_ok=True)

def _backup():
    import shutil
    from datetime import datetime
    
    fecha = datetime.now().strftime("%Y%m%d_%H%M%S")
    nombre = f"giorda_{fecha}"
    ruta_db = os.path.join(BACKUP_DIR, f"{nombre}.db")
    
    shutil.copy(DB_PATH, ruta_db)
    
    import sqlite3
    ruta_sql = os.path.join(BACKUP_DIR, f"{nombre}.sql")
    conn = sqlite3.connect(DB_PATH)
    with open(ruta_sql, "w", encoding="utf-8") as f:
        for line in conn.iterdump():
            f.write(line + "\n")
    conn.close()
    
    return {"ok": True, "archivo": f"{nombre}.db"}


def _listar():
    import os
    if not os.path.exists(BACKUP_DIR):
        return []
    archivos = sorted(os.listdir(BACKUP_DIR), reverse=True)
    from datetime import datetime
    resultado = []
    for a in archivos:
        ruta = os.path.join(BACKUP_DIR, a)
        resultado.append({
            "nombre": a,
            "fecha": datetime.fromtimestamp(os.path.getmtime(ruta)).strftime("%Y-%m-%d %H:%M"),
            "tamano": os.path.getsize(ruta)
        })
    return resultado


class RestoreRequest(BaseModel):
    archivo: str


@router.post("/crear")
def crear_backup():
    try:
        result = _backup()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/listar")
def listar_backups():
    try:
        return _listar()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/restaurar")
def restaurar_backup(data: RestoreRequest):
    import shutil
    import sqlite3
    
    ruta = os.path.join(BACKUP_DIR, data.archivo)
    if not os.path.exists(ruta):
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    
    try:
        if data.archivo.endswith(".sql"):
            conn = sqlite3.connect(DB_PATH)
            for line in open(ruta, encoding="utf-8"):
                if line.strip():
                    try:
                        conn.execute(line)
                    except:
                        pass
            conn.commit()
            conn.close()
        else:
            shutil.copy(ruta, DB_PATH)
        
        return {"ok": True, "mensaje": f"Restaurado desde: {data.archivo}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
