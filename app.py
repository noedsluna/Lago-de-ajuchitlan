from flask import Flask, request, redirect, session, abort, send_from_directory, render_template_string, jsonify
from pathlib import Path
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import sqlite3, os, json, uuid, html, secrets, hmac, unicodedata, re
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
ROOT=Path(__file__).resolve().parent; DB=ROOT/'lago.db'; UP=ROOT/'static'/'uploads'; UP.mkdir(parents=True,exist_ok=True)
def load_local_env():
    env_file=ROOT/'.env'
    if not env_file.is_file(): return
    for line in env_file.read_text(encoding='utf-8').splitlines():
        line=line.strip()
        if not line or line.startswith('#') or '=' not in line: continue
        key,value=line.split('=',1); key=key.strip(); value=value.strip().strip('\"').strip("'")
        if key and key not in os.environ: os.environ[key]=value
load_local_env()
app=Flask(__name__,static_folder='static')
app.secret_key=os.environ.get('LAGO_SECRET_KEY') or secrets.token_hex(32)
# Cookies de sesión con protecciones razonables. En alojamiento HTTPS, configura LAGO_COOKIE_SECURE=1.
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_SECURE=os.environ.get('LAGO_COOKIE_SECURE','0').lower() in ('1','true','yes'))
ADMIN_USER=os.environ.get('LAGO_ADMIN_USER','admin')
ADMIN_PASSWORD_HASH=os.environ.get('LAGO_ADMIN_PASSWORD_HASH')
# Migración automática de la antigua contraseña en texto del .env a un hash Werkzeug.
# La contraseña se conserva solo en memoria durante este proceso; el archivo local se reescribe.
_legacy_admin_password=os.environ.get('LAGO_ADMIN_PASSWORD')
if not ADMIN_PASSWORD_HASH and _legacy_admin_password:
    ADMIN_PASSWORD_HASH=generate_password_hash(_legacy_admin_password)
    os.environ['LAGO_ADMIN_PASSWORD_HASH']=ADMIN_PASSWORD_HASH
    env_file=ROOT/'.env'
    if env_file.is_file():
        lines=[]
        for line in env_file.read_text(encoding='utf-8').splitlines():
            if line.strip().startswith('LAGO_ADMIN_PASSWORD=') or line.strip().startswith('LAGO_ADMIN_PASSWORD_HASH='):
                continue
            lines.append(line)
        lines.append('LAGO_ADMIN_PASSWORD_HASH='+ADMIN_PASSWORD_HASH)
        env_file.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    os.environ.pop('LAGO_ADMIN_PASSWORD',None)
    _legacy_admin_password=None

def admin_password_matches(candidate):
    try:
        return bool(ADMIN_PASSWORD_HASH and check_password_hash(ADMIN_PASSWORD_HASH, candidate or ''))
    except (ValueError, TypeError):
        return False

# Límite sencillo por IP para frenar intentos repetidos en este proceso.
_login_attempts={}
def login_is_limited(key):
    now=datetime.now(timezone.utc).timestamp()
    attempts=[t for t in _login_attempts.get(key,[]) if now-t < 600]
    _login_attempts[key]=attempts
    return len(attempts)>=8
def record_login_failure(key):
    now=datetime.now(timezone.utc).timestamp()
    attempts=[t for t in _login_attempts.get(key,[]) if now-t < 600]
    attempts.append(now); _login_attempts[key]=attempts

ALLOWED={'.jpg','.jpeg','.png','.webp','.gif','.mp4','.webm','.mov'}
def db():
 c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c
