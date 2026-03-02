import sys
import threading
import json
import os
from client_stub import ParkingClient, RpcError, RpcTimeoutError

""" CONFIGS """

def _load_client_config():
    cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    try:
        with open(cfg_path) as f:
            cfg = json.load(f)
            return cfg["client"]["server_host"], cfg["ports"]["rpc"]
    except Exception:
        return "127.0.0.1", 9001


print_lock = threading.Lock()

def on_event(event_str):
    parts = event_str.split()
    if len(parts) >= 3:
        lot_id = parts[1]
        free   = parts[2]
        ts     = parts[3] if len(parts) > 3 else ""
        with print_lock:
            print(f"\r  [LIVE] Lot {lot_id} → {free} free  ({ts[:19]})")
            print("parking> ", end="", flush=True)


def print_lots(lots):
    print(f"\n  {'Lot':<6} {'Capacity':>10} {'Occupied':>10} {'Reserved':>10} {'Free':>6}")
    print(f"  {'─'*6} {'─'*10} {'─'*10} {'─'*10} {'─'*6}")
    for lot in lots:
        reserved = lot['capacity'] - lot['occupied'] - lot['free']
        print(f"  {lot['id']:<6} {lot['capacity']:>10} {lot['occupied']:>10} {reserved:>10} {lot['free']:>6}")
    print()


def print_help():
    print("""
  lots                    — show all parking lots
  avail   <lotId>           — show free spaces in a lot    (e.g. avail A)
  reserve <lotId> <plate> — reserve a spot               (e.g. reserve A 7ABC123)
  cancel  <lotId> <plate> — cancel a reservation         (e.g. cancel A 7ABC123)
  sub     <lotId>         — subscribe to live updates    (e.g. sub A)
  unsub   <lotId>         — unsubscribe from updates     (e.g. unsub A)
  help                    — show this message
  quit                    — exit
""")


def main():
    host, port = _load_client_config()
    args = sys.argv[1:]
    if "--host" in args:
        host = args[args.index("--host") + 1]
    if "--port" in args:
        port = int(args[args.index("--port") + 1])

    print(f"Connecting to parking server at {host}:{port} …")
    try:
        client = ParkingClient(host, port, timeout=5.0, on_event=on_event)
    except ConnectionRefusedError:
        print(f"ERROR: Could not connect to {host}:{port} — is server.py running?")
        sys.exit(1)

    print("Connected.  Type 'help' for commands.\n")

    subscriptions = {}

    while True:
        try:
            line = input("parking> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nDisconnecting.")
            break

        if not line:
            continue

        parts = line.split()
        cmd   = parts[0].lower()

        try:
            if cmd in ("quit", "exit"):
                break

            elif cmd == "help":
                print_help()

            elif cmd == "lots":
                print_lots(client.getLots())

            elif cmd == "avail":
                if len(parts) < 2:
                    print("  Usage: avail <lotId>")
                    continue
                free = client.getAvailability(parts[1])
                print(f"  Lot {parts[1]}: {free} free spaces\n")

            elif cmd == "reserve":
                if len(parts) < 3:
                    print("  Usage: reserve <lotId> <plate>")
                    continue
                client.reserve(parts[1], parts[2])
                print(f"  Reserved a spot in lot {parts[1]} for plate {parts[2]}\n")

            elif cmd == "cancel":
                if len(parts) < 3:
                    print("  Usage: cancel <lotId> <plate>")
                    continue
                client.cancel(parts[1], parts[2])
                print(f"  Cancelled reservation for plate {parts[2]} in lot {parts[1]}\n")

            elif cmd == "sub":
                if len(parts) < 2:
                    print("  Usage: sub <lotId>")
                    continue
                lot_id = parts[1]
                if lot_id in subscriptions:
                    print(f"  Already subscribed lot {lot_id}\n")
                    continue
                sub_id = client.subscribe(lot_id)
                subscriptions[lot_id] = sub_id
                print(f"  Subscribed lot {lot_id} (subId={sub_id}) — live updates will appear above\n")

            elif cmd == "unsub":
                if len(parts) < 2:
                    print("  Usage: unsub <lotId>")
                    continue
                lot_id = parts[1]
                if lot_id not in subscriptions:
                    print(f"  Not subscribed to lot {lot_id}\n")
                    continue
                client.unsubscribe(subscriptions.pop(lot_id))
                print(f"  Unsubscribed from lot {lot_id}\n")

            else:
                print(f"  Unknown command '{cmd}'.  Type 'help'.")

        except RpcTimeoutError:
            print("  ERROR: Server did not respond in time.\n")
        except RpcError as e:
            print(f"  ERROR: {e}\n")
        except ConnectionError as e:
            print(f"  ERROR: Lost connection: {e}")
            break

    client.close()
    print("Goodbye.")


if __name__ == "__main__":
    main()