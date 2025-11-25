import requests
import time
import schedule
from datetime import datetime

def ping_render():
    """Ping the Render backend to keep it awake"""
    # UPDATE THIS WITH YOUR ACTUAL RENDER URL
    backend_url = "https://your-app-name.onrender.com"
    
    try:
        response = requests.get(f"{backend_url}/ping", timeout=10)
        if response.status_code == 200:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Ping successful")
            return True
        else:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Ping failed with status: {response.status_code}")
            return False
    except Exception as e:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Ping error: {e}")
        return False

def run_scheduler():
    """Run the ping every 10 minutes"""
    print("Starting JayDL Ping Service...")
    print("Pinging every 10 minutes to keep Render awake")
    print(f"Target: https://your-app-name.onrender.com")
    print("First ping in 10 seconds...")
    
    time.sleep(10)
    
    # Schedule ping every 10 minutes
    schedule.every(10).minutes.do(ping_render)
    
    # Run immediately on start
    ping_render()
    
    # Keep running
    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == "__main__":
    run_scheduler()