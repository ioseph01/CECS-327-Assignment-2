import socket
import sys
import time
import random
import json
import os


# Load Config
def _load_sensor_config():
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    try:
        with open(config_path) as f:
            cfg = json.load(f)
            return cfg["client"]["server_host"], cfg["ports"]["sensor"]
    except Exception:
        return "127.0.0.1", 9002

DEFAULT_HOST, DEFAULT_PORT = _load_sensor_config()


# Creates a TCP connection to the server's sensory port
def connect(host, port):
    sock = socket.create_connection((host, port), timeout=5)
    print(f"Connected to sensor port {host}:{port}")
    return sock

# Sends sensor update command to the server
def send_update(sock, lot_id, delta):
    msg = f"UPDATE {lot_id} {delta:+d}\n"
    sock.sendall(msg.encode("utf-8"))
    response = sock.makefile("rb").readline().decode().strip()
    return response

# Runs a simulation of parking sensors
def monitor(host, port, interval=1.5):
    sock = connect(host, port)
    lots = ["A", "B", "C"]
    print(f"Sending random updates every {interval}s.  Ctrl+C to stop.\n")
    try:
        while True:
            lot_id = random.choice(lots)
            delta  = random.choices([+1, -1], weights=[50, 50])[0]
            response = send_update(sock, lot_id, delta)
            print(f"UPDATE {lot_id} {delta:+d} -> server: {response}")
            time.sleep(interval)
    except KeyboardInterrupt:
        pass

    sock.close()
    print("\nDisconnected.")


if __name__ == "__main__":
    args = sys.argv[1:]
    host = DEFAULT_HOST
    port = DEFAULT_PORT
    monitor(host, port)