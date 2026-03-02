# CECS-327-Assignment-2: Campus Smart Parking Finder 


# TO RUN:

In one terminal, launch the server with `python3 server.py`.

In a second terminal, launch the sensor simulation with `python3 sensor.py`.

In one or more terminals, launch clients with `python3 client.py`.

# Then type commands like:
- `PING`
- `LOTS`
- `RESERVE A ABC123`
- `AVAIL A`
- `CANCEL A ABC123`

# RPC path
client.py → client_stub.py → TCP → rpc_skeleton.py → server.py → rpc_skeleton.py → client_stub.py → client.py
