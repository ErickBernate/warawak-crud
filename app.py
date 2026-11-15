"""Prototipo Warawak: login, listado y creación de productos (Flask + SQLite)."""
import os
import uuid

from flask import Flask, flash, redirect, render_template, request, url_for
from flask_login import (
    LoginManager,
    UserMixin,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "cambia-esta-clave-en-produccion")
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///warawak.db"
app.config["MAX_CONTENT_LENGTH"] = 3 * 1024 * 1024  # tope de toda la petición

CARPETA_IMAGENES = os.path.join(app.static_folder, "img", "productos")
os.makedirs(CARPETA_IMAGENES, exist_ok=True)
EXTENSIONES_PERMITIDAS = {"png", "jpg", "jpeg", "webp", "gif"}
MAX_IMAGEN_BYTES = 2 * 1024 * 1024
MAX_VALOR = 100_000_000

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Inicia sesión para ver los productos."


class Usuario(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

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


@login_manager.user_loader
def cargar_usuario(user_id):
    return db.session.get(Usuario, int(user_id))


@app.template_filter("pesos")
def formato_pesos(valor):
    """5500 -> '$ 5.500'"""
    return "$ " + f"{valor:,}".replace(",", ".")


# ---------------------------------------------------------------- datos de ejemplo
USUARIO_DEMO = ("Fulanito Perez", "warawak")

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
    if Usuario.query.count() == 0:
        usuario = Usuario(nombre=USUARIO_DEMO[0])
        usuario.poner_password(USUARIO_DEMO[1])
        db.session.add(usuario)
    if Producto.query.count() == 0:
        for nombre, valor in PRODUCTOS_INICIALES:
            db.session.add(Producto(nombre=nombre, valor=valor))
    db.session.commit()


with app.app_context():
    db.create_all()
    sembrar_datos()


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


# ---------------------------------------------------------------- rutas
@app.route("/")
def raiz():
    if current_user.is_authenticated:
        return redirect(url_for("inicio"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("inicio"))

    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        password = request.form.get("password", "")
        usuario = Usuario.query.filter_by(nombre=nombre).first()
        if usuario and usuario.verificar_password(password):
            login_user(usuario)
            return redirect(url_for("inicio"))
        flash("El nombre o la contraseña no coinciden. Revisa los datos e intenta de nuevo.", "error")

    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


@app.route("/inicio")
@login_required
def inicio():
    productos = Producto.query.order_by(Producto.id).all()
    return render_template("inicio.html", productos=productos)


@app.route("/productos/crear", methods=["GET", "POST"])
@login_required
def crear():
    errores, datos = {}, {}

    if request.method == "POST":
        datos = {
            campo: request.form.get(campo, "").strip()
            for campo in ("nombre", "valor", "descripcion")
        }

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
        hay_foto = bool(foto and foto.filename)
        if hay_foto:
            error_foto = validar_foto(foto)
            if error_foto:
                errores["foto"] = error_foto

        if not errores:
            nombre_imagen = None
            if hay_foto:
                nombre_imagen = f"{uuid.uuid4().hex}.{extension_de(foto.filename)}"
                foto.save(os.path.join(CARPETA_IMAGENES, nombre_imagen))

            db.session.add(
                Producto(
                    nombre=datos["nombre"],
                    valor=valor,
                    descripcion=datos["descripcion"],
                    imagen=nombre_imagen,
                )
            )
            db.session.commit()
            flash(f"Producto creado: {datos['nombre']}.", "success")
            return redirect(url_for("inicio"))

        if hay_foto:
            flash("Revisa el formulario. Vuelve a elegir la foto, porque el navegador no la conserva.", "error")
        else:
            flash("Revisa los campos marcados e intenta de nuevo.", "error")

    return render_template("crear.html", errores=errores, datos=datos)


@app.errorhandler(413)
def peticion_muy_grande(_error):
    flash("La imagen supera el tamaño permitido (2 MB). Elige una más liviana.", "error")
    return redirect(url_for("crear"))


if __name__ == "__main__":
    app.run(debug=True)
