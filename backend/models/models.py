from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.sql import func
from core.database import Base
from datetime import datetime


class Usuario(Base):
    __tablename__ = "usuarios"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    password_hash = Column(String)
    nombre = Column(String)
    rol = Column(String, default="operador")


class Cliente(Base):
    __tablename__ = "clientes"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String, index=True)
    telefono = Column(String, default="")
    dni_cuit = Column(String, default="")
    saldo_deudor = Column(Float, default=0)
    fecha_creacion = Column(DateTime, default=datetime.utcnow)
    activo = Column(Boolean, default=True)


class Vehiculo(Base):
    __tablename__ = "vehiculos"
    id = Column(Integer, primary_key=True, index=True)
    patente = Column(String, unique=True, index=True)
    modelo = Column(String, default="")
    cliente_id = Column(Integer, ForeignKey("clientes.id"), nullable=True)
    activo = Column(Boolean, default=True)


class Producto(Base):
    __tablename__ = "productos"
    id = Column(Integer, primary_key=True, index=True)
    marca = Column(String, default="")
    modelo = Column(String, default="")
    descripcion = Column(String, default="")
    medida = Column(String, default="")
    sku = Column(String, default="")
    codigo = Column(String, default="")
    tipo = Column(String, default="neumatico")
    precio_costo = Column(Float, default=0)
    costo_base = Column(Float, default=0)
    margen_ganancia = Column(Float, default=0)
    precio_venta_final = Column(Float, default=0)
    precio_venta_contado = Column(Float, default=0)
    precio_cuota_6 = Column(Float, default=0)
    precio_cuota_12 = Column(Float, default=0)
    stock_real = Column(Integer, default=0)
    stock_local = Column(Integer, default=0)
    activo = Column(Boolean, default=True)
    imagen_url = Column(String, default="")
    categoria = Column(String, default="")
    proveedor = Column(String, default="")
    publicar_web = Column(Boolean, default=True)
    foto_base64 = Column(Text, default="")


class Servicio(Base):
    __tablename__ = "servicios"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String)
    descripcion = Column(String, default="")
    precio_sugerido = Column(Float, default=0)
    activo = Column(Boolean, default=True)


class Categoria(Base):
    __tablename__ = "categorias"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String, index=True)
    descripcion = Column(String, default="")
    fecha_creacion = Column(DateTime, server_default=func.now())


class CoeficienteFinanciacion(Base):
    __tablename__ = "coeficientes_financiacion"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String)
    proveedor = Column(String, default="")
    cuotas = Column(Integer, default=1)
    coeficiente = Column(Float, default=1.0)
    unidad_negocio_id = Column(Integer, default=28)
    activo = Column(Boolean, default=True)


class Venta(Base):
    __tablename__ = "ventas"
    id = Column(Integer, primary_key=True, index=True)
    fecha_creacion = Column(DateTime, server_default=func.now())
    cliente_id = Column(Integer, ForeignKey("clientes.id"), nullable=True)
    cliente_nombre = Column(String, default="")
    cliente_telefono = Column(String, default="")
    vehiculo_patente = Column(String, default="")
    vehiculo_modelo = Column(String, default="")
    vehiculo_id = Column(Integer, ForeignKey("vehiculos.id"), nullable=True)
    kilometraje = Column(Integer, default=0)
    es_cotizacion = Column(Boolean, default=False)
    cotizacion_original_id = Column(Integer, nullable=True)
    items = Column(Text, default="[]")  # JSON string
    subtotal_neto = Column(Float, default=0)
    monto_bonificacion = Column(Float, default=0)
    alicuota_iva = Column(Float, default=0)
    total_venta = Column(Float, default=0)
    metodo_pago = Column(String, default="Efectivo")
    coeficiente_id = Column(Integer, nullable=True)
    monto_abonado = Column(Float, default=0)
    monto_debe = Column(Float, default=0)
    enviar_a_taller = Column(Boolean, default=False)
    observaciones = Column(String, default="")
    datos_cliente_snapshot = Column(Text, default="{}")  # JSON string


class IngresoTaller(Base):
    __tablename__ = "ingresos_taller"
    id = Column(Integer, primary_key=True, index=True)
    fecha_ingreso = Column(DateTime, server_default=func.now())
    vehiculo_modelo = Column(String, default="")
    vehiculo_patente = Column(String, default="")
    cliente_nombre = Column(String, default="")
    cliente_telefono = Column(String, default="")
    mecanico_nombre = Column(String, default="")
    estado = Column(String, default="PENDIENTE")
    venta_ref_id = Column(Integer, nullable=True)
    items = Column(String, default="[]")


