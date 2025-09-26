#!/usr/bin/env python3
import os
import subprocess
import sys
import shutil

CONFIG_DIR = "/root/stunnel"
CERTS_DIR = os.path.join(CONFIG_DIR, "certs")
MARKER_FILE = "/root/.vpn_setup_done"
OVPN_SCRIPT = "/root/openvpn-install.sh"

os.makedirs(CONFIG_DIR, exist_ok=True)
os.makedirs(CERTS_DIR, exist_ok=True)

def run_cmd(cmd_list, check=True, interactive=False):
    if interactive:
        subprocess.run(cmd_list, check=check)
    else:
        subprocess.run(cmd_list, check=check, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

# --- Dependencies (first run only) ---
def install_dependencies():
    print("[*] Installing dependencies (first run only)...")
    run_cmd(["apt", "update"], interactive=True)
    run_cmd([
        "apt", "install", "-y",
        "curl", "openssl", "docker.io", "docker-compose", "ufw", "socat", "nano", "python3-pip"
    ], interactive=True)
    run_cmd(["pip3", "install", "paramiko", "scp", "requests"], interactive=True)
    print("[+] Dependencies installed")

# --- OpenVPN Installer (Non-IR) ---
def ensure_openvpn_installer():
    local_script = "./openvpn-install.sh"
    if not os.path.exists(OVPN_SCRIPT):
        if os.path.exists(local_script):
            print("[*] Using local OpenVPN installer...")
            shutil.copy2(local_script, OVPN_SCRIPT)
            run_cmd(["chmod", "+x", OVPN_SCRIPT])
            print("[+] Local OpenVPN installer copied.")
        else:
            print("[*] Downloading OpenVPN installer from 0xamirreza/openvpn-stunnel repository...")
            run_cmd([
                "curl", "-o", OVPN_SCRIPT,
                "https://raw.githubusercontent.com/0xamirreza/openvpn-stunnel/master/openvpn-install.sh"
            ])
            run_cmd(["chmod", "+x", OVPN_SCRIPT])
            print("[+] OpenVPN installer downloaded from your repository.")






# --- Certificate Download Function ---
def download_stunnel_cert(host, username, password=None, key_file=None, port=22):
    """Download stunnel.pem from Non-IR server via SSH/SCP"""
    print(f"[*] Connecting to {host} to download stunnel.pem...")
    
    try:
        import paramiko
        from scp import SCPClient
        
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        # Connect via password or key
        if key_file and os.path.exists(key_file):
            ssh.connect(host, port=port, username=username, key_filename=key_file)
        elif password:
            ssh.connect(host, port=port, username=username, password=password)
        else:
            print("[!] No authentication method provided")
            return False
        
        # Download the certificate
        with SCPClient(ssh.get_transport()) as scp:
            remote_cert = "/root/stunnel/certs/stunnel.pem"
            local_cert = os.path.join(CONFIG_DIR, "stunnel.pem")
            
            scp.get(remote_cert, local_cert)
            print(f"[+] Downloaded stunnel.pem to {local_cert}")
        
        ssh.close()
        return True
        
    except Exception as e:
        print(f"[!] Error downloading certificate: {e}")
        return False

# --- First Run Setup ---
def first_run_setup():
    print("[!] First setup required")
    choice = input("Select server type:\n1) Non-IR Server (VPN Server, outside)\n2) IR Server (Inside, tunnels VPN)\nEnter choice [1-2]: ").strip()

    if choice == "1":
        server_type = "non-ir"
        print("[*] Non-IR server first run setup")

        # Install dependencies
        install_dependencies()

        # Download OpenVPN installer
        ensure_openvpn_installer()

        # Generate stunnel certificate
        domain_cn = input("Enter your domain for CN in certificate (e.g vpn.example.com): ").strip()
        key_path = os.path.join(CERTS_DIR, "stunnel.key")
        crt_path = os.path.join(CERTS_DIR, "stunnel.crt")
        pem_path = os.path.join(CERTS_DIR, "stunnel.pem")

        run_cmd([
            "openssl", "req", "-x509", "-nodes", "-newkey", "rsa:2048",
            "-keyout", key_path,
            "-out", crt_path,
            "-days", "365",
            "-subj", f"/C=IR/ST=Tehran/L=Tehran/O=0xopenvpn/OU=TemplateV/CN={domain_cn}"
        ])
        with open(pem_path, "w") as pem_file:
            with open(key_path, "r") as kf:
                pem_file.write(kf.read())
            with open(crt_path, "r") as cf:
                pem_file.write(cf.read())
        print(f"[+] Certificate generated at {pem_path}")

        # Run OpenVPN installer interactively for first client
        print("[!] Running OpenVPN installer now. Configure your first client interactively.\n")
        run_cmd([OVPN_SCRIPT], interactive=True)

        # stunnel_server.conf
        stunnel_conf = os.path.join(CONFIG_DIR, "stunnel_server.conf")
        with open(stunnel_conf, "w") as f:
            f.write("""pid =
foreground = yes
debug = 5

[openvpn]
accept = 0.0.0.0:443
connect = 127.0.0.1:1194
cert = /certs/stunnel.pem
""")

        # docker-compose.yml
        docker_compose = os.path.join(CONFIG_DIR, "docker-compose.yml")
        with open(docker_compose, "w") as f:
            f.write("""version: '3'
services:
  stunnel-server:
    image: chainguard/stunnel:latest
    container_name: stunnel-server
    restart: unless-stopped
    user: root
    volumes:
      - ./stunnel_server.conf:/etc/stunnel/stunnel_server.conf:ro
      - ./certs/stunnel.pem:/certs/stunnel.pem:ro
    network_mode: host
    command: ["/etc/stunnel/stunnel_server.conf"]
""")

        run_cmd(["ufw", "allow", "443/tcp"])
        run_cmd(["ufw", "allow", "1194/tcp"])
        print("[+] Non-IR first-run setup complete. Starting stunnel server...")
        
        # Start the stunnel server automatically
        os.chdir(CONFIG_DIR)
        run_cmd(["docker-compose", "up", "-d"])
        print("[+] Stunnel server started. Opening menu...")

    elif choice == "2":
        server_type = "ir"
        print("[*] IR server first run setup")
        
        # Install dependencies first
        install_dependencies()
        
        # Get Non-IR server details
        domain = input("Enter Non-IR VPS domain (e.g. vpn.example.com): ").strip()
        
        print("\n[*] To download stunnel.pem, we need SSH access to the Non-IR server")
        ssh_user = input("Enter SSH username for Non-IR server (default: root): ").strip() or "root"
        ssh_port = input("Enter SSH port (default: 22): ").strip() or "22"
        
        auth_method = input("Authentication method:\n1) Password\n2) SSH Key\nChoose [1-2]: ").strip()
        
        cert_downloaded = False
        
        if auth_method == "1":
            ssh_pass = input("Enter SSH password: ").strip()
            cert_downloaded = download_stunnel_cert(domain, ssh_user, password=ssh_pass, port=int(ssh_port))
        elif auth_method == "2":
            key_path = input("Enter path to SSH private key (default: ~/.ssh/id_rsa): ").strip()
            if not key_path:
                key_path = os.path.expanduser("~/.ssh/id_rsa")
            cert_downloaded = download_stunnel_cert(domain, ssh_user, key_file=key_path, port=int(ssh_port))
        else:
            print("[!] Invalid authentication method")
        
        if not cert_downloaded:
            print("[!] Failed to download certificate. You'll need to manually copy stunnel.pem to /root/stunnel/")
            input("Press Enter after you've manually copied the certificate...")

        # stunnel_client.conf
        stunnel_conf = os.path.join(CONFIG_DIR, "stunnel_client.conf")
        with open(stunnel_conf, "w") as f:
            f.write(f"""client = yes
foreground = yes

[openvpn]
accept = 0.0.0.0:1194
connect = {domain}:443
cert = /certs/stunnel.pem
verifyChain = no
TIMEOUTclose = 0
socket = l:TCP_NODELAY=1
socket = r:TCP_NODELAY=1
""")

        # docker-compose.yml
        docker_compose = os.path.join(CONFIG_DIR, "docker-compose.yml")
        with open(docker_compose, "w") as f:
            f.write("""version: '3'
services:
  stunnel-client:
    image: chainguard/stunnel:latest
    container_name: stunnel-client
    restart: unless-stopped
    command: ["/etc/stunnel/stunnel_client.conf"]
    volumes:
      - ./stunnel_client.conf:/etc/stunnel/stunnel_client.conf:ro
      - ./stunnel.pem:/certs/stunnel.pem:ro
    network_mode: host
    dns:
      - 1.1.1.1
      - 1.0.0.1
""")
        run_cmd(["ufw", "allow", "1194/tcp"])
        print("[+] IR server setup complete. Starting stunnel client...")
        
        # Start the stunnel client
        os.chdir(CONFIG_DIR)
        run_cmd(["docker-compose", "up", "-d"])
        print("[+] Opening menu...")

    else:
        print("[!] Invalid choice")
        sys.exit(1)

    # Marker file
    with open(MARKER_FILE, "w") as f:
        f.write(server_type)
    return server_type

# --- Load server type ---
def load_server_type():
    if os.path.exists(MARKER_FILE):
        with open(MARKER_FILE, "r") as f:
            return f.read().strip()
    return None

# --- Non-IR Menu ---
def uninstall_non_ir():
    print("[!] Uninstalling Non-IR server...")
    run_cmd(["docker", "rm", "-f", "stunnel-server"], check=False)
    run_cmd(["docker-compose", "-f", os.path.join(CONFIG_DIR, "docker-compose.yml"), "down"], check=False)
    for f in ["stunnel_server.conf", "docker-compose.yml", "certs"]:
        path = os.path.join(CONFIG_DIR, f)
        if os.path.exists(path):
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
    if os.path.exists(MARKER_FILE):
        os.remove(MARKER_FILE)
    print("[+] Non-IR server uninstalled successfully.")

def start_stunnel_server():
    """Start the stunnel server"""
    print("[*] Starting stunnel server...")
    try:
        os.chdir(CONFIG_DIR)
        run_cmd(["docker-compose", "up", "-d"])
        print("[+] Stunnel server started")
    except Exception as e:
        print(f"[!] Error starting stunnel server: {e}")

def stop_stunnel_server():
    """Stop the stunnel server"""
    print("[*] Stopping stunnel server...")
    try:
        os.chdir(CONFIG_DIR)
        run_cmd(["docker-compose", "down"], check=False)
        print("[+] Stunnel server stopped")
    except Exception as e:
        print(f"[!] Error stopping stunnel server: {e}")

def non_ir_menu():
    while True:
        print("\n=== Non-IR Server Menu ===")
        print("1) Check Cert Timeleft")
        print("2) Edit stunnel_server.conf")
        print("3) Start stunnel server")
        print("4) Stop stunnel server")
        print("5) Uninstall Non-IR server")
        print("0) Exit")
        choice = input("Enter choice [0-5]: ").strip()
        
        if choice == "1":
            crt_file = os.path.join(CERTS_DIR, "stunnel.crt")
            if os.path.exists(crt_file):
                run_cmd(["openssl", "x509", "-enddate", "-noout", "-in", crt_file], interactive=True)
            else:
                print("[!] Certificate file not found.")
                
        elif choice == "2":
            run_cmd(["nano", os.path.join(CONFIG_DIR, "stunnel_server.conf")], interactive=True)
            
        elif choice == "3":
            start_stunnel_server()
            
        elif choice == "4":
            stop_stunnel_server()
            
        elif choice == "5":
            stop_stunnel_server()
            uninstall_non_ir()
            break
            
        elif choice == "0":
            break
        else:
            print("[!] Invalid choice")

# --- IR Menu ---
def uninstall_ir():
    print("[!] Uninstalling IR server...")
    run_cmd(["docker", "rm", "-f", "stunnel-client"], check=False)
    run_cmd(["docker-compose", "-f", os.path.join(CONFIG_DIR, "docker-compose.yml"), "down"], check=False)
    for f in ["stunnel_client.conf", "docker-compose.yml", "stunnel.pem"]:
        path = os.path.join(CONFIG_DIR, f)
        if os.path.exists(path):
            os.remove(path)
    if os.path.exists(MARKER_FILE):
        os.remove(MARKER_FILE)
    print("[+] IR server uninstalled successfully.")

def start_stunnel_client():
    """Start the stunnel client"""
    print("[*] Starting stunnel client...")
    try:
        os.chdir(CONFIG_DIR)
        run_cmd(["docker-compose", "up", "-d"])
        print("[+] Stunnel client started")
    except Exception as e:
        print(f"[!] Error starting stunnel client: {e}")

def stop_stunnel_client():
    """Stop the stunnel client"""
    print("[*] Stopping stunnel client...")
    try:
        os.chdir(CONFIG_DIR)
        run_cmd(["docker-compose", "down"], check=False)
        print("[+] Stunnel client stopped")
    except Exception as e:
        print(f"[!] Error stopping stunnel client: {e}")

def ir_menu():
    while True:
        print("\n=== IR Server Menu ===")
        print("1) Check health")
        print("2) Edit stunnel_client.conf")
        print("3) Edit DNS in docker-compose.yml")
        print("4) Start stunnel client")
        print("5) Stop stunnel client")
        print("6) Uninstall IR server")
        print("0) Exit")
        choice = input("Enter choice [0-6]: ").strip()
        
        if choice == "1":
            run_cmd(["docker", "ps"], interactive=True)
            
        elif choice == "2":
            run_cmd(["nano", os.path.join(CONFIG_DIR, "stunnel_client.conf")], interactive=True)
            
        elif choice == "3":
            run_cmd(["nano", os.path.join(CONFIG_DIR, "docker-compose.yml")], interactive=True)
            
        elif choice == "4":
            start_stunnel_client()
            
        elif choice == "5":
            stop_stunnel_client()
            
        elif choice == "6":
            stop_stunnel_client()
            uninstall_ir()
            break
            
        elif choice == "0":
            break
        else:
            print("[!] Invalid choice")

# --- Main ---
def main():
    server_type = load_server_type()
    if not server_type:
        server_type = first_run_setup()

    if server_type == "non-ir":
        non_ir_menu()
    elif server_type == "ir":
        ir_menu()
    else:
        print("[!] Unknown server type in marker file")
        sys.exit(1)

if __name__ == "__main__":
    main()
