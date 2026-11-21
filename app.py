"""Prototipo Warawak: login, cuentas de usuario, listado, creación, edición y eliminación de productos (Flask + SQLite)."""
import os
import re
import secrets
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import Flask, abort, flash, redirect, render_template, request, session, url_for
from flask_login import (
    LoginManager,
    UserMixin,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFError, CSRFProtect
from sqlalchemy import func, inspect, select, text, update
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)


def obtener_secret_key():
    """Clave que firma las sesiones.

    1) Variable de entorno SECRET_KEY (lo recomendado en un servidor).
    2) Si no existe, una clave aleatoria guardada en instance/secret_key, fuera de Git.
    Nunca queda escrita en el código.
    """
    clave = os.environ.get("SECRET_KEY")
    if clave:
        return clave
    os.makedirs(app.instance_path, exist_ok=True)
    ruta = os.path.join(app.instance_path, "secret_key")
    if os.path.isfile(ruta):
        with open(ruta, encoding="utf-8") as archivo:
            clave = archivo.read().strip()
        if len(clave) >= 32:
            return clave
    clave = secrets.token_hex(32)
    with open(ruta, "w", encoding="utf-8") as archivo:
        archivo.write(clave)
    try:
        os.chmod(ruta, 0o600)
    except OSError:
        pass
    return clave


app.config["SECRET_KEY"] = obtener_secret_key()
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///warawak.db"
app.config["MAX_CONTENT_LENGTH"] = 3 * 1024 * 1024  # tope de toda la petición
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"  # el navegador no envía la sesión desde otros sitios
app.config["SESSION_COOKIE_HTTPONLY"] = True
# En un sitio con HTTPS, define la variable de entorno SESSION_COOKIE_SECURE=1
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("SESSION_COOKIE_SECURE") == "1"
app.config["WTF_CSRF_TIME_LIMIT"] = None  # el token vale mientras dure la sesión

CARPETA_IMAGENES = os.path.join(app.static_folder, "img", "productos")
os.makedirs(CARPETA_IMAGENES, exist_ok=True)
EXTENSIONES_PERMITIDAS = {"png", "jpg", "jpeg", "webp", "gif"}
MAX_IMAGEN_BYTES = 2 * 1024 * 1024
MAX_VALOR = 100_000_000
MAX_EXISTENCIAS = 99_999     # tope de existencias por producto
UMBRAL_STOCK_BAJO = 5        # hasta esta cantidad se marca "existencias bajas"
EXISTENCIAS_EJEMPLO = 20     # para los productos de ejemplo de una base nueva
MAX_NOTA = 200
HORA_COLOMBIA = timezone(timedelta(hours=-5))  # Colombia no usa horario de verano

csrf = CSRFProtect(app)  # exige token en todos los formularios POST
db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Inicia sesión para continuar."


class Usuario(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(80), unique=True, nullable=False)
    contacto = db.Column(db.String(120), unique=True, nullable=True)  # correo o teléfono
    password_hash = db.Column(db.String(255), nullable=False)
    rol = db.Column(db.String(20), nullable=False, default="cliente")  # "cliente" o "admin"
    creado_en = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    @property
    def es_admin(self):
        return self.rol == "admin"

    def poner_password(self, password):
        self.password_hash = generate_password_hash(password)

    def verificar_password(self, password):
        return check_password_hash(self.password_hash, password)


class Producto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(120), nullable=False)
    valor = db.Column(db.Integer, nullable=False)
    descripcion = db.Column(db.Text, nullable=False, default="")
    imagen = db.Column(db.String(255), nullable=True)
    existencias = db.Column(db.Integer, nullable=False, default=0)
    movimientos = db.relationship(
        "Movimiento", backref="producto", cascade="all, delete-orphan", order_by="Movimiento.id"
    )

    @property
    def estado_stock(self):
        if self.existencias <= 0:
            return "agotado"
        return "bajo" if self.existencias <= UMBRAL_STOCK_BAJO else "disponible"

    @property
    def estado_texto(self):
        return {"agotado": "Agotado", "bajo": "Existencias bajas", "disponible": "Disponible"}[self.estado_stock]


class Movimiento(db.Model):
    """Registro de cada cambio de existencias (entrada, salida, conteo físico...)."""

    __tablename__ = "movimiento_inventario"
    id = db.Column(db.Integer, primary_key=True)
    producto_id = db.Column(db.Integer, db.ForeignKey("producto.id"), nullable=False, index=True)
    tipo = db.Column(db.String(20), nullable=False)  # inicial, entrada, salida, ajuste (venta y devolucion, más adelante)
    cantidad = db.Column(db.Integer, nullable=False)  # con signo: +entra, -sale
    saldo = db.Column(db.Integer, nullable=False)     # existencias después del movimiento
    nota = db.Column(db.String(MAX_NOTA), nullable=False, default="")
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuario.id"), nullable=True)
    creado_en = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    usuario = db.relationship("Usuario")


ESTADOS_PEDIDO = {
    "recibido": "Recibido",
    "preparacion": "En preparación",
    "entregado": "Entregado",
    "cancelado": "Cancelado",
}


def _sin_zona(fecha):
    return fecha.replace(tzinfo=None) if fecha else None


