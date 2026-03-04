# CECS-327-Assignment-2: Campus Smart Parking Finder 

## Setup:
No dependencies except Python and built-in libraries are used so there is no need to create a virtual environment and activate it.

## To Run:

In one terminal, launch the server with `python3 server.py`.

In a second terminal, launch the sensor simulation with `python3 sensor.py`.

In one or more terminals, launch clients with `python3 client.py`.

## Then type commands like:
- `PING`
- `LOTS`
- `RESERVE <lot> ABC123`
- `AVAIL <lot>`
- `CANCEL <lot> ABC123`
- `SUB <lot>`
- `UNSUB <lot>`
- `HELP`
## RPC path
client.py -> client_stub.py -> TCP -> rpc_skeleton.py -> server.py -> rpc_skeleton.py -> client_stub.py -> client.py

## Note about endianess: 
JSON is used so not too much worry about endianess. The concern becomes data managing, message formatting, and error handling. 

## Publish/Subscribe System
The approach we took for our design was a mix of both TCP connections for events and dedicated notifier threads for subscriptions. Subscribed clients are dedicated a thread and queue for non-blocking while the separate TCP connection is for distinct connections between RPC requests and event reception.
