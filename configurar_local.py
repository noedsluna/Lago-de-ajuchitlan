"""Primera configuración local de la web y de los dos microservicios."""
from pathlib import Path
from getpass import getpass
import hashlib
import secrets

ROOT = Path(__file__).resolve().parent
WEB = ROOT / '.env'
DOCKER = ROOT / '.env.docker'


def read_values(path):
    if not path.is_file():
        return {}
    values = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        if line.strip() and not line.lstrip().startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            values[key.strip()] = value.strip()
    return values


def write_values(path, values):
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(''.join(f'{key}={value}\n' for key, value in values.items()), encoding='utf-8')
    temp.replace(path)


def admin_hash(password):
    salt = secrets.token_hex(12)
    rounds = 600000
    digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), rounds).hex()
    return f'pbkdf2:sha256:{rounds}${salt}${digest}'


def main():
    web = read_values(WEB)
    docker = read_values(DOCKER)
    # Se conserva el token si ya existía; nunca regenerarlo en cada arranque.
    token = web.get('LAGO_SERVICE_TOKEN') or docker.get('LAGO_SERVICE_TOKEN') or secrets.token_urlsafe(48)
    web['LAGO_SECRET_KEY'] = web.get('LAGO_SECRET_KEY') or secrets.token_urlsafe(48)
    web['LAGO_SERVICE_TOKEN'] = token
    web['LAGO_ADMIN_USER'] = 'admin'
    if not web.get('LAGO_ADMIN_PASSWORD_HASH'):
        print('Configuración inicial del administrador local. Usuario: admin')
        pwd = getpass('Elige una contraseña para esta copia local: ')
        if not pwd:
            raise SystemExit('No se admiten contraseñas vacías.')
        print('Advertencia: admin/admin solo es adecuado para una demostración sin exposición a internet.')
        web['LAGO_ADMIN_PASSWORD_HASH'] = admin_hash(pwd)
    web['LAGO_USUARIOS_URL'] = 'http://127.0.0.1:5181'
    web['LAGO_PUESTOS_URL'] = 'http://127.0.0.1:5182'
    web['LAGO_COOKIE_SECURE'] = '0'
    web['PORT'] = '5090'
    docker['LAGO_SERVICE_TOKEN'] = token
    write_values(WEB, web)
    write_values(DOCKER, docker)
    for subdir in ('datos/usuarios', 'datos/puestos', 'static/uploads'):
        (ROOT / subdir).mkdir(parents=True, exist_ok=True)
    from crear_datos_demo import create
    create(ROOT / 'lago.db')
    print('\nConfiguración guardada. No subas .env, .env.docker, datos ni *.db a GitHub.')
    print('Usuarios: http://127.0.0.1:5181/salud')
    print('Puestos: http://127.0.0.1:5182/salud')
    print('Web local: http://127.0.0.1:5090/')


if __name__ == '__main__':
    main()
