import os
from flask import Flask, render_template, request
import requests
from datetime import datetime, timedelta

app = Flask(__name__)

API_KEY = os.environ.get("API_KEY")


def get_coordinates(location):
    """
    Australia-only location lookup.
    Supports:
    - Australian place/suburb/city names, e.g. Sydney, Bondi Beach, Parramatta
    - Australian postcodes, e.g. 2000, 2134, 3000
    """
    cleaned = location.strip()

    if not cleaned:
        return None

    # If input is a 4-digit Australian postcode, use ZIP endpoint
    if cleaned.isdigit() and len(cleaned) == 4:
        zip_url = "https://api.openweathermap.org/data/2.5/weather"
        params = {
            "zip": f"{cleaned},AU",
            "appid": API_KEY,
            "units": "metric"
        }

        response = requests.get(zip_url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        # Weather endpoint returns coordinates directly
        if str(data.get("cod")) != "200":
            return None

        return {
            "name": data.get("name", cleaned),
            "lat": data["coord"]["lat"],
            "lon": data["coord"]["lon"],
            "country": data.get("sys", {}).get("country", "AU"),
            "state": ""
        }

    # Otherwise treat input as Australian place/suburb/city name
    geo_url = "http://api.openweathermap.org/geo/1.0/direct"

    queries = [
        f"{cleaned},AU",
        cleaned
    ]

    for query in queries:
        params = {
            "q": query,
            "limit": 5,
            "appid": API_KEY
        }

        response = requests.get(geo_url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        if data:
            # Prefer Australian result only
            for item in data:
                if item.get("country") == "AU":
                    return {
                        "name": item.get("name", cleaned),
                        "lat": item["lat"],
                        "lon": item["lon"],
                        "country": item.get("country", "AU"),
                        "state": item.get("state", "")
                    }

    return None


def get_weather_data(lat, lon):
    current_url = "https://api.openweathermap.org/data/2.5/weather"
    forecast_url = "https://api.openweathermap.org/data/2.5/forecast"

    current_params = {
        "lat": lat,
        "lon": lon,
        "appid": API_KEY,
        "units": "metric"
    }

    forecast_params = {
        "lat": lat,
        "lon": lon,
        "appid": API_KEY,
        "units": "metric"
    }

    current_response = requests.get(current_url, params=current_params, timeout=10)
    forecast_response = requests.get(forecast_url, params=forecast_params, timeout=10)

    current_response.raise_for_status()
    forecast_response.raise_for_status()

    return current_response.json(), forecast_response.json()


def calculate_time_windows(sunrise_dt, sunset_dt):
    golden_morning_start = sunrise_dt
    golden_morning_end = sunrise_dt + timedelta(hours=1)

    blue_morning_start = sunrise_dt - timedelta(minutes=30)
    blue_morning_end = sunrise_dt

    golden_evening_start = sunset_dt - timedelta(hours=1)
    golden_evening_end = sunset_dt

    blue_evening_start = sunset_dt
    blue_evening_end = sunset_dt + timedelta(minutes=30)

    return {
        "golden_morning": (golden_morning_start, golden_morning_end),
        "blue_morning": (blue_morning_start, blue_morning_end),
        "golden_evening": (golden_evening_start, golden_evening_end),
        "blue_evening": (blue_evening_start, blue_evening_end),
    }


def score_forecast_item(item, sunrise_dt, sunset_dt, timezone_offset):
    score = 50
    reasons = []

    forecast_time = datetime.utcfromtimestamp(item["dt"] + timezone_offset)
    cloud = item["clouds"]["all"]
    wind = item["wind"]["speed"]
    rain = 0

    if "rain" in item and "3h" in item["rain"]:
        rain = item["rain"]["3h"]

    main_condition = item["weather"][0]["main"].lower()

    if abs((forecast_time - sunrise_dt).total_seconds()) <= 7200:
        score += 15
        reasons.append("close to sunrise lighting")

    if abs((forecast_time - sunset_dt).total_seconds()) <= 7200:
        score += 20
        reasons.append("close to sunset lighting")

    if 20 <= cloud <= 60:
        score += 20
        reasons.append("moderate cloud cover creates softer light")
    elif cloud < 20:
        score += 8
        reasons.append("clear sky provides bright conditions")
    elif 61 <= cloud <= 85:
        score += 5
        reasons.append("cloud cover is usable but less ideal")
    else:
        score -= 10
        reasons.append("heavy cloud cover reduces light quality")

    if wind < 4:
        score += 15
        reasons.append("low wind is good for outdoor shoots")
    elif 4 <= wind <= 8:
        score += 5
        reasons.append("wind is manageable")
    else:
        score -= 15
        reasons.append("high wind may affect comfort and image quality")

    if rain == 0:
        score += 10
        reasons.append("no rain expected")
    elif 0 < rain <= 0.5:
        score -= 5
        reasons.append("slight rain risk")
    else:
        score -= 25
        reasons.append("rain makes outdoor photography unsuitable")

    if main_condition == "thunderstorm":
        score -= 30
        reasons.append("storm conditions are unsafe")
    elif main_condition == "snow":
        score -= 10
        reasons.append("snow reduces practicality for most shoots")
    elif main_condition in ["mist", "fog", "haze"]:
        score -= 5
        reasons.append("visibility may be reduced")

    score = max(0, min(100, score))

    if score >= 85:
        rating = "Excellent"
    elif score >= 70:
        rating = "Good"
    elif score >= 55:
        rating = "Acceptable"
    elif score >= 40:
        rating = "Poor"
    else:
        rating = "Unsuitable"

    explanation = ". ".join(reasons[:4]).capitalize() + "."

    return {
        "time": forecast_time.strftime("%I:%M %p"),
        "datetime_obj": forecast_time,
        "temp": item["main"]["temp"],
        "condition": item["weather"][0]["description"].title(),
        "cloud": cloud,
        "wind": wind,
        "score": score,
        "rating": rating,
        "explanation": explanation
    }


def build_photography_report(current_data, forecast_data):
    city_name = current_data.get("name", "Unknown location")
    country = current_data.get("sys", {}).get("country", "AU")

    timezone_offset = current_data.get("timezone", 0)

    local_current_dt = datetime.utcfromtimestamp(current_data["dt"] + timezone_offset)
    sunrise_dt = datetime.utcfromtimestamp(current_data["sys"]["sunrise"] + timezone_offset)
    sunset_dt = datetime.utcfromtimestamp(current_data["sys"]["sunset"] + timezone_offset)

    if sunrise_dt <= local_current_dt <= sunset_dt:
        theme = current_data["weather"][0]["main"].lower()
    else:
        theme = "night"

    windows = calculate_time_windows(sunrise_dt, sunset_dt)

    scored_forecasts = []
    for item in forecast_data["list"][:8]:
        scored_forecasts.append(
            score_forecast_item(item, sunrise_dt, sunset_dt, timezone_offset)
        )

    best_slots = sorted(scored_forecasts, key=lambda x: x["score"], reverse=True)[:3]
    overall_score = round(sum(item["score"] for item in scored_forecasts) / len(scored_forecasts))

    if overall_score >= 85:
        overall_rating = "Excellent"
        summary = "Excellent conditions for outdoor photography."
    elif overall_score >= 70:
        overall_rating = "Good"
        summary = "Good conditions with strong potential for quality outdoor sessions."
    elif overall_score >= 55:
        overall_rating = "Acceptable"
        summary = "Conditions are acceptable, but timing should be chosen carefully."
    elif overall_score >= 40:
        overall_rating = "Poor"
        summary = "Conditions are below ideal for outdoor photography."
    else:
        overall_rating = "Unsuitable"
        summary = "Outdoor photography is not recommended."

    best_reason = best_slots[0]["explanation"] if best_slots else "No forecast explanation available."

    report = {
        "location_label": f"{city_name}, {country}",
        "current_temp": current_data["main"]["temp"],
        "current_condition": current_data["weather"][0]["description"].title(),
        "current_humidity": current_data["main"]["humidity"],
        "current_wind": current_data["wind"]["speed"],
        "sunrise": sunrise_dt.strftime("%I:%M %p"),
        "sunset": sunset_dt.strftime("%I:%M %p"),
        "overall_score": overall_score,
        "overall_rating": overall_rating,
        "summary": summary,
        "why": best_reason,
        "best_slots": best_slots,
        "forecast_items": scored_forecasts,
        "golden_morning": f"{windows['golden_morning'][0].strftime('%I:%M %p')} - {windows['golden_morning'][1].strftime('%I:%M %p')}",
        "blue_morning": f"{windows['blue_morning'][0].strftime('%I:%M %p')} - {windows['blue_morning'][1].strftime('%I:%M %p')}",
        "golden_evening": f"{windows['golden_evening'][0].strftime('%I:%M %p')} - {windows['golden_evening'][1].strftime('%I:%M %p')}",
        "blue_evening": f"{windows['blue_evening'][0].strftime('%I:%M %p')} - {windows['blue_evening'][1].strftime('%I:%M %p')}",
        "theme": theme
    }

    return report


@app.route("/", methods=["GET", "POST"])
def home():
    report = None
    error = None
    location = ""

    if request.method == "POST":
        location = request.form.get("location", "").strip()

        if not location:
            error = "Please enter an Australian suburb, city, or postcode."
        else:
            try:
                coords = get_coordinates(location)

                if not coords:
                    error = "Australian location not found. Please enter a suburb, city, or 4-digit postcode."
                else:
                    current_data, forecast_data = get_weather_data(coords["lat"], coords["lon"])
                    report = build_photography_report(current_data, forecast_data)

            except requests.exceptions.RequestException:
                error = "Could not connect to the weather service. Please try again later."
            except KeyError:
                error = "Weather data was incomplete. Please try another Australian location."
            except Exception:
                error = "Something went wrong. Please check your API key and try again."

    return render_template("index.html", report=report, error=error, location=location)


if __name__ == "__main__":
    app.run(debug=True)
