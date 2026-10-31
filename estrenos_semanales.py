#!/usr/bin/env python3
"""Genera la cartelera semanal de estrenos de cine en España usando TMDb.

Salida: estrenos_semanales.txt y estrenos_semanales.json.
Esta versión genera el contenido, pero NO lo envía directamente a WhatsApp.
"""
import json
import os
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
GENRES = {
    28: "Acción", 12: "Aventura", 16: "Animación", 35: "Comedia",
    80: "Crimen", 99: "Documental", 18: "Drama", 10751: "Familia",
    14: "Fantasía", 36: "Historia", 27: "Terror", 10402: "Música",
    9648: "Misterio", 10749: "Romance", 878: "Ciencia ficción",
    10770: "TV", 53: "Thriller", 10752: "Bélica", 37: "Western",
}


def tmdb_get(path, params=None):
    api_key = os.getenv("TMDB_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "Falta TMDB_API_KEY. En GitHub, ve a Settings > Secrets and variables "
            "> Actions > New repository secret y añade tu clave API v3 de TMDb."
        )
    query = {"api_key": api_key, "language": "es-ES"}
    query.update(params or {})
    url = f"{API_BASE}{path}?{urllib.parse.urlencode(query)}"
    request = urllib.request.Request(
        url, headers={"Accept": "application/json", "User-Agent": "MontajeFinal-Estrenos/1.0"}
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        if exc.code in (401, 403):
            raise RuntimeError("TMDb ha rechazado la clave; revisa que sea la clave API v3.") from exc
        raise RuntimeError(f"Error HTTP de TMDb ({exc.code}): {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"No se pudo conectar con TMDb: {exc.reason}") from exc


def trailer_for(movie_id):
    try:
        videos = tmdb_get(f"/movie/{movie_id}/videos", {"language": "es-ES"}).get("results", [])
        videos = [v for v in videos if v.get("site") == "YouTube" and v.get("key")]
        trailers = [v for v in videos if v.get("type") == "Trailer"]
        spanish = [v for v in trailers if v.get("iso_639_1") == "es"]
        choices = spanish or trailers or videos
        if not choices:
            return None
        choices.sort(key=lambda v: (not v.get("official", False), v.get("published_at", "")))
        return "https://www.youtube.com/watch?v=" + choices[0]["key"]
    except RuntimeError as exc:
        print(f"Aviso: no se pudo consultar el tráiler de {movie_id}: {exc}", file=sys.stderr)
        return None


def get_releases(start, end):
    found = {}
    for page in range(1, MAX_PAGES + 1):
        data = tmdb_get("/discover/movie", {
            "region": "ES",
            "with_release_type": "2|3",
            "primary_release_date.gte": start.isoformat(),
            "primary_release_date.lte": end.isoformat(),
            "sort_by": "primary_release_date.asc",
            "include_adult": "false",
            "page": page,
        })
        for movie in data.get("results", []):
            if movie.get("id"):
                found[movie["id"]] = movie
        if page >= min(int(data.get("total_pages", 1)), MAX_PAGES) or len(found) >= MAX_MOVIES:
            break

    movies = sorted(
        found.values(),
        key=lambda m: (m.get("release_date") or "9999-12-31", (m.get("title") or "").casefold())
    )[:MAX_MOVIES]
    for movie in movies:
        movie["trailer_url"] = trailer_for(movie["id"])
        movie["poster_url"] = IMAGE_BASE + movie["poster_path"] if movie.get("poster_path") else None
    return movies


def format_date(value):
    try:
        return date.fromisoformat(value).strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        return value or "Fecha por confirmar"


def build_message(movies, start, end):
    lines = [
        f"🎬 ESTRENOS DE CINE | {start:%d/%m}–{end:%d/%m/%Y}",
        "Montaje Final · Cartelera semanal en España",
        "",
    ]
    if not movies:
        lines += [
            "No se han encontrado estrenos en TMDb para este periodo.",
            "Esto no confirma que no haya estrenos: verifica otras fuentes antes de publicar.",
        ]
    else:
        lines += ["🍿 ESTRENOS DE LA SEMANA", ""]
        for movie in movies:
            title = movie.get("title") or movie.get("original_title") or "Título no disponible"
            genres = ", ".join(GENRES[g] for g in movie.get("genre_ids", []) if g in GENRES)
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
            lines.append("")

        featured = max(movies, key=lambda m: float(m.get("popularity") or 0))
        featured_title = featured.get("title") or featured.get("original_title") or "Título por confirmar"
        lines += [
            "⭐ PELÍCULA DESTACADA",
            f"{featured_title} — destacada por popularidad registrada en TMDb.",
            "",
            "💬 ¿Cuál tienes más ganas de ver? ¡Te leemos!",
        ]
    lines += [
        "",
        "Datos de TMDb (The Movie Database). Las fechas pueden cambiar; verifica con distribuidoras y salas.",
        "#EstrenosSemanales #MontajeFinal",
    ]
    return "\n".join(lines).strip() + "\n"


def main():
    now = datetime.now(TZ)
    # GitHub ejecuta a las 08:00 y 09:00 UTC para cubrir el cambio horario.
    # Solo la ejecución que corresponda a las 10:00 locales genera la cartelera.
    if os.getenv("GITHUB_EVENT_NAME") == "schedule" and now.hour != 10:
        print(f"Ejecución omitida para ajustar horario: ahora son las {now:%H:%M} en Europe/Madrid.")
        return 0

    start = now.date()
    end = start + timedelta(days=6)  # miércoles a martes
    print(f"Consultando estrenos de España entre {start} y {end}…")
    movies = get_releases(start, end)
    message = build_message(movies, start, end)

    Path("estrenos_semanales.txt").write_text(message, encoding="utf-8")
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
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Cartelera generada: {len(movies)} películas.")
    print("Archivos creados: estrenos_semanales.txt y estrenos_semanales.json")
    print("\n--- VISTA PREVIA ---\n")
    print(message)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
