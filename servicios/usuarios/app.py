"""Microservicio de usuarios del Lago de Ajuchitlán.
Almacena sus cuentas en /data/usuarios.db y expone una API interna protegida.
"""
import hmac
import os
from pathlib import Path
import sqlite3
import re
from flask import Flask, request, jsonify
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
DB = Path(os.environ.get('USUARIOS_DB', '/data/usuarios.db'))
SEED = Path(os.environ.get('LAGO_SEED_DB', '/seed/lago.db'))
TOKEN = os.environ.get('LAGO_SERVICE_TOKEN', '')


def connection():
    con = sqlite3.connect(DB, timeout=12)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA busy_timeout=12000')
    return con


def initialize():
    DB.parent.mkdir(parents=True, exist_ok=True)
    fresh = not DB.exists()
    with connection() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS users (
         id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
         email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
         role TEXT NOT NULL DEFAULT 'user', created_at TEXT DEFAULT CURRENT_TIMESTAMP,
         active INTEGER NOT NULL DEFAULT 1)""")
        if fresh and SEED.is_file():
            with sqlite3.connect(SEED) as source:
                source.row_factory = sqlite3.Row
                try:
                    rows = source.execute('SELECT id,name,email,password_hash,role,created_at,active FROM users').fetchall()
                except sqlite3.Error:
                    rows = []
            for r in rows:
                con.execute('INSERT OR IGNORE INTO users(id,name,email,password_hash,role,created_at,active) VALUES(?,?,?,?,?,?,?)',tuple(r))


def public(row):
    return {key: row[key] for key in ('id','name','email','role','created_at','active') if key in row.keys()}


@app.before_request
def protect():
    if request.path == '/salud':
        return None
    supplied = request.headers.get('X-Service-Token', '')
    if not TOKEN or not hmac.compare_digest(TOKEN, supplied):
        return jsonify(error='API interna: acceso restringido'), 403


@app.get('/salud')
def health():
    with connection() as con:
        total = con.execute('SELECT COUNT(*) FROM users').fetchone()[0]
    return jsonify(servicio='usuarios', estado='ok', registros=total)


@app.get('/interno/usuarios')
def list_users():
    q = request.args.get('q','').strip()
    with connection() as con:
        if q:
            rows = con.execute('SELECT * FROM users WHERE name LIKE ? OR email LIKE ? ORDER BY created_at DESC,id DESC',(f'%{q}%',f'%{q}%')).fetchall()
        else:
            rows = con.execute('SELECT * FROM users ORDER BY created_at DESC,id DESC').fetchall()
        admins = con.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND active=1").fetchone()[0]
        count = con.execute('SELECT COUNT(*) FROM users').fetchone()[0]
    return jsonify(items=[public(r) for r in rows], admins_activos=admins, total=count)


@app.get('/interno/usuarios/<int:uid>')
def get_user(uid):
    with connection() as con:
        row = con.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()
    return (jsonify(public(row)) if row else (jsonify(error='No encontrado'),404))


@app.post('/interno/login')
def verify_login():
    data = request.get_json(silent=True) or {}
    email = str(data.get('email','')).strip().lower()
    password = str(data.get('password',''))
    with connection() as con:
        row = con.execute('SELECT * FROM users WHERE email=?',(email,)).fetchone()
    if not row or not row['active'] or not check_password_hash(row['password_hash'],password):
        return jsonify(error='Credenciales incorrectas'),401
    return jsonify(public(row))


@app.post('/interno/usuarios')
def create_user():
    data = request.get_json(silent=True) or {}
    name = str(data.get('name','')).strip()
    email = str(data.get('email','')).strip().lower()
    password = str(data.get('password',''))
    if not 2 <= len(name) <= 100 or not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+',email) or len(password)<8:
        return jsonify(error='Datos no válidos'),400
    try:
        with connection() as con:
            result = con.execute('INSERT INTO users(name,email,password_hash,role) VALUES (?,?,?,?)',(name,email,generate_password_hash(password),'user'))
            uid = result.lastrowid
    except sqlite3.IntegrityError:
        return jsonify(error='Correo registrado'),409
    return jsonify(id=uid,name=name,email=email,role='user'),201


@app.put('/interno/usuarios/<int:uid>')
def update_user(uid):
    data = request.get_json(silent=True) or {}
    name = str(data.get('name','')).strip()
    email = str(data.get('email','')).strip().lower()
    password = str(data.get('password',''))
    if not 2 <= len(name) <= 100 or not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+',email) or (password and len(password)<8):
        return jsonify(error='Datos no válidos'),400
    try:
        with connection() as con:
            row = con.execute('SELECT id FROM users WHERE id=?',(uid,)).fetchone()
            if row is None: return jsonify(error='No encontrado'),404
            con.execute('UPDATE users SET name=?,email=? WHERE id=?',(name,email,uid))
            if password:
                con.execute('UPDATE users SET password_hash=? WHERE id=?',(generate_password_hash(password),uid))
    except sqlite3.IntegrityError:
        return jsonify(error='Correo registrado'),409
    return jsonify(ok=True)


@app.post('/interno/usuarios/<int:uid>/rol')
def set_role(uid):
    data = request.get_json(silent=True) or {}
    role = data.get('role')
    if role not in ('user','admin'): return jsonify(error='Rol no permitido'),400
    with connection() as con:
        row = con.execute('SELECT role,active FROM users WHERE id=?',(uid,)).fetchone()
        if not row: return jsonify(error='No encontrado'),404
        admins = con.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND active=1").fetchone()[0]
        if row['role']=='admin' and row['active'] and role=='user' and admins<=1:
            return jsonify(error='No se puede quitar al último administrador activo'),409
        con.execute('UPDATE users SET role=? WHERE id=?',(role,uid))
    return jsonify(ok=True)


@app.post('/interno/usuarios/<int:uid>/estado')
def set_active(uid):
    with connection() as con:
        row = con.execute('SELECT role,active FROM users WHERE id=?',(uid,)).fetchone()
        if not row: return jsonify(error='No encontrado'),404
        admins = con.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND active=1").fetchone()[0]
        if row['role']=='admin' and row['active'] and admins<=1:
            return jsonify(error='No se puede bloquear al último administrador activo'),409
        active = 0 if row['active'] else 1
        con.execute('UPDATE users SET active=? WHERE id=?',(active,uid))
    return jsonify(ok=True,active=active)


@app.delete('/interno/usuarios/<int:uid>')
def delete_user(uid):
    with connection() as con:
        row = con.execute('SELECT role,active FROM users WHERE id=?',(uid,)).fetchone()
        if not row: return jsonify(error='No encontrado'),404
        admins = con.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND active=1").fetchone()[0]
        if row['role']=='admin' and row['active'] and admins<=1:
            return jsonify(error='No se puede eliminar al último administrador activo'),409
        con.execute('DELETE FROM users WHERE id=?',(uid,))
    return jsonify(ok=True)


initialize()
if __name__ == '__main__':
    app.run(host='0.0.0.0',port=int(os.environ.get('PORT','5001')),debug=False)
