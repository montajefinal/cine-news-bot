import os
import feedparser
import tweepy
import time
import json

# Extrae las credenciales de las variables de entorno del servidor
API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
ACCESS_TOKEN_SECRET = os.getenv("ACCESS_TOKEN_SECRET")

# Autenticación en Tweepy (usando API v2)
client = tweepy.Client(
    consumer_key=API_KEY, consumer_secret=API_SECRET,
    access_token=ACCESS_TOKEN, access_token_secret=ACCESS_TOKEN_SECRET
)

# 2. Configuración del Feed RSS
URL_FEED = "https://www.sensacine.com/rss/noticias-cine.xml"
ARCHIVO_REGISTRO = "noticias_publicadas.json"

def cargar_registro():
    """Carga el registro de noticias ya publicadas para no repetir."""
    if os.path.exists(ARCHIVO_REGISTRO):
        with open(ARCHIVO_REGISTRO, "r") as f:
            return json.load(f)
    return []

def guardar_registro(registro):
    """Guarda las URLs publicadas."""
    with open(ARCHIVO_REGISTRO, "w") as f:
        json.dump(registro, f)

def publicar_noticias():
    print("Buscando nuevas noticias de cine...")
    
    # 1. Camuflaje: Le decimos a la web que somos un navegador Windows normal
    navegador_falso = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    feed = feedparser.parse(URL_FEED, agent=navegador_falso)
    
    # 2. Chivato de ingesta de datos
    print(f"🔍 Noticias detectadas en el feed: {len(feed.entries)}")
    
    publicadas = cargar_registro()
    
    for entrada in feed.entries[:5]:
        link = entrada.link
        titulo = entrada.title
        
        if link not in publicadas:
            texto_tweet = f"🎬 Novedad: {titulo}\n\n{link} #Cine #MontajeFinal"
            
            try:
                client.create_tweet(text=texto_tweet)
                print(f"✅ Tweet publicado: {titulo}")
                
                publicadas.append(link)
                guardar_registro(publicadas)
                time.sleep(10) 
            except Exception as e:
                print(f"❌ Error al publicar: {e}")
        else:
            # 3. Chivato de control de duplicados
            print(f"⏭️ Saltando (ya publicada): {titulo}")
            
if __name__ == "__main__":
    publicar_noticias()
