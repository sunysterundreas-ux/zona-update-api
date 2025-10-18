# --- Патч для совместимости pyppeteer и websockets ---
import sys, asyncio, re, pymysql
from bs4 import BeautifulSoup
from requests_html import HTMLSession
from flask import Flask, request, jsonify
import websockets

if not hasattr(websockets, "client"):
    try:
        import websockets.legacy.client as legacy_client
        websockets.client = legacy_client
        sys.modules["websockets.client"] = legacy_client
        print("[i] Патч: websockets.client → websockets.legacy.client применён")
    except Exception as e:
        print(f"[!] Не удалось применить патч websockets.client: {e}")
# ------------------------------------------------------

# Настройки базы (Бегет)
DB_HOST = "fernandess.beget.tech"
DB_USER = "fernandess_films"
DB_PASS = "GRG121dx"
DB_NAME = "fernandess_films"

# Flask сервер
app = Flask(__name__)


def db_connect():
    """Создаёт подключение к MySQL на Бегете"""
    return pymysql.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASS,
        database=DB_NAME,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor
    )


def parse_zona_page(url):
    """Парсит страницу фильма на Zona.plus"""
    print(f"🔹 Парсим {url}")
    session = HTMLSession()
    try:
        r = session.get(url)
        r.html.render(timeout=120, sleep=5, keep_page=True, scrolldown=4)
        soup = BeautifulSoup(r.html.html, "html.parser")

        data = {
            "kp_id": None,
            "title_name": None,
            "rating_kp": None,
            "rating_imdb": None,
            "year": None,
            "genres": None,
            "country": None,
            "actors": None,
            "duration": None,
            "premiere": None,
            "description": None,
            "poster": None,
            "video": None,
            "zona_link": url,
            "type": "movie" if "movies" in url else "serial",
        }

        # 🔹 ID Кинопоиска
        div_entity = soup.find("div", class_="entity-title-wrap")
        if div_entity and div_entity.has_attr("data-id"):
            data["kp_id"] = div_entity["data-id"]

        # 🔹 Название
        title_span = soup.find("span", class_="js-title", itemprop="name")
        if title_span:
            data["title_name"] = title_span.get_text(strip=True)

        # 🔹 Рейтинги
        kp_rating = soup.find("span", class_="entity-rating-kp", title="КиноПоиск")
        if kp_rating:
            data["rating_kp"] = kp_rating.get_text(strip=True)

        imdb_rating = soup.find("span", class_="entity-rating-imdb", title="IMDb")
        if imdb_rating:
            data["rating_imdb"] = imdb_rating.get_text(strip=True)

        # 🔹 Год
        year_block = soup.find("dt", string=re.compile("Год"))
        if year_block:
            parent_dl = year_block.find_parent("dl")
            if parent_dl:
                digits = re.findall(r"\d{4}", parent_dl.get_text())
                if digits:
                    data["year"] = digits[0]

        # 🔹 Жанры
        genres_dd = soup.find("dd", class_="entity-desc-value js-genres")
        if genres_dd:
            genres = [span.get_text(strip=True) for span in genres_dd.find_all("span", itemprop="genre")]
            data["genres"] = ", ".join(genres)

        # 🔹 Страны
        countries_dd = soup.find("dd", class_="entity-desc-value js-countries")
        if countries_dd:
            countries = [span.get_text(strip=True) for span in countries_dd.find_all("span", class_="entity-desc-link-u")]
            data["country"] = ", ".join(countries)

        # 🔹 Актёры
        actors_dt = soup.find("dt", string=re.compile("Актёры"))
        if actors_dt:
            parent_dl = actors_dt.find_parent("dl")
            if parent_dl:
                spans = parent_dl.find_all("span", itemprop="name")
                actors = [s.get_text(strip=True) for s in spans]
                data["actors"] = ", ".join(actors)

        # 🔹 Время
        for dl in soup.find_all("dl", class_="entity-desc-item-wrap"):
            dt = dl.find("dt", class_="entity-desc-item")
            if dt and "Время" in dt.get_text():
                dd = dl.find("dd", class_="entity-desc-value")
                if dd:
                    text = re.sub(r"[^А-Яа-яЁё0-9 :]", "", dd.get_text(strip=True))
                    data["duration"] = text

        # 🔹 Премьера
        for dl in soup.find_all("dl", class_="entity-desc-item-wrap"):
            dt = dl.find("dt", class_="entity-desc-item")
            if dt and "Премьера" in dt.get_text():
                dd = dl.find("dd", class_="entity-desc-value")
                if dd:
                    text = re.sub(r"[^А-Яа-яЁё0-9 .,:-]", "", dd.get_text(strip=True))
                    data["premiere"] = text

        # 🔹 Описание
        desc_div = soup.find("div", class_="entity-desc-description", itemprop="description")
        if desc_div:
            data["description"] = desc_div.get_text(strip=True)

        # 🔹 Постер
        link_thumb = soup.find("link", itemprop="thumbnail")
        if link_thumb and link_thumb.has_attr("content"):
            data["poster"] = link_thumb["content"]

        # 🔹 Видео
        video_match = re.search(r'<video[^>]+src=["\']([^"\']+\.mp4[^"\']*)["\']', str(soup))
        if video_match:
            data["video"] = video_match.group(1)

        session.close()
        return data

    except Exception as e:
        session.close()
        print(f"❌ Ошибка при парсинге: {e}")
        return None


def update_movie_in_db(data):
    """Обновляет фильм в базе по zona_link"""
    try:
        conn = db_connect()
        with conn.cursor() as cursor:
            sql = """
            UPDATE movies SET
                kp_id=%s, title_name=%s, year=%s, country=%s, genres=%s, actors=%s,
                duration=%s, premiere=%s, description=%s, rating_kp=%s, rating_imdb=%s,
                poster=%s, video=%s, type=%s
            WHERE zona_link=%s
            """
            cursor.execute(sql, (
                data["kp_id"], data["title_name"], data["year"], data["country"], data["genres"],
                data["actors"], data["duration"], data["premiere"], data["description"],
                data["rating_kp"], data["rating_imdb"], data["poster"], data["video"],
                data["type"], data["zona_link"]
            ))
            conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"❌ Ошибка обновления в базе: {e}")
        return False


@app.route("/parse", methods=["GET"])
def parse_route():
    """Основной endpoint — принимает ?url=..."""
    url = request.args.get("url")
    if not url:
        return jsonify({"error": "Не указана ссылка ?url"}), 400

    movie = parse_zona_page(url)
    if not movie:
        return jsonify({"error": "Ошибка при парсинге страницы"}), 500

    success = update_movie_in_db(movie)
    if not success:
        return jsonify({"error": "Ошибка при обновлении базы"}), 500

    return jsonify({"success": True, "title": movie["title_name"], "zona_link": movie["zona_link"]})


@app.route("/")
def index():
    return jsonify({"status": "Zona Parser API работает", "endpoint": "/parse?url=..."})



import os

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