class Turno(Base):
    __tablename__ = "turnos"
    id = Column(Integer, primary_key=True, index=True)
    fecha_hora = Column(DateTime)
    vehiculo_modelo = Column(String, default="")
    cliente_nombre = Column(String, default="")
    observaciones = Column(String, default="")
    estado = Column(String, default="CONFIRMADO")


class MovimientoCuenta(Base):
    __tablename__ = "movimientos_cuenta"
    id = Column(Integer, primary_key=True, index=True)
    cliente_id = Column(Integer, ForeignKey("clientes.id"))
    tipo = Column(String, default="cargo")  # cargo | pago
    monto = Column(Float, default=0)
    descripcion = Column(String, default="")
    metodo_pago = Column(String, default="")
    fecha = Column(DateTime, server_default=func.now())
    venta_id = Column(Integer, nullable=True)


class Proveedor(Base):
    __tablename__ = "proveedores"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String, index=True)
    telefono = Column(String, default="")
    email = Column(String, default="")
    cuit = Column(String, default="")
    direccion = Column(String, default="")
    saldo_deudor = Column(Float, default=0)
    activo = Column(Boolean, default=True)
    fecha_creacion = Column(DateTime, server_default=func.now())


class CompraProveedor(Base):
    __tablename__ = "compras_proveedor"
    id = Column(Integer, primary_key=True, index=True)
    proveedor_id = Column(Integer, ForeignKey("proveedores.id"))
    fecha = Column(DateTime, server_default=func.now())
    descripcion = Column(String, default="")
    numero_factura = Column(String, default="")
    items = Column(Text, default="[]")  # JSON
    total = Column(Float, default=0)
    metodo_pago = Column(String, default="efectivo")  # efectivo | cheque | cuenta_corriente
    pagado = Column(Float, default=0)
    observaciones = Column(String, default="")


class MovimientoProveedor(Base):
    __tablename__ = "movimientos_proveedor"
    id = Column(Integer, primary_key=True, index=True)
    proveedor_id = Column(Integer, ForeignKey("proveedores.id"))
    tipo = Column(String, default="cargo")  # cargo | pago
    monto = Column(Float, default=0)
    descripcion = Column(String, default="")
    metodo_pago = Column(String, default="")  # efectivo | cheque | transferencia
    numero_cheque = Column(String, default="")
    fecha = Column(DateTime, server_default=func.now())
    compra_id = Column(Integer, nullable=True)


class MovimientoCliente(Base):
    __tablename__ = "movimientos_cliente"
    id = Column(Integer, primary_key=True, index=True)
    cliente_id = Column(Integer, ForeignKey("clientes.id"))
    tipo = Column(String, default="credito")  # credito | pago
    monto = Column(Float, default=0)
    descripcion = Column(String, default="")
    metodo_pago = Column(String, default="efectivo")
    fecha = Column(DateTime, server_default=func.now())
    venta_id = Column(Integer, nullable=True)


class Empleado(Base):
    __tablename__ = "empleados"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String, index=True)
    telefono = Column(String, default="")
    activo = Column(Boolean, default=True)
    fecha_creacion = Column(DateTime, server_default=func.now())


class SueldoEmpleado(Base):
    __tablename__ = "sueldos_empleado"
    id = Column(Integer, primary_key=True, index=True)
    empleado_id = Column(Integer, ForeignKey("empleados.id"))
    mes = Column(Integer)  # 1-12
    anio = Column(Integer)  # 2025, 2026, etc.
    monto_sueldo = Column(Float, default=0)
    total_adelantos = Column(Float, default=0)
    saldo = Column(Float, default=0)  # sueldo - adelantos
    pagado = Column(Boolean, default=False)
    fecha_creacion = Column(DateTime, server_default=func.now())


class AdelantoEmpleado(Base):
    __tablename__ = "adelantos_empleado"
    id = Column(Integer, primary_key=True, index=True)
    empleado_id = Column(Integer, ForeignKey("empleados.id"))
    mes = Column(Integer)
    anio = Column(Integer)
    monto = Column(Float, default=0)
    descripcion = Column(String, default="")
    fecha = Column(DateTime, server_default=func.now())
