#!/usr/bin/env python3
"""Sube la programación (EPG) de los canales a Firebase Realtime Database.

Formato que escribe (el mismo que usa la app del reproductor):
  epg_rows/<canal> = {fecha, fuente, slug, actualizado, rows: [{i, f, p}]}
  epg_info/<canal> = {fecha, fuente, slug, actualizado}
  i / f = hora de inicio / fin en 24 h ("HH:MM"), p = título del programa.

Variables de entorno:
  FIREBASE_CREDENTIALS  contenido del .json de la cuenta de servicio
  FIREBASE_DB_URL       URL de la Realtime Database
  DRY_RUN=1             solo prueba: descarga y muestra, no escribe en Firebase
"""
import json
import os
import re
import sys
import time
import unicodedata
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

TZ = ZoneInfo("America/Tegucigalpa")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")

# ID del canal en Firebase (nodo "canales") -> scraper que lo alimenta.
# Para desactivar un canal, borra su línea.
CANALES = {
    "-P57t6dgMhyRS1utX7rg": "stve",         # STVE
    "-P3YxJH0O5lSHk9XHDMz": "deportestvc",  # Deportes TVC HON 
    "-P2rlc_nYDXmxf_2jGii": "canal5",       # Canal 5 HD HON
    "-P2kf9CH99dNh6b94yCp": "canal5",       # Canal 5 HON
}

URLS = {
    "stve": "https://www.stvetelebasica.com/programacion",
    "deportestvc": "https://www.deportestvc.com/programacion",
    "canal5": "https://www.televicentro.com/programacion", 
}

DIAS_ES = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]
DIAS_EN = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MESES = {"ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
         "jul": 7, "ago": 8, "sep": 9, "set": 9, "oct": 10, "nov": 11, "dic": 12}


# ---------------------------------------------------------------- utilidades

def hhmm(minutos):
    minutos %= 1440
    return f"{minutos // 60:02d}:{minutos % 60:02d}"


def hhmm_texto(s):
    h, m = s.strip().split(":")[:2]
    return hhmm(int(h) * 60 + int(m))


def limpiar(texto):
    return re.sub(r"\s+", " ", texto or "").strip()[:120]


def normalizar(texto):
    sin = unicodedata.normalize("NFD", texto or "")
    return sin.encode("ascii", "ignore").decode().lower().strip()


RE_12H = re.compile(r"(\d{1,2}):(\d{2})\s*([ap])\.?\s?m", re.I)


def minutos_12h(texto):
    """'12:05 AM' -> 5, '1:30 PM' -> 810. None si no es una hora."""
    m = RE_12H.search(texto or "")
    if not m:
        return None
    h = int(m.group(1)) % 12
    if m.group(3).lower() == "p":
        h += 12
    return h * 60 + int(m.group(2))


def construir_filas(entradas, previo=None):
    """entradas: [(minuto_de_inicio, titulo)] de un día.
    El fin de cada programa es el inicio del siguiente; el último termina a medianoche.
    previo: título del último programa del día anterior (sigue al aire pasada la medianoche)."""
    orden = sorted((e for e in entradas if e[1]), key=lambda e: e[0])
    depurado = []
    for ini, tit in orden:
        if depurado and depurado[-1][0] == ini:   # misma hora repetida
            continue
        if depurado and depurado[-1][1] == tit:   # mismo programa seguido: se fusiona
            continue
        depurado.append((ini, tit))
    if not depurado:
        return []
    if previo and depurado[0][0] > 0:
        if depurado[0][1] == previo:
            depurado[0] = (0, previo)
        else:
            depurado.insert(0, (0, previo))
    filas = []
    for k, (ini, tit) in enumerate(depurado):
        fin = depurado[k + 1][0] if k + 1 < len(depurado) else 1440
        filas.append({"i": hhmm(ini), "f": hhmm(fin), "p": tit})
    return filas


def lunes_de(d):
    return d - timedelta(days=d.weekday())


# ------------------------------------------------------------------ scrapers

