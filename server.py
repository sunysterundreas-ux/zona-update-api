# --- Патч для совместимости websockets и pyppeteer ---
import sys, types
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

from flask import Flask, request, jsonify
from requests_html import HTMLSession
from bs4 import BeautifulSoup
import pymysql
import re
import time

# ============= НАСТРОЙКИ ==============
DB_HOST = "fernandess.beget.tech"
DB_USER = "fernandess_films"
DB_PASS = "GRG121dx"
DB_NAME = "fernandess_films"
# =====================================

app = Flask(__name__)

# --- Подключение к базе ---
def db_connect():
    return pymysql.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASS,
        database=DB_NAME,
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor
    )


# --- Основная функция парсинга ---
def parse_zona_page(url):
    print(f"\n🔹 Парсим: {url}")
    session = HTMLSession()
    try:
        r = session.get(url)
        r.html.render(timeout=120, sleep=6, keep_page=True, scrolldown=5)
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
            "type": "movie" if "movies" in url else "serial"
        }

        # kp_id
        div_entity = soup.find("div", class_="entity-title-wrap")
        if div_entity and div_entity.has_attr("data-id"):
            data["kp_id"] = div_entity["data-id"]

        # title_name
        title_span = soup.find("span", class_="js-title", itemprop="name")
        if title_span:
            data["title_name"] = title_span.get_text(strip=True)

        # ratings
        kp_rating = soup.find("span", class_="entity-rating-kp", title="КиноПоиск")
        if kp_rating:
            data["rating_kp"] = kp_rating.get_text(strip=True)
        imdb_rating = soup.find("span", class_="entity-rating-imdb", title="IMDb")
        if imdb_rating:
            data["rating_imdb"] = imdb_rating.get_text(strip=True)

        # year
        year_block = soup.find("dt", string=re.compile("Год"))
        if year_block:
            parent_dl = year_block.find_parent("dl")
            if parent_dl:
                digits = re.findall(r"\d{4}", parent_dl.get_text())
                if digits:
                    data["year"] = digits[0]

        # genres
        genres_dd = soup.find("dd", class_="entity-desc-value js-genre")
        if not genres_dd:
            genres_dd = soup.find("dd", class_="entity-desc-value js-genres")
        if genres_dd:
            genres = [span.get_text(strip=True) for span in genres_dd.find_all("span", itemprop="genre")]
            data["genres"] = ", ".join(genres)

        # country
        countries_dd = soup.find("dd", class_="entity-desc-value js-countries")
        if countries_dd:
            countries = [span.get_text(strip=True) for span in countries_dd.find_all("span", class_="entity-desc-link-u")]
            data["country"] = ", ".join(countries)

        # actors
        actors_dt = soup.find("dt", string=re.compile("Актёры"))
        if actors_dt:
            parent_dl = actors_dt.find_parent("dl")
            if parent_dl:
                spans = parent_dl.find_all("span", itemprop="name")
                actors = [s.get_text(strip=True) for s in spans]
                data["actors"] = ", ".join(actors)

        # duration
        for dl in soup.find_all("dl", class_="entity-desc-item-wrap"):
            dt = dl.find("dt", class_="entity-desc-item")
            if dt and "Время" in dt.get_text():
                dd = dl.find("dd", class_="entity-desc-value")
                if dd:
                    text = re.sub(r"[^А-Яа-яЁё0-9 :]", "", dd.get_text(strip=True))
                    data["duration"] = text

        # premiere
        for dl in soup.find_all("dl", class_="entity-desc-item-wrap"):
            dt = dl.find("dt", class_="entity-desc-item")
            if dt and "Премьера" in dt.get_text():
                dd = dl.find("dd", class_="entity-desc-value")
                if dd:
                    text = re.sub(r"[^А-Яа-яЁё0-9 .,:-]", "", dd.get_text(strip=True))
                    data["premiere"] = text

        # description
        desc_div = soup.find("div", class_="entity-desc-description", itemprop="description")
        if desc_div:
            data["description"] = desc_div.get_text(strip=True)

        # poster
        link_thumb = soup.find("link", itemprop="thumbnail")
        if link_thumb and link_thumb.has_attr("content"):
            data["poster"] = link_thumb["content"]

        # video
        video_match = re.search(r'<video[^>]+src=["\']([^"\']+\.mp4[^"\']*)["\']', str(soup))
        if video_match:
            data["video"] = video_match.group(1)

        return data

    except Exception as e:
        print(f"❌ Ошибка при парсинге {url}: {e}")
        return None
    finally:
        session.close()


# --- Сохранение / обновление в базе ---
def save_movie(data):
    conn = db_connect()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM movies WHERE zona_link=%s", (data["zona_link"],))
    exists = cursor.fetchone()

    if exists:
        # обновляем
        sql = """
        UPDATE movies SET
        kp_id=%s, title_name=%s, year=%s, country=%s, genres=%s, actors=%s,
        duration=%s, premiere=%s, description=%s, rating_kp=%s, rating_imdb=%s,
        poster=%s, video=%s, type=%s
        WHERE zona_link=%s
        """
        cursor.execute(sql, (
            data["kp_id"], data["title_name"], data["year"], data["country"],
            data["genres"], data["actors"], data["duration"], data["premiere"],
            data["description"], data["rating_kp"], data["rating_imdb"],
            data["poster"], data["video"], data["type"], data["zona_link"]
        ))
        action = "updated"
    else:
        sql = """
        INSERT INTO movies (kp_id, title_name, year, country, genres, actors, duration,
                            premiere, description, rating_kp, rating_imdb, poster, video,
                            zona_link, type)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """
        cursor.execute(sql, (
            data["kp_id"], data["title_name"], data["year"], data["country"],
            data["genres"], data["actors"], data["duration"], data["premiere"],
            data["description"], data["rating_kp"], data["rating_imdb"],
            data["poster"], data["video"], data["zona_link"], data["type"]
        ))
        action = "inserted"

    conn.commit()
    cursor.close()
    conn.close()
    return action


# --- Flask endpoint ---
@app.route("/parse", methods=["GET"])
def parse_from_php():
    url = request.args.get("url")
    if not url:
        return jsonify({"error": "Не указана ссылка (url)"}), 400

    data = parse_zona_page(url)
    if not data:
        return jsonify({"error": "Ошибка при парсинге страницы"}), 500

    result = save_movie(data)
    return jsonify({"success": True, "action": result, "title": data["title_name"]})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
