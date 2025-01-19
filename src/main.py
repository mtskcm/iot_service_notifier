from loguru import logger
import paho.mqtt.client as mqtt
import json
import sys
from apprise import Apprise
from paho.mqtt.client import MQTTMessage

THRESHOLDS = {
    "temperature": {"high": 30.0, "low": 0.0},
    "humidity": {"low": 20.0},
    "pressure": {"high": 101325.0, "low": 98000.0},
    "sound": {"high": 70.0},
    "light": {"high": 90.0},
    "rssi": {"low": -70},
}

PUSHSAFER_KEY = "psafer://OO3pYKxoV4r7MVwRAEf1"

def send_notification(title: str, body: str):
    """
    Sends a Pushsafer notification using Apprise.
    """
    apobj = Apprise(debug=True)
    apobj.add(PUSHSAFER_KEY)

    if apobj.notify(title=title, body=body):
        logger.info("Notification successfully sent.")
    else:
        logger.error("Failed to send the notification.")

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
                if "high" in threshold and value > threshold["high"]:
                    logger.warning(f"High {name} detected: {value} {units}")
                    send_notification(
                        title=f"High {name.capitalize()} Alert",
                        body=f"{name.capitalize()} exceeded threshold: {value} {units}"
                    )
                elif "low" in threshold and value < threshold["low"]:
                    logger.warning(f"Low {name} detected: {value} {units}")
                    send_notification(
                        title=f"Low {name.capitalize()} Alert",
                        body=f"{name.capitalize()} fell below threshold: {value} {units}"
                    )
    except json.JSONDecodeError:
        logger.error(f"Failed to decode JSON payload: {msg.payload}")
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")

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