class Pedido(db.Model):
    """Pedido confirmado por un cliente. El número de pedido es su id."""

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuario.id"), nullable=False, index=True)
    estado = db.Column(db.String(20), nullable=False, default="recibido", index=True)
    unidades = db.Column(db.Integer, nullable=False)
    total = db.Column(db.Integer, nullable=False)
    nota = db.Column(db.String(MAX_NOTA), nullable=False, default="")
    token = db.Column(db.String(64), unique=True, nullable=True)  # evita pedidos duplicados por doble clic
    creado_en = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    preparacion_en = db.Column(db.DateTime, nullable=True)
    entregado_en = db.Column(db.DateTime, nullable=True)
    cancelado_en = db.Column(db.DateTime, nullable=True)
    cancelado_por = db.Column(db.String(20), nullable=True)  # "cliente" o "administrador"
    motivo = db.Column(db.String(MAX_NOTA), nullable=False, default="")
    usuario = db.relationship("Usuario")
    detalles = db.relationship("PedidoDetalle", backref="pedido", cascade="all, delete-orphan", order_by="PedidoDetalle.id")

    @property
    def estado_texto(self):
        return ESTADOS_PEDIDO.get(self.estado, self.estado)

    @property
    def segundos_espera(self):
        """Desde que se recibió hasta que empezó la preparación."""
        if self.preparacion_en and self.creado_en:
            return int((_sin_zona(self.preparacion_en) - _sin_zona(self.creado_en)).total_seconds())
        return None

    @property
    def segundos_total(self):
        """Desde que se recibió hasta que se entregó."""
        if self.entregado_en and self.creado_en:
            return int((_sin_zona(self.entregado_en) - _sin_zona(self.creado_en)).total_seconds())
        return None


class PedidoDetalle(db.Model):
    """Cada línea del pedido, con el nombre y el precio del momento de la compra."""

    __tablename__ = "pedido_detalle"
    id = db.Column(db.Integer, primary_key=True)
    pedido_id = db.Column(db.Integer, db.ForeignKey("pedido.id"), nullable=False, index=True)
    producto_id = db.Column(db.Integer, nullable=True)  # sin llave foránea: el producto puede eliminarse
    nombre = db.Column(db.String(120), nullable=False)
    valor_unitario = db.Column(db.Integer, nullable=False)
    cantidad = db.Column(db.Integer, nullable=False)

    @property
    def subtotal(self):
        return self.valor_unitario * self.cantidad


@login_manager.user_loader
def cargar_usuario(user_id):
    return db.session.get(Usuario, int(user_id))


@app.template_filter("pesos")
def formato_pesos(valor):
    """5500 -> '$ 5.500'"""
    return "$ " + f"{valor:,}".replace(",", ".")


@app.template_filter("miles")
def formato_miles(valor):
    """12000 -> '12.000'"""
    return f"{valor:,}".replace(",", ".")


@app.template_filter("fecha_local")
def formato_fecha_local(valor):
    """Fecha guardada en UTC -> '16/11/2026 14:35' en hora de Colombia."""
    if valor is None:
        return "—"
    return valor.replace(tzinfo=timezone.utc).astimezone(HORA_COLOMBIA).strftime("%d/%m/%Y %H:%M")


@app.template_filter("duracion")
def formato_duracion(segundos):
    """135 -> '2 min 15 s'"""
    if segundos is None:
        return "—"
    minutos, resto = divmod(max(segundos, 0), 60)
    horas, minutos = divmod(minutos, 60)
    if horas:
        return f"{horas} h {minutos} min"
    return f"{minutos} min {resto} s" if minutos else f"{resto} s"


TIPOS_MOVIMIENTO = {
    "inicial": "Existencias iniciales",
    "entrada": "Entrada",
    "salida": "Salida",
    "ajuste": "Conteo físico",
    "venta": "Venta",
    "devolucion": "Devolución",
}


@app.template_filter("tipo_movimiento")
def nombre_tipo_movimiento(tipo):
    return TIPOS_MOVIMIENTO.get(tipo, tipo)


@app.after_request
def cabeceras_de_seguridad(respuesta):
    respuesta.headers.setdefault("X-Content-Type-Options", "nosniff")
    respuesta.headers.setdefault("X-Frame-Options", "DENY")  # evita que otro sitio la muestre en un iframe
    respuesta.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    return respuesta


# ---------------------------------------------------------------- datos de ejemplo
PRODUCTOS_INICIALES = [
    ("Fresas con crema", 5500),
    ("Milo Caliente", 5000),
    ("Cheesecake de frutos rojos", 6000),
    ("Torta de zanahoria", 5000),
    ("Cheesecake de mango", 6000),
    ("Torta de yogurt Griego y arandanos", 6000),
    ("Jugo de Maracuya", 5500),
    ("Frape de cafe con licor", 1000),
]


def sembrar_datos():
    """Solo productos de ejemplo. Los administradores se crean con `python crear_admin.py`."""
    if Producto.query.count() == 0:
        for nombre, valor in PRODUCTOS_INICIALES:
            producto = Producto(nombre=nombre, valor=valor, existencias=EXISTENCIAS_EJEMPLO)
            producto.movimientos.append(
                Movimiento(tipo="inicial", cantidad=EXISTENCIAS_EJEMPLO, saldo=EXISTENCIAS_EJEMPLO,
                           nota="Existencias de ejemplo")
            )
            db.session.add(producto)
    db.session.commit()


def migrar_base():
    """Agrega las columnas nuevas a una base creada con una versión anterior de la app."""
    inspector = inspect(db.engine)
    columnas = {c["name"] for c in inspector.get_columns("usuario")}
    columnas_producto = {c["name"] for c in inspector.get_columns("producto")}
    with db.engine.begin() as conexion:
        if "existencias" not in columnas_producto:
            conexion.execute(text("ALTER TABLE producto ADD COLUMN existencias INTEGER NOT NULL DEFAULT 0"))
        if "contacto" not in columnas:
            conexion.execute(text("ALTER TABLE usuario ADD COLUMN contacto VARCHAR(120)"))
            conexion.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_usuario_contacto ON usuario (contacto)"))
        if "creado_en" not in columnas:
            conexion.execute(text("ALTER TABLE usuario ADD COLUMN creado_en DATETIME"))
        if "rol" not in columnas:
            conexion.execute(text("ALTER TABLE usuario ADD COLUMN rol VARCHAR(20) NOT NULL DEFAULT 'cliente'"))


with app.app_context():
    db.create_all()
    migrar_base()
    sembrar_datos()


