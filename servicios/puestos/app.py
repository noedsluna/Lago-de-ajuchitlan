"""Microservicio de puestos y servicios: API HTTP y datos propios en SQLite."""
import hmac
import os
import sqlite3
from pathlib import Path
from flask import Flask, request, jsonify

app = Flask(__name__)
DB = Path(os.environ.get('PUESTOS_DB','/data/puestos.db'))
SEED = Path(os.environ.get('LAGO_SEED_DB','/seed/lago.db'))
TOKEN = os.environ.get('LAGO_SERVICE_TOKEN','')
FIELDS=('name','category','description','hours','location','contact','photos','menu')


def connection():
    con=sqlite3.connect(DB,timeout=12)
    con.row_factory=sqlite3.Row
    con.execute('PRAGMA busy_timeout=12000')
    return con


def initialize():
    DB.parent.mkdir(parents=True,exist_ok=True)
    fresh=not DB.exists()
    with connection() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS businesses (
          id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
          category TEXT, description TEXT, hours TEXT, location TEXT,
          contact TEXT, photos TEXT DEFAULT '[]', menu TEXT DEFAULT '[]')""")
        if fresh and SEED.is_file():
            with sqlite3.connect(SEED) as source:
                source.row_factory=sqlite3.Row
                try:
                    rows=source.execute('SELECT id,name,category,description,hours,location,contact,photos,menu FROM businesses').fetchall()
                except sqlite3.Error:
                    rows=[]
            for r in rows:
                con.execute('INSERT OR IGNORE INTO businesses(id,name,category,description,hours,location,contact,photos,menu) VALUES (?,?,?,?,?,?,?,?,?)',tuple(r))


@app.before_request
def protect():
    if request.path=='/salud': return None
    if not TOKEN or not hmac.compare_digest(TOKEN,request.headers.get('X-Service-Token','')):
        return jsonify(error='API interna: acceso restringido'),403


@app.get('/salud')
def health():
    with connection() as con: total=con.execute('SELECT COUNT(*) FROM businesses').fetchone()[0]
    return jsonify(servicio='puestos',estado='ok',registros=total)


@app.get('/interno/negocios')
def list_businesses():
    with connection() as con:
        rows=con.execute('SELECT * FROM businesses ORDER BY id DESC').fetchall()
    return jsonify(items=[dict(r) for r in rows],total=len(rows))


@app.get('/interno/negocios/<int:bid>')
def get_business(bid):
    with connection() as con:
        row=con.execute('SELECT * FROM businesses WHERE id=?',(bid,)).fetchone()
    return jsonify(dict(row)) if row else (jsonify(error='No encontrado'),404)


def from_payload():
    data=request.get_json(silent=True) or {}
    return [str(data.get(key,'') or '').strip() if key not in ('photos','menu') else str(data.get(key,'[]') or '[]') for key in FIELDS]


@app.post('/interno/negocios')
def create_business():
    vals=from_payload()
    if not vals[0]: return jsonify(error='El nombre es obligatorio'),400
    with connection() as con:
        if con.execute('SELECT COUNT(*) FROM businesses').fetchone()[0]>=12:
            return jsonify(error='Máximo 12 puestos'),409
        cur=con.execute('INSERT INTO businesses('+','.join(FIELDS)+') VALUES(?,?,?,?,?,?,?,?)',vals)
        bid=cur.lastrowid
    return jsonify(ok=True,id=bid),201


@app.put('/interno/negocios/<int:bid>')
def update_business(bid):
    vals=from_payload()
    if not vals[0]: return jsonify(error='El nombre es obligatorio'),400
    with connection() as con:
        if not con.execute('SELECT 1 FROM businesses WHERE id=?',(bid,)).fetchone():
            return jsonify(error='No encontrado'),404
        con.execute('UPDATE businesses SET '+','.join(key+'=?' for key in FIELDS)+' WHERE id=?',vals+[bid])
    return jsonify(ok=True)


@app.delete('/interno/negocios/<int:bid>')
def delete_business(bid):
    with connection() as con:
        if not con.execute('SELECT 1 FROM businesses WHERE id=?',(bid,)).fetchone():
            return jsonify(error='No encontrado'),404
        con.execute('DELETE FROM businesses WHERE id=?',(bid,))
    return jsonify(ok=True)


initialize()
if __name__=='__main__':
    app.run(host='0.0.0.0',port=int(os.environ.get('PORT','5002')),debug=False)
