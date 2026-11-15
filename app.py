import os
import csv
import io

import requests
from flask import Flask, render_template, request, send_file
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

app.config["UPLOAD_FOLDER"] = os.path.join("static", "uploads")
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024

os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

NASA_MAP_KEY = os.getenv("NASA_MAP_KEY")

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}


def allowed_file(filename):
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS
    )


def get_nasa_records():
    if not NASA_MAP_KEY:
        raise ValueError("NASA MAP_KEY is missing. Check your .env file.")

    area = "54,5.5,102,40"
    source = "VIIRS_NOAA20_NRT"
    days = "5"

    url = (
        "https://firms.modaps.eosdis.nasa.gov/api/area/csv/"
        f"{NASA_MAP_KEY}/{source}/{area}/{days}"
    )

    response = requests.get(url, timeout=30)
    response.raise_for_status()

    reader = csv.DictReader(io.StringIO(response.text))

    if not reader.fieldnames or "latitude" not in reader.fieldnames:
        raise ValueError("NASA returned an unexpected response.")

    return list(reader), reader.fieldnames


def filter_records(records, region, selected_date, confidence, search):
    if region == "tamilnadu":
        filtered = []

        for item in records:
            try:
                lat = float(item["latitude"])
                lon = float(item["longitude"])

                if 8.0 <= lat <= 13.6 and 76.0 <= lon <= 80.5:
                    filtered.append(item)

            except (KeyError, TypeError, ValueError):
                continue

        records = filtered

    if selected_date:
        records = [
            item for item in records
            if item.get("acq_date") == selected_date
        ]

    if confidence in ["H", "N", "L"]:
        records = [
            item for item in records
            if str(item.get("confidence", "")).upper() == confidence
        ]

    if search:
        search = search.lower()

        records = [
            item for item in records
            if search in str(item.get("latitude", "")).lower()
            or search in str(item.get("longitude", "")).lower()
            or search in str(item.get("acq_date", "")).lower()
            or search in str(item.get("confidence", "")).lower()
        ]

    return records


@app.route("/", methods=["GET", "POST"])
def home():
    image_url = None
    message = None
    location = ""

    if request.method == "POST":
        location = request.form.get("location", "").strip()
        image = request.files.get("satellite_image")

        if not image or image.filename == "":
            message = "Please select an image."

        elif not allowed_file(image.filename):
            message = "Please upload JPG, JPEG, PNG or WEBP."

        else:
            filename = secure_filename(image.filename)
            image_path = os.path.join(
                app.config["UPLOAD_FOLDER"], filename
            )

            image.save(image_path)
            image_url = "/" + image_path.replace("\\", "/")

            message = (
                "Image received successfully! "
                "Automatic fire detection is not enabled yet."
            )

    return render_template(
        "index.html",
        image_url=image_url,
        message=message,
        location=location
    )


@app.route("/hotspots")
def hotspots():
    region = request.args.get("region", "india").lower()
    selected_date = request.args.get("date", "").strip()
    confidence = request.args.get("confidence", "all").upper()
    search = request.args.get("search", "").strip()

    if region not in ["india", "tamilnadu"]:
        region = "india"

    if confidence not in ["ALL", "H", "N", "L"]:
        confidence = "ALL"

    total_count = 0
    high_count = 0
    nominal_count = 0
    low_count = 0
    records = []
    error = None

    try:
        all_records, fieldnames = get_nasa_records()

        region_records = filter_records(
            all_records, region, selected_date, "ALL", ""
        )

        for item in region_records:
            value = str(item.get("confidence", "")).upper()

            if value == "H":
                high_count += 1
            elif value == "N":
                nominal_count += 1
            elif value == "L":
                low_count += 1

        records = filter_records(
            all_records,
            region,
            selected_date,
            confidence,
            search
        )

        total_count = len(records)

    except requests.RequestException:
        error = "Could not connect to NASA FIRMS. Please try again later."

    except (ValueError, csv.Error):
        error = "NASA data response could not be read. Check your .env file."

    return render_template(
        "hotspots.html",
        hotspots=records,
        total_count=total_count,
        high_count=high_count,
        nominal_count=nominal_count,
        low_count=low_count,
        selected_date=selected_date,
        selected_region=region,
        selected_confidence=confidence,
        search=search,
        error=error
    )


@app.route("/download-report")
def download_report():
    region = request.args.get("region", "india").lower()
    selected_date = request.args.get("date", "").strip()
    confidence = request.args.get("confidence", "ALL").upper()
    search = request.args.get("search", "").strip()

    try:
        records, fieldnames = get_nasa_records()

        records = filter_records(
            records,
            region,
            selected_date,
            confidence,
            search
        )

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=fieldnames)

        writer.writeheader()
        writer.writerows(records)

        file_data = io.BytesIO(output.getvalue().encode("utf-8"))
        file_data.seek(0)

        return send_file(
            file_data,
            mimetype="text/csv",
            as_attachment=True,
            download_name="FireWatch_Hotspot_Report.csv"
        )

    except (requests.RequestException, ValueError, csv.Error):
        return "Unable to generate the hotspot report.", 500


@app.errorhandler(413)
def file_too_large(error):
    return "Image is too large. Maximum size is 10 MB.", 413


if __name__ == "__main__":
    app.run(debug=True)