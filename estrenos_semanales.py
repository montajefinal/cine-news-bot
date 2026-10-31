
#!/usr/bin/env python3
"""Genera los estrenos semanales de cine en España para Montaje Final.

Crea:
- estrenos_semanales.txt
- estrenos_semanales.json
- posters/ con los pósteres descargados

Solo incluye películas con estreno teatral en España registrado en TMDb.
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

MAX_PAGES = 5
MAX_WEEKLY_MOVIES = 6
RELEASE_TYPES_THEATRICAL = {2, 3}

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
                "TMDb ha rechazado la clave API v3. "
                "Revisa el secreto TMDB_API_KEY de GitHub."
            ) from exc

        raise RuntimeError(
            f"Error HTTP de TMDb ({exc.code}): {detail}"
        ) from exc

    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"No se pudo conectar con TMDb: {exc.reason}"
        ) from exc


def spanish_theatrical_release(movie_id, start, end):
    """Devuelve la fecha de estreno en salas de España, si está registrada.

    Tipos TMDb:
    2 = estreno teatral limitado
    3 = estreno teatral general

    No usa la fecha mundial ni la fecha principal como sustituto.
    """
    data = tmdb_get(f"/movie/{movie_id}/release_dates")
    releases = []

    for country in data.get("results", []):
        if country.get("iso_3166_1") != "ES":
            continue

        for release in country.get("release_dates", []):
            release_type = release.get("type")
            release_datetime = release.get("release_date", "")
            release_day = release_datetime[:10]

            if release_type not in RELEASE_TYPES_THEATRICAL:
                continue

            try:
                parsed_day = date.fromisoformat(release_day)
            except (TypeError, ValueError):
                continue

            if start <= parsed_day <= end:
                releases.append((parsed_day, release_type))

    if not releases:
        return None

    # Si hay estreno general y limitado, conserva la fecha más temprana
    # registrada para las salas españolas dentro de la semana.
    releases.sort(key=lambda item: (item[0], item[1] != 3))
    return releases[0][0].isoformat()


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

        # Prioriza vídeos oficiales y después los más recientes.
        choices.sort(
            key=lambda video: (
                not video.get("official", False),
                video.get("published_at", ""),
            ),
            reverse=True,
        )

        return "https://www.youtube.com/watch?v=" + choices[0]["key"]

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
        print(f"Aviso: {movie.get('title', 'Película')} no tiene póster.")
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

    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        print(f"Aviso: no se pudo descargar el póster de {title}: {exc}")
        return None


def get_releases(start, end):
    """Obtiene y verifica estrenos teatrales registrados en España."""
    candidates = {}

    for page in range(1, MAX_PAGES + 1):
        data = tmdb_get(
            "/discover/movie",
            {
                "region": "ES",
                # General primero: TMDb prioriza esa fecha cuando exista.
                "with_release_type": "3|2",
                # Usar release_date, no primary_release_date.
                "release_date.gte": start.isoformat(),
                "release_date.lte": end.isoformat(),
                "sort_by": "popularity.desc",
                "include_adult": "false",
                "page": page,
            },
        )

        for movie in data.get("results", []):
            if movie.get("id"):
                candidates[movie["id"]] = movie

        total_pages = int(data.get("total_pages", 1))
        if page >= min(total_pages, MAX_PAGES):
            break

    # Verificar cada película contra las fechas por país.
    # Esto evita usar por error una fecha mundial como fecha española.
    verified = []

    ordered_candidates = sorted(
        candidates.values(),
        key=lambda movie: (
            float(movie.get("popularity") or 0),
            int(movie.get("vote_count") or 0),
            float(movie.get("vote_average") or 0),
        ),
        reverse=True,
    )

    for movie in ordered_candidates:
        try:
            spanish_date = spanish_theatrical_release(
                movie["id"], start, end
            )
        except RuntimeError as exc:
            # Si no se puede verificar una película, no se presenta
            # como estreno confirmado.
            print(
                f"Aviso: no se pudo verificar el estreno español de "
                f"{movie.get('title', movie['id'])}: {exc}",
                file=sys.stderr,
            )
            continue

        if not spanish_date:
            print(
                f"Descartada (sin fecha teatral española en el periodo): "
                f"{movie.get('title', movie['id'])}"
            )
            continue

        movie["release_date"] = spanish_date
        verified.append(movie)

    # Seleccionar las seis más destacadas entre las verificadas.
    verified.sort(
        key=lambda movie: (
            float(movie.get("popularity") or 0),
            int(movie.get("vote_count") or 0),
            float(movie.get("vote_average") or 0),
        ),
        reverse=True,
    )
    movies = verified[:MAX_WEEKLY_MOVIES]

    # Mostrar en orden cronológico.
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
        f"🎬 ESTRENOS DE CINE EN ESPAÑA | {start:%d/%m}–{end:%d/%m/%Y}",
        "Montaje Final · Cartelera semanal española",
        "",
    ]

    if not movies:
        lines += [
            "No se han encontrado estrenos teatrales españoles "
            "verificados en TMDb para este periodo.",
            "Puede haber estrenos aún no registrados en la base de datos.",
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
            "Fuente: TMDb (The Movie Database). "
            "Solo se incluyen fechas teatrales de España registradas en TMDb. "
            "Conviene contrastar con distribuidoras y salas."
        ),
        "#EstrenosSemanales #MontajeFinal",
    ]

    return "\n".join(lines).strip() + "\n"


def main():
    now = datetime.now(TZ)

    # El workflow programado ejecuta a las 08:00 y 09:00 UTC.
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

    print(
        "Consultando estrenos teatrales registrados en España "
        f"entre {start} y {end}..."
    )

    movies = get_releases(start, end)
    message = build_message(movies, start, end)

    Path("estrenos_semanales.txt").write_text(
        message,
        encoding="utf-8",
    )

    payload = {
        "generated_at": now.isoformat(),
        "region": "ES",
        "region_name": "España",
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "count": len(movies),
        "source": "TMDb",
        "release_scope": "Spanish theatrical releases verified via release_dates",
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

    print(f"Estrenos españoles verificados: {len(movies)}.")
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
