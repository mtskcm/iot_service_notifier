from loguru import logger
import paho.mqtt.client as mqtt
import json
from datetime import datetime
from apprise import Apprise
from paho.mqtt.client import MQTTMessage
from models import Settings, Notification
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS

settings = Settings()

# Thresholds pre inteligentne notifikacie
THRESHOLDS = {
    "temperature": {"high": 30.0, "low": 15.0, "trend_threshold": 10.0},
    "humidity": {"low": 20.0, "high": 60.0, "trend_threshold": 20.0},
    "pressure": {"high": 101325.0, "low": 98000.0, "trend_threshold": 2000.0},
    "sound": {"high": 70.0, "trend_threshold": 40.0},
    "light": {"high": 90.0, "trend_threshold": 30.0},
    "rssi": {"low": -70},
}
# Inicializácia klienta
influx_client = InfluxDBClient(
    url=settings.influxdb_url, token=settings.influxdb_token, org=settings.influxdb_org
)
write_api = influx_client.write_api(write_options=SYNCHRONOUS)

def save_to_influx(metric_name, value, unit, timestamp):
    try:
        point = Point(metric_name).field("value", value).field("unit", unit).time(timestamp)
        write_api.write(bucket=settings.influxdb_bucket, org=settings.influxdb_org, record=point)
        logger.info(f"Saved {metric_name} to InfluxDB: {value} {unit} at {timestamp}")
    except Exception as e:
        logger.error(f"Error saving to InfluxDB: {e}")

def calculate_sleep_conditions():
    try:
        query = f"""
        from(bucket: "{settings.influxdb_bucket}")
          |> range(start: -24h)
          |> filter(fn: (r) => r._field == "value")
        """
        result = influx_client.query_api().query(query, org=settings.influxdb_org)
        data = {}

        # zoradenie dat podla metriky
        for table in result:
            for record in table.records:
                metric = record.get_measurement()
                value = record.get_value()
                if metric not in data:
                    data[metric] = []
                data[metric].append(value)

        insights = {}

        # analyza metrik
        for metric, values in data.items():
            average = sum(values) / len(values)
            above_threshold = sum(1 for v in values if v > THRESHOLDS[metric].get("high", float('inf')))
            below_threshold = sum(1 for v in values if v < THRESHOLDS[metric].get("low", float('-inf')))

            insights[metric] = {
                "average": average,
                "above_threshold": above_threshold,
                "below_threshold": below_threshold,
            }

            logger.info(f"{metric.capitalize()} - Average: {average}, Above Threshold: {above_threshold}, Below Threshold: {below_threshold}")

        return insights

    except Exception as e:
        logger.error(f"Error calculating sleep conditions: {e}")
        return {}

def calculate_environment_quality_index():

    try:
        conditions = calculate_sleep_conditions()
        if not conditions:
            return None

        # vahy pre kazdu metriku
        weights = {
            "temperature": 0.3,
            "humidity": 0.1,
            "light": 0.3,
            "sound": 0.3,
        }

        # vypocet indexu kvality
        quality_index = 0
        for metric, weight in weights.items():
            if metric in conditions:
                average = conditions[metric]["average"]
                if metric in THRESHOLDS:
                    high = THRESHOLDS[metric].get("high", float('inf'))
                    low = THRESHOLDS[metric].get("low", float('-inf'))
                    deviation = max(0, average - high) + max(0, low - average)
                    quality_index += deviation * weight

        logger.info(f"Environment Quality Index: {quality_index}")
        return quality_index

    except Exception as e:
        logger.error(f"Error calculating environment quality index: {e}")
        return None

def generate_sleep_report():

    try:
        conditions = calculate_sleep_conditions()
        quality_index = calculate_environment_quality_index()

        if conditions and quality_index is not None:
            report = "Sleep Environment Report:\n"
            for metric, data in conditions.items():
                report += (
                    f"- {metric.capitalize()}:\n"
                    f"  - Average: {data['average']:.2f}\n"
                    f"  - Above Threshold: {data['above_threshold']} times\n"
                    f"  - Below Threshold: {data['below_threshold']} times\n"
                )
            report += f"\nOverall Quality Index: {quality_index:.2f} (Lower is better)\n"
            logger.info(report)
            send_notification("Sleep Environment Report", report)

    except Exception as e:
        logger.error(f"Error generating sleep report: {e}")

def analyze_trends(metric_name, time_interval="6h"):
    """
    Analyze trends for a specific metric by checking the difference between the oldest
    and newest values in a given time range.
    """
    query = f"""
    from(bucket: "{settings.influxdb_bucket}")
      |> range(start: -{time_interval})
      |> filter(fn: (r) => r._measurement == "{metric_name}")
      |> filter(fn: (r) => r._field == "value")
    """
    try:
        result = influx_client.query_api().query(query, org=settings.influxdb_org)
        values = [record.get_value() for table in result for record in table.records]

        if len(values) < 2:
            logger.info(f"Not enough data points for trend analysis of {metric_name}.")
            return 0  # No trend can be calculated

        # Calculate the trend as the difference between the newest and oldest values
        trend = values[-1] - values[0]
        logger.info(f"Trend for {metric_name}: {trend}")
        return trend
    except Exception as e:
        logger.error(f"Error during trend analysis for {metric_name}: {e}")
        return 0

