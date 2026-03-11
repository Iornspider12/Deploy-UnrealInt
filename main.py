from fastapi import FastAPI, Request, Response
from contextlib import asynccontextmanager
from starlette.middleware.cors import CORSMiddleware
import httpx
import asyncio
import socket
import uvicorn
import json
from fastapi.staticfiles import StaticFiles


def external_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # connect() doesn't actually send packets
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    finally:
        s.close()
    return ip


servers = []
with open("ports.json", "r", encoding="utf-8-sig") as f:
    ports = json.load(f)   # data is a list

    # Use localhost for local development, external_ip for production
    host = "localhost" if __debug__ else external_ip()
    for port in ports:
        servers.append(
            {"url": f"http://{host}:{port}", "free": 0, "busy": 0})


async def update_resource_metrics():
    while True:
        for server in servers:
            try:
                # Assuming each backend exposes a /metrics endpoint for resource usage
                async with httpx.AsyncClient() as client:
                    response = await client.get(f"{server['url']}/metrics", timeout=1)
                    if response.status_code == 200:
                        metrics = response.json()
                        server['free'] = metrics.get("free", 0)
                        server['busy'] = metrics.get("busy", 0)
            except httpx.RequestError:
                print(f"Could not reach backend at {server['url']}")
            except Exception as err:
                print(f"Error updating metrics for {server['url']}: {err}")
        await asyncio.sleep(10)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic
    task = asyncio.create_task(update_resource_metrics())
    yield  # <-- the app runs while this context is active
    # Shutdown logic
    task.cancel()

app = FastAPI(lifespan=lifespan)

# Allow CORS for dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)


@app.get("/")
async def home():
    """Home Page - version check"""
    return {'version': 'load_balancer - 0.0.1'}


@app.get("/health")
async def health_check():
    """Simple health check endpoint - responds immediately"""
    return {'status': 'healthy', 'service': 'load_balancer'}


@app.api_route("/offer", methods=["POST"])
async def forward_request(request: Request):
    # Find the server with the least connections and available resources
    # This is a simplified example; a real implementation would consider weights and thresholds
    least_loaded = sorted(
        servers, key=lambda d: d['free'], reverse=True)[0]

    try:
        async with httpx.AsyncClient() as client:
            target_url = f"{least_loaded['url']}/start"
            response = await client.request(
                method=request.method,
                url=target_url,
                headers=request.headers,
                data=await request.body(),
                params=request.query_params,
                timeout=30
            )
            return response.json()
    except httpx.RequestError as err:
        print(f"Request to backend failed: {err}")
        return Response(
            content=json.dumps({'message': "Backend server error", 'error': str(err)}),
            status_code=500,
            media_type="application/json"
        )
    finally:
        least_loaded["free"] -= 1
        least_loaded["busy"] += 1


@app.api_route("/stop", methods=["POST"])
async def stop_slot(request: Request):
    """Stop a WebRTC session and free the slot.
    
    Finds the correct orchestrator from the servers list by matching port,
    then forwards the stop request with the slot ID (follows /offer pattern).
    The slot ID format is "host:port-slotnum".
    """
    try:
        params = await request.json()
        slot = params.get('slot')
        
        if not slot:
            return Response(
                content=json.dumps({'msg': 'Missing slot parameter'}),
                status_code=400,
                media_type="application/json"
            )
        
        print(f"[stop endpoint] Attempting to stop slot: {slot}")
        
        # Parse port from slot ID format "host:port-slotnum"
        # The host in slot ID might be 0.0.0.0 (bind address), so we match by port
        try:
            host_port = slot.rsplit('-', 1)[0]
            port = host_port.split(':')[-1]
        except (ValueError, IndexError):
            return Response(
                content=json.dumps({'msg': 'Invalid slot format'}),
                status_code=400,
                media_type="application/json"
            )
        
        # Find the matching server by port from servers list (same logic as /offer uses)
        # This ensures we use the correct connectable address (localhost or external_ip)
        # instead of the bind address (0.0.0.0) from the slot ID
        target_server = None
        for server in servers:
            server_url = server['url']
            # Extract port from server URL (format: "http://host:port")
            if f":{port}" in server_url or server_url.endswith(f":{port}"):
                target_server = server
                break
        
        if not target_server:
            return Response(
                content=json.dumps({'msg': f'No server found for port {port}', 'slot': slot}),
                status_code=404,
                media_type="application/json"
            )
        
        # Use server URL from list and slot ID directly (no encoding, follows /offer pattern)
        target_url = f"{target_server['url']}/stop/{slot}"
        
        print(f"[stop endpoint] Target URL: {target_url}")
        
        # Make request (follows /offer pattern - forwards payload)
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(target_url, timeout=10)
                
                if response.status_code == 200:
                    result = response.json()
                    print(f"[stop endpoint] Success: {result}")
                    
                    # Update metrics
                    target_server["free"] += 1
                    target_server["busy"] = max(0, target_server["busy"] - 1)
                    
                    return result
                elif response.status_code == 404:
                    return Response(
                        content=json.dumps({'msg': 'Slot not found', 'slot': slot}),
                        status_code=404,
                        media_type="application/json"
                    )
                else:
                    return Response(
                        content=json.dumps({'msg': f'Server returned error status {response.status_code}', 'slot': slot}),
                        status_code=response.status_code,
                        media_type="application/json"
                    )
                    
        except httpx.RequestError as err:
            print(f"[stop endpoint] Network error: {err}")
            return Response(
                content=json.dumps({'msg': 'Could not reach orchestrator', 'error': str(err), 'slot': slot}),
                status_code=503,
                media_type="application/json"
            )
        
    except Exception as err:
        print(f"[stop endpoint] Error: {err}")
        return Response(
            content=json.dumps({'msg': 'Error stopping slot', 'error': str(err)}),
            status_code=500,
            media_type="application/json"
        )


app.mount("/public", StaticFiles(directory="public", html=True), name="static")

if __name__ == '__main__':

    import argparse

    parser = argparse.ArgumentParser(
        description="Run FastAPI app with custom host and port.")

    if __debug__:
        parser.add_argument(
            "--host",
            type=str,
            default="localhost",
            help="Host address to bind the server.")
    else:
        parser.add_argument(
            "--host",
            type=str,
            default="0.0.0.0",
            help="Host address to bind the server.")

    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port number to bind the server.")
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port)
