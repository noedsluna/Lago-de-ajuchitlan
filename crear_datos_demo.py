"""Crea una base inicial sin usuarios ni contraseñas reales para demostración local."""
from pathlib import Path
import json
import sqlite3
import sys

def create(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return
    with sqlite3.connect(path) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS businesses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, category TEXT, description TEXT,
            hours TEXT, location TEXT, contact TEXT,
            photos TEXT DEFAULT '[]', menu TEXT DEFAULT '[]')""")
        db.execute("""CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'user',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            active INTEGER NOT NULL DEFAULT 1)""")
        db.execute("""CREATE TABLE IF NOT EXISTS page_content (
            path TEXT PRIMARY KEY, html TEXT NOT NULL,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
        db.execute("""CREATE TABLE IF NOT EXISTS custom_pages (
            slug TEXT PRIMARY KEY, title TEXT NOT NULL,
            html TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
        demos = [
            ('Puesto de gorditas (demo)', 'Comida',
             'Ejemplo para comprobar el registro de establecimientos.',
             'Horario de muestra', 'Área del lago', '',
             ['/static/uploads/gorditas-la-receta.jpg'],
             [{'title':'Gorditas','items':['Queso','Migajas']}]),
            ('Puesto de antojitos (demo)', 'Comida',
             'Registro de demostración, reemplazable desde la administración.',
             'Horario de muestra', 'Área del lago', '',
             ['/static/uploads/antojitos-el-lago-1.jpg'],
             [{'title':'Antojitos','items':['Quesadillas','Sopes']}]),
            ('Puesto de frituras (demo)', 'Comida',
             'Registro de demostración para el directorio del lago.',
             'Horario de muestra', 'Área del lago', '',
             ['/static/uploads/frituras-dona-lola.jpg'], [])
        ]
        for name,category,description,hours,location,contact,photos,menu in demos:
            db.execute("""INSERT INTO businesses
                (name,category,description,hours,location,contact,photos,menu)
                VALUES(?,?,?,?,?,?,?,?)""",
                (name,category,description,hours,location,contact,
                 json.dumps(photos,ensure_ascii=False),json.dumps(menu,ensure_ascii=False)))

if __name__ == '__main__':
    create(sys.argv[1] if len(sys.argv)>1 else 'lago.db')
