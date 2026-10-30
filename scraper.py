import json
from datetime import datetime
from bs4 import BeautifulSoup
import requests

# Lista de sitios web de programación
URLS = {
    "hch": "https://hch.tv/",
    "televicentro": "https://www.televicentro.com/programacion",
    "deportestvc": "https://www.deportestvc.com/programacion",
    "telebasica": "https://www.stvetelebasica.com/programacion",
    "tnh": "https://tnh.gob.hn/television",
    "canal11": "https://canal11.hn/programacion/",
}

headers = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


def extraer_hch(soup):
  programas = []
  # Basado en la estructura HTML provista para HCH
  franjas = soup.find_all("li", class_="franja")
  for franja in franjas:
    hora = franja.find("time")
    nombre = franja.find("p", class_="nombre")
    if hora and nombre:
      programas.append({
          "hora": hora.get_text(strip=True),
          "titulo": nombre.get_text(strip=True),
      })
  return programas


def extraer_generico(soup):
  # Estructura genérica de respaldo para buscar títulos y horas en otras webs
  programas = []
  for item in soup.find_all(["li", "div"], class_=["programa", "show", "item"]):
    titulo = item.find(["h3", "h4", "span"], class_=["titulo", "nombre"])
    hora = item.find("time")
    if titulo:
      programas.append({
          "hora": hora.get_text(strip=True) if hora else "Por definir",
          "titulo": titulo.get_text(strip=True),
      })
  return programas


def main():
  datos_totales = {
      "actualizado": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
      "canales": {},
  }

  for canal, url in URLS.items():
    print(f"Scrapeando {canal} -> {url}")
    try:
      response = requests.get(url, headers=headers, timeout=15)
      if response.status_code == 200:
        soup = BeautifulSoup(response.text, "lxml")

        if canal == "hch":
          programas = extraer_hch(soup)
        else:
          programas = extraer_generico(soup)

        datos_totales["canales"][canal] = {
            "estado": "exito",
            "programacion": programas,
        }
      else:
        datos_totales["canales"][canal] = {
            "estado": "error",
            "codigo": response.status_code,
            "programacion": [],
        }
    except Exception as e:
      print(f"Error al conectar con {canal}: {e}")
      datos_totales["canales"][canal] = {
          "estado": "exception",
          "mensaje": str(e),
          "programacion": [],
      }

  # Guardar el resultado en un archivo JSON
  with open("programacion.json", "w", encoding="utf-8") as f:
    json.dump(datos_totales, f, ensure_ascii=False, indent=4)
  print("Programación guardada exitosamente en programacion.json")


if __name__ == "__main__":
  main()
