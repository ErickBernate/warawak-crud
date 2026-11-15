# Warawak - prototipo de CRUD de productos

Prototipo funcional hecho con Flask y SQLite. Por ahora incluye login y el listado de productos (Inicio).

## Instalación

```
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Ejecución

```
python app.py
```

Abre http://127.0.0.1:5000 en el navegador.

## Usuario de prueba

- Nombre: `Fulanito Perez`
- Contraseña: `warawak`

La base de datos (`instance/warawak.db`) se crea sola la primera vez, con este usuario y los productos de ejemplo.

## Imágenes opcionales

Para que el diseño se parezca más al de Figma, copia estos archivos en `static/img/`:

- `login.jpg`: foto del equipo para la pantalla de login
- `banner.jpg`: foto del local para el banner de Inicio
- `logo.svg`: reemplázalo por el logo real de Warawak
