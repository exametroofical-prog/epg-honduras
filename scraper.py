import json
from datetime import datetime
from bs4 import BeautifulSoup
import requests

# Cabecera para simular que la petición viene de un navegador web real y evitar bloqueos (como el error 403)
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML,"
        " like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}


def extraer_hch():
  url = "https://hch.tv/"  # O la ruta específica de programación de HCH
  try:
    response = requests.get(url, headers=HEADERS, timeout=10)
    if response.status_code == 200:
      soup = BeautifulSoup(response.text, "html.parser")
      programacion = []

      # Ajusta estos selectores según la estructura HTML de la página de HCH
      # Ejemplo genérico de búsqueda de elementos de programación:
      for item in soup.select(
          ".program-item"
      ):  # Cambia por la clase real de la web
        titulo = item.find("h3").get_text(strip=True) if item.find("h3") else ""
        hora = (
            item.find(".time").get_text(strip=True)
            if item.find(".time")
            else ""
        )
        if titulo:
          programacion.append({"hora": hora, "titulo": titulo})

      # Si ya tienes tu propia lógica funcional para HCH, mantenla y solo agrégale headers=HEADERS a requests.get()
      return {"estado": "exito", "programacion": programacion}
  except Exception as e:
    return {"estado": "error", "mensaje": str(e), "programacion": []}


# Estructura principal del JSON que se guardará
datos_epg = {
    "actualizado": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "canales": {
        "hch": extraer_hch(),
        # Repite la lógica adaptada para cada canal restante (televicentro, deportestvc, etc.) usando headers=HEADERS en sus requests.get()
    },
}

with open("programacion.json", "w", encoding="utf-8") as f:
  json.dump(datos_epg, f, ensure_ascii=False, indent=4)

print("EPG actualizada correctamente.")