def admin_requerido(vista):
    """Solo administradores. Sin sesión -> login; cliente con sesión -> 403."""
    @login_required
    @wraps(vista)
    def envoltura(*args, **kwargs):
        if not current_user.es_admin:
            abort(403)
        return vista(*args, **kwargs)

    return envoltura


def destino_tras_login(usuario):
    if usuario.es_admin:
        return url_for("inicio")
    return url_for("carrito") if leer_carrito() else url_for("raiz")


# ---------------------------------------------------------------- carrito (guardado en la sesión)
MAX_CANTIDAD = 20            # unidades por producto
MAX_PRODUCTOS_EN_CARRITO = 30  # productos distintos


def leer_carrito():
    """Carrito de la sesión como {id_producto: cantidad}, ya saneado."""
    crudo = session.get("carrito")
    carrito = {}
    if isinstance(crudo, dict):
        for clave, cantidad in crudo.items():
            try:
                producto_id, unidades = int(clave), int(cantidad)
            except (TypeError, ValueError):
                continue
            if 1 <= unidades <= MAX_CANTIDAD:
                carrito[producto_id] = unidades
    return carrito


def guardar_carrito(carrito):
    session["carrito"] = {str(producto_id): unidades for producto_id, unidades in carrito.items()}


def detalle_carrito():
    """(líneas, unidades, total) con los precios ACTUALES de la base de datos.

    Los productos que el administrador ya eliminó se quitan del carrito.
    """
    carrito = leer_carrito()
    if not carrito:
        return [], 0, 0
    productos = {p.id: p for p in Producto.query.filter(Producto.id.in_(list(carrito))).all()}
    lineas = [
        {
            "producto": productos[pid],
            "cantidad": cant,
            "subtotal": productos[pid].valor * cant,
            "disponible": productos[pid].existencias,
            "limite": min(MAX_CANTIDAD, productos[pid].existencias),
            "excede": cant > productos[pid].existencias,
        }
        for pid, cant in carrito.items()
        if pid in productos
    ]
    lineas.sort(key=lambda linea: linea["producto"].id)
    if len(lineas) != len(carrito):
        guardar_carrito({l["producto"].id: l["cantidad"] for l in lineas})
    return lineas, sum(l["cantidad"] for l in lineas), sum(l["subtotal"] for l in lineas)


def solo_compradores(vista):
    """El carrito es para visitantes y clientes: el administrador va a su panel."""
    @wraps(vista)
    def envoltura(*args, **kwargs):
        if current_user.is_authenticated and current_user.es_admin:
            return redirect(url_for("inicio"))
        return vista(*args, **kwargs)

    return envoltura


def _mover_stock(producto_id, delta, tipo, nota="", usuario_id=None, esperado=None, validar_tope=True):
    """Cambia las existencias y deja el movimiento en la sesión, SIN confirmar la transacción.

    - Normal: solo se aplica si las existencias resultantes no quedan negativas (ni pasan del tope).
      Es una sola sentencia UPDATE condicionada, así dos operaciones simultáneas nunca dejan el stock en negativo.
    - Con `esperado` (conteo físico): solo se aplica si las existencias siguen siendo las que se vieron.
    Devuelve el saldo resultante, o None si no se pudo aplicar.
    """
    condiciones = [Producto.id == producto_id]
    if esperado is not None:
        condiciones.append(Producto.existencias == esperado)
    else:
        condiciones.append(Producto.existencias + delta >= 0)
        if validar_tope:
            condiciones.append(Producto.existencias + delta <= MAX_EXISTENCIAS)
    resultado = db.session.execute(
        update(Producto)
        .where(*condiciones)
        .values(existencias=Producto.existencias + delta)
        .execution_options(synchronize_session=False)
    )
    if resultado.rowcount != 1:
        return None
    saldo = db.session.execute(select(Producto.existencias).where(Producto.id == producto_id)).scalar_one()
    db.session.add(
        Movimiento(producto_id=producto_id, tipo=tipo, cantidad=delta, saldo=saldo,
                   nota=nota[:MAX_NOTA], usuario_id=usuario_id)
    )
    return saldo


def aplicar_movimiento(producto_id, delta, tipo, nota="", usuario_id=None, esperado=None):
    """Un movimiento manual de inventario: se confirma o no cambia nada. Devuelve el saldo o None."""
    saldo = _mover_stock(producto_id, delta, tipo, nota, usuario_id, esperado)
    if saldo is None:
        db.session.rollback()
        return None
    db.session.commit()
    return saldo


def crear_pedido(usuario, lineas, nota, token):
    """Guarda el pedido y descuenta las existencias en UNA sola transacción.

    Si alguna línea no tiene stock suficiente, no se guarda nada (ni se descuenta nada).
    Devuelve (pedido, None) si salió bien, (pedido_existente, "duplicado") si el token ya se usó
    (doble clic) o (None, mensaje) si falta stock.
    """
    pedido = Pedido(
        usuario_id=usuario.id, token=token, nota=nota,
        unidades=sum(l["cantidad"] for l in lineas), total=sum(l["subtotal"] for l in lineas),
    )
    db.session.add(pedido)
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        return Pedido.query.filter_by(token=token, usuario_id=usuario.id).first(), "duplicado"

    for linea in sorted(lineas, key=lambda l: l["producto"].id):
        producto, cantidad = linea["producto"], linea["cantidad"]
        producto_id, nombre, valor = producto.id, producto.nombre, producto.valor
        saldo = _mover_stock(producto_id, -cantidad, "venta", f"Pedido #{pedido.id}", usuario.id)
        if saldo is None:
            db.session.rollback()
            quedan = db.session.execute(select(Producto.existencias).where(Producto.id == producto_id)).scalar() or 0
            return None, f"Ya no hay suficientes unidades de {nombre} (quedan {quedan})."
        pedido.detalles.append(
            PedidoDetalle(producto_id=producto_id, nombre=nombre, valor_unitario=valor, cantidad=cantidad)
        )
    db.session.commit()
    return pedido, None


