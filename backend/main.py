import os
import sys
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from core.database import engine, SessionLocal, Base
from core.auth import hash_password
from models.models import (
    Usuario, CoeficienteFinanciacion, Servicio
)
from routers import auth, operaciones, finanzas, crm, reportes, taller, cuenta_corriente, compras, articulos, sueldos, backup

app = FastAPI(title="GiordaOS API", version="1.0.0")

def get_base_path():
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        internal_dir = os.path.join(exe_dir, '_internal')
        if os.path.isdir(internal_dir):
            return internal_dir
        return exe_dir
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BASE_PATH = get_base_path()
FRONTEND_DIR = os.path.join(BASE_PATH, "frontend")

# Routers
app.include_router(auth.router)
app.include_router(operaciones.router)
app.include_router(finanzas.router)
app.include_router(crm.router)
app.include_router(reportes.router)
app.include_router(taller.router)
app.include_router(cuenta_corriente.router)
app.include_router(compras.router)
app.include_router(articulos.router)
app.include_router(sueldos.router)
app.include_router(backup.router)

# Static files
app.mount("/admin", StaticFiles(directory=os.path.join(FRONTEND_DIR, "admin"), html=True), name="admin")


@app.get("/login.html")
def serve_login():
    return FileResponse(os.path.join(FRONTEND_DIR, "login.html"))


@app.get("/")
def root():
    return FileResponse(os.path.join(FRONTEND_DIR, "login.html"))


@app.get("/api/v1/finanzas/admin/coeficientes-tarjetas")
def serve_coeficientes():
    return FileResponse(os.path.join(FRONTEND_DIR, "admin", "coeficientes-tarjetas.html"))


@app.get("/Backups_GiordaOS/{filename}")
def serve_backup_file(filename: str):
    backup_path = os.path.join(BASE_PATH, "..", "Backups_GiordaOS", filename)
    if os.path.exists(backup_path):
        return FileResponse(backup_path)
    raise HTTPException(status_code=404, detail="Archivo no encontrado")


@app.on_event("startup")
def startup_seed():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        # Seed usuarios
        if not db.query(Usuario).first():
            db.add(Usuario(username="sergio", password_hash=hash_password("giorda123"), nombre="Sergio Giorda", rol="gerencia"))
            db.add(Usuario(username="invitado", password_hash=hash_password("demo"), nombre="Invitado", rol="operador"))
            db.commit()

        # Seed coeficientes de financiación
        if not db.query(CoeficienteFinanciacion).first():
            planes = [
                ("GALICIA NAVE 3 Cuotas", 3, 1.05),
                ("GALICIA NAVE 6 Cuotas", 6, 1.18),
                ("GALICIA NAVE 12 Cuotas", 12, 1.26),
                ("Naranja Z 1 Pago", 1, 1.11),
                ("Naranja 6 Cuotas", 6, 1.20),
                ("Naranja 10 Cuotas", 10, 1.32),
                ("Prov. Visa/Master 12 Cuotas", 12, 1.32),
                ("Visa/Master 3 Cuotas", 3, 1.20),
                ("Visa/Master 6 Cuotas", 6, 1.36),
                ("Prov. Naranja 10 Cuotas", 10, 1.25),
            ]
            for nombre, cuotas, coef in planes:
                db.add(CoeficienteFinanciacion(nombre=nombre, cuotas=cuotas, coeficiente=coef, unidad_negocio_id=28))
            db.commit()

        # Seed servicios
        if not db.query(Servicio).first():
            servicios = [
                ("ALINEADO AUTO", 25000),
                ("BALANCEADO AUTO", 8000),
                ("ALINEADO CAMIONETA", 35000),
                ("BALANCEADO CAMIONETA", 12000),
                ("ROTACION", 5000),
                ("MANO DE OBRA", 30000),
                ("PARCHE AUTO", 3000),
            ]
            for nombre, precio in servicios:
                db.add(Servicio(nombre=nombre, precio_sugerido=precio, activo=True))
            db.commit()
    finally:
        db.close()


if __name__ == "__main__" or getattr(sys, 'frozen', False):
    import uvicorn
    print("=" * 50)
    print("GIORDA NEUMATICOS - ERP SYSTEM")
    print("=" * 50)
    print(f"Base path: {BASE_PATH}")
    print(f"Frontend: {FRONTEND_DIR}")
    print(f"Database: {os.path.join(BASE_PATH, 'giorda.db')}")
    print("=" * 50)
    print("Iniciando servidor en http://127.0.0.1:8000")
    print("Presiona Ctrl+C para detener")
    print("=" * 50)
    uvicorn.run(app, host="127.0.0.1", port=8000)
