import requests, math, sys, heapq, difflib
from collections import defaultdict
from colorama import init, Fore, Style
from datetime import datetime, timedelta

# Initialize colorama
init(autoreset=True)

GEOJSON_URL = "https://raw.githubusercontent.com/geohacker/namma-metro/master/metro-lines-stations.geojson"

# Config
AVG_SPEED_KMH = 35.0      # Commercial speed
DWELL_SEC = 30            # Dwell time per stop
NEAREST_NEIGH = 4         # Connect to K nearest neighbors

# ---------- helpers ----------
def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dl/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

def normalize(s): 
    return (s or "").strip().lower().replace(" station", "")

def fetch_geojson(url):
    try:
        print(f"{Fore.YELLOW}Fetching data from GitHub...")
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(Fore.RED + f"Error fetching data: {e}")
        sys.exit(1)

# ---------- core logic ----------
def build_network(geojson):
    stations = {}
    line_groups = defaultdict(list)
    
    features = geojson.get('features', [])
    if not features:
        print(Fore.RED + "Error: GeoJSON has no 'features' list.")
        return {}, {}

    for feature in features:
        geom = feature.get('geometry', {})
        raw_props = feature.get('properties', {})
        props = {k.lower(): v for k, v in raw_props.items()}
        
        if geom.get('type') != 'Point': continue
            
        # Robust Key Search
        raw_name = (props.get('name') or props.get('station_name') or 
                   props.get('stop_name') or props.get('title'))
                   
        if not raw_name: continue
        
        line_info = (props.get('line') or props.get('lines') or 
                    props.get('route') or props.get('color')) 
        
        sid = normalize(raw_name)
        coords = geom.get('coordinates')
        
        # Parse lines
        current_lines = set()
        if isinstance(line_info, str):
            parts = [p.strip() for p in line_info.replace(';',',').split(',') if p.strip()]
            current_lines.update(parts)
        elif isinstance(line_info, list):
            current_lines.update([str(x) for x in line_info])
        
        if not current_lines: current_lines.add("Metro")

        if sid not in stations:
            stations[sid] = {
                'id': sid,
                'display_name': raw_name, 
                'lat': coords[1], 
                'lon': coords[0],
                'lines': set()
            }
        
        stations[sid]['lines'].update(current_lines)

        for l in current_lines:
            if sid not in line_groups[l]:
                line_groups[l].append(sid)

    return stations, line_groups

def build_graph(stations, line_groups):
    adj = defaultdict(list)
    for line, sids in line_groups.items():
        if len(sids) < 2: continue
        for sid_a in sids:
            a = stations[sid_a]
            candidates = []
            for sid_b in sids:
                if sid_a == sid_b: continue
                b = stations[sid_b]
                d_km = haversine_km(a['lat'], a['lon'], b['lat'], b['lon'])
                candidates.append((d_km, sid_b))
            candidates.sort(key=lambda x: x[0])
            
            for d_km, neighbor_sid in candidates[:NEAREST_NEIGH]:
                ride_sec = (d_km / AVG_SPEED_KMH) * 3600
                total_cost = ride_sec + DWELL_SEC
                adj[sid_a].append((neighbor_sid, total_cost, d_km))
    return adj

def dijkstra(adj, start_id, goal_id):
    pq = [(0, start_id, [])]
    visited = set()
    min_times = {start_id: 0}

    while pq:
        cost, cur, path = heapq.heappop(pq)
        if cur in visited: continue
        visited.add(cur)
        path = path + [cur]
        if cur == goal_id: return path, cost

        for neighbor, edge_cost, _ in adj[cur]:
            new_cost = cost + edge_cost
            if new_cost < min_times.get(neighbor, float('inf')):
                min_times[neighbor] = new_cost
                heapq.heappush(pq, (new_cost, neighbor, path))
    return None, 0

# ---------- UI with Fuzzy Search ----------
def get_user_selection(stations, prompt_text):
    # Pre-compute lists for fuzzy matching
    all_names = [s['display_name'] for s in stations.values()]
    name_to_id = {s['display_name']: s['id'] for s in stations.values()}

    while True:
        query = input(f"{prompt_text}: ").strip()
        if not query: return None
        
        # 1. Exact/Substring match (Case Insensitive)
        matches = [s for s in stations.values() if query.lower() in s['display_name'].lower()]
        
        # 2. If no direct matches, try Fuzzy Match (Typo handling)
        if not matches:
            # Get top 3 close matches, cutoff 0.5 means "50% similar"
            guesses = difflib.get_close_matches(query, all_names, n=3, cutoff=0.5)
            if guesses:
                print(f"{Fore.YELLOW}No exact match. Did you mean...?")
                matches = [stations[name_to_id[g]] for g in guesses]
            else:
                print(f"{Fore.RED}No matches found. Check spelling.")
                continue
        
        # 3. Selection Logic
        if len(matches) == 1:
            # Auto-select if it's a perfect match or the only guess
            print(f"{Fore.CYAN}Selected: {matches[0]['display_name']}")
            return matches[0]['id']
        
        print(f"{Fore.CYAN}Multiple matches found:")
        for i, m in enumerate(matches[:10], 1):
            lines = ", ".join(m['lines'])
            print(f" {i}. {m['display_name']} ({lines})")
        
        sel = input("Select number (or Enter to search again): ")
        if sel.isdigit():
            idx = int(sel) - 1
            if 0 <= idx < len(matches):
                return matches[idx]['id']

def main():
    print(f"{Fore.GREEN}{Style.BRIGHT}=== Namma Metro Route Estimator (Smart) ===")
    print(f"{Style.DIM}Fetches live data.")
    
    data = fetch_geojson(GEOJSON_URL)
    stations, line_groups = build_network(data)
    
    print(f"{Fore.BLUE}Loaded {len(stations)} stations.")

    while True:
        print("\n" + "-"*30)
        start_id = get_user_selection(stations, "Origin Station")
        if not start_id: break
        goal_id = get_user_selection(stations, "Destination Station")
        if not goal_id: break
        
        adj = build_graph(stations, line_groups)
        path, total_seconds = dijkstra(adj, start_id, goal_id)
        
        if not path:
            print(f"{Fore.RED}No route found (Graph disconnected).")
        else:
            print(f"\n{Fore.GREEN}Route Found:")
            dist = 0.0
            for i in range(len(path)):
                s = stations[path[i]]
                if i > 0:
                    prev = stations[path[i-1]]
                    dist += haversine_km(s['lat'], s['lon'], prev['lat'], prev['lon'])
                meta = f"[{','.join(s['lines'])}]"
                print(f"  {i+1}. {s['display_name']} {Style.DIM}{meta}")
            
            eta = datetime.now() + timedelta(seconds=total_seconds)
            print(f"\n{Fore.WHITE}{Style.BRIGHT}Summary:")
            print(f"  Total Distance: {dist:.2f} km")
            print(f"  Est. Time:      {int(total_seconds//60)} min {int(total_seconds%60)} sec")
            print(f"  Arrival:        {eta.strftime('%H:%M:%S')}")

        if input("\nCheck another route? (y/n): ").lower() != 'y':
            break

if __name__ == "__main__":
    main()