TRANSICIONES = {
    "preparar": ("recibido", "preparacion", "preparacion_en"),
    "entregar": ("preparacion", "entregado", "entregado_en"),
}


def cambiar_estado(pedido_id, accion):
    """Avanza el pedido un paso. Solo si está en el estado de origen (evita pasos repetidos)."""
    origen, destino, columna = TRANSICIONES[accion]
    resultado = db.session.execute(
        update(Pedido)
        .where(Pedido.id == pedido_id, Pedido.estado == origen)
        .values(estado=destino, **{columna: datetime.now(timezone.utc)})
        .execution_options(synchronize_session=False)
    )
    if resultado.rowcount != 1:
        db.session.rollback()
        return False
    db.session.commit()
    return True


def cancelar_pedido(pedido_id, usuario, por, motivo=""):
    """Cancela el pedido y devuelve las existencias, todo en una transacción.

    El cliente solo puede cancelar si el pedido sigue "recibido"; el administrador, también "en preparación".
    """
    permitidos = ("recibido",) if por == "cliente" else ("recibido", "preparacion")
    resultado = db.session.execute(
        update(Pedido)
        .where(Pedido.id == pedido_id, Pedido.estado.in_(permitidos))
        .values(estado="cancelado", cancelado_en=datetime.now(timezone.utc), cancelado_por=por, motivo=motivo[:MAX_NOTA])
        .execution_options(synchronize_session=False)
    )
    if resultado.rowcount != 1:
        db.session.rollback()
        return False
    for detalle in PedidoDetalle.query.filter_by(pedido_id=pedido_id).all():
        existe = db.session.execute(select(Producto.id).where(Producto.id == detalle.producto_id)).first()
        if not existe:
            continue  # el producto ya se eliminó: no hay existencias que devolver
        saldo = _mover_stock(detalle.producto_id, detalle.cantidad, "devolucion",
                             f"Pedido #{pedido_id} cancelado", usuario.id, validar_tope=False)
        if saldo is None:
            db.session.rollback()
            return False
    db.session.commit()
    return True


def interpretar_existencias(texto):
    """'15' -> 15. Solo enteros de 0 a MAX_EXISTENCIAS; si no, None."""
    texto = texto.strip()
    if not (texto.isascii() and texto.isdigit()):
        return None
    valor = int(texto)
    return valor if valor <= MAX_EXISTENCIAS else None


@app.context_processor
def datos_del_carrito():
    es_admin = current_user.is_authenticated and current_user.es_admin
    return {
        "mostrar_carrito": not es_admin,
        "carrito_unidades": 0 if es_admin else detalle_carrito()[1],
        "pedidos_pendientes": Pedido.query.filter_by(estado="recibido").count() if es_admin else 0,
    }


# ---------------------------------------------------------------- validaciones
def interpretar_valor(texto):
    """'12.000', '$ 12000' o '12000' -> 12000. Devuelve None si no es válido."""
    limpio = texto.replace("$", "").replace(".", "").replace(",", "").replace(" ", "")
    if not (limpio.isascii() and limpio.isdigit()):
        return None
    valor = int(limpio)
    return valor if 0 < valor < MAX_VALOR else None


def extension_de(nombre_archivo):
    return nombre_archivo.rsplit(".", 1)[-1].lower() if "." in nombre_archivo else ""


def validar_foto(foto):
    """Devuelve un mensaje de error, o None si la foto es válida."""
    if extension_de(foto.filename) not in EXTENSIONES_PERMITIDAS:
        return "Formato no permitido. Usa PNG, JPG, WEBP o GIF."
    foto.seek(0, os.SEEK_END)
    tamano = foto.tell()
    foto.seek(0)
    if tamano > MAX_IMAGEN_BYTES:
        return "La imagen pesa más de 2 MB. Elige una más liviana."
    return None


def leer_formulario():
    """Lee y valida el formulario de producto (sirve para crear y para editar).

    Devuelve (datos, errores, valor, foto). `foto` es None si no se eligió ninguna.
    """
    datos = {
        campo: request.form.get(campo, "").strip()
        for campo in ("nombre", "valor", "descripcion")
    }
    errores = {}

    if not datos["nombre"]:
        errores["nombre"] = "Escribe el nombre del producto."
    elif len(datos["nombre"]) > 120:
        errores["nombre"] = "El nombre admite hasta 120 caracteres."

    valor = interpretar_valor(datos["valor"])
    if valor is None:
        errores["valor"] = (
            "Escribe un valor mayor que cero y menor a 100.000.000, "
            "solo con números (ejemplo: 12000 o 12.000)."
        )

    if len(datos["descripcion"]) > 500:
        errores["descripcion"] = "La descripción admite hasta 500 caracteres."

    foto = request.files.get("foto")
    if not (foto and foto.filename):
        foto = None
    else:
        error_foto = validar_foto(foto)
        if error_foto:
            errores["foto"] = error_foto

    return datos, errores, valor, foto


def avisar_errores(foto):
    if foto is not None:
        flash("Revisa el formulario. Vuelve a elegir la foto, porque el navegador no la conserva.", "error")
    else:
        flash("Revisa los campos marcados e intenta de nuevo.", "error")


def guardar_foto(foto):
    """Guarda la foto con un nombre aleatorio y devuelve ese nombre."""
    nombre_imagen = f"{uuid.uuid4().hex}.{extension_de(foto.filename)}"
    foto.save(os.path.join(CARPETA_IMAGENES, nombre_imagen))
    return nombre_imagen


def borrar_foto(nombre_imagen):
    if not nombre_imagen:
        return
    ruta = os.path.join(CARPETA_IMAGENES, os.path.basename(nombre_imagen))
    if os.path.isfile(ruta):
        os.remove(ruta)


