import requests
import time
import schedule

def ping_backend():
    try:
        response = requests.get('https://jaydl-backend.onrender.com/ping', timeout=10)
        print(f"Ping successful: {response.status_code}")
    except Exception as e:
        print(f"Ping failed: {e}")

# Schedule pings every 5 minutes
schedule.every(5).minutes.do(ping_backend)

if __name__ == "__main__":
    print("Starting ping service...")
    while True:
        schedule.run_pending()
        time.sleep(1)