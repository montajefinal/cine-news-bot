
#!/usr/bin/env python3
"""Genera la cartelera semanal española de Montaje Final.

Archivos generados:
- estrenos_semanales.txt
- estrenos_semanales.json
- cartelera_estrenos.png
- posters/ con los pósteres descargados
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

from PIL import Image, ImageDraw, ImageFont, ImageOps

API_BASE = "https://api.themoviedb.org/3"
IMAGE_BASE = "https://image.tmdb.org/t/p/w500"
TZ = ZoneInfo("Europe/Madrid")

MAX_PAGES = 5
MAX_WEEKLY_MOVIES = 6
RELEASE_TYPES_THEATRICAL = {2, 3}

GENRES = {
    28: "Acción", 12: "Aventura", 16: "Animación",
    35: "Comedia", 80: "Crimen", 99: "Documental",
    18: "Drama", 10751: "Familia", 14: "Fantasía",
    36: "Historia", 27: "Terror", 10402: "Música",
    9648: "Misterio", 10749: "Romance",
    878: "Ciencia ficción", 10770: "TV",
    53: "Thriller", 10752: "Bélica", 37: "Western",
}


def tmdb_get(path, params=None):
    """Consulta la API de TMDb."""
    api_key = os.getenv("TMDB_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "Falta TMDB_API_KEY. Configúrala en GitHub > "
            "Settings > Secrets and variables > Actions."
        )

    query = {"api_key": api_key, "language": "es-ES"}
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
                "Revisa el secreto TMDB_API_KEY."
            ) from exc
        raise RuntimeError(
            f"Error HTTP de TMDb ({exc.code}): {detail}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"No se pudo conectar con TMDb: {exc.reason}"
        ) from exc


def spanish_theatrical_release(movie_id, start, end):
    """Busca fechas de estreno teatral registradas específicamente en España."""
    data = tmdb_get(f"/movie/{movie_id}/release_dates")
    releases = []

    for country in data.get("results", []):
        if country.get("iso_3166_1") != "ES":
            continue

        for release in country.get("release_dates", []):
            if release.get("type") not in RELEASE_TYPES_THEATRICAL:
                continue

            try:
                release_day = date.fromisoformat(
                    release.get("release_date", "")[:10]
                )
            except (TypeError, ValueError):
                continue

            if start <= release_day <= end:
                releases.append((release_day, release.get("type")))

    if not releases:
        return None

    releases.sort(key=lambda item: (item[0], item[1] != 3))
    return releases[0][0].isoformat()


def trailer_for(movie_id):
    """Busca un tráiler de YouTube, priorizando el español y los oficiales."""
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
                bool(video.get("official", False)),
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
    """Descarga el póster y devuelve la ruta relativa."""
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
    destination = folder / f"{safe_title[:70] or 'pelicula'}-{movie['id']}.jpg"

    request = urllib.request.Request(
        IMAGE_BASE + poster_path,
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
    """Filtra por estrenos teatrales españoles comprobados en TMDb."""
    candidates = {}

    for page in range(1, MAX_PAGES + 1):
        data = tmdb_get(
            "/discover/movie",
            {
                "region": "ES",
                "with_release_type": "3|2",
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

        if page >= min(int(data.get("total_pages", 1)), MAX_PAGES):
            break

    verified = []
    ordered = sorted(
        candidates.values(),
        key=lambda movie: (
            float(movie.get("popularity") or 0),
            int(movie.get("vote_count") or 0),
            float(movie.get("vote_average") or 0),
        ),
        reverse=True,
    )

    for movie in ordered:
        try:
            spanish_date = spanish_theatrical_release(
                movie["id"], start, end
            )
        except RuntimeError as exc:
            print(
                f"Aviso: no se pudo verificar {movie.get('title', movie['id'])}: {exc}",
                file=sys.stderr,
            )
            continue

        if not spanish_date:
            print(
                "Descartada (sin fecha teatral española en el periodo): "
                f"{movie.get('title', movie['id'])}"
            )
            continue

        movie["release_date"] = spanish_date
        verified.append(movie)

    verified.sort(
        key=lambda movie: (
            float(movie.get("popularity") or 0),
            int(movie.get("vote_count") or 0),
            float(movie.get("vote_average") or 0),
        ),
        reverse=True,
    )
    movies = verified[:MAX_WEEKLY_MOVIES]
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
    try:
        return date.fromisoformat(value).strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        return value or "Fecha por confirmar"


def build_message(movies, start, end):
    """Genera el texto semanal para compartir."""
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
        lines += ["🍿 LOS ESTRENOS MÁS DESTACADOS DE LA SEMANA", ""]

        for movie in movies:
            title = (
                movie.get("title")
                or movie.get("original_title")
                or "Título no disponible"
            )
            genres = ", ".join(
                GENRES[g] for g in movie.get("genre_ids", []) if g in GENRES
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
        "Fuente: TMDb (The Movie Database). Solo se incluyen fechas "
        "teatrales de España registradas en TMDb. Contrasta con "
        "distribuidoras y salas antes de publicar.",
        "#EstrenosSemanales #MontajeFinal",
    ]
    return "\n".join(lines).strip() + "\n"


def generate_promo_image(movies, start, end):
    """Crea una cartelera vertical 1080x1350 lista para compartir."""
    width, height = 1080, 1350
    canvas = Image.new("RGB", (width, height), (13, 16, 25))
    draw = ImageDraw.Draw(canvas)

    regular = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    bold = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

    def font(size, is_bold=False):
        try:
            return ImageFont.truetype(
                bold if is_bold else regular, size
            )
        except OSError:
            return ImageFont.load_default()

    white = (255, 255, 255)
    gold = (245, 190, 75)
    muted = (190, 199, 216)
    panel = (24, 29, 43)

    # Cabecera
    draw.rounded_rectangle((32, 28, 1048, 205), radius=28, fill=panel)
    draw.text((60, 48), "MONTAJE FINAL", font=font(20, True), fill=gold)
    draw.text((60, 82), "ESTRENOS DE CINE", font=font(48, True), fill=white)
    draw.text(
        (62, 145),
        f"EN ESPAÑA · {start:%d/%m} — {end:%d/%m/%Y}",
        font=font(25),
        fill=muted,
    )

    if not movies:
        draw.rounded_rectangle((32, 235, 1048, 520), radius=24, fill=panel)
        draw.text(
            (60, 280),
            "Sin estrenos españoles verificados",
            font=font(27, True),
            fill=white,
        )
        draw.text(
            (60, 330),
            "para este periodo en TMDb.",
            font=font(24),
            fill=muted,
        )
    else:
        margin, gap_x, gap_y = 32, 24, 20
        card_w = (width - margin * 2 - gap_x) // 2
        card_h, top = 330, 225

        for index, movie in enumerate(movies[:6]):
            col, row = index % 2, index // 2
            x = margin + col * (card_w + gap_x)
            y = top + row * (card_h + gap_y)

            draw.rounded_rectangle(
                (x, y, x + card_w, y + card_h),
                radius=22,
                fill=panel,
            )

            # Póster
            poster = None
            poster_file = movie.get("poster_file")
            if poster_file and Path(poster_file).exists():
                try:
                    with Image.open(poster_file) as source:
                        poster = ImageOps.fit(
                            source.convert("RGB"),
                            (150, 225),
                            method=Image.Resampling.LANCZOS,
                        )
                except (OSError, ValueError):
                    poster = None

            if poster is None:
                poster = Image.new("RGB", (150, 225), (55, 62, 79))
                ImageDraw.Draw(poster).text(
                    (17, 100), "SIN PÓSTER",
                    font=font(16, True), fill=white,
                )

            canvas.paste(poster, (x + 14, y + 15))

            # Título con ajuste de línea
            text_x = x + 180
            text_w = card_w - 196
            title = (
                movie.get("title")
                or movie.get("original_title")
                or "Título pendiente"
            )

            title_lines, current = [], ""
            for word in title.split():
                candidate = f"{current} {word}".strip()
                if draw.textbbox(
                    (0, 0), candidate, font=font(22, True)
                )[2] <= text_w:
                    current = candidate
                else:
                    if current:
                        title_lines.append(current)
                    current = word
            if current:
                title_lines.append(current)

            for i, line in enumerate(title_lines[:3]):
                draw.text(
                    (text_x, y + 20 + i * 28),
                    line,
                    font=font(22, True),
                    fill=white,
                )

            draw.text(
                (text_x, y + 108),
                format_date(movie.get("release_date")),
                font=font(18, True),
                fill=gold,
            )

            genres = [
                GENRES[g] for g in movie.get("genre_ids", []) if g in GENRES
            ]
            genre_text = ", ".join(genres[:2]) if genres else "Cine"
            if len(genre_text) > 24:
                genre_text = genre_text[:21] + "…"

            draw.text(
                (text_x, y + 140),
                genre_text,
                font=font(16),
                fill=muted,
            )

            # Sinopsis ajustada al espacio disponible
            overview = " ".join((movie.get("overview") or "").split())
            synopsis_lines, current = [], ""
            for word in overview.split():
                candidate = f"{current} {word}".strip()
                if draw.textbbox(
                    (0, 0), candidate, font=font(13)
                )[2] <= text_w:
                    current = candidate
                else:
                    if current:
                        synopsis_lines.append(current)
                    current = word
            if current:
                synopsis_lines.append(current)

            for i, line in enumerate(synopsis_lines[:3]):
                draw.text(
                    (text_x, y + 171 + i * 20),
                    line,
                    font=font(13),
                    fill=(210, 215, 225),
                )

            if movie.get("trailer_url"):
                draw.text(
                    (x + 18, y + 258),
                    "TRÁILER DISPONIBLE ▶",
                    font=font(15, True),
                    fill=gold,
                )

    # Pie
    draw.line((32, 1255, 1048, 1255), fill=(64, 72, 91), width=2)
    draw.text(
        (34, 1270),
        "Fechas españolas registradas en TMDb",
        font=font(17),
        fill=muted,
    )
    draw.text(
        (34, 1300),
        "#EstrenosSemanales  #MontajeFinal",
        font=font(18, True),
        fill=gold,
    )

    output = Path("cartelera_estrenos.png")
    canvas.save(output, format="PNG", optimize=True)
    print(f"Cartelera visual guardada: {output}")
    return output.as_posix()


def main():
    now = datetime.now(TZ)

    # Las ejecuciones programadas se lanzan a las 08:00 y 09:00 UTC.
    # Solo generar a las 10:00 en horario peninsular.
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
    image_file = generate_promo_image(movies, start, end)

    Path("estrenos_semanales.txt").write_text(
        message, encoding="utf-8"
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
        "image_file": image_file,
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
        "estrenos_semanales.json, cartelera_estrenos.png y posters/."
    )
    print("\n--- VISTA PREVIA DEL TEXTO ---\n")
    print(message)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