def send_notification(title: str, body: str):

    apobj = Apprise(debug=True)
    apobj.add(settings.pushsafer_key)

    if apobj.notify(title=title, body=body):
        logger.info(f"Notification successfully sent: {title}")
    else:
        logger.error(f"Failed to send the notification: {title}")

def handle_sensor_data(client: mqtt.Client, userdata, msg: MQTTMessage):

    try:
        data = json.loads(msg.payload.decode("utf-8"))
        logger.info(f"Received sensor data: {data}")

        # samostatne spracovanie statusu
        if "status" in data:
            logger.info(f"Received status update: {data['status']}")
            return

        # validacia timestampu
        timestamp = data.get("dt")
        if not timestamp:
            logger.error("Missing 'dt' in sensor data payload.")
            return

        # koverzia timestampu na datetime
        dt_object = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))

        # kontrola ci je 0800 casu
        if dt_object.hour == 0 and dt_object.minute == 8:
            generate_sleep_report()

        # kontrola hranicnyhc hodnot
        for metric in data.get("metrics", []):
            name = metric["name"]
            value = metric["value"]
            units = metric.get("units", "unknown")

            save_to_influx(name, value, units, timestamp)

            # analyza trendu
            trend = analyze_trends(name)
            if abs(trend) > THRESHOLDS.get(name, {}).get("trend_threshold", 5):
                send_notification(
                    f"{name.capitalize()} Trend Alert",
                    f"A significant trend was detected in {name}: {trend} {units}.",
                )

            # posielanie notifikacii na zaklade hranicnych hodnot
            thresholds = THRESHOLDS.get(name, {})
            if "high" in thresholds and value > thresholds["high"]:
                send_notification(
                    f"{name.capitalize()} High Alert",
                    f"The {name} value is too high: {value} {units} (Threshold: {thresholds['high']}).",
                )
            elif "low" in thresholds and value < thresholds["low"]:
                send_notification(
                    f"{name.capitalize()} Low Alert",
                    f"The {name} value is too low: {value} {units} (Threshold: {thresholds['low']}).",
                )

    except json.JSONDecodeError:
        logger.error(f"Failed to decode JSON payload: {msg.payload}")
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")

def get_alert_message(name: str, value: float, units: str, level: str) -> str:

    messages = {
        "temperature": {
            "high": f"The temperature is {value} {units}, exceeding the threshold. Ensure proper ventilation or cooling to maintain comfort and avoid overheating.",
            "low": f"The temperature is {value} {units}, below the threshold. Consider using a heater or wearing warm clothing.",
        },
        "humidity": {
            "high": f"Humidity has risen to {value} {units}. High humidity may cause discomfort. Consider using a dehumidifier.",
            "low": f"Humidity has dropped to {value} {units}. Dry air may cause skin or respiratory discomfort. Use a humidifier or increase ventilation.",
        },
        "pressure": {
            "high": f"Atmospheric pressure is {value} {units}, exceeding the normal range. Ensure ventilation in enclosed spaces.",
            "low": f"Atmospheric pressure is {value} {units}. This may indicate stormy weather. Stay updated on weather forecasts.",
        },
        "sound": {
            "high": f"High sound levels detected: {value} {units}. Prolonged exposure may cause discomfort. Consider reducing noise for a calmer environment.",
        },
        "light": {
            "high": f"Intense light levels detected: {value} {units}. Consider reducing light exposure, especially during nighttime, for better sleep quality.",
        },
        "rssi": {
            "low": f"Signal strength is weak: {value} {units}. Consider checking your network connection or moving closer to the Wi-Fi router.",
        },
    }

    return messages.get(name, {}).get(level, f"{name.capitalize()} is at {value} {units}.")

def on_connect(client: mqtt.Client, userdata, flags, reason_code, properties):
    logger.debug(f"Connected with result code {reason_code}")

    # subscribe na vsetky topics dynamicky
    topic = f"{settings.base_topic}+/zen-e6614103e7698839/#"
    client.subscribe(topic)
    client.message_callback_add(topic, handle_sensor_data)
    logger.info(f"Subscribed to topic: {topic}")

    # publish online status
    client.publish(
        settings.status_topic,
        json.dumps({"status": "online"}),
        qos=1,
        retain=True,
    )
    logger.info(f"Published online status to {settings.status_topic}.")

def on_disconnect(client: mqtt.Client, userdata, reason_code):
    logger.info(f"Disconnected with reason code {reason_code}")

def main():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

    # set last will
    client.will_set(
        settings.status_topic,
        json.dumps({"status": "offline"}),
        qos=1,
        retain=True,
    )

    # set MQTT credentials
    client.username_pw_set(settings.user, settings.password)
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect

    # pripojenie na broker
    client.connect(settings.broker, settings.port, 60)

    logger.info("Waiting for messages...")
    client.loop_forever()

if __name__ == "__main__":
    main()
