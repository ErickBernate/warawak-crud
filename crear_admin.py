"""Crea un administrador, o convierte una cuenta existente en administrador.

Los administradores NO se pueden crear desde la página web: solo con este script.

Uso (con el entorno virtual activo):
    python crear_admin.py
"""
from getpass import getpass

from app import (
    Usuario,
    app,
    db,
    limpiar_nombre,
    normalizar_contacto,
    usuario_por_nombre,
)

nombre = limpiar_nombre(input("Nombre del administrador: "))
if not 2 <= len(nombre) <= 80:
    raise SystemExit("El nombre debe tener entre 2 y 80 caracteres. No se hizo ningún cambio.")

with app.app_context():
    existente = usuario_por_nombre(nombre)

    if existente:
        if existente.es_admin:
            raise SystemExit(f"{existente.nombre} ya es administrador. No se hizo ningún cambio.")
        respuesta = input(
            f"Ya existe una cuenta de cliente llamada {existente.nombre}. "
            "¿Convertirla en administrador? (s/n): "
        )
        if respuesta.strip().lower() != "s":
            raise SystemExit("No se hizo ningún cambio.")
        existente.rol = "admin"
        db.session.commit()
        print(f"{existente.nombre} ahora es administrador (su contraseña no cambió).")
    else:
        contacto = normalizar_contacto(input("Email o teléfono: "))
        if contacto is None:
            raise SystemExit("Escribe un correo válido o un teléfono de 7 a 15 dígitos. No se hizo ningún cambio.")
        if Usuario.query.filter_by(contacto=contacto).first():
            raise SystemExit("Ese correo o teléfono ya tiene una cuenta. No se hizo ningún cambio.")

        password = getpass("Contraseña (mínimo 8 caracteres): ")
        if len(password) < 8:
            raise SystemExit("La contraseña debe tener al menos 8 caracteres. No se hizo ningún cambio.")
        if password != getpass("Repite la contraseña: "):
            raise SystemExit("Las contraseñas no coinciden. No se hizo ningún cambio.")

        administrador = Usuario(nombre=nombre, contacto=contacto, rol="admin")
        administrador.poner_password(password)
        db.session.add(administrador)
        db.session.commit()
        print(f"Administrador creado: {administrador.nombre}")

    print(f"Administradores registrados: {Usuario.query.filter_by(rol='admin').count()}")
