#!/usr/bin/env python3
"""
Improved Local Setup Script - Cross-platform
Better error handling and environment variable management
"""

import subprocess
import sys
import socket
import json
import time
import os
import platform
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

def get_local_ip():
    """Get the local IP address"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def check_service(host, port, name, timeout=2):
    """Check if a port is accessible"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()
        if result == 0:
            return True
        return False
    except Exception as e:
        return False

def check_prerequisites():
    """Check all prerequisites before starting"""
    print("Checking prerequisites...")
    print()
    
    issues = []
    
    # Check Ollama
    if not check_service("localhost", 11434, "Ollama"):
        issues.append("Ollama is not running. Start with: ollama serve")
    
    # Check VOICE_IP
    voice_ip = os.getenv("VOICE_IP")
    if not voice_ip:
        print("⚠ VOICE_IP not set in .env file or environment!")
        print("   Please create a .env file with: VOICE_IP=your_voice_service_ip")
        print("   Or set it as environment variable")
        return False
    
    print(f"✓ VOICE_IP found: {voice_ip}")
    
    # Check ports
    for port in [8000, 8001, 8002]:
        if check_service("localhost", port, f"Port-{port}", timeout=0.5):
            issues.append(f"Port {port} is already in use")
    
    if issues:
        print("⚠ Issues found:")
        for issue in issues:
            print(f"  - {issue}")
        print()
        response = input("Continue anyway? (y/n): ")
        if response.lower() != 'y':
            print("Exiting. Please fix issues first.")
            return False
    
    print("✓ Prerequisites check passed")
    print()
    return True

def update_frontend_files(ip):
    """Update frontend files with the local IP"""
    print(f"Updating frontend files with IP: {ip}")
    try:
        result = subprocess.run(
            [sys.executable, "route_to.py", "--ip", ip],
            capture_output=True,
            text=True,
            check=True
        )
        print("✓ Frontend files updated")
        return True
    except subprocess.CalledProcessError as e:
        print(f"✗ Failed to update frontend files: {e.stderr}")
        return False
    except Exception as e:
        print(f"✗ Error updating frontend files: {e}")
        return False

def create_ports_json(ports):
    """Create ports.json file"""
    ports_file = Path("ports.json")
    try:
        with open(ports_file, "w") as f:
            json.dump(ports, f)
        print(f"✓ Created {ports_file} with ports: {ports}")
        return True
    except Exception as e:
        print(f"✗ Failed to create ports.json: {e}")
        return False

def start_orchestrator_windows(port, slots, env_vars):
    """Start orchestrator on Windows with proper environment"""
    # Use the same Python that's running this script
    python_cmd = sys.executable
    
    # Create a temporary batch file with environment variables
    batch_content = f"""@echo off
set VOICE_IP={env_vars['VOICE_IP']}
set EXT_IP={env_vars['EXT_IP']}
set OLLAMA_URL={env_vars.get('OLLAMA_URL', 'http://localhost:11434')}
set OLLAMA_MODEL={env_vars.get('OLLAMA_MODEL', 'gemma2:2b')}
cd /d "{os.getcwd()}"
"{python_cmd}" orch.py --host 0.0.0.0 --port {port} --slots {slots}
pause
"""
    batch_file = Path(f"start_orch_{port}.bat")
    try:
        with open(batch_file, "w") as f:
            f.write(batch_content)
        
        # Start in new window - use shell=True for proper Windows start command
        # The start command syntax is: start "Window Title" command
        cmd = f'start "Orchestrator-{port}" "{batch_file.absolute()}"'
        subprocess.Popen(
            cmd,
            cwd=os.getcwd(),
            shell=True
        )
        return True
    except Exception as e:
        print(f"✗ Error starting orchestrator on port {port}: {e}")
        return False

def start_orchestrator_unix(port, slots, env_vars):
    """Start orchestrator on Unix-like systems"""
    env = os.environ.copy()
    env.update(env_vars)
    
    log_file = Path(f"orch_{port}.log")
    try:
        with open(log_file, "w") as log:
            process = subprocess.Popen(
                [sys.executable, "orch.py", "--host", "0.0.0.0", "--port", str(port), "--slots", str(slots)],
                stdout=log,
                stderr=log,
                env=env
            )
        print(f"  Log file: {log_file}")
        return True
    except Exception as e:
        print(f"✗ Error starting orchestrator on port {port}: {e}")
        return False

