
#!/usr/bin/env python3
"""Genera los estrenos semanales de cine en España para Montaje Final.

Crea:
- estrenos_semanales.txt
- estrenos_semanales.json
- posters/ con los pósteres descargados

No publica directamente en WhatsApp.
"""

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

API_BASE = "https://api.themoviedb.org/3"
IMAGE_BASE = "https://image.tmdb.org/t/p/w500"
TZ = ZoneInfo("Europe/Madrid")

MAX_PAGES = 10
MAX_MOVIES = 50
MAX_WEEKLY_MOVIES = 6

GENRES = {
    28: "Acción",
    12: "Aventura",
    16: "Animación",
    35: "Comedia",
    80: "Crimen",
    99: "Documental",
    18: "Drama",
    10751: "Familia",
    14: "Fantasía",
    36: "Historia",
    27: "Terror",
    10402: "Música",
    9648: "Misterio",
    10749: "Romance",
    878: "Ciencia ficción",
    10770: "TV",
    53: "Thriller",
    10752: "Bélica",
    37: "Western",
}


def tmdb_get(path, params=None):
    """Consulta la API de TMDb."""
    api_key = os.getenv("TMDB_API_KEY", "").strip()

    if not api_key:
        raise RuntimeError(
            "Falta TMDB_API_KEY. Configúrala en GitHub > "
            "Settings > Secrets and variables > Actions."
        )

    query = {
        "api_key": api_key,
        "language": "es-ES",
    }
    query.update(params or {})

    url = f"{API_BASE}{path}?{urllib.parse.urlencode(query)}"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "MontajeFinal-Estrenos/1.0",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            return json.loads(response.read().decode("utf-8"))

    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]

        if exc.code in (401, 403):
            raise RuntimeError(
                "TMDb ha rechazado la clave API v3. Revisa TMDB_API_KEY."
            ) from exc

        raise RuntimeError(
            f"Error HTTP de TMDb ({exc.code}): {detail}"
        ) from exc

    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"No se pudo conectar con TMDb: {exc.reason}"
        ) from exc


def trailer_for(movie_id):
    """Busca un tráiler de YouTube, priorizando los que están en español."""
    try:
        videos = tmdb_get(
            f"/movie/{movie_id}/videos",
            {"language": "es-ES"},
        ).get("results", [])

        videos = [
            video for video in videos
            if video.get("site") == "YouTube" and video.get("key")
        ]

        trailers = [
            video for video in videos
            if video.get("type") == "Trailer"
        ]

        spanish = [
            video for video in trailers
            if video.get("iso_639_1") == "es"
        ]

        choices = spanish or trailers or videos

        if not choices:
            return None

        choices.sort(
            key=lambda video: (
                not video.get("official", False),
                video.get("published_at", ""),
            ),
            reverse=False,
        )

        return (
            "https://www.youtube.com/watch?v="
            + choices[0]["key"]
        )

    except RuntimeError as exc:
        print(
            f"Aviso: no se pudo consultar el tráiler {movie_id}: {exc}",
            file=sys.stderr,
        )
        return None


def download_poster(movie):
    """Descarga el póster y devuelve la ruta relativa del archivo."""
    poster_path = movie.get("poster_path")

    if not poster_path:
        print(
            f"Aviso: {movie.get('title', 'Película')} no tiene póster."
        )
        return None

    folder = Path("posters")
    folder.mkdir(parents=True, exist_ok=True)

    title = (
        movie.get("title")
        or movie.get("original_title")
        or str(movie["id"])
    )

    safe_title = re.sub(
        r"[^a-zA-Z0-9_-]+", "-", title
    ).strip("-_").lower()

    filename = f"{safe_title[:70] or 'pelicula'}-{movie['id']}.jpg"
    destination = folder / filename
    url = IMAGE_BASE + poster_path

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "MontajeFinal-Estrenos/1.0"},
    )

    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            content_type = response.headers.get("Content-Type", "")
            image_data = response.read()

        if not content_type.lower().startswith("image/") or not image_data:
            print(f"Aviso: imagen no válida para {title}.")
            return None

        destination.write_bytes(image_data)
        print(f"Póster guardado: {destination}")

        return destination.as_posix()

    except (
        urllib.error.URLError,
        OSError,
        TimeoutError,
    ) as exc:
        print(
            f"Aviso: no se pudo descargar el póster de {title}: {exc}"
        )
        return None


