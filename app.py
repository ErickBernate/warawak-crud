"""Prototipo Warawak: login y listado de productos (Flask + SQLite)."""
import os

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


if __name__ == "__main__":
    app.run(debug=True)
