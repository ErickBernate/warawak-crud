# Warawak - menú digital y administración de productos

Prototipo funcional hecho con Flask y SQLite.

- **Visitantes:** ven el menú digital (nombre, valor, descripción y foto de cada producto) sin iniciar sesión.
- **Clientes:** cuentas creadas desde "Regístrate". Por ahora solo ven el menú; más adelante tendrán carrito y pagos.
- **Administradores:** los únicos que acceden al panel para crear, editar y eliminar productos.
  Se crean únicamente con el script `crear_admin.py`, nunca desde la página.

## Instalación

```
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Crear administradores

Con el entorno virtual activo, ejecuta una vez por cada administrador:

```
python crear_admin.py
```

Si el nombre ya existe como cliente, el script ofrece convertirlo en administrador sin cambiar su contraseña.

## Ejecución

```
python app.py
```

Abre http://127.0.0.1:5000 en el navegador.

Para desarrollar con recarga automática de cambios (nunca en un servidor público):

```
$env:FLASK_DEBUG="1"
python app.py
```

## Seguridad y configuración

- **Clave secreta (`SECRET_KEY`):** firma las sesiones y no está escrita en el código.
  En un servidor, defínela como variable de entorno. Para generar una:
  `python -c "import secrets; print(secrets.token_hex(32))"`.
  Si no existe la variable, la app crea una clave aleatoria en `instance/secret_key`, que no va al repositorio.
- **Protección CSRF:** todos los formularios POST (incluido "Salir") llevan un token de verificación.
- **HTTPS:** en un sitio publicado con HTTPS, define `SESSION_COOKIE_SECURE=1` para que la sesión solo viaje cifrada.
- **Modo desarrollo:** apagado por defecto. Se activa solo con `FLASK_DEBUG=1`.

## Otros scripts

- `python restablecer_password.py`: asigna una contraseña nueva a un usuario.

## Datos

La base de datos (`instance/warawak.db`) se crea sola la primera vez, con los productos de ejemplo.
Las fotos subidas se guardan en `static/img/productos/`. Ninguna de las dos va al repositorio.

## Imágenes opcionales

Para que el diseño se parezca más al de Figma, copia estos archivos en `static/img/`:

- `login.jpg`: foto del equipo para las pantallas de login y registro
- `banner.jpg`: foto del local para el banner
- `logo.svg`: reemplázalo por el logo real de Warawak