def get_releases(start, end):
    """Obtiene los estrenos españoles y selecciona los seis más destacados."""
    found = {}

    for page in range(1, MAX_PAGES + 1):
        data = tmdb_get(
            "/discover/movie",
            {
                "region": "ES",
                "with_release_type": "2|3",
                "primary_release_date.gte": start.isoformat(),
                "primary_release_date.lte": end.isoformat(),
                "sort_by": "primary_release_date.asc",
                "include_adult": "false",
                "page": page,
            },
        )

        for movie in data.get("results", []):
            if movie.get("id"):
                found[movie["id"]] = movie

        total_pages = int(data.get("total_pages", 1))

        if page >= min(total_pages, MAX_PAGES):
            break

        if len(found) >= MAX_MOVIES:
            break

    candidates = list(found.values())[:MAX_MOVIES]

    # Priorizar popularidad, número de votos y valoración.
    candidates.sort(
        key=lambda movie: (
            float(movie.get("popularity") or 0),
            int(movie.get("vote_count") or 0),
            float(movie.get("vote_average") or 0),
        ),
        reverse=True,
    )

    movies = candidates[:MAX_WEEKLY_MOVIES]

    # Presentar las películas en orden cronológico.
    movies.sort(
        key=lambda movie: (
            movie.get("release_date") or "9999-12-31",
            (movie.get("title") or "").casefold(),
        )
    )

    for movie in movies:
        movie["trailer_url"] = trailer_for(movie["id"])

        movie["poster_url"] = (
            IMAGE_BASE + movie["poster_path"]
            if movie.get("poster_path")
            else None
        )

        movie["poster_file"] = download_poster(movie)

    return movies


def format_date(value):
    """Convierte la fecha al formato español."""
    try:
        return date.fromisoformat(value).strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        return value or "Fecha por confirmar"


def build_message(movies, start, end):
    """Construye el mensaje listo para revisar y compartir."""
    lines = [
        f"🎬 ESTRENOS DE CINE | {start:%d/%m}–{end:%d/%m/%Y}",
        "Montaje Final · Cartelera semanal en España",
        "",
    ]

    if not movies:
        lines += [
            "No se han encontrado estrenos en TMDb para este periodo.",
            (
                "Esto no confirma que no haya estrenos: "
                "verifica otras fuentes antes de publicar."
            ),
        ]

    else:
        lines += [
            "🍿 LOS ESTRENOS MÁS DESTACADOS DE LA SEMANA",
            "",
        ]

        for movie in movies:
            title = (
                movie.get("title")
                or movie.get("original_title")
                or "Título no disponible"
            )

            genres = ", ".join(
                GENRES[genre_id]
                for genre_id in movie.get("genre_ids", [])
                if genre_id in GENRES
            )

            overview = (movie.get("overview") or "").strip()

            if len(overview) > 360:
                overview = overview[:357].rsplit(" ", 1)[0] + "…"

            lines += [
                f"🎥 {title} ({format_date(movie.get('release_date'))})",
                f"🎭 {genres or 'Género por confirmar'}",
                overview or "Sinopsis pendiente de confirmar.",
            ]

            if movie.get("trailer_url"):
                lines.append("▶️ Tráiler: " + movie["trailer_url"])

            if movie.get("poster_file"):
                lines.append("🖼️ Póster: " + movie["poster_file"])

            lines.append("")

        featured = max(
            movies,
            key=lambda movie: float(movie.get("popularity") or 0),
        )

        featured_title = (
            featured.get("title")
            or featured.get("original_title")
            or "Título por confirmar"
        )

        lines += [
            "⭐ PELÍCULA DESTACADA",
            f"{featured_title} — destacada por popularidad registrada en TMDb.",
            "",
            "💬 ¿Cuál tienes más ganas de ver? ¡Te leemos!",
        ]

    lines += [
        "",
        (
            "Datos de TMDb (The Movie Database). "
            "Las fechas pueden cambiar; verifica con distribuidoras y salas."
        ),
        "#EstrenosSemanales #MontajeFinal",
    ]

    return "\n".join(lines).strip() + "\n"


def main():
    now = datetime.now(TZ)

    # La programación ejecuta a las 08:00 y 09:00 UTC.
    # Solo genera la cartelera a las 10:00, hora peninsular.
    if (
        os.getenv("GITHUB_EVENT_NAME") == "schedule"
        and now.hour != 10
    ):
        print(
            "Ejecución omitida para ajustar horario: "
            f"ahora son las {now:%H:%M} en Europe/Madrid."
        )
        return 0

    start = now.date()
    end = start + timedelta(days=6)

    print(f"Consultando estrenos de España entre {start} y {end}...")

    movies = get_releases(start, end)
    message = build_message(movies, start, end)

    Path("estrenos_semanales.txt").write_text(
        message,
        encoding="utf-8",
    )

    payload = {
        "generated_at": now.isoformat(),
        "region": "ES",
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "count": len(movies),
        "source": "TMDb",
        "movies": movies,
        "message": message,
        "whatsapp_delivery": "not_configured",
    }

    Path("estrenos_semanales.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    poster_count = sum(
        1 for movie in movies if movie.get("poster_file")
    )

    print(f"Cartelera generada: {len(movies)} películas.")
    print(f"Pósteres descargados: {poster_count}.")
    print(
        "Archivos creados: estrenos_semanales.txt, "
        "estrenos_semanales.json y carpeta posters/."
    )
    print("\n--- VISTA PREVIA ---\n")
    print(message)

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
