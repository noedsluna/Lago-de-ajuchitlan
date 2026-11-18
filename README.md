# Lago de Ajuchitlán — 2 microservicios

La página principal se ejecuta **en Windows con Python + Flask**. Docker Compose ejecuta **solo 2 contenedores**: `usuarios` y `puestos`.

## Requisitos

- Python 3 instalado en Windows (`py --version`).
- Docker Desktop abierto (motor Linux/WSL 2 activo).
- Visual Studio Code con la carpeta de este proyecto abierta.
- Conexión a internet la primera vez para instalar Flask y descargar la imagen Python de Docker.

## Primera ejecución (terminal integrada de VS Code, PowerShell)

1. `py configurar_local.py` — crea `.env` y `.env.docker` privados y la base local de demostración. Pide contraseña para `admin`.
2. `docker compose --env-file .env.docker up -d --build` — construye/inicia únicamente `usuarios` y `puestos`.
3. `docker compose --env-file .env.docker ps -a` — verifica que ambos estén encendidos.
4. `py -m pip install -r requirements.txt` — instala Flask para la web de Windows.
5. `py app.py` — inicia la web local. Mantén abierta esta terminal.
6. Abre `http://127.0.0.1:5090/` y `http://127.0.0.1:5090/admin/entrar`.

En una segunda terminal puedes iniciar Docker, y en la primera mantener la web. Si utilizas otra terminal en VS Code, abre **Terminal > New Terminal**.

## Prueba de funcionamiento

- `http://127.0.0.1:5181/salud` — usuarios.
- `http://127.0.0.1:5182/salud` — puestos.
- El panel administrativo puede registrar puestos. `Ver base de datos` muestra los registros a través de las API de ambos servicios.
- Registra un usuario de prueba (contraseña de 8 caracteres o más) y comprueba que se puede iniciar sesión.
- Detén y vuelve a arrancar los contenedores; comprueba que los datos permanecen guardados.

## Comandos importantes

```powershell
docker compose --env-file .env.docker ps -a
docker compose --env-file .env.docker stop
docker compose --env-file .env.docker start
docker compose --env-file .env.docker logs --tail=50
```

No uses `docker compose down` si quieres que los contenedores sigan apareciendo en Docker Desktop. `down` elimina los contenedores, aunque la carpeta `datos` guarda las bases. Para reconstruir después de modificar código usa `up -d --build`.

## Archivos y carpetas

- `app.py`: servidor web Flask en Windows. Se conecta por HTTP a ambos microservicios.
- `servicios/usuarios/app.py`: API de usuarios; guarda los datos en `datos/usuarios/usuarios.db`.
- `servicios/puestos/app.py`: API de puestos; guarda los datos en `datos/puestos/puestos.db`.
- `servicios/Dockerfile`: construye las imágenes Python de ambos microservicios.
- `compose.yaml`: configura únicamente los 2 contenedores, puertos, comprobaciones y persistencia.
- `configurar_local.py`: crea las claves locales, la contraseña cifrada y variables de conexión.
- `crear_datos_demo.py`: genera puestos de ejemplo sin cuentas reales.
- `lago.db`: se crea localmente para contenido de la página; no se sube a GitHub.
- `static/uploads/`: guarda fotos subidas en la web; las originales de demostración sí están incluidas.
- `.gitignore`, `.dockerignore`: impiden versionar/copiar contraseñas, bases privadas y temporales.

## Arquitectura

Navegador -> `web local:5090` -> API `usuarios:5181` / `puestos:5182` -> SQLite independiente de cada servicio. Los puertos 5181/5182 se exponen **solo a 127.0.0.1** en Windows. Las API internas requieren un token secreto compartido mediante variables de entorno. No es necesario XAMPP.

## GitHub

No publiques `.env`, `.env.docker`, `lago.db`, `datos/`, contraseñas ni registros reales. Este proyecto es para desarrollo local y no está configurado para exposición pública en Internet.