def normalizar(texto):
    """Minúsculas, sin tildes ni signos: 'Sándwich-Jamón Pavo' -> 'sandwich jamon pavo'."""
    sin_tildes = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", sin_tildes.lower()).strip()


def buscar_productos(consulta):
    """Coincidencia exacta de nombre si existe; si no, nombres que contengan el texto."""
    buscado = normalizar(consulta)
    if not buscado:
        return []
    todos = Producto.query.order_by(Producto.id).all()
    exactos = [p for p in todos if normalizar(p.nombre) == buscado]
    return exactos or [p for p in todos if buscado in normalizar(p.nombre)]


CORREO_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
TELEFONO_RE = re.compile(r"^\+?[0-9]{7,15}$")


def normalizar_contacto(texto):
    """Correo (en minúsculas) o teléfono (solo dígitos y +). Devuelve None si no es ninguno."""
    texto = texto.strip()
    if len(texto) <= 120 and CORREO_RE.match(texto):
        return texto.lower()
    limpio = re.sub(r"[\s\-().]", "", texto)
    if not TELEFONO_RE.match(limpio):
        return None
    # Celulares de Colombia: +57 300 123 4567 y 300 123 4567 son el mismo número.
    colombiano = re.match(r"^(?:\+57|0057|57)([0-9]{10})$", limpio)
    return colombiano.group(1) if colombiano else limpio


def limpiar_nombre(texto):
    return " ".join(texto.split())


def usuario_por_nombre(nombre):
    """Búsqueda sin distinguir mayúsculas de minúsculas."""
    return Usuario.query.filter(func.lower(Usuario.nombre) == nombre.lower()).first()


PANELES = {
    "no_encontrado": "No se encontró el Producto",
    "eliminado": "Producto eliminado correctamente",
}


def pantalla_busqueda(accion):
    """Búsqueda por nombre, compartida por Editar y Eliminar."""
    consulta = request.args.get("q")
    panel = PANELES.get(request.args.get("resultado"))
    error = None
    encontrados = []

    if consulta is not None:
        consulta = consulta.strip()
        if not normalizar(consulta):
            error = "Escribe el nombre del producto que buscas."
        else:
            encontrados = buscar_productos(consulta)
            if len(encontrados) == 1:
                destino = "editar_producto" if accion == "editar" else "eliminar_producto"
                return redirect(url_for(destino, producto_id=encontrados[0].id))
            if not encontrados:
                panel = PANELES["no_encontrado"]

    return render_template(
        "buscar.html",
        accion=accion,
        q_valor=consulta or "",
        error=error,
        panel=panel,
        productos=encontrados,
    )


# ---------------------------------------------------------------- rutas
@app.route("/")
def raiz():
    """Menú digital público: lo ve cualquier persona, sin iniciar sesión."""
    consulta = request.args.get("q", "").strip()[:120]
    productos = Producto.query.order_by(Producto.id).all()
    buscado = normalizar(consulta)
    if buscado:
        productos = [p for p in productos if buscado in normalizar(p.nombre)]
    return render_template("menu_publico.html", productos=productos, consulta=consulta if buscado else "")


@app.route("/producto/<int:producto_id>")
def ver_producto(producto_id):
    producto = db.session.get(Producto, producto_id)
    if producto is None:
        flash("No se encontró el producto.", "error")
        return redirect(url_for("raiz"))
    return render_template(
        "producto_detalle.html", producto=producto, max_cantidad=min(MAX_CANTIDAD, producto.existencias)
    )


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(destino_tras_login(current_user))

    if request.method == "POST":
        nombre = limpiar_nombre(request.form.get("nombre", ""))
        password = request.form.get("password", "")
        usuario = usuario_por_nombre(nombre) if nombre else None
        if usuario and usuario.verificar_password(password):
            login_user(usuario)
            return redirect(destino_tras_login(usuario))
        flash("El nombre o la contraseña no coinciden. Revisa los datos e intenta de nuevo.", "error")

    return render_template("login.html")


@app.route("/registro", methods=["GET", "POST"])
def registro():
    if current_user.is_authenticated:
        return redirect(destino_tras_login(current_user))

    errores, datos = {}, {}
    if request.method == "POST":
        nombre = limpiar_nombre(request.form.get("nombre", ""))
        datos = {"nombre": nombre, "contacto": request.form.get("contacto", "").strip()}
        password = request.form.get("password", "")

        if len(nombre) < 2:
            errores["nombre"] = "Escribe tu nombre (mínimo 2 caracteres)."
        elif len(nombre) > 80:
            errores["nombre"] = "El nombre admite hasta 80 caracteres."
        elif usuario_por_nombre(nombre):
            errores["nombre"] = "Ese nombre ya está registrado. Usa otro o inicia sesión."

        contacto = normalizar_contacto(datos["contacto"])
        if contacto is None:
            errores["contacto"] = "Escribe un correo válido (nombre@dominio.com) o un teléfono de 7 a 15 dígitos."
        elif Usuario.query.filter_by(contacto=contacto).first():
            errores["contacto"] = "Ese correo o teléfono ya tiene una cuenta."

        if len(password) < 8:
            errores["password"] = "La contraseña debe tener al menos 8 caracteres."
        elif len(password) > 128:
            errores["password"] = "La contraseña admite hasta 128 caracteres."

        if not errores:
            usuario = Usuario(nombre=nombre, contacto=contacto, rol="cliente")  # nunca se toma de la web
            usuario.poner_password(password)
            db.session.add(usuario)
            try:
                db.session.commit()
            except IntegrityError:  # dos personas registrándose a la vez con los mismos datos
                db.session.rollback()
                errores["nombre"] = "No se pudo crear la cuenta porque esos datos ya existen. Revisa e intenta de nuevo."
            else:
                flash("Cuenta creada correctamente. Ya puedes iniciar sesión.", "success")
                return redirect(url_for("login"))

        flash("Revisa los campos marcados e intenta de nuevo.", "error")

    return render_template("registro.html", errores=errores, datos=datos)