with db() as c:
 c.execute("CREATE TABLE IF NOT EXISTS businesses(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,category TEXT,description TEXT,hours TEXT,location TEXT,contact TEXT,photos TEXT DEFAULT '[]',menu TEXT DEFAULT '[]')")
 c.execute("CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,email TEXT NOT NULL UNIQUE,password_hash TEXT NOT NULL,role TEXT NOT NULL DEFAULT 'user',created_at TEXT DEFAULT CURRENT_TIMESTAMP,active INTEGER NOT NULL DEFAULT 1)")
 user_columns={row[1] for row in c.execute('PRAGMA table_info(users)').fetchall()}
 if 'active' not in user_columns: c.execute('ALTER TABLE users ADD COLUMN active INTEGER NOT NULL DEFAULT 1')
 c.execute("CREATE TABLE IF NOT EXISTS page_content(path TEXT PRIMARY KEY, html TEXT NOT NULL, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)")
 c.execute("CREATE TABLE IF NOT EXISTS custom_pages(slug TEXT PRIMARY KEY, title TEXT NOT NULL, html TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
 # Migración compatible con la base de datos creada por versiones anteriores.
 columns={row[1] for row in c.execute("PRAGMA table_info(businesses)").fetchall()}
 needs_menu_migration='menu' not in columns
 if needs_menu_migration: c.execute("ALTER TABLE businesses ADD COLUMN menu TEXT DEFAULT '[]'")
 # Solo durante la primera migración completa el menú conocido de Gorditas Doña Lupe.
 if needs_menu_migration:
  starter_menu=json.dumps([
   {'title':'Gorditas Colonenses','items':['Pollo con papas','Picadillo']},
   {'title':'Gorditas Queretanas','items':['Migajas','Queso']}
  ],ensure_ascii=False)
  c.execute("UPDATE businesses SET menu=? WHERE (menu IS NULL OR menu='' OR menu='[]') AND lower(name) LIKE '%lupe%' AND lower(name) LIKE '%gordita%'",(starter_menu,))
def esc(x): return html.escape(str(x or ''),quote=True)
def format_local_datetime(value):
    """Convierte la fecha UTC a la hora local de Querétaro."""
    if not value:
        return ''
    try:
        dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        try:
            local_zone = ZoneInfo('America/Mexico_City')
        except ZoneInfoNotFoundError:
            # Alternativa para Windows sin base de zonas horarias.
            local_zone = timezone(timedelta(hours=-6), name='America/Mexico_City')
        return dt.astimezone(local_zone).strftime('%Y-%m-%d %H:%M:%S')
    except (ValueError, TypeError, OverflowError):
        return str(value)
def page(title,body):
 return render_template_string('''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{{title}} | Lago de Ajuchitlán</title><style>:root{--navy:#062b3a;--aqua:#55dce4;--bg:#eef5f5;--ink:#173640;--muted:#617a81}*{box-sizing:border-box}body{margin:0;font-family:Arial,sans-serif;background:var(--bg);color:var(--ink)}header{background:var(--navy);color:white;padding:16px max(5%,calc((100% - 1100px)/2));display:flex;align-items:center;justify-content:space-between;gap:15px;flex-wrap:wrap}header a{color:white;text-decoration:none;font-weight:bold}header .site-brand{display:flex;align-items:center;gap:10px;white-space:nowrap}header .site-brand img{width:58px;height:44px;object-fit:contain;background:transparent;border:0;border-radius:0;padding:0;box-shadow:none}header nav{display:flex;gap:12px;flex-wrap:wrap;font-size:13px}main{max-width:1100px;margin:32px auto;padding:0 18px}h1{margin:0 0 8px;font-size:clamp(26px,4vw,38px)}p{line-height:1.6}.muted{color:var(--muted)}.card{background:white;border:1px solid #d8e5e7;border-radius:16px;padding:22px;box-shadow:0 12px 30px #062b3a0c;margin:18px 0}.button,button{display:inline-block;border:0;border-radius:9px;background:var(--aqua);color:#062b3a;padding:11px 16px;font-weight:bold;text-decoration:none;cursor:pointer}.secondary{background:#e3eff0;color:#183b45}.danger{background:#ffe3e3;color:#8c2222}.field{display:flex;flex-direction:column;gap:6px;margin:12px 0}.field label{font-size:13px;font-weight:bold}.field input,.field textarea,.field select{width:100%;padding:12px;border:1px solid #cadbdd;border-radius:8px;font:inherit;background:#fcfefe}.field textarea{min-height:105px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:16px}.biz img{width:100%;height:190px;object-fit:cover;border-radius:10px}.pill{display:inline-block;background:#e2f9f8;color:#087986;border-radius:30px;padding:5px 10px;font-size:12px;font-weight:bold}.actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px}.photos{display:flex;gap:8px;flex-wrap:wrap}.photos img{width:85px;height:70px;object-fit:cover;border-radius:7px}.menu-editor{background:#f8fcfc;border:1px solid #c9e5e6}.menu-group-editor{background:#fff;border:1px solid #d8e5e7;border-radius:12px;padding:14px;margin:12px 0}.food-menu{margin:18px 0;padding:16px;background:#f5fbfb;border:1px solid #d4e8e9;border-radius:12px}.food-menu h3{margin-top:0}.menu-group{margin-top:12px}.menu-group ul{margin:6px 0;padding-left:24px}.menu-group li{padding:3px 0}.biz>img{width:100%;height:190px;object-fit:cover;border-radius:10px}.stats{display:flex;gap:10px;flex-wrap:wrap}.stats span{background:#eaf7f8;border-radius:10px;padding:12px 16px;font-weight:bold}@media(max-width:600px){header{padding:14px}main{margin:20px auto}.card{padding:16px}}</style></head><body><header><a class="site-brand" href="/"><img src="/img/logo-ajuchitlan.png" alt=""><span>Lago de Ajuchitlán</span></a><nav><a href="/">Inicio</a><a href="/historia">Historia</a><a href="/leyendas">Leyendas</a><a href="/actividades">Actividades</a><a href="/lugares">Lugares cercanos</a><a href="/servicios">Puestos y servicios</a>{% if logged %}<a href="/admin">Administración</a><a href="/admin/usuarios">Usuarios</a><a href="/salir">Cerrar sesión</a>{% endif %}</nav></header><main><h1>{{title}}</h1>{{body|safe}}</main></body></html>''',title=title,body=body,logged=session.get('admin_logged') is True)
def logged(): return session.get('admin_logged') is True and session.get('role') == 'admin'

@app.before_request
def validate_user_session():
    uid=session.get('user_id')
    if uid:
        try:
            with db() as c: row=c.execute('SELECT active,role,name,email FROM users WHERE id=?',(uid,)).fetchone()
            if not row or not row['active']:
                session.clear()
            else:
                session['role']=row['role']; session['user_name']=row['name']; session['user_email']=row['email']
                if row['role']=='admin': session['admin_logged']=True
                else: session.pop('admin_logged',None)
        except sqlite3.Error:
            pass

EDITABLE_PAGES={
 'index.html':'Inicio','historia.html':'Historia','leyendas.html':'Leyendas',
 'servicios.html':'Puestos y servicios','lugares.html':'Lugares cercanos',
 'actividades.html':'Actividades','pesca.html':'Pesca','juegos-infantiles.html':'Juegos infantiles',
 'recorrido-turistico.html':'Recorrido turístico','patos.html':'Patos',
 'caminata.html':'Caminata','fauna.html':'Fauna','areas-convivencia.html':'Áreas de convivencia',
 'paseo-en-lancha.html':'Paseo en lancha'
}
def editable_pages():
    pages=dict(EDITABLE_PAGES)
    with db() as c:
        for row in c.execute('SELECT slug,title FROM custom_pages ORDER BY title').fetchall(): pages[row['slug']+'.html']=row['title']
    return pages
def get_page_html(filename):
    if filename not in editable_pages(): abort(404)
    with db() as c:
        row=c.execute('SELECT html FROM page_content WHERE path=?',(filename,)).fetchone()
        custom=c.execute('SELECT html FROM custom_pages WHERE slug=?',(filename[:-5],)).fetchone() if filename.endswith('.html') else None
    if row:
        saved = row['html'] or ''
        # Recover from accidental blank saves by falling back to the bundled source page.
        body_match = re.search(r'<body\b[^>]*>(.*?)</body>', saved, flags=re.I|re.S)
        visible = re.sub(r'<(script|style|nav|header|footer)\b[^>]*>.*?</\1>', '', body_match.group(1), flags=re.I|re.S) if body_match else ''
        plain = re.sub(r'<[^>]+>', '', visible).replace('&nbsp;', ' ').strip()
        has_media = bool(re.search(r'<(img|video|iframe|main|section|article)\b', visible, flags=re.I))
        if len(plain) >= 20 or has_media:
            return saved
    if custom: return custom['html']
    return (ROOT/filename).read_text(encoding='utf-8')
def send_site_page(filename):
    from flask import Response
    content=get_page_html(filename)
    common = r"""
<style>
body>header:not(.lago-topbar){display:none!important}.main-nav{display:none!important}.menu-toggle{display:none!important}.lago-topbar{position:fixed;top:0;left:0;right:0;width:100%;z-index:9998;display:flex;align-items:center;gap:12px;padding:9px 16px;background:#062b3a;color:#fff;box-shadow:0 3px 18px #001a2440;font:14px Arial,sans-serif}
body{padding-top:58px!important}.lago-topbar button,.lago-topbar a{color:#fff;background:transparent;border:0;text-decoration:none;cursor:pointer;font:inherit}
.lago-brand{display:flex;align-items:center;gap:9px;font-weight:bold;flex:1}.lago-brand img{width:40px;height:40px;object-fit:contain}.lago-iconbtn{font-size:23px!important;padding:6px 9px!important;border-radius:8px}.lago-iconbtn:hover{background:#ffffff18}
.lago-search{display:flex;gap:5px;align-items:center}.lago-search input{width:min(24vw,230px);padding:9px 12px;border:1px solid #ffffff44;border-radius:22px;background:#ffffff12;color:white}
.lago-profile{position:relative}.lago-avatar{width:38px;height:38px;border-radius:50%;object-fit:cover;border:2px solid #55dce4;cursor:pointer;background:#164a58}.lago-pop{display:none;position:absolute;right:0;top:47px;width:245px;padding:12px;background:#082f3d;color:#fff;border:1px solid #ffffff30;border-radius:12px;box-shadow:0 12px 30px #0004}.lago-pop.open{display:block}.lago-pop button,.lago-pop a{display:block;width:100%;text-align:left;padding:10px;border-radius:7px}.lago-pop button:hover,.lago-pop a:hover{background:#ffffff18}.lago-userrow{display:flex;gap:10px;align-items:center;padding:8px;border-bottom:1px solid #ffffff25;margin-bottom:6px}
.lago-drawer{position:fixed;z-index:10000;left:0;top:0;bottom:0;width:285px;max-width:85vw;background:#082f3d;color:#fff;transform:translateX(-105%);transition:transform .22s;overflow:auto;padding:16px;box-shadow:8px 0 32px #0003;font:14px Arial,sans-serif}.lago-drawer.open{transform:translateX(0)}.lago-drawer a,.lago-drawer summary{display:block;padding:11px 12px;color:#fff;text-decoration:none;border-radius:8px;cursor:pointer}.lago-drawer a:hover,.lago-drawer summary:hover{background:#ffffff17}.lago-drawer details a{padding-left:30px;color:#b9eff0}.lago-drawer .drawer-label{font-size:11px;letter-spacing:1.5px;color:#55dce4;padding:18px 12px 5px}.lago-scrim{display:none;position:fixed;inset:0;background:#00151d88;z-index:9999}.lago-scrim.open{display:block}
body.lago-dark{background:#101c22!important;color:#edf7f8!important}body.lago-dark main,body.lago-dark section,body.lago-dark article,body.lago-dark div{color:inherit}body.lago-dark .card{background:#172a32!important;color:#edf7f8!important;border-color:#29444d!important}body.lago-dark h1,body.lago-dark h2,body.lago-dark h3,body.lago-dark h4,body.lago-dark p,body.lago-dark li,body.lago-dark small,body.lago-dark label,body.lago-dark strong{color:#edf7f8!important}body.lago-dark .muted,body.lago-dark .subtitle,body.lago-dark .description{color:#c3d5da!important}body.lago-dark a:not(.lago-topbar a){color:#70e4e8}body.lago-dark button,body.lago-dark .button{color:#062b3a!important}body.lago-dark input,body.lago-dark textarea,body.lago-dark select{color:#edf7f8;background:#20363f;border-color:#49616a}
/* Contraste garantizado para controles del menú y texto en ambos temas */
.lago-topbar .lago-iconbtn{color:#ffffff!important;background:transparent!important;min-width:40px;min-height:40px;display:inline-flex;align-items:center;justify-content:center;font-weight:700!important;opacity:1!important;text-shadow:0 1px 2px #00151d}
.lago-topbar .lago-iconbtn:hover,.lago-topbar .lago-iconbtn:focus-visible{background:#ffffff24!important;outline:2px solid #55dce4;outline-offset:1px}
.lago-topbar #lagoMenuBtn{display:inline-flex!important;flex-shrink:0!important;color:#ffffff!important;font-size:26px!important;visibility:visible!important;opacity:1!important}
.lago-topbar #lagoThemeBtn{color:#ffffff!important;font-size:23px!important;visibility:visible!important}
body.lago-dark{color:#f2fbfc!important}
body.lago-dark main,body.lago-dark main *:not(.button):not(button){text-shadow:none}
body.lago-dark h1,body.lago-dark h2,body.lago-dark h3,body.lago-dark h4,body.lago-dark p,body.lago-dark li,body.lago-dark small,body.lago-dark label,body.lago-dark strong,body.lago-dark span{color:#f2fbfc!important;opacity:1!important}
body.lago-dark .muted,body.lago-dark .subtitle,body.lago-dark .description{color:#c8dfe4!important;opacity:1!important}
body.lago-dark .lago-topbar,body.lago-dark .lago-topbar *{color:#fff!important}
body.lago-dark .lago-pop,body.lago-dark .lago-drawer{background:#082f3d!important;color:#fff!important}
body.lago-dark .lago-drawer a,body.lago-dark .lago-drawer summary,body.lago-dark .lago-pop a,body.lago-dark .lago-pop button{color:#fff!important}

@media(max-width:760px){.lago-search input{width:100px}.lago-brand span{font-size:13px}.lago-topbar{gap:6px;padding:7px}}

/* Corrección de contraste: tarjetas de contenido en modo oscuro.
   Mantiene la estructura y el diseño; evita texto claro sobre tarjetas blancas. */
body.lago-dark .history-block,
body.lago-dark .access-card,
body.lago-dark .activity-card,
body.lago-dark .activity-card-copy,
body.lago-dark .legend-full-card,
body.lago-dark .detail-body,
body.lago-dark .note-panel,
body.lago-dark .route-stats,
body.lago-dark .route-layout,
body.lago-dark .local-food-card,
body.lago-dark .business-card,
body.lago-dark .business-directory-card,
body.lago-dark .directory-tools,
body.lago-dark .directory-admin-note,
body.lago-dark .auth-card,
body.lago-dark .card,
body.lago-dark .panel,
body.lago-dark .admin-card,
body.lago-dark .editor-panel,
body.lago-dark .editor-sidebar,
body.lago-dark .editor-preview-frame {
  background-color: #172a32 !important;
  color: #edf7f8 !important;
  border-color: #29444d !important;
}
body.lago-dark .history-block h3,
body.lago-dark .history-block h4,
body.lago-dark .history-block p,
body.lago-dark .access-card h3,
body.lago-dark .access-card p,
body.lago-dark .access-card small,
body.lago-dark .activity-card-copy h2,
body.lago-dark .activity-card-copy p,
body.lago-dark .legend-full-copy h2,
body.lago-dark .legend-full-copy p,
body.lago-dark .detail-body h1,
body.lago-dark .detail-body h2,
body.lago-dark .detail-body h3,
body.lago-dark .detail-body h4,
body.lago-dark .detail-body p,
body.lago-dark .detail-body li,
body.lago-dark .route-layout h2,
body.lago-dark .route-layout h3,
body.lago-dark .route-layout p,
body.lago-dark .route-layout li,
body.lago-dark .route-stats strong,
body.lago-dark .route-stats span,
body.lago-dark .route-stats p,
body.lago-dark .local-food-copy h3,
body.lago-dark .local-food-copy h4,
body.lago-dark .local-food-copy p,
body.lago-dark .local-food-copy li,
body.lago-dark .directory-admin-note p {
  color: #edf7f8 !important;
  opacity: 1 !important;
}
body.lago-dark .history-block p,
body.lago-dark .access-card p,
body.lago-dark .access-card small,
body.lago-dark .activity-card-copy p,
body.lago-dark .legend-full-copy p:not(.eyebrow),
body.lago-dark .detail-body p,
body.lago-dark .detail-body li,
body.lago-dark .route-layout p,
body.lago-dark .route-layout li,
body.lago-dark .local-food-copy p,
body.lago-dark .local-food-copy li {
  color: #c8dfe4 !important;
}
body.lago-dark .explore-strip,
body.lago-dark .location-section,
body.lago-dark .directory-section,
body.lago-dark .section-wrap,
body.lago-dark .about-section {
  color: #edf7f8;
}
body.lago-dark input,
body.lago-dark textarea,
body.lago-dark select {
  background-color: #20363f !important;
  color: #edf7f8 !important;
  border-color: #49616a !important;
}

</style>
<div class="lago-topbar" id="lagoTopbar"><button class="lago-iconbtn" id="lagoMenuBtn" aria-label="Abrir menú">☰</button><a class="lago-brand" href="/"><img src="/img/logo-ajuchitlan.png" alt=""><span>Lago de Ajuchitlán</span></a><form class="lago-search" id="lagoSearchForm"><input id="lagoSearchInput" type="search" placeholder="Buscar…" aria-label="Buscar"><button class="lago-iconbtn" aria-label="Buscar">⌕</button></form><button class="lago-iconbtn" id="lagoThemeBtn" title="Cambiar apariencia">☾</button><div class="lago-profile"><img class="lago-avatar" id="lagoAvatar" alt="Perfil" title="Perfil y sesión"><div class="lago-pop" id="lagoProfilePop"><div class="lago-userrow"><img class="lago-avatar" id="lagoAvatarSmall" alt="" style="width:44px;height:44px"><div><strong id="lagoUserName">Visitante</strong><div id="lagoUserRole" style="font-size:12px;color:#a9dfe2">Visitante</div></div></div><button id="lagoChangePhoto">Cambiar foto de perfil</button><button id="lagoThemeProfile">Cambiar claro/oscuro</button><a id="lagoAdminLink" href="/admin/editor" style="display:none">Administración y editor</a><a id="lagoLoginLink" href="/login">Iniciar sesión</a><a id="lagoRegisterLink" href="/registro">Registrarse</a><a id="lagoLogoutLink" href="/salir" style="display:none">Cerrar sesión</a></div></div></div>
<div class="lago-scrim" id="lagoScrim"></div><aside class="lago-drawer" id="lagoDrawer"><div style="display:flex;align-items:center;justify-content:space-between"><strong>Explorar el lago</strong><button class="lago-iconbtn" id="lagoCloseDrawer">×</button></div><a href="/">⌂　Inicio</a><div class="drawer-label">HISTORIA Y CULTURA</div><details><summary>Historia</summary><a href="/historia">Historia del lago</a><a href="/leyendas">Leyendas</a></details><div class="drawer-label">SERVICIOS</div><details><summary>Puestos y servicios</summary><a href="/servicios">Todos los puestos</a><a href="/lugares">Lugares cercanos</a></details><div class="drawer-label">ACTIVIDADES</div><details><summary>Actividades</summary><a href="/actividades">Todas las actividades</a><a href="/pesca.html">Pesca</a><a href="/juegos-infantiles.html">Juegos infantiles</a><a href="/recorrido-turistico.html">Recorrido turístico</a><a href="/patos.html">Patos y fauna</a><a href="/paseo-en-lancha.html">Paseo en lancha</a></details><a href="/admin/editor" id="lagoDrawerAdmin" style="display:none">⚙　Administración y editor</a></aside>
<script id="lago-navigation-script">(function(){const $=id=>document.getElementById(id),drawer=$('lagoDrawer'),scrim=$('lagoScrim'),pop=$('lagoProfilePop');function closeDrawer(){drawer.classList.remove('open');scrim.classList.remove('open')}$('lagoMenuBtn').onclick=()=>{drawer.classList.add('open');scrim.classList.add('open')};$('lagoCloseDrawer').onclick=closeDrawer;scrim.onclick=closeDrawer;
function theme(t){document.body.classList.toggle('lago-dark',t==='dark');try{localStorage.setItem('lago-theme',t)}catch(e){}$('lagoThemeBtn').textContent=t==='dark'?'☀':'☾'}let initial='light';try{initial=localStorage.getItem('lago-theme')||'light'}catch(e){}theme(initial);$('lagoThemeBtn').onclick=()=>theme(document.body.classList.contains('lago-dark')?'light':'dark');$('lagoThemeProfile').onclick=()=>theme(document.body.classList.contains('lago-dark')?'light':'dark');
const avatarSvg='data:image/svg+xml;charset=utf-8,'+encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 80 80"><circle cx="40" cy="40" r="39" fill="#1b6571"/><circle cx="40" cy="29" r="14" fill="#d7f3f2"/><path d="M12 73c3-18 16-26 28-26s25 8 28 26" fill="#d7f3f2"/></svg>');let photo=avatarSvg;try{photo=localStorage.getItem('lago-profile-photo')||avatarSvg}catch(e){}$('lagoAvatar').src=photo;$('lagoAvatarSmall').src=photo;$('lagoAvatar').onclick=()=>pop.classList.toggle('open');document.addEventListener('click',e=>{if(!e.target.closest('.lago-profile'))pop.classList.remove('open')});
$('lagoChangePhoto').onclick=()=>{const input=document.createElement('input');input.type='file';input.accept='image/*';input.onchange=()=>{const f=input.files[0];if(!f)return;if(f.size>2*1024*1024){alert('Elige una imagen de menos de 2 MB.');return}const rd=new FileReader();rd.onload=()=>{try{localStorage.setItem('lago-profile-photo',rd.result)}catch(e){}$('lagoAvatar').src=rd.result;$('lagoAvatarSmall').src=rd.result};rd.readAsDataURL(f)};input.click()};
fetch('/api/paginas').then(r=>r.json()).then(pages=>{const drawer=$('lagoDrawer');const admin=$('lagoDrawerAdmin');pages.forEach(p=>{const a=document.createElement('a');a.href=p.url;a.textContent=p.title;if(admin)drawer.insertBefore(a,admin);else drawer.appendChild(a);});}).catch(()=>{});
fetch('/api/sesion').then(r=>r.json()).then(s=>{if(s.logged_in){$('lagoUserName').textContent=s.name||'Cuenta';$('lagoUserRole').textContent=s.admin?'Administrador':'Usuario';$('lagoLoginLink').style.display='none';$('lagoRegisterLink').style.display='none';$('lagoLogoutLink').style.display='block';if(s.admin){$('lagoAdminLink').style.display='block';$('lagoDrawerAdmin').style.display='block'}}}).catch(()=>{});
$('lagoSearchForm').addEventListener('submit',e=>{e.preventDefault();const q=$('lagoSearchInput').value.trim().toLocaleLowerCase('es');if(!q)return;const pages=[['Inicio','/'],['Historia','/historia'],['Leyendas','/leyendas'],['Puestos y servicios','/servicios'],['Lugares cercanos','/lugares'],['Actividades','/actividades'],['Pesca','/pesca.html'],['Juegos infantiles','/juegos-infantiles.html'],['Recorrido turístico','/recorrido-turistico.html']];const match=pages.find(p=>p[0].toLocaleLowerCase('es').includes(q));if(match){location.href=match[1];return}const el=[...document.querySelectorAll('h1,h2,h3,p,li')].find(x=>x.innerText.toLocaleLowerCase('es').includes(q));if(el){el.scrollIntoView({behavior:'smooth',block:'center'});el.style.outline='2px solid #55dce4'}else alert('No se encontró ese término en esta página.')});
})();</script>
"""
    lower=content.lower()
    if '</body>' in lower:
        idx=lower.rfind('</body>')
        content=content[:idx]+common+content[idx:]
    else:
        content += common
    return Response(content, mimetype='text/html; charset=utf-8')
@app.route('/')
def home(): return send_site_page('index.html')

@app.route('/historia')
def history_page(): return send_site_page('historia.html')

@app.route('/leyendas')
def legends_page(): return send_site_page('leyendas.html')

@app.route('/actividades')
def activities_page(): return send_site_page('actividades.html')

@app.route('/lugares')
def places_page(): return send_site_page('lugares.html')

@app.route('/api/paginas')
def custom_pages_api():
    with db() as c: rows=c.execute('SELECT slug,title FROM custom_pages ORDER BY title').fetchall()
    return jsonify([{'slug':r['slug'],'title':r['title'],'url':'/pagina/'+r['slug']} for r in rows])

@app.route('/api/sesion')
def session_info():
    return jsonify({'logged_in': bool(session.get('user_id') or logged()), 'admin': logged(), 'name': session.get('user_name') or session.get('user_email') or ('Administrador' if logged() else ''), 'role': session.get('role','visitor')})

@app.route('/admin/editor')
def page_editor():
    if not logged(): return redirect('/admin/entrar')
    options=''.join(f"<option value=\"{esc(path)}\">{esc(label)}</option>" for path,label in editable_pages().items())
    body=f"""<style>main{{max-width:none!important;width:100%;padding:0 18px!important;margin:18px auto!important}}.editor-workspace{{display:grid;grid-template-columns:minmax(300px,340px) minmax(0,1fr);gap:14px;align-items:start;width:100%}}.editor-toolbar{{position:sticky;top:10px;max-height:calc(100vh - 24px);overflow:auto;margin:0}}.editor-toolbar .actions{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:7px}}.editor-toolbar button,.editor-toolbar .button{{font-size:12px;padding:10px 8px;text-align:center}}.editor-toolbar .field{{min-width:0!important}}.editor-toolbar input[type=color]{{height:38px;padding:3px}}.editor-canvas{{min-width:0;width:100%;margin:0}}.editor-canvas iframe{{display:block;width:100%;height:calc(100vh - 190px)!important;min-height:650px}}.editor-toolbar #layersPanel button{{display:block;width:100%;text-align:left;margin:4px 0;background:#edf6f6}}.editor-toolbar #layersPanel{{max-height:220px;overflow:auto}}@media(max-width:900px){{main{{padding:0 8px!important}}.editor-workspace{{grid-template-columns:1fr}}.editor-toolbar{{position:sticky;top:0;max-height:38vh;z-index:5}}.editor-toolbar .actions{{grid-template-columns:repeat(3,minmax(0,1fr))}}}}</style><div class='card'><p>Selecciona una página y edita el contenido directamente en la vista previa. Haz clic en un texto para modificarlo; haz clic en una imagen para cambiar su dirección. También puedes agregar una sección sencilla.</p><div class='field'><label for='pageChoice'>Página que deseas editar</label><select id='pageChoice'>{options}</select></div><div class='actions'><button id='loadPage'>Cargar página</button><button class='button secondary' id='addSection'>＋ Agregar sección</button><button id='savePage'>Guardar cambios</button><a class='button secondary' href='/admin'>Volver al panel de administración</a><a class='button secondary' href='/admin/paginas'>Administrar páginas</a><a class='button secondary' href='/' target='_blank'>Ver sitio público ↗</a></div><p id='editorStatus' class='muted'>Los cambios se guardan en la base de datos local de este proyecto.</p></div><div class='editor-workspace'><div class='card editor-toolbar'><strong>Herramientas de edición</strong><p class='muted' style='margin:6px 0'>Selecciona un elemento y edítalo desde aquí.</p><div class='actions'>
<button type='button' id='boldTool' class='secondary'>Negrita</button><button type='button' id='italicTool' class='secondary'>Cursiva</button><button type='button' id='underlineTool' class='secondary'>Subrayar</button><button type='button' id='alignLeft' class='secondary'>Alinear izquierda</button><button type='button' id='alignCenter' class='secondary'>Centrar</button><button type='button' id='alignRight' class='secondary'>Alinear derecha</button><button type='button' id='alignJustify' class='secondary'>Justificar</button>
<label class='field' style='margin:0;min-width:120px'>Tamaño <select id='fontSizeTool'><option value='2'>Pequeño</option><option value='3' selected>Normal</option><option value='4'>Grande</option><option value='5'>Muy grande</option><option value='6'>Título</option></select></label>
<label class='field' style='margin:0'>Color <input type='color' id='colorTool' value='#173640'></label>
<button type='button' id='addText' class='secondary'>＋ Texto</button><button type='button' id='addBlockAfter' class='secondary'>＋ Bloque debajo</button><button type='button' id='textWidthTool' class='secondary'>Ancho del texto</button><button type='button' id='imageBesideText' class='secondary'>Imagen al lado del texto</button><button type='button' id='addImage' class='secondary'>＋ Imagen</button><button type='button' id='replaceImage' class='secondary'>Reemplazar imagen seleccionada</button><button type='button' id='resizeImage' class='secondary'>Tamaño de imagen</button><button type='button' id='cropImage' class='secondary'>Recortar imagen</button><button type='button' id='moveUp' class='secondary'>Mover ↑</button><button type='button' id='moveDown' class='secondary'>Mover ↓</button><button type='button' id='renamePageTitle' class='secondary'>Editar título</button><button type='button' id='addVideo' class='secondary'>＋ Video</button><label class='button secondary' for='uploadMedia'>Subir archivo</label><input id='uploadMedia' type='file' accept='image/*,video/mp4,video/webm,video/quicktime' style='display:none'><button type='button' id='undoTool' class='secondary'>↶ Deshacer</button><button type='button' id='redoTool' class='secondary'>↷ Rehacer</button><button type='button' id='desktopView' class='secondary'>Vista escritorio</button><button type='button' id='tabletView' class='secondary'>Vista tablet</button><button type='button' id='mobileView' class='secondary'>Vista celular</button><button type='button' id='layersTool' class='secondary'>Lista de elementos</button><button type='button' id='deleteElement' class='danger'>Eliminar elemento</button>
</div><p class='muted'>Arrastra texto e imágenes para moverlos. Las imágenes seleccionadas muestran controles de tamaño. Usa Guardar cambios para conservar la edición.</p><div id='layersPanel' style='display:none;margin-top:10px'></div></div>
<div class='card editor-canvas' style='padding:0;overflow:hidden'><iframe id='pagePreview' title='Vista previa editable' style='width:100%;height:78vh;border:0;background:white'></iframe></div></div>
<script>
const choice=document.getElementById('pageChoice'), frame=document.getElementById('pagePreview'), status=document.getElementById('editorStatus');
function clearResizeOverlay(doc){{const ov=doc&&doc.getElementById('__editorResizeOverlay');if(ov)ov.remove();}}
function positionResizeOverlay(doc,img){{const ov=doc&&doc.getElementById('__editorResizeOverlay');if(!ov||!img)return;const r=img.getBoundingClientRect();ov.style.left=(r.left+doc.defaultView.scrollX)+'px';ov.style.top=(r.top+doc.defaultView.scrollY)+'px';ov.style.width=r.width+'px';ov.style.height=r.height+'px';}}
function showResizeOverlay(doc,img){{if(!doc||!img)return;clearResizeOverlay(doc);const ov=doc.createElement('div');ov.id='__editorResizeOverlay';ov.style.cssText='position:absolute;border:2px solid #22cbd5;box-sizing:border-box;z-index:2147483000;pointer-events:none;';const positions=['nw','n','ne','e','se','s','sw','w'];const cursors=['nwse-resize','ns-resize','nesw-resize','ew-resize','nwse-resize','ns-resize','nesw-resize','ew-resize'];positions.forEach((pos,i)=>{{const h=doc.createElement('span');h.dataset.handle=pos;h.style.cssText='position:absolute;width:11px;height:11px;background:#fff;border:2px solid #12aeba;border-radius:2px;transform:translate(-50%,-50%);pointer-events:auto;cursor:'+cursors[i]+';';const coords={{nw:['0%','0%'],n:['50%','0%'],ne:['100%','0%'],e:['100%','50%'],se:['100%','100%'],s:['50%','100%'],sw:['0%','100%'],w:['0%','50%']}}[pos];h.style.left=coords[0];h.style.top=coords[1];h.addEventListener('pointerdown',e=>{{e.preventDefault();e.stopPropagation();const start={{x:e.clientX,y:e.clientY,w:img.getBoundingClientRect().width,h:img.getBoundingClientRect().height}};const aspect=start.w/(start.h||1);const move=ev=>{{let dx=ev.clientX-start.x,dy=ev.clientY-start.y;let nw=start.w,nh=start.h;if(pos.includes('e'))nw+=dx;if(pos.includes('w'))nw-=dx;if(pos.includes('s'))nh+=dy;if(pos.includes('n'))nh-=dy;if(ev.shiftKey)nh=nw/aspect;nw=Math.max(30,nw);nh=Math.max(25,nh);img.style.width=nw+'px';img.style.height=nh+'px';img.style.maxWidth='none';img.style.objectFit=img.style.objectFit||'contain';positionResizeOverlay(doc,img);}};const end=()=>{{doc.removeEventListener('pointermove',move);doc.removeEventListener('pointerup',end);doc.removeEventListener('pointercancel',end);snapshot();}};doc.addEventListener('pointermove',move);doc.addEventListener('pointerup',end);doc.addEventListener('pointercancel',end);}});ov.appendChild(h);}});doc.body.appendChild(ov);positionResizeOverlay(doc,img);}}
let currentHtml='';
let previewReady=false;
let replaceSelectedImage=false;
let undoStack=[], redoStack=[], lastSnapshot='', savedSelectionRange=null;
function rememberTextSelection(doc) {{
  try {{
    const sel=doc.getSelection();
    if(sel && sel.rangeCount && sel.anchorNode && doc.documentElement.contains(sel.anchorNode)) savedSelectionRange=sel.getRangeAt(0).cloneRange();
  }} catch(e) {{}}
}}
function prepareTextRuns(doc) {{
  const targets=[...doc.querySelectorAll('h1,h2,h3,h4,h5,p,li,blockquote,em,strong')];
  targets.forEach(el=>{{
    [...el.childNodes].forEach(node=>{{
      if(node.nodeType===3 && node.nodeValue.trim()) {{
        const span=doc.createElement('span');
        span.setAttribute('data-editor-text-run','1');
        span.textContent=node.nodeValue;
        el.replaceChild(span,node);
      }}
    }});
  }});
}}
function snapshot(){{const d=frame.contentDocument;if(!d||!d.documentElement)return;const now=d.body.innerHTML;if(now!==lastSnapshot){{undoStack.push(lastSnapshot);if(undoStack.length>50)undoStack.shift();lastSnapshot=now;redoStack=[];}}}}
function pushUndo(){{const d=frame.contentDocument;if(!d||!d.body)return;const now=d.body.innerHTML;if(now!==lastSnapshot)lastSnapshot=now;undoStack.push(now);if(undoStack.length>50)undoStack.shift();redoStack=[];}}
function restoreHtml(html){{const d=frame.contentDocument;if(!d)return;d.body.innerHTML=html;lastSnapshot=d.body.innerHTML;prepareEditableDocument(d);}}
function editorMessage(d) {{
  const doc=frame.contentDocument; if(!doc || !doc.body) {{ status.textContent='Primero pulsa Cargar página y espera a que aparezca la vista previa.'; return; }}
  if(!previewReady) {{ status.textContent='La vista previa aún no está lista. Pulsa Cargar página y espera un momento.'; return; }}
  pushUndo();
  let selected=doc.querySelector('[data-editor-selected="1"]');
  if(d==='ADD_SECTION') {{
    const s=doc.createElement('section'); s.style.cssText='padding:48px 6%;background:#eef5f5;color:#173640;min-height:120px';
    s.innerHTML='<h2>Nueva sección</h2><p>Haz clic aquí para escribir el contenido de esta sección.</p>';
    (doc.querySelector('main')||doc.body).appendChild(s); selected=s;
  }} else if(d && d.cmd) {{
    if(d.cmd==='FORMAT') {{
      const sel=doc.getSelection();
      if(savedSelectionRange && savedSelectionRange.startContainer && doc.documentElement.contains(savedSelectionRange.startContainer)) {{
        try {{ sel.removeAllRanges(); sel.addRange(savedSelectionRange); }} catch(e) {{}}
      }}
      let prop=null,val=null;
      if(d.value==='bold') {{prop='fontWeight';val='700';}}
      else if(d.value==='italic') {{prop='fontStyle';val='italic';}}
      else if(d.value==='underline') {{prop='textDecoration';val='underline';}}
      else if(String(d.value).startsWith('#')) {{prop='color';val=d.value;}}
      else if(String(d.value).startsWith('size:')) {{prop='fontSize';val=({{'2':'0.85em','3':'1em','4':'1.25em','5':'1.5em','6':'2em'}})[String(d.value).slice(5)]||'1em';}}
      if(prop && sel && sel.rangeCount && !sel.isCollapsed && doc.documentElement.contains(sel.getRangeAt(0).commonAncestorContainer)) {{
        const range=sel.getRangeAt(0);
        const span=doc.createElement('span');span.style[prop]=val;
        try {{
          const fragment=range.extractContents();span.appendChild(fragment);range.insertNode(span);
          sel.removeAllRanges();const next=doc.createRange();next.selectNodeContents(span);sel.addRange(next);savedSelectionRange=next.cloneRange();selected=span;
        }} catch(e) {{ if(selected) selected.style[prop]=val; }}
      }} else if(prop && selected) {{
        selected.style[prop]=val;
      }}
    }}
    if(d.cmd==='ADD_TEXT') {{
      const p=doc.createElement('p'); p.textContent='Escribe aquí tu texto nuevo.'; p.contentEditable='true';
      p.style.cssText='display:block;box-sizing:border-box;width:100%;min-height:2.2em;margin:12px 0;padding:8px 10px;border:1px dashed #22aeba;border-radius:6px;background:rgba(85,220,228,.10);color:inherit;';
      // Insertar justo después del elemento seleccionado, no al final de toda la página.
      // Si el elemento elegido es un contenedor grande, buscar el bloque más cercano al clic.
      let anchor=selected;
      if(anchor && anchor!==doc.body && anchor!==doc.documentElement) {{
        if(['SECTION','ARTICLE','MAIN','DIV'].includes(anchor.tagName)) {{
          const inner=anchor.querySelector('[data-editor-selected="1"]');
          if(inner && inner!==anchor) anchor=inner;
          else {{ const rect=anchor.getBoundingClientRect(); const candidates=[...anchor.querySelectorAll('h1,h2,h3,h4,p,blockquote,li')]; const visible=candidates.filter(x=>x.getClientRects().length); if(visible.length) anchor=visible.reduce((best,x)=>Math.abs(x.getBoundingClientRect().bottom-rect.bottom)<Math.abs(best.getBoundingClientRect().bottom-rect.bottom)?x:best,visible[0]); }}
        }}
        if(anchor && anchor.parentNode) anchor.insertAdjacentElement('afterend',p);
        else (doc.querySelector('main')||doc.body).appendChild(p);
      }} else (doc.querySelector('main')||doc.body).appendChild(p);
      selected=p; p.focus(); status.textContent='Texto agregado en el lugar seleccionado. Haz clic en el recuadro y escribe; puedes deshacer si no era el sitio correcto.';
    }}
    if(d.cmd==='ADD_BLOCK_AFTER') {{
      const section=doc.createElement('section'); section.style.cssText='display:block;clear:both;box-sizing:border-box;width:100%;padding:24px;margin:24px 0;background:#f0f7f7;border-radius:14px;';
      section.innerHTML='<h2 contenteditable="true">Nueva historia o apartado</h2><p contenteditable="true">Escribe aquí la información de este apartado.</p>';
      if(selected && selected.parentNode && selected!==doc.body) selected.insertAdjacentElement('afterend',section); else (doc.querySelector('main')||doc.body).appendChild(section); selected=section;
    }}
    if(d.cmd==='TEXT_WIDTH' && selected) {{
      const current=selected.style.maxWidth||'100%'; const value=prompt('Ancho máximo del texto (ejemplos: 600px, 70%, 100%):',current);
      if(value && /^(\\d+(px|%|rem|em|vw)?)$/.test(value.trim())) {{ selected.style.width='100%'; selected.style.maxWidth=/[a-z%]/.test(value.trim())?value.trim():value.trim()+'px'; selected.style.boxSizing='border-box'; }}
    }}
    if(d.cmd==='IMAGE_BESIDE_TEXT') {{
      if(!selected || !['P','H1','H2','H3','H4','BLOCKQUOTE','DIV'].includes(selected.tagName)) {{ alert('Primero selecciona el párrafo o texto que quieres acomodar junto a una imagen.'); }}
      else {{ const u=prompt('Dirección de la imagen (URL o ruta, por ejemplo /img/lago-portada.jpg):'); if(u) {{
        const wrap=doc.createElement('div'); wrap.style.cssText='display:grid;grid-template-columns:minmax(0,1fr) minmax(180px,40%);gap:24px;align-items:center;width:100%;box-sizing:border-box;margin:22px 0;';
        const textCol=doc.createElement('div'); textCol.style.cssText='min-width:0;'; const imgCol=doc.createElement('div'); imgCol.style.cssText='min-width:0;'; const im=doc.createElement('img'); im.src=u; im.alt='Imagen relacionada'; im.style.cssText='display:block;width:100%;height:auto;max-width:100%;object-fit:cover;border-radius:12px;';
        selected.parentNode.insertBefore(wrap,selected); textCol.appendChild(selected); imgCol.appendChild(im); wrap.append(textCol,imgCol); selected=wrap;
        const style=doc.createElement('style'); style.textContent='@media(max-width:650px){{.editor-side-by-side{{grid-template-columns:1fr!important}}}}'; doc.head.appendChild(style); wrap.classList.add('editor-side-by-side');
      }}
    }}
    }}
    if(d.cmd==='ADD_IMAGE') {{
      const u=prompt('Dirección de imagen (URL o ruta como /img/lago-portada.jpg):');
      if(u) {{ const im=doc.createElement('img'); im.src=u; im.alt='Imagen del Lago de Ajuchitlán'; im.style.maxWidth='100%'; (doc.querySelector('main')||doc.body).appendChild(im); selected=im; }}
    }}
    if(d.cmd==='ADD_VIDEO') {{
      const u=prompt('Pega el enlace de YouTube o la dirección del video:');
      if(u) {{ const m=u.match(/[?&]v=([^&]+)/)||u.match(/youtu\\.be\\/([^?&]+)/); const box=doc.createElement('div'); if(m) box.innerHTML='<iframe width="100%" height="420" src="https://www.youtube.com/embed/'+m[1]+'" allowfullscreen></iframe>'; else {{ const v=doc.createElement('video'); v.controls=true; v.style.maxWidth='100%'; v.src=u; box.appendChild(v); }} (doc.querySelector('main')||doc.body).appendChild(box); selected=box; }}
    }}
    if(d.cmd==='ALIGN' && selected) {{
      const map={{left:'left',center:'center',right:'right',justify:'justify'}};
      selected.style.textAlign=map[d.value]||'left';
    }}
    if(d.cmd==='CROP_IMAGE' && selected) {{
      let im=selected.tagName==='IMG'?selected:selected.querySelector('img');
      if(im) {{
        const top=prompt('Recorte superior en porcentaje (0 a 90):','0');
        if(top===null)return;
        const bottom=prompt('Recorte inferior en porcentaje (0 a 90):','0');
        if(bottom===null)return;
        const left=prompt('Recorte izquierdo en porcentaje (0 a 90):','0');
        if(left===null)return;
        const right=prompt('Recorte derecho en porcentaje (0 a 90):','0');
        if(right===null)return;
        const vals=[top,bottom,left,right].map(v=>Math.max(0,Math.min(90,Number(v)||0)));
        im.style.clipPath='inset('+vals[0]+'% '+vals[3]+'% '+vals[1]+'% '+vals[2]+'%)';
      }} else alert('Selecciona una imagen primero.');
    }}
    if(d.cmd==='RESIZE_IMAGE' && selected) {{
      let im=selected.tagName==='IMG'?selected:selected.querySelector('img');
      if(im) {{ const w=prompt('Ancho de la imagen en píxeles (por ejemplo 500) o porcentaje (por ejemplo 80%):',im.style.width||'100%'); if(w && /^(\\d+(px|%)?)$/.test(w.trim())) {{ im.style.width=/px|%$/.test(w.trim())?w.trim():w.trim()+'px'; im.style.height='auto'; im.style.maxWidth='100%'; selected=im; }} }}
      else alert('Selecciona una imagen primero.');
    }}
    if(d.cmd==='MOVE_UP' && selected && selected.previousElementSibling) {{ selected.parentNode.insertBefore(selected,selected.previousElementSibling); }}
    if(d.cmd==='MOVE_DOWN' && selected && selected.nextElementSibling) {{ selected.parentNode.insertBefore(selected.nextElementSibling,selected); }}
    if(d.cmd==='RENAME_TITLE') {{
      const title=doc.querySelector('main h1, h1');
      if(title) {{ const t=prompt('Nuevo título de esta página:',title.innerText); if(t!==null && t.trim()) title.innerText=t.trim(); selected=title; }}
      else alert('No se encontró un título principal en esta página.');
    }}
    if(d.cmd==='DELETE' && selected) {{ selected.remove(); }}
  }}
  if(selected && selected.isConnected) {{ doc.querySelectorAll('[data-editor-selected]').forEach(x=>{{x.removeAttribute('data-editor-selected');x.style.outline='';}}); selected.setAttribute('data-editor-selected','1'); selected.style.outline='2px solid #22cbd5'; }}
}}
async function loadPage() {{
  status.textContent='Cargando página…';
  try {{
    const r=await fetch('/admin/editor/contenido/'+encodeURIComponent(choice.value),{{cache:'no-store'}});
    if(!r.ok) throw new Error('El servidor respondió '+r.status);
    const d=await r.json(); currentHtml=d.html;
    const htmlMarkup=String(d.html||'').trim().toLowerCase(); const hasPageMarkup=['<html','<body','<main','<section','<article','<h1','<p','<img','<video','<iframe'].some(tag=>htmlMarkup.includes(tag)); if(!hasPageMarkup) throw new Error('El servidor no devolvió contenido HTML reconocible para esta página. No se guardará nada.');
    let initDone=false;
    const initializePreview=()=>{{
      if(initDone)return;
      try {{
        const doc=frame.contentDocument;
        if(!doc || !doc.body || !doc.documentElement || doc.URL==='about:blank')return;
        if(!doc.body.children.length && !doc.body.textContent.trim()) {{
          if(!frame.dataset.originalRetry){{
            frame.dataset.originalRetry='1';
            status.textContent='La vista previa llegó vacía; recuperando el archivo original…';
            fetch('/admin/editor/contenido/'+encodeURIComponent(choice.value)+'?original=1',{{cache:'no-store'}}).then(x=>{{if(!x.ok)throw new Error('No se pudo recuperar el archivo original ('+x.status+').');return x.json();}}).then(original=>{{if(!original.html)throw new Error('El archivo original no contiene HTML.');currentHtml=original.html;frame.onload=initializePreview;frame.srcdoc=original.html;previewReady=false;status.textContent='Recuperando vista previa…';}}).catch(err=>{{status.textContent='No se pudo mostrar la página: '+err.message+'. No guardes los cambios.';}});
          }} else {{status.textContent='La vista previa sigue vacía. No guardes cambios. Comprueba que el archivo original de la página siga en la carpeta del proyecto.';}}
          return;
        }}
        initDone=true; previewReady=true; delete frame.dataset.originalRetry;
        prepareTextRuns(doc);
        doc.body.contentEditable='true'; doc.designMode='on';
        doc.addEventListener('mouseup',()=>rememberTextSelection(doc));
        doc.addEventListener('keyup',()=>rememberTextSelection(doc));
        doc.addEventListener('selectionchange',()=>rememberTextSelection(doc));
        doc.querySelectorAll('img').forEach(img=>{{
          img.contentEditable='false';img.style.cursor='move';img.style.maxWidth='100%';img.style.title='';img.title='Haz clic para seleccionar; arrastra para mover. Usa las esquinas para ajustar el tamaño.';
          img.draggable=false; img.addEventListener('click',e=>{{e.preventDefault();e.stopPropagation();doc.querySelectorAll('[data-editor-selected]').forEach(x=>{{x.removeAttribute('data-editor-selected');x.style.outline='';}});img.setAttribute('data-editor-selected','1');img.style.outline='2px solid #22cbd5';showResizeOverlay(doc,img);}});
          img.addEventListener('pointerdown',e=>{{
            if(e.target!==img)return;
            const rect=img.getBoundingClientRect();const corner=(rect.right-e.clientX<18 && rect.bottom-e.clientY<18);
            if(corner){{img.style.resize='both';img.style.overflow='auto';return;}}
            if(e.button!==0)return;
            e.preventDefault();const startX=e.clientX,startY=e.clientY,oldLeft=parseFloat(img.dataset.moveX||'0'),oldTop=parseFloat(img.dataset.moveY||'0');
            img.setPointerCapture(e.pointerId);img.style.touchAction='none';
            const move=ev=>{{img.style.transform='translate('+(oldLeft+ev.clientX-startX)+'px,'+(oldTop+ev.clientY-startY)+'px)';img.dataset.moveX=oldLeft+ev.clientX-startX;img.dataset.moveY=oldTop+ev.clientY-startY;}};
            const end=()=>{{img.removeEventListener('pointermove',move);img.removeEventListener('pointerup',end);img.removeEventListener('pointercancel',end);}};
            img.addEventListener('pointermove',move);img.addEventListener('pointerup',end);img.addEventListener('pointercancel',end);
          }});
          img.addEventListener('dragstart',e=>e.preventDefault());
        }});
        doc.querySelectorAll('a,button,input,video,iframe,script,style,select,textarea').forEach(el=>{{el.contentEditable='false';if(el.tagName==='A')el.addEventListener('click',e=>e.preventDefault());}});
        doc.addEventListener('click',e=>{{
          const el=e.target;
          if(!el || el===doc.body || ['HTML','A','BUTTON','INPUT','VIDEO','IFRAME','SCRIPT','STYLE','SELECT','TEXTAREA'].includes(el.tagName)) return;
          doc.querySelectorAll('[data-editor-selected]').forEach(x=>{{x.removeAttribute('data-editor-selected');x.style.outline='';}});
          el.setAttribute('data-editor-selected','1');el.style.outline='2px solid #22cbd5';if(el.tagName==='IMG')showResizeOverlay(doc,el);else clearResizeOverlay(doc);
        }});
        doc.addEventListener('input',()=>{{snapshot();}});
        doc.addEventListener('pointerdown',e=>{{if(e.button!==0)return;const el=e.target.closest('[data-editor-selected="1"]');if(!el||['A','BUTTON','INPUT','VIDEO','IFRAME','SELECT','TEXTAREA'].includes(el.tagName))return;if(e.target.closest('a,button,input,select,textarea'))return;e.preventDefault();const sx=e.clientX,sy=e.clientY,ox=parseFloat(el.dataset.dragX||'0'),oy=parseFloat(el.dataset.dragY||'0');el.setPointerCapture(e.pointerId);const move=ev=>{{el.style.transform='translate('+(ox+ev.clientX-sx)+'px,'+(oy+ev.clientY-sy)+'px)';el.dataset.dragX=ox+ev.clientX-sx;el.dataset.dragY=oy+ev.clientY-sy;}};const end=()=>{{el.removeEventListener('pointermove',move);el.removeEventListener('pointerup',end);el.removeEventListener('pointercancel',end);snapshot();}};el.addEventListener('pointermove',move);el.addEventListener('pointerup',end);el.addEventListener('pointercancel',end);}});
        doc.querySelectorAll('img').forEach(im=>{{im.style.resize='both';im.style.overflow='auto';im.style.maxWidth='100%';}});lastSnapshot=doc.body.innerHTML;status.textContent='Página cargada. Selecciona texto o imagen; arrastra para mover. Guarda los cambios al terminar.';
      }} catch(err) {{ status.textContent='No se pudo preparar el editor: '+err.message; }}
    }};
    frame.onload=initializePreview;
    frame.srcdoc=d.html;
    // Respaldo para navegadores que no disparan onload de forma consistente con srcdoc.
    setTimeout(initializePreview,700);
  }} catch(err) {{ status.textContent='Error al cargar la página: '+err.message; }}
}}
document.getElementById('loadPage').onclick=()=>{{previewReady=false;loadPage();}};
document.getElementById('addSection').onclick=()=>editorMessage('ADD_SECTION');
function tool(cmd,value=null){{editorMessage({{cmd,value}});}}
document.getElementById('boldTool').onclick=()=>tool('FORMAT','bold');
document.getElementById('italicTool').onclick=()=>tool('FORMAT','italic');
document.getElementById('underlineTool').onclick=()=>tool('FORMAT','underline');
document.getElementById('alignLeft').onclick=()=>tool('ALIGN','left');
document.getElementById('alignCenter').onclick=()=>tool('ALIGN','center');
document.getElementById('alignRight').onclick=()=>tool('ALIGN','right');
document.getElementById('alignJustify').onclick=()=>tool('ALIGN','justify');
document.getElementById('cropImage').onclick=()=>tool('CROP_IMAGE');
document.getElementById('fontSizeTool').onchange=e=>tool('FORMAT','size:'+e.target.value);
document.getElementById('colorTool').onchange=e=>tool('FORMAT',e.target.value);
document.getElementById('addText').onclick=()=>tool('ADD_TEXT');
document.getElementById('addBlockAfter').onclick=()=>tool('ADD_BLOCK_AFTER');
document.getElementById('textWidthTool').onclick=()=>tool('TEXT_WIDTH');
document.getElementById('imageBesideText').onclick=()=>tool('IMAGE_BESIDE_TEXT');
document.getElementById('addImage').onclick=()=>tool('ADD_IMAGE');
document.getElementById('replaceImage').onclick=()=>{{const doc=frame.contentDocument;const sel=doc&&doc.querySelector('[data-editor-selected="1"]');if(!sel||!(sel.tagName==='IMG'||sel.querySelector('img'))){{status.textContent='Primero selecciona una imagen en la vista previa.';return;}}replaceSelectedImage=true;document.getElementById('uploadMedia').accept='image/*';document.getElementById('uploadMedia').click();}};
document.getElementById('resizeImage').onclick=()=>tool('RESIZE_IMAGE');
document.getElementById('moveUp').onclick=()=>tool('MOVE_UP');
document.getElementById('moveDown').onclick=()=>tool('MOVE_DOWN');
document.getElementById('renamePageTitle').onclick=()=>tool('RENAME_TITLE');
document.getElementById('addVideo').onclick=()=>tool('ADD_VIDEO');
document.getElementById('uploadMedia').onchange=async e=>{{const f=e.target.files[0];if(!f)return;const fd=new FormData();fd.append('file',f);status.textContent='Subiendo archivo…';try{{const r=await fetch('/admin/editor/subir', {{method:'POST',body:fd}});const d=await r.json();if(!r.ok)throw new Error(d.error||'No se pudo subir');const doc=frame.contentDocument;if(f.type.startsWith('image/')){{if(replaceSelectedImage){{let target=doc.querySelector('[data-editor-selected="1"]');if(target&&target.tagName!=='IMG')target=target.querySelector('img');if(!target)throw new Error('Selecciona una imagen antes de reemplazarla.');target.src=d.url;target.alt=f.name;target.style.maxWidth='100%';target.style.height='auto';}}else{{const im=doc.createElement('img');im.src=d.url;im.alt=f.name;im.style.cssText='max-width:100%;height:auto';(doc.querySelector('main')||doc.body).appendChild(im);doc.querySelectorAll('[data-editor-selected]').forEach(x=>{{x.removeAttribute('data-editor-selected');x.style.outline='';}});im.setAttribute('data-editor-selected','1');im.style.outline='2px solid #22cbd5';}}}}else{{const v=doc.createElement('video');v.src=d.url;v.controls=true;v.style.cssText='max-width:100%;height:auto';(doc.querySelector('main')||doc.body).appendChild(v);}}status.textContent='Archivo subido. Pulsa Guardar cambios para conservarlo en la página.';}}catch(err){{status.textContent='Error al subir: '+err.message;}}replaceSelectedImage=false;e.target.value='';}};
document.getElementById('deleteElement').onclick=()=>{{if(confirm('¿Eliminar el elemento seleccionado?'))tool('DELETE');}};
document.getElementById('savePage').onclick=async()=>{{
  const doc=frame.contentDocument;if(!previewReady||!doc||!doc.documentElement||!doc.body||(!doc.body.textContent.trim()&&!doc.body.querySelector('img,video,iframe,main,section,article'))){{status.textContent='La vista previa no está cargada o está vacía. Pulsa Cargar página y no se guardó nada.';return;}}
  status.textContent='Guardando cambios…';
  try {{
    clearResizeOverlay(doc);doc.querySelectorAll('[data-editor-selected]').forEach(x=>{{x.removeAttribute('data-editor-selected');if(x.style.outline==='2px solid rgb(34, 203, 213)'||x.style.outline.includes('22cbd5'))x.style.outline='';}});
    doc.querySelectorAll('[contenteditable],[data-drag-x],[data-drag-y],[data-move-x],[data-move-y]').forEach(x=>{{x.removeAttribute('contenteditable');x.removeAttribute('data-drag-x');x.removeAttribute('data-drag-y');x.removeAttribute('data-move-x');x.removeAttribute('data-move-y');}});
    doc.body.removeAttribute('contenteditable');doc.designMode='off';
    const html='<!doctype html>\\n'+doc.documentElement.outerHTML;
    const r=await fetch('/admin/editor/guardar',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{path:choice.value,html}})}});
    const d=await r.json();if(!r.ok)throw new Error(d.error||'No se pudieron guardar los cambios.');
    status.textContent='Cambios guardados correctamente. Abre el sitio público para revisarlos.';
    doc.body.contentEditable='true';doc.designMode='on';
  }} catch(err) {{status.textContent='Error al guardar: '+err.message;}}
}};
document.getElementById('undoTool').onclick=()=>{{const d=frame.contentDocument;if(!d||!undoStack.length){{status.textContent='No hay cambios anteriores para deshacer.';return;}}redoStack.push(d.body.innerHTML);restoreHtml(undoStack.pop());status.textContent='Se deshizo el último cambio.';}};
document.getElementById('redoTool').onclick=()=>{{const d=frame.contentDocument;if(!d||!redoStack.length){{status.textContent='No hay cambios para rehacer.';return;}}undoStack.push(d.body.innerHTML);restoreHtml(redoStack.pop());status.textContent='Se rehizo el cambio.';}};
document.getElementById('desktopView').onclick=()=>{{frame.style.maxWidth='100%';frame.style.width='100%';status.textContent='Vista de escritorio.';}};
document.getElementById('tabletView').onclick=()=>{{frame.style.width='820px';frame.style.maxWidth='100%';status.textContent='Vista de tablet.';}};
document.getElementById('mobileView').onclick=()=>{{frame.style.width='390px';frame.style.maxWidth='100%';status.textContent='Vista de celular.';}};
document.getElementById('layersTool').onclick=()=>{{const d=frame.contentDocument,panel=document.getElementById('layersPanel');if(!d)return;panel.style.display=panel.style.display==='none'?'block':'none';if(panel.style.display==='none')return;panel.innerHTML='';[...d.body.querySelectorAll('h1,h2,h3,p,img,video,section,article')].forEach((el,i)=>{{const b=document.createElement('button');b.type='button';b.textContent=(i+1)+'. '+(el.tagName==='IMG'?'Imagen':el.tagName==='VIDEO'?'Video':(el.innerText||el.tagName).trim().slice(0,35));b.onclick=()=>{{d.querySelectorAll('[data-editor-selected]').forEach(x=>{{x.removeAttribute('data-editor-selected');x.style.outline='';}});el.setAttribute('data-editor-selected','1');el.style.outline='2px solid #22cbd5';el.scrollIntoView({{behavior:'smooth',block:'center'}});}};panel.appendChild(b);}});}};
function prepareEditableDocument(d){{d.body.contentEditable='true';d.designMode='on';d.querySelectorAll('a,button,input,video,iframe,script,style,select,textarea').forEach(el=>{{el.contentEditable='false';if(el.tagName==='A')el.addEventListener('click',e=>e.preventDefault());}});}}
const requested=new URLSearchParams(location.search).get('pagina');if(requested&&[...choice.options].some(o=>o.value===requested))choice.value=requested;loadPage();</script>"""
    return page('Editar páginas del sitio',body)

@app.route('/admin/editor/contenido/<path:filename>')
def editor_content(filename):
    if not logged(): return jsonify({'error':'No autorizado'}),403
    if filename not in editable_pages(): return jsonify({'error':'Página no permitida'}),400
    html_content=get_page_html(filename)
    # El editor puede solicitar explícitamente el archivo original si la vista previa
    # no consigue mostrar el contenido guardado. No modifica ni borra la base de datos.
    if request.args.get('original') == '1':
        source = ROOT / filename
        if source.is_file():
            html_content = source.read_text(encoding='utf-8')
    body_match = re.search(r'<body\b[^>]*>(.*?)</body>', html_content, flags=re.I|re.S)
    body_text = re.sub(r'<(script|style)\b[^>]*>.*?</\1>', '', body_match.group(1), flags=re.I|re.S) if body_match else ''
    body_plain = re.sub(r'<[^>]+>', '', body_text).replace('&nbsp;', ' ').strip()
    if len(body_plain) < 20 and not re.search(r'<(img|video|iframe|main|section|article)\b', body_text, flags=re.I):
        source = ROOT / filename
        if source.is_file(): html_content = source.read_text(encoding='utf-8')
    if re.search(r'<head[^>]*>',html_content,re.I) and not re.search(r'<base\b',html_content,re.I):
        html_content=re.sub(r'(<head[^>]*>)',r'\1<base href="'+request.host_url+'">',html_content,count=1,flags=re.I)
    return jsonify({'html':html_content})

@app.route('/admin/editor/guardar',methods=['POST'])
def save_page_content():
    if not logged(): return jsonify({'error':'No autorizado'}),403
    data=request.get_json(silent=True) or {}; filename=data.get('path',''); html_content=data.get('html','')
    if filename not in editable_pages() or not isinstance(html_content,str) or len(html_content)>2_000_000:
        return jsonify({'error':'Contenido o página no válidos'}),400
    body_match = re.search(r'<body\b[^>]*>(.*?)</body>', html_content, flags=re.I|re.S)
    body_text = re.sub(r'<(script|style)\b[^>]*>.*?</\1>', '', body_match.group(1), flags=re.I|re.S) if body_match else ''
    body_plain = re.sub(r'<[^>]+>', '', body_text).replace('&nbsp;', ' ').strip()
    if len(body_plain) < 20 and not re.search(r'<(img|video|iframe|main|section|article)\b', body_text, flags=re.I):
        return jsonify({'error':'La vista previa está vacía. No se guardó nada para proteger el contenido anterior. Vuelve a cargar la página e inténtalo de nuevo.'}),400
    # Evita que la propia interfaz de edición se guarde dentro de la página pública.
    html_content=re.sub(r'<script>\s*\(function\(\)\{document.body.contentEditable=.*?</script>','',html_content,flags=re.S)
    with db() as c:
        c.execute('INSERT INTO page_content(path,html,updated_at) VALUES(?,?,CURRENT_TIMESTAMP) ON CONFLICT(path) DO UPDATE SET html=excluded.html,updated_at=CURRENT_TIMESTAMP',(filename,html_content))
        if filename.endswith('.html'): c.execute('UPDATE custom_pages SET html=? WHERE slug=?',(html_content,filename[:-5]))
    return jsonify({'ok':True})

@app.route('/admin/paginas', methods=['GET','POST'])
def manage_pages():
    if not logged(): return redirect('/admin/entrar')
    message=''
    if request.method=='POST':
        title=request.form.get('title','').strip()
        slug=unicodedata.normalize('NFKD',title).encode('ascii','ignore').decode().lower()
        slug=re.sub(r'[^a-z0-9]+','-',slug).strip('-')[:55]
        if not title or not slug: message='Escribe un nombre válido para la página.'
        else:
            with db() as c:
                exists=c.execute('SELECT 1 FROM custom_pages WHERE slug=?',(slug,)).fetchone()
                if slug+'.html' in EDITABLE_PAGES or exists: message='Ya existe una página con ese nombre o dirección.'
                else:
                    html_doc = ('<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+esc(title)+' | Lago de Ajuchitlán</title></head><body><main style="max-width:1100px;margin:70px auto;padding:24px"><section style="padding:32px;border-radius:18px;background:#fff"><p style="color:#009baa;letter-spacing:2px">LAGO DE AJUCHITLÁN</p><h1>'+esc(title)+'</h1><p>Haz clic aquí desde el editor para escribir la información de esta página.</p></section></main></body></html>')
                    c.execute('INSERT INTO custom_pages(slug,title,html) VALUES(?,?,?)',(slug,title,html_doc)); message='Página creada. Ya puedes editar su contenido.'
    with db() as c: rows=c.execute('SELECT slug,title,created_at FROM custom_pages ORDER BY created_at DESC').fetchall()
    items=''.join("<div class='card'><h3>"+esc(r['title'])+"</h3><p class='muted'>Dirección: /pagina/"+esc(r['slug'])+"</p><div class='actions'><a class='button' href='/admin/editor?pagina="+esc(r['slug'])+".html'>Editar contenido</a><a class='button secondary' target='_blank' href='/pagina/"+esc(r['slug'])+"'>Ver página</a><form method='post' action='/admin/paginas/"+esc(r['slug'])+"/eliminar' onsubmit=\"return confirm('¿Eliminar esta página y su contenido? Esta acción no se puede deshacer.')\"><button class='danger'>Eliminar página</button></form></div></div>" for r in rows)
    body="<div class='card'><p>Crea páginas independientes. Las páginas principales del proyecto no se eliminan desde aquí.</p>"+(('<p><strong>'+esc(message)+'</strong></p>') if message else '')+"<form method='post'><div class='field'><label>Nombre de la nueva página</label><input name='title' required maxlength='70' placeholder='Ej. Recorrido en video'></div><button type='submit'>＋ Crear página</button></form></div><h2>Páginas creadas</h2>"+(items or "<div class='card'>Todavía no has creado páginas nuevas.</div>")+"<p><a class='button secondary' href='/admin/editor'>Volver al editor</a></p>"
    return page('Administrar páginas',body)

@app.route('/admin/paginas/<slug>/eliminar', methods=['POST'])
def delete_custom_page(slug):
    if not logged(): return redirect('/admin/entrar')
    with db() as c:
        c.execute('DELETE FROM custom_pages WHERE slug=?',(slug,)); c.execute('DELETE FROM page_content WHERE path=?',(slug+'.html',))
    return redirect('/admin/paginas')

@app.route('/pagina/<slug>')
def view_custom_page(slug):
    with db() as c: row=c.execute('SELECT title FROM custom_pages WHERE slug=?',(slug,)).fetchone()
    if not row: abort(404)
    from flask import Response
    return Response(get_page_html(slug+'.html'),mimetype='text/html')

@app.route('/admin/editor/subir', methods=['POST'])
def upload_editor_media():
    if not logged(): return jsonify({'error':'No autorizado'}),403
    f=request.files.get('file')
    if not f or not f.filename: return jsonify({'error':'Selecciona un archivo.'}),400
    original=secure_filename(f.filename); ext=Path(original).suffix.lower()
    if ext not in ALLOWED: return jsonify({'error':'Formato no permitido. Usa JPG, PNG, WEBP, GIF, MP4, WEBM o MOV.'}),400
    if request.content_length and request.content_length>80*1024*1024: return jsonify({'error':'El archivo supera el límite de 80 MB.'}),413
    dest=ROOT/'static'/'uploads'; dest.mkdir(parents=True,exist_ok=True)
    name=uuid.uuid4().hex+ext; f.save(dest/name)
    return jsonify({'ok':True,'url':'/static/uploads/'+name,'filename':original})

@app.route('/login', methods=['GET','POST'])
def login_page():
    if request.method == 'GET':
        return send_from_directory(ROOT, 'login.html')
    email = request.form.get('email','').strip().lower()
    password = request.form.get('password','')
    # El administrador también puede entrar desde el formulario principal.
    if not login_is_limited('login:'+request.remote_addr) and email == ADMIN_USER.lower() and admin_password_matches(password):
        session.clear(); session['admin_logged'] = True; session['role'] = 'admin'
        return redirect('/admin')
    if login_is_limited('login:'+request.remote_addr):
        return redirect('/login?error=1')
    with db() as c:
        user = c.execute('SELECT id,name,email,password_hash,role,active FROM users WHERE email=?', (email,)).fetchone()
    if user and user['active'] and check_password_hash(user['password_hash'], password):
        _login_attempts.pop('login:'+request.remote_addr, None)
        session.clear(); session['user_id'] = user['id']; session['user_name'] = user['name']; session['user_email'] = user['email']; session['role'] = user['role']
        if user['role'] == 'admin':
            session['admin_logged'] = True
            return redirect('/admin')
        return redirect('/cuenta')
    record_login_failure('login:'+request.remote_addr)
    return redirect('/login?error=1')

@app.route('/registro', methods=['GET','POST'])
def register_page():
    if request.method == 'GET':
        return send_from_directory(ROOT, 'registro.html')
    name = request.form.get('name','').strip()
    email = request.form.get('email','').strip().lower()
    password = request.form.get('password','')
    if len(name) < 2 or len(name) > 100 or not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email) or len(password) < 8:
        return redirect('/registro?error=datos')
    try:
        with db() as c:
            cur = c.execute('INSERT INTO users(name,email,password_hash,role) VALUES(?,?,?,?)', (name,email,generate_password_hash(password),'user'))
            new_user_id = cur.lastrowid
    except sqlite3.IntegrityError:
        return redirect('/registro?error=existe')
    # Al terminar el registro, iniciar sesión automáticamente como usuario normal.
    # La cuenta nueva nunca recibe permisos de administrador por registrarse.
    session.clear()
    session['user_id'] = new_user_id
    session['user_name'] = name
    session['user_email'] = email
    session['role'] = 'user'
    return redirect('/cuenta')

@app.route('/cuenta')
def account_page():
    if session.get('role') == 'admin' and logged():
        return redirect('/admin')
    if session.get('user_id'):
        name = esc(session.get('user_name','Usuario'))
        body = f"<div class='card'><span class='pill'>Usuario registrado</span><h2>¡Hola, {name}!</h2><p>Tu sesión está activa. Puedes consultar todas las secciones del Lago de Ajuchitlán; tu cuenta no tiene permisos para modificar el contenido.</p><div class='actions'><a class='button' href='/'>Visitar la página</a><a class='button secondary' href='/salir'>Cerrar sesión</a></div></div>"
        return page('Mi cuenta', body)
    return redirect('/login')

@app.route('/pesca')
def pesca_page(): return send_site_page('pesca.html')

@app.route('/caminata')
def caminata_page(): return send_site_page('caminata.html')

@app.route('/juegos-infantiles')
def juegos_page(): return send_site_page('juegos-infantiles.html')

@app.route('/areas-convivencia')
def convivencia_page(): return send_site_page('areas-convivencia.html')

@app.route('/fauna')
def fauna_page(): return send_site_page('fauna.html')

@app.route('/paseo-en-lancha')
def lancha_page(): return send_site_page('paseo-en-lancha.html')

@app.route('/recorrido-turistico')
def recorrido_page(): return send_site_page('recorrido-turistico.html')

@app.route('/patos')
def patos_page(): return send_site_page('patos.html')

@app.route('/api/negocios')
def api_businesses():
    """Devuelve los puestos guardados para mostrarlos en el directorio público de Puestos y servicios."""
    with db() as c:
        rows = c.execute('SELECT id,name,category,description,hours,location,contact,photos,menu FROM businesses ORDER BY id DESC').fetchall()
    result = []
    for r in rows:
        try:
            photos = json.loads(r['photos'] or '[]')
        except (TypeError, ValueError):
            photos = []
        try:
            menu = json.loads(r['menu'] or '[]') if 'menu' in r.keys() else []
        except (TypeError, ValueError):
            menu = []
        normalized_photos = []
        if isinstance(photos, list):
            for photo in photos:
                if not isinstance(photo, str) or not photo.strip():
                    continue
                photo = photo.strip().replace('\\', '/')
                if photo.startswith('static/'):
                    photo = '/' + photo
                elif photo.startswith('uploads/'):
                    photo = '/static/' + photo
                normalized_photos.append(photo)
        result.append({
            'id': r['id'], 'name': r['name'], 'category': r['category'] or 'Otro',
            'description': r['description'] or '', 'hours': r['hours'] or '',
            'location': r['location'] or '', 'contact': r['contact'] or '',
            'photos': normalized_photos,
            'menu': menu if isinstance(menu, list) else []
        })
    return jsonify(result)
@app.route('/servicios')
def services():
 return send_from_directory(ROOT, 'servicios.html')

@app.route('/servicios.html')
def services_html_redirect():
 return redirect('/servicios')

def loginform():
 note = "Ingresa con las credenciales locales configuradas para el sitio."
 return "<form method='post'><div class='field'><label>Usuario</label><input name='username' required autocomplete='username'></div><div class='field'><label>Contraseña</label><input type='password' name='password' required autocomplete='current-password'></div><button>Entrar</button></form><p class='muted'>"+esc(note)+"</p>"
@app.route('/admin/entrar',methods=['GET','POST'])
def login():
 if request.method=='POST':
  key='admin-login:'+request.remote_addr
  if login_is_limited(key): return page('Acceso de administrador',"<div class='card'><p style='color:#a22'>Demasiados intentos. Espera 10 minutos e inténtalo de nuevo.</p></div>")
  if request.form.get('username','') == ADMIN_USER and admin_password_matches(request.form.get('password','')): _login_attempts.pop(key,None); session.clear(); session['admin_logged']=True; session['role']='admin'; return redirect('/admin')
  record_login_failure(key)
  return page('Acceso de administrador',"<div class='card'><p style='color:#a22'>Usuario o contraseña incorrectos.</p>"+loginform()+'</div>')
 return page('Acceso de administrador',"<div class='card'><p class='muted'>Panel privado para gestionar los puestos e imágenes.</p>"+loginform()+'</div>')
@app.route('/salir')
def logout():
 session.clear()
 return redirect('/')
def default_gorditas_menu():
 return [
  {'title':'Gorditas Colonenses','items':['Pollo con papas','Picadillo']},
  {'title':'Gorditas Queretanas','items':['Migajas','Queso']}
 ]
def parse_menu(raw):
 try: groups=json.loads(raw or '[]')
 except (TypeError, ValueError): return []
 cleaned=[]
 if isinstance(groups,list):
  for group in groups[:20]:
   if not isinstance(group,dict): continue
   title=str(group.get('title','')).strip()[:90]
   raw_items=group.get('items',[])
   if isinstance(raw_items,str): raw_items=raw_items.splitlines()
   items=[str(x).strip()[:180] for x in raw_items if str(x).strip()][:100] if isinstance(raw_items,list) else []
   if title and items: cleaned.append({'title':title,'items':items})
 return cleaned

def form(r=None):
 defaults={'name':'','category':'Comida','description':'','hours':'','location':'','contact':'','photos':'[]','menu':'[]'}
 if r is None: data=defaults.copy()
 else:
  keys=set(r.keys()) if hasattr(r,'keys') else set(r)
  data={k:(r[k] if k in keys and r[k] is not None else v) for k,v in defaults.items()}
 pics=json.loads(data['photos'] or '[]')
 existing=''.join(f"<label style='display:inline-flex;align-items:center;gap:5px;margin:6px'><input type='checkbox' name='keep_photos' value='{esc(p)}' checked><img src='{esc(p)}' style='width:80px;height:65px;object-fit:cover;border-radius:7px'></label>" for p in pics)
 cats=['Comida','Bebidas','Artesanías','Actividades','Servicios','Otro']; opts=''.join(f"<option value='{esc(x)}' {'selected' if data['category']==x else ''}>{esc(x)}</option>" for x in cats)
 try: groups=json.loads(data['menu'] or '[]')
 except (TypeError,ValueError): groups=[]
 # Solo la ficha conocida de Gorditas Doña Lupe recibe estos dos grupos de menú como ejemplo.
 normalized_name=str(data['name']).lower()
 if not groups and 'gordita' in normalized_name and 'lupe' in normalized_name: groups=default_gorditas_menu()
 group_html=''
 for group in groups:
  title=esc(group.get('title',''))
  items=group.get('items',[])
  if isinstance(items,list): items='\n'.join(str(x) for x in items)
  group_html+=f"<div class='menu-group-editor'><div class='field'><label>Nombre de la sección del menú</label><input class='menu-title' value='{title}' placeholder='Ej. Gorditas Colonenses' maxlength='90'></div><div class='field'><label>Platillos (uno por línea; puedes agregar precios)</label><textarea class='menu-items' placeholder='Ej. Pollo con papas&#10;Picadillo'>{esc(items)}</textarea></div><button type='button' class='button secondary remove-menu-group'>Quitar sección</button></div>"
 return f"""<form method='post' enctype='multipart/form-data' id='businessForm'>
 <div class='field'><label>Nombre del puesto o negocio *</label><input name='name' id='businessName' value='{esc(data['name'])}' required></div>
 <div class='field'><label>Tipo de puesto</label><select name='category' id='businessCategory'>{opts}</select><small class='muted'>Elige la categoría que corresponda. No todos los puestos son de comida.</small></div>
 <div class='field'><label>Descripción</label><textarea name='description'>{esc(data['description'])}</textarea></div>
 <div class='field'><label>Horario</label><input name='hours' value='{esc(data['hours'])}' placeholder='Ej. Sábados y domingos, 9:00 a. m. - 6:00 p. m.'></div>
 <div class='field'><label>Ubicación</label><input name='location' value='{esc(data['location'])}'></div>
 <div class='field'><label>Contacto</label><input name='contact' value='{esc(data['contact'])}'></div>
 <section class='card menu-editor'><h2>Menú de comida (opcional)</h2><p class='muted'>Úsalo solo para puestos que vendan alimentos. Cada puesto de comida puede tener sus propias secciones. Para Gorditas Doña Lupe usamos Gorditas Colonenses y Gorditas Queretanas; otros puestos pueden registrar su propio menú y los negocios que no venden comida pueden dejarlo vacío. Escribe un platillo por línea y, si lo deseas, su precio.</p>
 <div id='menuGroups'>{group_html}</div><button type='button' class='button secondary' id='addMenuGroup'>＋ Agregar sección del menú</button><input type='hidden' name='menu_json' id='menuJson' value='[]'></section>
 <div class='field'><label>Subir imágenes desde tu computadora</label><input type='file' name='photos' accept='.jpg,.jpeg,.png,.webp,.gif' multiple><small class='muted'>Puedes seleccionar varias fotos del puesto desde tu computadora.</small></div>
 {('<div class=field><label>Fotos actuales (desmarca las que quieras quitar)</label><div class=photos>'+existing+'</div></div>') if pics else ''}
 <div class='actions'><button type='submit'>Guardar puesto</button><a class='button secondary' href='/admin'>Cancelar</a></div>
 </form>
 <script>
 (function(){{
 const box=document.getElementById('menuGroups');
 const add=document.getElementById('addMenuGroup');
 const form=document.getElementById('businessForm');
 const hidden=document.getElementById('menuJson');
 function addGroup(title='',items=''){{
  const card=document.createElement('div'); card.className='menu-group-editor';
  const titleWrap=document.createElement('div'); titleWrap.className='field';
  const label=document.createElement('label'); label.textContent='Nombre de la sección del menú';
  const input=document.createElement('input'); input.className='menu-title'; input.maxLength=90; input.placeholder='Ej. Gorditas Colonenses'; input.value=title;
  titleWrap.append(label,input);
  const itemsWrap=document.createElement('div'); itemsWrap.className='field';
  const ilabel=document.createElement('label'); ilabel.textContent='Platillos (uno por línea; puedes agregar precios)';
  const textarea=document.createElement('textarea'); textarea.className='menu-items'; textarea.placeholder='Ej. Pollo con papas'; textarea.value=items;
  itemsWrap.append(ilabel,textarea);
  const remove=document.createElement('button'); remove.type='button'; remove.className='button secondary remove-menu-group'; remove.textContent='Quitar sección';
  remove.addEventListener('click',()=>card.remove()); card.append(titleWrap,itemsWrap,remove); box.append(card);
 }}
 add.addEventListener('click',()=>addGroup());
 box.querySelectorAll('.remove-menu-group').forEach(btn=>btn.addEventListener('click',()=>btn.closest('.menu-group-editor').remove()));
 form.addEventListener('submit',()=>{{
  const groups=[];
  box.querySelectorAll('.menu-group-editor').forEach(card=>{{
   const title=card.querySelector('.menu-title').value.trim();
   const items=card.querySelector('.menu-items').value.split('\\n').map(x=>x.trim()).filter(Boolean);
   if(title && items.length) groups.push({{title,items}});
  }});
  hidden.value=JSON.stringify(groups);
 }});
 }})();
 </script>"""

def savephotos():
 pics=request.form.getlist('keep_photos')
 for f in request.files.getlist('photos'):
  if not f or not f.filename: continue
  ext=Path(f.filename).suffix.lower()
  if ext not in ALLOWED: continue
  name=uuid.uuid4().hex+ext; f.save(UP/name); pics.append('/static/uploads/'+name)
 return json.dumps(list(dict.fromkeys(pics))[:12])
@app.route('/admin')
def admin():
 if not logged(): return redirect('/admin/entrar')
 with db() as c: rows=c.execute('SELECT * FROM businesses ORDER BY id DESC').fetchall()
 body=f"<div class='stats'><span>{len(rows)} puestos registrados</span><span>Base de datos SQLite</span><span>Fotos guardadas en el servidor</span></div><p><a class='button' href='/admin/negocio/nuevo'>+ Agregar puesto</a> <a class='button secondary' href='/admin/editor'>Editar páginas del sitio</a> <a class='button secondary' href='/admin/usuarios'>Administrar usuarios</a> <a class='button secondary' href='/'>Ver sitio público</a></p><div class='card'><h2>Negocios registrados</h2>"
 if not rows: body+="<p class='muted'>Aún no hay puestos. Agrega el primero con el botón de arriba.</p>"
 for r in rows:
  pics=json.loads(r['photos'] or '[]'); thumb=f"<img src='{pics[0]}' style='width:74px;height:60px;object-fit:cover;border-radius:8px'>" if pics else ''
  body+=f"<div style='display:flex;align-items:center;gap:14px;justify-content:space-between;border-top:1px solid #e0ebec;padding:14px 0;flex-wrap:wrap'>{thumb}<div style='flex:1;min-width:140px'><b>{esc(r['name'])}</b><div class='muted'>{esc(r['category'])}</div></div><div class='actions'><a class='button secondary' href='/admin/negocio/{r['id']}'>Editar</a><form method='post' action='/admin/negocio/{r['id']}/eliminar' onsubmit=\"return confirm('¿Eliminar este puesto?')\"><button class='danger'>Eliminar</button></form></div></div>"
 body+='</div>'
 return page('Panel de administración',body)
@app.route('/admin/usuarios')
def admin_users():
 if not logged(): return redirect('/admin/entrar')
 q=request.args.get('q','').strip()
 with db() as c:
  if q:
   users=c.execute("SELECT id,name,email,role,created_at,active FROM users WHERE name LIKE ? OR email LIKE ? ORDER BY created_at DESC,id DESC",(f'%{q}%',f'%{q}%')).fetchall()
  else:
   users=c.execute("SELECT id,name,email,role,created_at,active FROM users ORDER BY created_at DESC,id DESC").fetchall()
  admin_count=c.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND active=1").fetchone()[0]
 body="<p class='muted'>Administra las cuentas y sus permisos. Las contraseñas nunca se muestran.</p>"
 body+=f"<div class='stats'><span>{len(users)} usuarios mostrados</span><span>{admin_count} administradores activos</span></div>"
 body+=f"<form method='get' class='card' style='display:flex;gap:10px;flex-wrap:wrap;align-items:end'><div class='field' style='flex:1;min-width:220px;margin:0'><label for='q'>Buscar por nombre o correo</label><input id='q' name='q' value='{esc(q)}' placeholder='Escribe para buscar'></div><button type='submit'>Buscar</button><a class='button secondary' href='/admin/usuarios'>Limpiar</a></form>"
 body+="<div class='card'><div style='overflow-x:auto'><table style='width:100%;border-collapse:collapse;min-width:800px'><thead><tr><th style='text-align:left;padding:10px'>Nombre</th><th style='text-align:left;padding:10px'>Correo</th><th style='text-align:left;padding:10px'>Registro</th><th style='text-align:left;padding:10px'>Rol</th><th style='text-align:left;padding:10px'>Estado</th><th style='text-align:left;padding:10px'>Opciones</th></tr></thead><tbody>"
 for u in users:
  role_label='Administrador' if u['role']=='admin' else 'Usuario normal'
  status="<span class='pill'>Activo</span>" if u['active'] else "<span class='pill' style='background:#ffe3e3;color:#8c2222'>Bloqueado</span>"
  actions=[]
  actions.append(f"<a class='button secondary' href='/admin/usuarios/{u['id']}/editar'>Editar</a>")
  if u['id'] != session.get('user_id'):
   if u['role']=='admin':
    actions.append(f"<form method='post' action='/admin/usuarios/{u['id']}/rol' onsubmit='return confirm(&quot;¿Quitar el rol de administrador?&quot;)'><input type='hidden' name='role' value='user'><button class='button secondary'>Quitar administrador</button></form>")
   else:
    actions.append(f"<form method='post' action='/admin/usuarios/{u['id']}/rol' onsubmit='return confirm(&quot;¿Dar permisos de administrador a esta cuenta?&quot;)'><input type='hidden' name='role' value='admin'><button class='button secondary'>Hacer administrador</button></form>")
   toggle_label='Desbloquear' if not u['active'] else 'Bloquear'
   toggle_class='button' if not u['active'] else 'button secondary'
   actions.append(f"<form method='post' action='/admin/usuarios/{u['id']}/estado' onsubmit='return confirm(&quot;¿{toggle_label} esta cuenta?&quot;)'><button class='{toggle_class}'>{toggle_label}</button></form>")
   actions.append(f"<form method='post' action='/admin/usuarios/{u['id']}/eliminar' onsubmit='return confirm(&quot;Esta acción eliminará la cuenta de forma permanente. ¿Continuar?&quot;)'><button class='danger'>Eliminar</button></form>")
  else: actions.append("<span class='muted'>Tu cuenta actual</span>")
  body+=f"<tr style='border-top:1px solid #e0ebec;vertical-align:top'><td style='padding:12px 10px'>{esc(u['name'])}</td><td style='padding:12px 10px'>{esc(u['email'])}</td><td style='padding:12px 10px'>{esc(format_local_datetime(u['created_at']))}</td><td style='padding:12px 10px'><span class='pill'>{role_label}</span></td><td style='padding:12px 10px'>{status}</td><td style='padding:12px 10px'><div class='actions' style='margin:0'>{''.join(actions)}</div></td></tr>"
 body+="</tbody></table></div></div><p><a class='button secondary' href='/admin'>Volver al panel</a></p>"
 return page('Administración de usuarios',body)

@app.route('/admin/usuarios/<int:uid>/editar',methods=['GET','POST'])
def edit_user(uid):
 if not logged(): return redirect('/admin/entrar')
 with db() as c: user=c.execute('SELECT id,name,email,role,active FROM users WHERE id=?',(uid,)).fetchone()
 if not user: abort(404)
 error=''
 if request.method=='POST':
  name=request.form.get('name','').strip(); email=request.form.get('email','').strip().lower(); password=request.form.get('password','')
  if len(name)<2 or len(name)>100 or not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+',email): error='Revisa el nombre y el correo electrónico.'
  elif password and len(password)<8: error='La nueva contraseña debe tener al menos 8 caracteres.'
  else:
   try:
    with db() as c:
     c.execute('UPDATE users SET name=?,email=? WHERE id=?',(name,email,uid))
     if password: c.execute('UPDATE users SET password_hash=? WHERE id=?',(generate_password_hash(password),uid))
    if uid==session.get('user_id'):
     session['user_name']=name; session['user_email']=email
    return redirect('/admin/usuarios')
   except sqlite3.IntegrityError: error='Ese correo ya está registrado en otra cuenta.'
 body=f"<div class='card'><p class='muted'>Edita los datos de la cuenta. La contraseña solo se cambia si escribes una nueva.</p>{('<p>'+esc(error)+'</p>') if error else ''}<form method='post'><div class='field'><label for='name'>Nombre</label><input id='name' name='name' required maxlength='100' value='{esc(request.form.get('name',user['name']))}'></div><div class='field'><label for='email'>Correo electrónico</label><input id='email' name='email' type='email' required value='{esc(request.form.get('email',user['email']))}'></div><div class='field'><label for='password'>Nueva contraseña (opcional)</label><input id='password' name='password' type='password' minlength='8' autocomplete='new-password' placeholder='Deja vacío para no cambiarla'></div><div class='actions'><button type='submit'>Guardar cambios</button><a class='button secondary' href='/admin/usuarios'>Cancelar</a></div></form></div>"
 return page('Editar usuario',body)

@app.route('/admin/usuarios/<int:uid>/rol',methods=['POST'])
def change_user_role(uid):
 if not logged(): return redirect('/admin/entrar')
 role=request.form.get('role','')
 if role not in ('user','admin') or uid==session.get('user_id'): return redirect('/admin/usuarios')
 with db() as c:
  current=c.execute('SELECT role,active FROM users WHERE id=?',(uid,)).fetchone()
  if not current: abort(404)
  if current['role']=='admin' and role=='user':
   count=c.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND active=1").fetchone()[0]
   if count<=1: return page('No se puede cambiar el rol',"<div class='card'><p>No puedes quitar el último administrador activo.</p><a class='button secondary' href='/admin/usuarios'>Volver</a></div>")
  c.execute('UPDATE users SET role=? WHERE id=?',(role,uid))
 return redirect('/admin/usuarios')

@app.route('/admin/usuarios/<int:uid>/estado',methods=['POST'])
def toggle_user_status(uid):
 if not logged(): return redirect('/admin/entrar')
 if uid==session.get('user_id'): return redirect('/admin/usuarios')
 with db() as c:
  user=c.execute('SELECT role,active FROM users WHERE id=?',(uid,)).fetchone()
  if not user: abort(404)
  if user['active'] and user['role']=='admin':
   count=c.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND active=1").fetchone()[0]
   if count<=1: return page('No se puede bloquear',"<div class='card'><p>No puedes bloquear al último administrador activo.</p><a class='button secondary' href='/admin/usuarios'>Volver</a></div>")
  c.execute('UPDATE users SET active=? WHERE id=?',(0 if user['active'] else 1,uid))
 return redirect('/admin/usuarios')

@app.route('/admin/usuarios/<int:uid>/eliminar',methods=['POST'])
def delete_user(uid):
 if not logged(): return redirect('/admin/entrar')
 if uid==session.get('user_id'): return page('No se puede eliminar',"<div class='card'><p>No puedes eliminar la cuenta con la que tienes iniciada la sesión.</p><a class='button secondary' href='/admin/usuarios'>Volver</a></div>")
 with db() as c:
  user=c.execute('SELECT role,active FROM users WHERE id=?',(uid,)).fetchone()
  if not user: abort(404)
  if user['role']=='admin' and user['active']:
   count=c.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND active=1").fetchone()[0]
   if count<=1: return page('No se puede eliminar',"<div class='card'><p>No puedes eliminar al último administrador activo.</p><a class='button secondary' href='/admin/usuarios'>Volver</a></div>")
  c.execute('DELETE FROM users WHERE id=?',(uid,))
 return redirect('/admin/usuarios')

@app.route('/admin/negocio/nuevo',methods=['GET','POST'])
def new():
 if not logged(): return redirect('/admin/entrar')
 if request.method=='POST':
  name=request.form.get('name','').strip()
  if not name: return page('Agregar puesto',"<div class='card'>El nombre es obligatorio."+form(request.form)+'</div>')
  with db() as c:
   count=c.execute('SELECT COUNT(*) FROM businesses').fetchone()[0]
   if count >= 12: return page('Límite de puestos',"<div class='card'><h2>Ya tienes 12 puestos registrados</h2><p>Para este proyecto acordamos un máximo de 12. Edita o elimina un puesto antes de agregar otro.</p><a class='button' href='/admin'>Volver al panel</a></div>")
  with db() as c: c.execute('INSERT INTO businesses(name,category,description,hours,location,contact,photos,menu) VALUES(?,?,?,?,?,?,?,?)',(name,request.form.get('category','Otro'),request.form.get('description',''),request.form.get('hours',''),request.form.get('location',''),request.form.get('contact',''),savephotos(),json.dumps(parse_menu(request.form.get('menu_json','[]')),ensure_ascii=False)))
  return redirect('/admin')
 return page('Agregar puesto',"<p class='muted'>Los datos y las fotografías se guardarán en la base de datos y en el disco del servidor.</p><div class='card'>"+form()+'</div>')
@app.route('/admin/negocio/<int:bid>',methods=['GET','POST'])
def edit(bid):
 if not logged(): return redirect('/admin/entrar')
 with db() as c: r=c.execute('SELECT * FROM businesses WHERE id=?',(bid,)).fetchone()
 if not r: abort(404)
 if request.method=='POST':
  with db() as c: c.execute('UPDATE businesses SET name=?,category=?,description=?,hours=?,location=?,contact=?,photos=?,menu=? WHERE id=?',(request.form.get('name','').strip(),request.form.get('category','Otro'),request.form.get('description',''),request.form.get('hours',''),request.form.get('location',''),request.form.get('contact',''),savephotos(),json.dumps(parse_menu(request.form.get('menu_json','[]')),ensure_ascii=False),bid))
  return redirect('/admin')
 return page('Editar puesto',"<div class='card'>"+form(r)+'</div>')
@app.route('/admin/negocio/<int:bid>/eliminar',methods=['POST'])
def delete(bid):
 if not logged(): return redirect('/admin/entrar')
 with db() as c: c.execute('DELETE FROM businesses WHERE id=?',(bid,))
 return redirect('/admin')
@app.route('/<path:filename>')
def files(filename):
 p=(ROOT/filename).resolve()
 if p.is_file() and ROOT.resolve() in p.parents and p.suffix.lower() in {'.html','.css','.js','.mp4','.jpg','.png','.webp'}:
  if p.suffix.lower()=='.html' and p.name in EDITABLE_PAGES: return send_site_page(p.name)
  return send_from_directory(ROOT,filename)
 abort(404)
if __name__=='__main__': app.run(host='0.0.0.0',port=int(os.environ.get('PORT','5000')),debug=False)