def parse_stve(html, hoy):
    """stvetelebasica.com: semana completa estática (section.wrapper<día> .rowtableprogram)."""
    soup = BeautifulSoup(html, "lxml")

    def entradas(dia):
        # Cada día viene dos veces: una copia vacía dentro de <template> y la real. Se usa la real.
        secs = [s for s in soup.select("section.wrapper" + DIAS_ES[dia]) if s.find_parent("template") is None]
        if not secs:
            return None
        sec = secs[0]
        res = []
        for r in sec.select(".rowtableprogram"):
            h = r.select_one(".horawp")
            d = r.select_one(".descriptionwp")
            if not h or not d:
                continue
            m = minutos_12h(h.get_text(" "))
            t = limpiar(d.get_text(" "))
            if m is not None and t:
                res.append((m, t))
        return res

    hoy_e = entradas(hoy.weekday())
    if not hoy_e:
        raise ValueError("no se encontró la programación de hoy")
    prev_e = entradas((hoy.weekday() - 1) % 7) or []
    previo = sorted(prev_e)[-1][1] if prev_e else None
    return construir_filas(hoy_e, previo)


def extraer_guia_next(html):
    """Televicentro y Deportes TVC (Next.js): la guía viaja en el payload self.__next_f."""
    trozos = re.findall(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)', html)
    if not trozos:
        raise ValueError("no se encontró el payload de Next.js")
    texto = "".join(json.loads('"' + t + '"') for t in trozos)
    clave = '"guideDataView":'
    i = texto.find(clave)
    if i < 0:
        raise ValueError("no se encontró guideDataView")
    obj, _ = json.JSONDecoder().raw_decode(texto[i + len(clave):])
    return obj["firstSectionGuide"]


def indice_semana(html, hoy, n_semanas):
    """Qué elemento de firstSectionGuide es la semana actual.
    Si el HTML trae las pestañas de fecha ('LUN 26 Oct') se usan; si no, se asume que el 0 es la actual."""
    texto = BeautifulSoup(html, "lxml").get_text(" ")
    m = re.search(r"\bLUN\s*(\d{1,2})\s*(ene|feb|mar|abr|may|jun|jul|ago|sep|set|oct|nov|dic)", texto, re.I)
    if not m:
        return 0
    dia, mes = int(m.group(1)), MESES[m.group(2).lower()]
    candidatas = []
    for anio in (hoy.year - 1, hoy.year, hoy.year + 1):
        try:
            candidatas.append(date(anio, mes, dia))
        except ValueError:
            pass
    lunes_primero = min(candidatas, key=lambda c: abs((c - hoy).days))
    idx = (lunes_de(hoy) - lunes_primero).days // 7
    if not 0 <= idx < n_semanas:
        raise ValueError(f"la guía publicada no incluye la semana actual (empieza el {lunes_primero})")
    return idx


def parse_next(html, hoy):
    semanas = extraer_guia_next(html)
    s = indice_semana(html, hoy, len(semanas))

    def entradas(sem, dia):
        if not 0 <= sem < len(semanas):
            return None
        res = []
        for p in semanas[sem].get(DIAS_EN[dia]) or []:
            m = minutos_12h(p.get("hour"))
            t = limpiar(p.get("title") or p.get("description"))
            if m is not None and t:
                res.append((m, t))
        return res

    d = hoy.weekday()
    hoy_e = entradas(s, d)
    if not hoy_e:
        raise ValueError("no hay programas para hoy")
    prev_e = entradas(s, d - 1) if d > 0 else entradas(s - 1, 6)
    previo = sorted(prev_e)[-1][1] if prev_e else None
    return construir_filas(hoy_e, previo)


def parse_canal11(html, hoy):
    """canal11.hn: la semana completa está en window.C11.GRILLA (con hora de fin)."""
    i = html.find("window.C11")
    if i < 0:
        raise ValueError("no se encontró window.C11")
    j = html.find("{", i)
    datos, _ = json.JSONDecoder().raw_decode(html[j:])
    grilla, dias = datos["GRILLA"], datos["DIAS"]
    programas = datos.get("PROGRAMAS") or {}
    idx = [normalizar(x) for x in dias].index(DIAS_ES[hoy.weekday()])
    filas = []
    for ini, fin, slug, titulo in grilla[idx]:
        t = limpiar(titulo)
        if not t and slug:
            t = limpiar((programas.get(slug) or {}).get("titulo", ""))
        if not t:
            continue
        filas.append({"i": hhmm_texto(ini), "f": hhmm_texto(fin), "p": t})
    if not filas:
        raise ValueError("no hay programas para hoy")
    return filas


PARSERS = {
    "stve": parse_stve,
    "deportestvc": parse_next,
    "canal5": parse_next,
    "canal11": parse_canal11,
}


# ----------------------------------------------------------------- red/Firebase

def descargar(url):
    ultimo = None
    for intento in range(3):
        try:
            r = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "es-HN,es;q=0.9"}, timeout=30)
            r.raise_for_status()
            return r.content.decode("utf-8", errors="replace")  # evita acentos rotos
        except Exception as e:
            ultimo = e
            time.sleep(3 * (intento + 1))
    raise RuntimeError(f"no se pudo descargar {url}: {ultimo}")


