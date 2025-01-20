from loguru import logger
import paho.mqtt.client as mqtt
import json
import sys
from apprise import Apprise
from paho.mqtt.client import MQTTMessage

# Thresholds for intelligent alerts
THRESHOLDS = {
    "temperature": {"high": 30.0, "low": 15.0},
    "humidity": {"low": 20.0, "high": 60.0},
    "pressure": {"high": 101325.0, "low": 98000.0},
    "sound": {"high": 70.0},
    "light": {"high": 90.0},
    "rssi": {"low": -70},
}

# Pushsafer private key
PUSHSAFER_KEY = "psafer://OO3pYKxoV4r7MVwRAEf1"

def send_notification(title: str, body: str):
    """
    Sends a Pushsafer notification using Apprise.
    """
    apobj = Apprise(debug=True)
    apobj.add(PUSHSAFER_KEY)

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

        # Iterate through metrics and check thresholds
        for metric in data.get("metrics", []):
            name = metric["name"]
            value = metric["value"]
            units = metric["units"]

            if name in THRESHOLDS:
                threshold = THRESHOLDS[name]
                alert_message = None

                # High threshold check
                if "high" in threshold and value > threshold["high"]:
                    logger.warning(f"High {name} detected: {value} {units}")
                    alert_message = get_alert_message(name, value, units, "high")

                # Low threshold check
                elif "low" in threshold and value < threshold["low"]:
                    logger.warning(f"Low {name} detected: {value} {units}")
                    alert_message = get_alert_message(name, value, units, "low")

                # Send notification if an alert is triggered
                if alert_message:
                    send_notification(
                        title=f"{name.capitalize()} Alert",
                        body=alert_message
                    )

    except json.JSONDecodeError:
        logger.error(f"Failed to decode JSON payload: {msg.payload}")
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")

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

def handle_command(client: mqtt.Client, userdata, msg: MQTTMessage):
    """
    Handles commands received on the topic services/notifier/mk137vq/cmd.
    """
    try:
        command = json.loads(msg.payload.decode("utf-8"))
        logger.info(f"Received command: {command}")

        if command.get("cmd") == "shutdown":
            logger.info("Shutting down the service as requested.")
            client.publish(
                "services/notifier/mk137vq/status",
                json.dumps({"status": "offline"}),
                qos=1,
                retain=True,
            )
            client.disconnect()
            client.loop_stop()
            logger.info("Client disconnected and loop stopped. Exiting now.")
            sys.exit(0)
        else:
            logger.warning(f"Unknown command received: {command}")

    except json.JSONDecodeError:
        logger.error(f"Failed to decode JSON payload: {msg.payload}")
    except Exception as e:
        logger.error(f"An error occurred while handling the command: {e}")

def on_connect(client: mqtt.Client, userdata, flags, reason_code, properties):
    logger.debug(f"Connected with result code {reason_code}")

    # Subscribe to sensor data topics and command topics
    client.subscribe("gateway/+/+/#")  # Subscribes to all sensor topics dynamically
    client.message_callback_add("gateway/+/+/#", handle_sensor_data)

    client.subscribe("services/notifier/mk137vq/cmd")
    client.message_callback_add("services/notifier/mk137vq/cmd", handle_command)

    # Publish status "online"
    client.publish(
        "services/notifier/mk137vq/status",
        json.dumps({"status": "online"}),
        qos=1,
        retain=True,
    )
    logger.info(
        "Subscribed to topics: gateway/+/+/#, services/notifier/mk137vq/cmd"
    )

def on_disconnect(client: mqtt.Client, userdata, reason_code):
    logger.info(f"Disconnected with reason code {reason_code}")

def main():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

    # Set Last Will and Testament (LWT) for status topic
    client.will_set(
        "services/notifier/mk137vq/status",
        json.dumps({"status": "offline"}),
        qos=1,
        retain=True,
    )

    # MQTT credentials
    client.username_pw_set("maker", "mother.mqtt.password")
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect

    # Connect to the broker
    client.connect("147.232.205.176", 1883, 60)

    logger.info("Waiting for messages...")
    client.loop_forever()


if __name__ == "__main__":
    main()