def start_orchestrator(port, slots, env_vars):
    """Start an orchestrator instance"""
    if platform.system() == "Windows":
        return start_orchestrator_windows(port, slots, env_vars)
    else:
        return start_orchestrator_unix(port, slots, env_vars)

def main():
    print("=" * 60)
    print("3-Tier Orchestration - Improved Local Setup")
    print("=" * 60)
    print()
    
    # Check prerequisites first
    if not check_prerequisites():
        sys.exit(1)
    
    # Get local IP
    local_ip = get_local_ip()
    print(f"Detected Local IP: {local_ip}")
    print()
    
    # Set environment variables (load from .env)
    voice_ip = os.getenv("VOICE_IP")
    if not voice_ip:
        print("⚠️  ERROR: VOICE_IP not set in .env file or environment!")
        print("   Please create a .env file with: VOICE_IP=3.15.186.202")
        sys.exit(1)
    
    env_vars = {
        "VOICE_IP": voice_ip,
        "EXT_IP": local_ip,
        "OLLAMA_URL": os.getenv("OLLAMA_URL", "http://localhost:11434"),
        "OLLAMA_MODEL": os.getenv("OLLAMA_MODEL", "gemma2:2b")
    }
    print(f"✓ Using VOICE_IP: {voice_ip}")
    
    # Update frontend files
    if not update_frontend_files(local_ip):
        print("Failed to update frontend files. Exiting.")
        sys.exit(1)
    
    # Create ports.json
    orchestrator_ports = [8001, 8002]
    if not create_ports_json(orchestrator_ports):
        print("Failed to create ports.json. Exiting.")
        sys.exit(1)
    
    # Start orchestrators
    print()
    print("Starting orchestrators...")
    print(f"  Environment: VOICE_IP={voice_ip}, EXT_IP={local_ip}")
    print()
    
    started_ports = []
    for port in orchestrator_ports:
        print(f"  Starting orchestrator on port {port}...", end=" ")
        if start_orchestrator(port, slots=2, env_vars=env_vars):
            print("✓")
            started_ports.append(port)
        else:
            print("✗")
        time.sleep(2)
    
    print()
    print("Waiting for orchestrators to initialize...")
    time.sleep(10)  # Increased wait time
    
    # Verify orchestrators - check multiple times with retries
    print()
    print("Verifying orchestrators...")
    all_ok = True
    for port in orchestrator_ports:
        # Try checking multiple times with longer timeout
        is_running = False
        for attempt in range(3):
            if check_service("localhost", port, f"Orchestrator-{port}", timeout=5):
                is_running = True
                break
            time.sleep(2)  # Wait between retries
        
        if is_running:
            print(f"  ✓ Orchestrator on port {port} is running")
        else:
            print(f"  ✗ Orchestrator on port {port} is NOT responding")
            all_ok = False
    
    if not all_ok:
        print()
        print("⚠️  WARNING: Some orchestrators failed to start!")
        print()
        print("Troubleshooting steps:")
        print("  1. Check orchestrator windows/logs for errors")
        print("  2. Verify VOICE_IP is set: set VOICE_IP=localhost")
        print("  3. Ensure Ollama is running: ollama serve")
        print("  4. Check dependencies: pip install -r reqs.txt")
        print("  5. Test manually: python orch.py --port 8001 --slots 1")
        print()
        response = input("Continue with load balancer anyway? (y/n): ")
        if response.lower() != 'y':
            print("Exiting. Please fix orchestrator issues first.")
            sys.exit(1)
    
    # Start load balancer
    print()
    print("=" * 60)
    print("Starting Load Balancer on port 8000")
    print("=" * 60)
    print()
    print("Access the frontend at:")
    print(f"  Unified: http://localhost:8000/public/unified.html")
    print()
    print(f"Or from other devices:")
    print(f"  http://{local_ip}:8000/public/unified.html")
    print()
    print("Press Ctrl+C to stop the load balancer")
    print("=" * 60)
    print()
    
    # Start load balancer
    try:
        subprocess.run([sys.executable, "main.py", "--host", "0.0.0.0", "--port", "8000"])
    except KeyboardInterrupt:
        print("\nShutting down...")
        # Cleanup temporary batch files on Windows
        if platform.system() == "Windows":
            for port in orchestrator_ports:
                batch_file = Path(f"start_orch_{port}.bat")
                if batch_file.exists():
                    try:
                        batch_file.unlink()
                    except:
                        pass

if __name__ == "__main__":
    main()