@app.route("/carrito")
@solo_compradores
def carrito():
    lineas, unidades, total = detalle_carrito()
    return render_template(
        "carrito.html", lineas=lineas, unidades=unidades, total=total,
        hay_excedidos=any(l["excede"] for l in lineas),
    )


@app.route("/carrito/agregar/<int:producto_id>", methods=["POST"])
@solo_compradores
def carrito_agregar(producto_id):
    desde_detalle = request.form.get("destino") == "carrito"
    volver_a_menu = redirect(url_for("raiz", q=request.form.get("q", "").strip()[:120] or None))

    producto = db.session.get(Producto, producto_id)
    if producto is None:
        flash("No se encontró el producto.", "error")
        return redirect(url_for("raiz"))

    volver_con_error = (
        redirect(url_for("ver_producto", producto_id=producto_id)) if desde_detalle else volver_a_menu
    )
    try:
        cantidad = int(request.form.get("cantidad", "1"))
    except ValueError:
        cantidad = 0
    if not 1 <= cantidad <= MAX_CANTIDAD:
        flash(f"Elige una cantidad entre 1 y {MAX_CANTIDAD}.", "error")
        return volver_con_error

    if producto.existencias <= 0:
        flash(f"{producto.nombre} está agotado.", "error")
        return volver_con_error

    carrito_actual = leer_carrito()
    if producto_id not in carrito_actual and len(carrito_actual) >= MAX_PRODUCTOS_EN_CARRITO:
        flash(f"Tu carrito ya tiene el máximo de {MAX_PRODUCTOS_EN_CARRITO} productos distintos.", "error")
        return redirect(url_for("carrito"))

    limite = min(MAX_CANTIDAD, producto.existencias)
    nueva = carrito_actual.get(producto_id, 0) + cantidad
    if nueva > limite:
        carrito_actual[producto_id] = limite
        if producto.existencias < MAX_CANTIDAD:
            flash(f"Solo hay {producto.existencias} unidades de {producto.nombre}: tu carrito quedó en {limite}.", "error")
        else:
            flash(f"El máximo es {MAX_CANTIDAD} unidades por producto: {producto.nombre} quedó en {MAX_CANTIDAD}.", "error")
    else:
        carrito_actual[producto_id] = nueva
        flash(f"Agregado al carrito: {producto.nombre} (x{cantidad}).", "success")
    guardar_carrito(carrito_actual)

    return redirect(url_for("carrito")) if desde_detalle else volver_a_menu


@app.route("/carrito/cambiar/<int:producto_id>", methods=["POST"])
@solo_compradores
def carrito_cambiar(producto_id):
    carrito_actual = leer_carrito()
    if producto_id in carrito_actual:
        accion = request.form.get("accion")
        if accion == "mas":
            producto = db.session.get(Producto, producto_id)
            limite = min(MAX_CANTIDAD, producto.existencias) if producto else 0
            if carrito_actual[producto_id] + 1 > limite:
                flash("No hay más unidades disponibles de este producto.", "error")
            else:
                carrito_actual[producto_id] += 1
        elif accion == "menos":
            carrito_actual[producto_id] -= 1
            if carrito_actual[producto_id] < 1:
                del carrito_actual[producto_id]
        elif accion == "quitar":
            del carrito_actual[producto_id]
        guardar_carrito(carrito_actual)
    return redirect(url_for("carrito"))


@app.route("/carrito/vaciar", methods=["POST"])
@solo_compradores
def carrito_vaciar():
    session.pop("carrito", None)
    return redirect(url_for("carrito"))


@app.route("/pedido/nuevo", methods=["GET", "POST"])
@solo_compradores
def pedido_nuevo():
    """Revisar y confirmar el pedido. Exige cuenta; el pago y la entrega son en el local."""
    if not current_user.is_authenticated:
        flash("Inicia sesión o crea una cuenta para confirmar tu pedido.", "error")
        return redirect(url_for("login"))

    if request.method == "POST":
        token = request.form.get("token", "")[:64]
        existente = Pedido.query.filter_by(token=token, usuario_id=current_user.id).first() if token else None
        if existente:  # doble clic o reenvío: no se crea otro pedido
            session.pop("carrito", None)
            return redirect(url_for("ver_pedido", pedido_id=existente.id))

    lineas, unidades, total = detalle_carrito()
    if not lineas:
        return redirect(url_for("carrito"))
    if any(l["excede"] for l in lineas):
        flash("Hay productos con más unidades de las disponibles. Ajusta las cantidades marcadas.", "error")
        return redirect(url_for("carrito"))

    if request.method == "POST":
        nota = " ".join(request.form.get("nota", "").split())
        if not token:
            flash("No se pudo verificar el pedido. Inténtalo de nuevo.", "error")
            return redirect(url_for("pedido_nuevo"))
        if len(nota) > MAX_NOTA:
            flash(f"La nota admite hasta {MAX_NOTA} caracteres.", "error")
            return redirect(url_for("pedido_nuevo"))
        if request.form.get("total_esperado") != str(total):
            flash("Los precios o las cantidades cambiaron. Revisa el total actualizado antes de confirmar.", "error")
            return redirect(url_for("pedido_nuevo"))

        pedido, error = crear_pedido(current_user, lineas, nota, token)
        if error == "duplicado" and pedido:
            session.pop("carrito", None)
            return redirect(url_for("ver_pedido", pedido_id=pedido.id))
        if pedido is None:
            flash(error, "error")
            return redirect(url_for("carrito"))
        session.pop("carrito", None)
        flash(f"Pedido #{pedido.id} recibido. Págalo y retíralo en el local.", "success")
        return redirect(url_for("ver_pedido", pedido_id=pedido.id))

    return render_template(
        "pedido_nuevo.html", lineas=lineas, unidades=unidades, total=total, token=secrets.token_hex(16),
        max_nota=MAX_NOTA,
    )


