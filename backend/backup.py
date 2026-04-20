import sqlite3
import shutil
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "giorda.db")
BACKUP_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "Backups_GiordaOS")

if os.environ.get("VERCEL") != "1":
    os.makedirs(BACKUP_DIR, exist_ok=True)

def hacer_backup():
    fecha = datetime.now().strftime("%Y%m%d_%H%M%S")
    nombre = f"giorda_{fecha}"
    
    ruta_db = os.path.join(BACKUP_DIR, f"{nombre}.db")
    ruta_sql = os.path.join(BACKUP_DIR, f"{nombre}.sql")
    
    shutil.copy(DB_PATH, ruta_db)
    
    conn = sqlite3.connect(DB_PATH)
    with open(ruta_sql, "w", encoding="utf-8") as f:
        for line in conn.iterdump():
            f.write(line + "\n")
    conn.close()
    
    archivos = sorted(os.listdir(BACKUP_DIR))
    return {
        "ok": True,
        "fecha": fecha,
        "archivos": archivos,
        "mensaje": f"Backup creado: {nombre}"
    }

def listar_backups():
    if not os.path.exists(BACKUP_DIR):
        return []
    archivos = sorted(os.listdir(BACKUP_DIR), reverse=True)
    resultado = []
    for a in archivos:
        ruta = os.path.join(BACKUP_DIR, a)
        resultado.append({
            "nombre": a,
            "fecha": datetime.fromtimestamp(os.path.getmtime(ruta)).strftime("%Y-%m-%d %H:%M"),
            "tamano": os.path.getsize(ruta)
        })
    return resultado

def restaurar_backup(nombre_archivo):
    ruta = os.path.join(BACKUP_DIR, nombre_archivo)
    if not os.path.exists(ruta):
        return {"ok": False, "error": "Archivo no encontrado"}
    
    if nombre_archivo.endswith(".sql"):
        conn = sqlite3.connect(DB_PATH)
        conn.execute("DROP TABLE IF EXISTS sqlite_stat1")
        conn.execute("DROP TABLE IF EXISTS sqlite_stat2")
        conn.execute("DROP TABLE IF EXISTS sqlite_stat3")
        conn.execute("DROP TABLE IF EXISTS sqlite_stat4")
        conn.execute("DROP TABLE IF EXISTS sqlite_master")
        for line in open(ruta, encoding="utf-8"):
            if line.strip():
                conn.execute(line)
        conn.commit()
        conn.close()
    else:
        shutil.copy(ruta, DB_PATH)
    
    return {"ok": True, "mensaje": f"Restaurado desde: {nombre_archivo}"}

def restaurar_sql_directo(sql_path):
    if not os.path.exists(sql_path):
        return {"ok": False, "error": "Archivo no encontrado"}
    
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DROP TABLE IF EXISTS sqlite_stat1")
    conn.execute("DROP TABLE IF EXISTS sqlite_stat2")
    conn.execute("DROP TABLE IF EXISTS sqlite_stat3")
    conn.execute("DROP TABLE IF EXISTS sqlite_stat4")
    conn.execute("DROP TABLE IF EXISTS sqlite_master")
    for line in open(sql_path, encoding="utf-8"):
        if line.strip():
            try:
                conn.execute(line)
            except:
                pass
    conn.commit()
    conn.close()
    return {"ok": True, "mensaje": "Restaurado exitosamente"}

if __name__ == "__main__":
    print("Backup GiordaOS")
    print("1. Hacer backup")
    print("2. Listar backups")
    op = input("Opcion: ")
    if op == "1":
        print(hacer_backup())
    elif op == "2":
        for b in listar_backups():
            print(f"{b['nombre']} - {b['fecha']} - {b['tamano']} bytes")
