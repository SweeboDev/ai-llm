import requests
import json

def get_real_world_temp(site_code):
    try:
        with open("location_map.json", "r") as f:
            mapping = json.load(f)
        coords = mapping.get(site_code.upper())
        if not coords:
            return None

        lat = coords["lat"]
        lon = coords["lon"]

        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true"
        response = requests.get(url, timeout=5)
        data = response.json()
        return data["current_weather"]["temperature"]
    except Exception as e:
        print(f"[REAL WEATHER ERROR] {e}")
        return None

def load_sla_for_location(site, building, datahall):
    import json
    with open("sla.json", "r", encoding="utf-8") as f:
        rules = json.load(f)
    for rule in rules:
        if (rule["site"].upper() == site.upper() and
            rule["building"].upper() == building.upper() and
            rule["datahall"].upper() == datahall.upper()):
            return rule
    return None

def check_sla_breaches(data_rows, sla_rule):
    breaches = []

    for row in data_rows:
        # Handle historical vs live shape
        point_name = None
        value = None

        if "Point Name" in row and "readvalue" in row:
            point_name = row["Point Name"].lower()
            value = float(row["readvalue"])
        elif "Primary_Key" in row and "Temperature" in row:
            point_name = "temperature"
            value = float(row["Temperature"])
        elif "Primary_Key" in row and "Humidity" in row:
            point_name = "humidity"
            value = float(row["Humidity"])
        else:
            continue  # Skip invalid rows

        if point_name == "temperature":
            if value < sla_rule["temp_min"] or value > sla_rule["temp_max"]:
                breaches.append({
                    **row,
                    "breach_type": "Temperature",
                    "expected_min": sla_rule["temp_min"],
                    "expected_max": sla_rule["temp_max"]
                })
        elif point_name == "humidity":
            if value < sla_rule["hum_min"] or value > sla_rule["hum_max"]:
                breaches.append({
                    **row,
                    "breach_type": "Humidity",
                    "expected_min": sla_rule["hum_min"],
                    "expected_max": sla_rule["hum_max"]
                })

    return breaches




def get_extremes_near_sla(data_rows, sla_rule):
    temps = []
    hums = []

    for r in data_rows:
        if "Point Name" in r and "readvalue" in r:
            if r["Point Name"].lower() == "temperature":
                temps.append(float(r["readvalue"]))
            elif r["Point Name"].lower() == "humidity":
                hums.append(float(r["readvalue"]))
        elif "Primary_Key" in r:
            key = r["Primary_Key"].lower()
            if "temperature" in key and "Temperature" in r:
                temps.append(float(r["Temperature"]))
            elif "humidity" in key and "Humidity" in r:
                hums.append(float(r["Humidity"]))

    summary = {}

    if temps:
        summary["temp_max_actual"] = round(max(temps), 1)
        summary["temp_min_actual"] = round(min(temps), 1)
        summary["temp_max_sla"] = round(sla_rule["temp_max"], 1)
        summary["temp_min_sla"] = round(sla_rule["temp_min"], 1)

    if hums:
        summary["hum_max_actual"] = round(max(hums), 1)
        summary["hum_min_actual"] = round(min(hums), 1)
        summary["hum_max_sla"] = round(sla_rule["hum_max"], 1)
        summary["hum_min_sla"] = round(sla_rule["hum_min"], 1)

    return summary