@app.route("/pedidos")
@login_required
def mis_pedidos():
    if current_user.es_admin:
        return redirect(url_for("pedidos_admin"))
    pedidos = Pedido.query.filter_by(usuario_id=current_user.id).order_by(Pedido.id.desc()).all()
    return render_template("mis_pedidos.html", pedidos=pedidos)


@app.route("/pedidos/<int:pedido_id>")
@login_required
def ver_pedido(pedido_id):
    pedido = db.session.get(Pedido, pedido_id)
    if pedido is None or (not current_user.es_admin and pedido.usuario_id != current_user.id):
        flash("No se encontró el pedido.", "error")
        return redirect(url_for("pedidos_admin" if current_user.es_admin else "mis_pedidos"))
    return render_template("pedido_detalle.html", pedido=pedido, max_nota=MAX_NOTA)


@app.route("/pedidos/<int:pedido_id>/cancelar", methods=["POST"])
@login_required
def pedido_cancelar(pedido_id):
    pedido = db.session.get(Pedido, pedido_id)
    if pedido is None or (not current_user.es_admin and pedido.usuario_id != current_user.id):
        flash("No se encontró el pedido.", "error")
        return redirect(url_for("pedidos_admin" if current_user.es_admin else "mis_pedidos"))

    por = "administrador" if current_user.es_admin else "cliente"
    motivo = " ".join(request.form.get("motivo", "").split())[:MAX_NOTA] if current_user.es_admin else ""
    if cancelar_pedido(pedido_id, current_user, por, motivo):
        flash(f"Pedido #{pedido_id} cancelado. Las existencias se devolvieron al inventario.", "success")
    elif current_user.es_admin:
        flash("Este pedido ya no se puede cancelar (ya fue entregado o cancelado).", "error")
    else:
        flash("Este pedido ya no se puede cancelar porque el local ya lo está atendiendo. Comunícate con el local.", "error")
    return redirect(url_for("ver_pedido", pedido_id=pedido_id))


@app.route("/admin/pedidos")
@admin_requerido
def pedidos_admin():
    filtro = request.args.get("estado", "")
    consulta = Pedido.query
    if filtro in ESTADOS_PEDIDO:
        consulta = consulta.filter_by(estado=filtro)
    else:
        filtro = ""
    pedidos = consulta.order_by(Pedido.id.desc()).limit(200).all()
    conteos = dict(db.session.execute(select(Pedido.estado, func.count()).group_by(Pedido.estado)).all())
    return render_template(
        "pedidos_admin.html", pedidos=pedidos, filtro=filtro, conteos=conteos,
        total_pedidos=sum(conteos.values()), estados=ESTADOS_PEDIDO,
    )


@app.route("/pedidos/<int:pedido_id>/estado", methods=["POST"])
@admin_requerido
def pedido_estado(pedido_id):
    accion = request.form.get("accion", "")
    destino = (
        url_for("pedidos_admin", estado=request.form.get("filtro") or None)
        if request.form.get("volver") == "lista"
        else url_for("ver_pedido", pedido_id=pedido_id)
    )
    if db.session.get(Pedido, pedido_id) is None:
        flash("No se encontró el pedido.", "error")
        return redirect(url_for("pedidos_admin"))
    if accion not in TRANSICIONES:
        flash("Acción no válida.", "error")
        return redirect(destino)
    if cambiar_estado(pedido_id, accion):
        flash(f"Pedido #{pedido_id}: {'en preparación' if accion == 'preparar' else 'entregado'}.", "success")
    else:
        flash(f"El pedido #{pedido_id} ya cambió de estado. Revisa su estado actual.", "error")
    return redirect(destino)


@app.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    session.pop("carrito", None)  # el carrito no queda en un equipo compartido
    return redirect(url_for("raiz"))


@app.route("/inicio")
@admin_requerido
def inicio():
    productos = Producto.query.order_by(Producto.id).all()
    return render_template("inicio.html", productos=productos)


@app.route("/productos/crear", methods=["GET", "POST"])
@admin_requerido
def crear():
    errores, datos = {}, {"existencias": "0"}

    if request.method == "POST":
        datos, errores, valor, foto = leer_formulario()
        datos["existencias"] = request.form.get("existencias", "").strip()
        existencias = interpretar_existencias(datos["existencias"])
        if existencias is None:
            errores["existencias"] = (
                f"Escribe las existencias iniciales: un número entero entre 0 y {formato_miles(MAX_EXISTENCIAS)} "
                "(0 si aún no hay)."
            )
        if not errores:
            producto = Producto(
                nombre=datos["nombre"],
                valor=valor,
                descripcion=datos["descripcion"],
                imagen=guardar_foto(foto) if foto else None,
                existencias=existencias,
            )
            if existencias > 0:
                producto.movimientos.append(
                    Movimiento(tipo="inicial", cantidad=existencias, saldo=existencias,
                               nota="Existencias iniciales al crear el producto", usuario_id=current_user.id)
                )
            db.session.add(producto)
            db.session.commit()
            flash(f"Producto creado: {datos['nombre']}.", "success")
            return redirect(url_for("inicio"))
        avisar_errores(foto)

    return render_template("producto_form.html", modo="crear", producto=None, errores=errores, datos=datos)


@app.route("/productos/editar")
@admin_requerido
def editar_buscar():
    return pantalla_busqueda("editar")


@app.route("/productos/eliminar")
@admin_requerido
def eliminar_buscar():
    return pantalla_busqueda("eliminar")


