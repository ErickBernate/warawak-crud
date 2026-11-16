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
