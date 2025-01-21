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

# Thresholds for intelligent alerts
THRESHOLDS = {
    "temperature": {"high": 30.0, "low": 15.0},
    "humidity": {"low": 20.0, "high": 60.0},
    "pressure": {"high": 101325.0, "low": 98000.0},
    "sound": {"high": 70.0},
    "light": {"high": 90.0},
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
    """
    Analyzes sleep conditions based on stored data in InfluxDB.
    """
    try:
        query = f"""
        from(bucket: "{settings.influxdb_bucket}")
          |> range(start: -24h)
          |> filter(fn: (r) => r._field == "value")
        """
        result = influx_client.query_api().query(query, org=settings.influxdb_org)
        data = {}

        # Organize data by metric
        for table in result:
            for record in table.records:
                metric = record.get_measurement()
                value = record.get_value()
                if metric not in data:
                    data[metric] = []
                data[metric].append(value)

        insights = {}

        # Analyze metrics
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
    """
    Calculates an index for sleep environment quality based on temperature, humidity, light, and sound.
    """
    try:
        conditions = calculate_sleep_conditions()
        if not conditions:
            return None

        # Weight factors for each metric
        weights = {
            "temperature": 0.3,
            "humidity": 0.3,
            "light": 0.2,
            "sound": 0.2,
        }

        # Calculate quality index
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
    """
    Generates a detailed sleep report based on historical data.
    """
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
            return 0  # Not enough data for trend analysis

        trend = values[-1] - values[0]
        logger.info(f"Trend for {metric_name}: {trend}")
        return trend
    except Exception as e:
        logger.error(f"Error in analyze_trends query: {e}")
        return 0

def send_notification(title: str, body: str):
    """
    Sends a Pushsafer notification using Apprise.
    """
    apobj = Apprise(debug=True)
    apobj.add(settings.pushsafer_key)

    if apobj.notify(title=title, body=body):
        logger.info(f"Notification successfully sent: {title}")
    else:
        logger.error(f"Failed to send the notification: {title}")

def handle_sensor_data(client: mqtt.Client, userdata, msg: MQTTMessage):
    """
    Handles sensor data received from topics.
    """
    try:
        data = json.loads(msg.payload.decode("utf-8"))
        logger.info(f"Received sensor data: {data}")

        # Handle "status" messages separately
        if "status" in data:
            logger.info(f"Received status update: {data['status']}")
            return

        # Validate timestamp
        timestamp = data.get("dt")
        if not timestamp:
            logger.error("Missing 'dt' in sensor data payload.")
            return

        # Convert timestamp to datetime object
        dt_object = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))

        # Check if the time is midnight
        if dt_object.hour == 0 and dt_object.minute == 0:
            generate_sleep_report()

        # Iterate through metrics and check thresholds
        for metric in data.get("metrics", []):
            name = metric["name"]
            value = metric["value"]
            units = metric.get("units", "unknown")

            # Save to InfluxDB
            save_to_influx(name, value, units, timestamp)

            # Analyze trends
            trend = analyze_trends(name, time_interval="6h")
            if abs(trend) > 5:
                alert_message = f"Significant trend detected for {name}: {trend} {units}/hour"
                send_notification(title=f"{name.capitalize()} Alert", body=alert_message)

            # Check thresholds and send notifications
            if name in THRESHOLDS:
                threshold = THRESHOLDS[name]
                alert_message = None

                if "high" in threshold and value > threshold["high"]:
                    logger.warning(f"High {name} detected: {value} {units}")
                    alert_message = get_alert_message(name, value, units, "high")

                elif "low" in threshold and value < threshold["low"]:
                    logger.warning(f"Low {name} detected: {value} {units}")
                    alert_message = get_alert_message(name, value, units, "low")

                if alert_message:
                    send_notification(
                        title=f"{name.capitalize()} Alert",
                        body=alert_message
                    )

    except json.JSONDecodeError:
        logger.error(f"Failed to decode JSON payload: {msg.payload}")
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")

def analyze_trend(data):
    """
    Analyzes the trend of historical data.
    :param data: List of historical data points.
    :return: Trend direction (positive/negative).
    """
    if len(data) < 2:
        return 0
    return data[-1]["value"] - data[0]["value"]

def predict_future_value(current_value, trend, time_interval=1):
    """
    Predicts a future value based on the current value and trend.
    :param current_value: Current value of the metric.
    :param trend: Trend direction (positive/negative).
    :param time_interval: Time interval for prediction (in hours).
    :return: Predicted value.
    """
    return current_value + trend * time_interval

def get_alert_message(name: str, value: float, units: str, level: str) -> str:
    """
    Generates a detailed alert message with added value.
    """
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

    # Subscribe to all sensor data topics
    topic = f"{settings.base_topic}+/zen-e6614103e7698839/#"
    client.subscribe(topic)
    client.message_callback_add(topic, handle_sensor_data)
    logger.info(f"Subscribed to topic: {topic}")

    # Publish "online" status to the status topic
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

    # Set Last Will and Testament (LWT) for status topic
    client.will_set(
        settings.status_topic,
        json.dumps({"status": "offline"}),
        qos=1,
        retain=True,
    )

    # Set MQTT credentials
    client.username_pw_set(settings.user, settings.password)
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect

    # Connect to the broker
    client.connect(settings.broker, settings.port, 60)

    logger.info("Waiting for messages...")
    client.loop_forever()

if __name__ == "__main__":
    main()