@app.route("/productos/<int:producto_id>/editar", methods=["GET", "POST"])
@admin_requerido
def editar_producto(producto_id):
    producto = db.session.get(Producto, producto_id)
    if producto is None:
        return redirect(url_for("editar_buscar", resultado="no_encontrado"))
    errores = {}
    datos = {
        "nombre": producto.nombre,
        "valor": str(producto.valor),
        "descripcion": producto.descripcion,
    }

    if request.method == "POST":
        datos, errores, valor, foto = leer_formulario()
        if not errores:
            imagen_anterior = producto.imagen
            producto.nombre = datos["nombre"]
            producto.valor = valor
            producto.descripcion = datos["descripcion"]
            if foto:
                producto.imagen = guardar_foto(foto)
            db.session.commit()
            if foto:
                borrar_foto(imagen_anterior)
            flash(f"Cambios guardados: {datos['nombre']}.", "success")
            return redirect(url_for("inicio"))
        avisar_errores(foto)

    return render_template("producto_form.html", modo="editar", producto=producto, errores=errores, datos=datos)


@app.route("/productos/<int:producto_id>/eliminar", methods=["GET", "POST"])
@admin_requerido
def eliminar_producto(producto_id):
    producto = db.session.get(Producto, producto_id)
    if producto is None:
        return redirect(url_for("eliminar_buscar", resultado="no_encontrado"))

    if request.method == "POST":
        imagen = producto.imagen
        db.session.delete(producto)
        db.session.commit()
        borrar_foto(imagen)
        return redirect(url_for("eliminar_buscar", resultado="eliminado"))

    return render_template(
        "eliminar.html",
        producto=producto,
        confirmar=request.args.get("confirmar") == "1",
    )


@app.route("/inventario")
@admin_requerido
def inventario():
    productos = Producto.query.order_by(func.lower(Producto.nombre)).all()
    return render_template(
        "inventario.html",
        productos=productos,
        agotados=sum(1 for p in productos if p.existencias <= 0),
        bajos=sum(1 for p in productos if 0 < p.existencias <= UMBRAL_STOCK_BAJO),
        umbral=UMBRAL_STOCK_BAJO,
        max_existencias=MAX_EXISTENCIAS,
    )


@app.route("/inventario/<int:producto_id>")
@admin_requerido
def inventario_producto(producto_id):
    producto = db.session.get(Producto, producto_id)
    if producto is None:
        flash("No se encontró el producto.", "error")
        return redirect(url_for("inventario"))
    movimientos = (
        Movimiento.query.filter_by(producto_id=producto_id).order_by(Movimiento.id.desc()).limit(50).all()
    )
    return render_template(
        "inventario_producto.html", producto=producto, movimientos=movimientos,
        max_existencias=MAX_EXISTENCIAS, max_nota=MAX_NOTA,
    )


@app.route("/inventario/<int:producto_id>/movimiento", methods=["POST"])
@admin_requerido
def inventario_movimiento(producto_id):
    producto = db.session.get(Producto, producto_id)
    if producto is None:
        flash("No se encontró el producto.", "error")
        return redirect(url_for("inventario"))

    desde_lista = request.form.get("volver") == "lista"
    destino = url_for("inventario") if desde_lista else url_for("inventario_producto", producto_id=producto_id)

    tipo = request.form.get("tipo", "")
    nota = " ".join(request.form.get("nota", "").split())
    if tipo not in ("entrada", "salida", "ajuste"):
        flash("Elige un tipo de movimiento válido.", "error")
        return redirect(destino)
    if len(nota) > MAX_NOTA:
        flash(f"La nota admite hasta {MAX_NOTA} caracteres.", "error")
        return redirect(destino)

    try:
        cantidad = int(request.form.get("cantidad", ""))
    except ValueError:
        cantidad = -1
    minimo = 0 if tipo == "ajuste" else 1
    if not minimo <= cantidad <= MAX_EXISTENCIAS:
        flash(f"La cantidad debe ser un número entero entre {minimo} y {formato_miles(MAX_EXISTENCIAS)}.", "error")
        return redirect(destino)

    anterior = producto.existencias
    esperado = None
    if tipo == "entrada":
        delta = cantidad
        if anterior + cantidad > MAX_EXISTENCIAS:
            flash(f"Las existencias no pueden superar {formato_miles(MAX_EXISTENCIAS)}.", "error")
            return redirect(destino)
    elif tipo == "salida":
        delta = -cantidad
        if cantidad > anterior:
            flash(f"No puedes sacar {cantidad}: solo hay {anterior} de {producto.nombre}.", "error")
            return redirect(destino)
    else:  # conteo físico: fija el total contado y guarda la diferencia
        delta = cantidad - anterior
        esperado = anterior

    saldo = aplicar_movimiento(producto_id, delta, tipo, nota, current_user.id, esperado)
    if saldo is None:
        flash("Las existencias cambiaron mientras registrabas el movimiento. Revisa el valor actual e inténtalo de nuevo.", "error")
    elif tipo == "entrada":
        flash(f"Entrada registrada: +{cantidad} de {producto.nombre}. Existencias: {saldo}.", "success")
    elif tipo == "salida":
        flash(f"Salida registrada: −{cantidad} de {producto.nombre}. Existencias: {saldo}.", "success")
    elif delta == 0:
        flash(f"Conteo registrado: {producto.nombre} coincide con el sistema ({saldo}).", "success")
    else:
        flash(f"Conteo registrado: {producto.nombre} pasó de {anterior} a {saldo} (diferencia {delta:+d}).", "success")
    return redirect(destino)


@app.errorhandler(CSRFError)
def csrf_invalido(_error):
    return render_template("400.html"), 400


@app.errorhandler(403)
def sin_permiso(_error):
    return render_template("403.html"), 403


@app.errorhandler(413)
def peticion_muy_grande(_error):
    flash("La imagen supera el tamaño permitido (2 MB). Elige una más liviana.", "error")
    return redirect(request.url)


if __name__ == "__main__":
    # Para desarrollar con recarga automática: $env:FLASK_DEBUG="1"  (nunca en un servidor público)
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")
