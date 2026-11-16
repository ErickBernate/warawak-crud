"""Cambia la contraseña de un usuario existente.

Uso (con el entorno virtual activo y la app detenida):
    python restablecer_password.py
"""
from getpass import getpass

from app import app, db, limpiar_nombre, usuario_por_nombre

nombre = limpiar_nombre(input("Nombre del usuario: "))

with app.app_context():
    usuario = usuario_por_nombre(nombre)
    if usuario is None:
        raise SystemExit("No existe ningún usuario con ese nombre.")

    password = getpass("Contraseña nueva (mínimo 8 caracteres): ")
    if len(password) < 8:
        raise SystemExit("La contraseña debe tener al menos 8 caracteres. No se hizo ningún cambio.")
    if password != getpass("Repite la contraseña nueva: "):
        raise SystemExit("Las contraseñas no coinciden. No se hizo ningún cambio.")

    usuario.poner_password(password)
    db.session.commit()
    print(f"Contraseña actualizada para: {usuario.nombre}")