def fuente_y_slug(ch):
    """Misma regla que la app: así lo que se sube es considerado válido por el reproductor."""
    gato = str(ch.get("gatotv") or "").strip()
    mitv_raw = str(ch.get("mitv") or "").strip()
    web = str(ch.get("epg_web") or "").strip()
    pref = str(ch.get("epg_fuente") or "").strip().lower()
    mitv = mitv_raw.split("/", 1)[1].strip() if "/" in mitv_raw else mitv_raw
    if gato and mitv:
        fuente = "mitv" if pref == "mitv" else "gatotv"
    elif gato:
        fuente = "gatotv"
    elif mitv:
        fuente = "mitv"
    else:
        fuente = "web"
    slug = {"gatotv": gato, "mitv": mitv, "web": web}[fuente]
    return fuente, slug


def conectar():
    import firebase_admin
    from firebase_admin import credentials, db
    cred = credentials.Certificate(json.loads(os.environ["FIREBASE_CREDENTIALS"]))
    firebase_admin.initialize_app(cred, {"databaseURL": os.environ["FIREBASE_DB_URL"].strip().rstrip("/")})
    return db


def subir(db, canal_id, fuente, slug, fecha, filas):
    info = {"fecha": fecha, "fuente": fuente, "slug": slug, "actualizado": int(time.time() * 1000)}
    datos = dict(info)
    datos["rows"] = filas
    db.reference(f"epg_rows/{canal_id}").set(datos)   # primero las filas
    db.reference(f"epg_info/{canal_id}").set(info)    # luego el aviso de que está al día


def guardar_archivos(fecha, exportar):
    """Deja la programación en archivos que se pueden abrir desde el repo."""
    with open("programacion.json", "w", encoding="utf-8") as f:
        json.dump({"fecha": fecha, "canales": exportar}, f, ensure_ascii=False, indent=2)
    lineas = [f"Programación del {fecha} (hora de Honduras)", ""]
    for canal_id, c in exportar.items():
        lineas.append(f"{c['nombre']}  [{canal_id}]  fuente: {c['fuente']}")
        for r in c["rows"]:
            lineas.append(f"  {r['i']} - {r['f']}  {r['p']}")
        lineas.append("")
    with open("programacion.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(lineas))


def main():
    hoy = datetime.now(TZ).date()
    fecha = hoy.isoformat()
    dry = os.environ.get("DRY_RUN") == "1"
    db = conectar()
    canales = db.reference("canales").get() or {}

    paginas, resultados = {}, {}

    def obtener(scraper):
        if scraper not in resultados:
            try:
                url = URLS[scraper]
                if url not in paginas:
                    paginas[url] = descargar(url)
                resultados[scraper] = PARSERS[scraper](paginas[url], hoy)
            except Exception as e:
                resultados[scraper] = e
        if isinstance(resultados[scraper], Exception):
            raise resultados[scraper]
        return resultados[scraper]

    print(f"Fecha (Honduras): {fecha}" + ("  [DRY_RUN: no se escribe]" if dry else ""))
    fallos = []
    exportar = {}
    for canal_id, scraper in CANALES.items():
        ch = canales.get(canal_id)
        nombre = ch.get("nombre", canal_id) if isinstance(ch, dict) else canal_id
        try:
            if not isinstance(ch, dict):
                raise ValueError("el ID no existe en el nodo canales")
            fuente, slug = fuente_y_slug(ch)
            if not slug:
                raise ValueError("el canal no tiene gatotv, mitv ni epg_web configurado")
            filas = obtener(scraper)
            if not filas:
                raise ValueError("sin programas")
            if not dry:
                subir(db, canal_id, fuente, slug, fecha, filas)
            exportar[canal_id] = {"nombre": nombre, "fuente": fuente, "slug": slug, "rows": filas}
            print(f"[OK] {nombre}: {len(filas)} programas ({fuente}) {filas[0]['i']} -> {filas[-1]['f']}")
            if dry:
                for f in filas[:3]:
                    print(f"       {f['i']}-{f['f']}  {f['p']}")
        except Exception as e:
            fallos.append(nombre)
            print(f"[FALLO] {nombre}: {e}")

    guardar_archivos(fecha, exportar)
    if fallos:
        print("Con errores: " + ", ".join(fallos))
        sys.exit(1)


if __name__ == "__main__":
    main()
