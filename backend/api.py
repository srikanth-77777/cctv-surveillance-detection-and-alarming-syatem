from fastapi import FastAPI, Depends, Request, UploadFile, File, Header, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from sqlalchemy import desc
import uvicorn
import os
import sys
import shutil
import jwt
import secrets
import glob
import time
import threading
from datetime import datetime, timedelta

# Add the parent directory to Python's path so "backend" is recognizable
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database import get_db, AlertLog, User, ContactMessage
from backend.detector import ObjectDetector
from backend.notifier import notifier
from pydantic import BaseModel
import hashlib

# JWT Configuration
JWT_SECRET = secrets.token_hex(32)  # Unique key generated every server start
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 24

def create_jwt_token(username: str) -> str:
    """Generate a signed JWT token with expiry."""
    payload = {
        "sub": username,
        "iat": datetime.utcnow(),
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRY_HOURS)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def verify_token(authorization: str = Header(None)):
    """FastAPI dependency to validate JWT from Authorization header."""
    if not authorization:
        return None
    try:
        # Support both "Bearer <token>" and raw token
        token = authorization.replace("Bearer ", "") if authorization.startswith("Bearer ") else authorization
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload["sub"]  # Return the username
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None

def require_auth(authorization: str = Header(None)):
    """Strict auth dependency — rejects request if token is invalid."""
    user = verify_token(authorization)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return user

app = FastAPI(title="Surveillance API")

# Custom Error Pages
def make_error_html(code: int, title: str, description: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AegisSec - Error {code}</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg-color: #0f172a;
            --text-primary: #f8fafc;
            --text-secondary: #94a3b8;
            --accent: #ef4444;
            --accent-glow: rgba(239, 68, 68, 0.2);
        }}
        body {{
            font-family: 'Inter', sans-serif;
            background-color: var(--bg-color);
            color: var(--text-primary);
            margin: 0;
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
            text-align: center;
            background-image: radial-gradient(circle at 50% 50%, rgba(239, 68, 68, 0.05) 0%, transparent 60%);
        }}
        .container {{
            background: rgba(30, 41, 59, 0.7);
            backdrop-filter: blur(12px);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 16px;
            padding: 48px;
            max-width: 500px;
            width: 90%;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.2);
        }}
        h1 {{
            font-size: 5rem;
            margin: 0;
            color: var(--accent);
            text-shadow: 0 0 10px var(--accent-glow);
        }}
        h2 {{
            font-size: 1.5rem;
            margin: 10px 0;
        }}
        p {{
            color: var(--text-secondary);
            margin-bottom: 30px;
            line-height: 1.5;
        }}
        a {{
            display: inline-block;
            background: linear-gradient(135deg, #ef4444, #b91c1c);
            color: white;
            text-decoration: none;
            padding: 12px 24px;
            border-radius: 8px;
            font-weight: 600;
            transition: opacity 0.3s;
        }}
        a:hover {{
            opacity: 0.9;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>{code}</h1>
        <h2>{title}</h2>
        <p>{description}</p>
        <a href="/frontend/index.html">Return to Safety</a>
    </div>
</body>
</html>"""

@app.exception_handler(404)
async def not_found_exception_handler(request: Request, exc: Exception):
    if request.url.path.startswith("/api"):
        return JSONResponse({"status": "error", "message": "Resource not found"}, status_code=404)
    return HTMLResponse(content=make_error_html(404, "Page Not Found", "The secure sector you are trying to access does not exist or has been relocated."), status_code=404)

@app.exception_handler(500)
async def internal_server_exception_handler(request: Request, exc: Exception):
    if request.url.path.startswith("/api"):
        return JSONResponse({"status": "error", "message": "Internal server error"}, status_code=500)
    return HTMLResponse(content=make_error_html(500, "Internal Breakdown", "Our central nodes encountered an unexpected security hardware error. Please try again later."), status_code=500)


# ── CORS Policy ─────────────────────────────────────────────────────
# Allows requests from localhost and deployed Railway domains (*.railway.app, *.up.railway.app)
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8050",
        "http://127.0.0.1:8050",
    ],
    allow_origin_regex=r"https?://.*(railway\.app|localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Setup Paths
BASE_DIR = os.path.dirname(os.path.dirname(__file__))
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")
ALERTS_DIR = os.path.join(BASE_DIR, "alerts")
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")
VIDEO_PATH = os.path.join(BASE_DIR, "videos", "testing_video3.mp4")

# Ensure directories exist
os.makedirs(ALERTS_DIR, exist_ok=True)
os.makedirs(UPLOADS_DIR, exist_ok=True)
if not os.path.exists(FRONTEND_DIR):
    os.makedirs(FRONTEND_DIR, exist_ok=True)

# Mount static files
app.mount("/frontend", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
app.mount("/alerts", StaticFiles(directory=ALERTS_DIR), name="alerts")

# ── Alert Retention Policy ──────────────────────────────────────────
ALERT_MAX_AGE_DAYS = 7      # Delete snapshots older than 7 days
ALERT_MAX_FILES = 200        # Keep at most 200 newest files
CLEANUP_INTERVAL_HOURS = 6   # Run cleanup every 6 hours

def cleanup_alerts():
    """Remove old alert snapshots based on age and count limits."""
    removed = 0
    now = time.time()
    max_age_seconds = ALERT_MAX_AGE_DAYS * 86400

    # Get all jpg files sorted by modification time (newest first)
    alert_files = glob.glob(os.path.join(ALERTS_DIR, "*.jpg"))
    alert_files.sort(key=os.path.getmtime, reverse=True)

    for i, filepath in enumerate(alert_files):
        file_age = now - os.path.getmtime(filepath)
        # Delete if older than max age OR exceeds file count limit
        if file_age > max_age_seconds or i >= ALERT_MAX_FILES:
            try:
                os.remove(filepath)
                removed += 1
            except OSError:
                pass

    if removed > 0:
        print(f"[CLEANUP] Removed {removed} old alert snapshots.")
    return removed

def _background_cleanup_loop():
    """Background thread that runs cleanup periodically."""
    while True:
        time.sleep(CLEANUP_INTERVAL_HOURS * 3600)
        cleanup_alerts()

# Run cleanup on startup
print("[SERVER] Running alert folder cleanup...")
cleanup_alerts()

# Start background cleanup thread
_cleanup_thread = threading.Thread(target=_background_cleanup_loop, daemon=True)
_cleanup_thread.start()

# Initialize Detectors
live_detector = ObjectDetector(VIDEO_PATH, source_name="testing_video3.mp4")
custom_detector = None # Will be initialized on upload

@app.get("/api/sources")
async def get_sources(user: str = Depends(require_auth)):
    """Scans the videos directory and returns list of available sources including webcams."""
    videos_dir = os.path.join(BASE_DIR, "videos")
    files = glob.glob(os.path.join(videos_dir, "*.mp4"))
    video_sources = [os.path.basename(f) for f in files]
    
    # We can also add "0" for webcam detection
    sources = []
    for source in video_sources:
        sources.append({"id": source, "name": source, "type": "file"})
    sources.append({"id": "0", "name": "Webcam (0)", "type": "device"})
    return {"sources": sources, "current": getattr(live_detector, "source_name", "testing_video3.mp4")}

class SourceUpdate(BaseModel):
    source: str

@app.post("/api/source")
async def update_source(data: SourceUpdate, user: str = Depends(require_auth)):
    global live_detector
    
    source_val = data.source
    source_name = source_val
    
    # Determine the actual path
    if source_val == "0":
        actual_source = 0
        source_name = "Webcam"
    else:
        # Check if the file exists in videos/ or uploads/
        videos_path = os.path.join(BASE_DIR, "videos", source_val)
        uploads_path = os.path.join(BASE_DIR, "uploads", source_val)
        if os.path.exists(videos_path):
            actual_source = videos_path
        elif os.path.exists(uploads_path):
            actual_source = uploads_path
        else:
            return JSONResponse({"error": "Video source file not found"}, status_code=400)
            
    # Release and re-initialize live_detector
    targets = live_detector.target_objects
    threshold = live_detector.confidence_threshold
    email_enabled = notifier.enabled
    
    live_detector.release()
    live_detector = ObjectDetector(actual_source, source_name=source_name)
    live_detector.set_config(targets, threshold, email_enabled)
    
    return {"status": "success", "message": f"Source updated to {source_name}"}


@app.get("/")
async def root():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/frontend/login.html")

@app.get("/api/video_feed")
async def video_feed(token: str = None, authorization: str = Header(None)):
    """Supports both header auth and ?token= query param (needed for <img src>)."""
    auth = authorization or (f"Bearer {token}" if token else None)
    user = verify_token(auth)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    return StreamingResponse(
        live_detector.generate_frames(),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )

@app.post("/api/upload")
async def upload_video(file: UploadFile = File(...), user: str = Depends(require_auth)):
    global custom_detector
    
    # Save uploaded file
    file_path = os.path.join(UPLOADS_DIR, file.filename)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    # Free existing custom detector if one is running
    if custom_detector:
        custom_detector.release()

    # Re-initialize detection on the custom video stream
    custom_detector = ObjectDetector(file_path, source_name=file.filename)
    custom_detector.set_config(
        live_detector.target_objects, 
        live_detector.confidence_threshold, 
        notifier.enabled
    )
    
    return {"status": "success", "message": "Video loaded. Ready for playback.", "filename": file.filename}

class DemoSelectRequest(BaseModel):
    filename: str

@app.post("/api/select_demo")
async def select_demo(data: DemoSelectRequest, user: str = Depends(require_auth)):
    global custom_detector
    
    file_path = os.path.join(BASE_DIR, "videos", data.filename)
    if not os.path.exists(file_path):
        return JSONResponse({"status": "error", "message": "Demo video not found"}, status_code=404)
        
    if custom_detector:
        custom_detector.release()
        
    custom_detector = ObjectDetector(file_path, source_name=data.filename)
    custom_detector.set_config(
        live_detector.target_objects,
        live_detector.confidence_threshold,
        notifier.enabled
    )
    return {"status": "success", "message": f"Demo video {data.filename} loaded.", "filename": data.filename}


@app.get("/api/custom_feed")
async def custom_feed(token: str = None, authorization: str = Header(None)):
    """Supports both header auth and ?token= query param (needed for <img src>)."""
    auth = authorization or (f"Bearer {token}" if token else None)
    user = verify_token(auth)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    
    global custom_detector
    if not custom_detector:
        return JSONResponse({"error": "No custom video loaded"}, status_code=400)
        
    return StreamingResponse(
        custom_detector.generate_frames(),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )

@app.get("/api/alerts")
async def get_alerts(limit: int = 20, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    logs = db.query(AlertLog).order_by(desc(AlertLog.timestamp)).limit(limit).all()
    results = [
        {
            "id": log.id,
            "timestamp": log.timestamp.isoformat() + "Z",
            "object_class": log.object_class,
            "confidence": log.confidence,
            "image_url": f"/alerts/{log.image_path}",
            "source_video": log.source_video
        }
        for log in logs
    ]
    return JSONResponse(content={"alerts": results})

@app.post("/api/config")
async def update_config(request: Request, user: str = Depends(require_auth)):
    data = await request.json()
    targets = data.get("targets", ["person", "car"])
    threshold = data.get("threshold", 0.5)
    email_enabled = data.get("email_enabled", False)
    receiver_email = data.get("receiver_email", "recipient@example.com")
    
    # Update global targets
    live_detector.set_config(targets, threshold, email_enabled)
    if custom_detector:
        custom_detector.set_config(targets, threshold, email_enabled)
        
    notifier.enabled = email_enabled
    notifier.receiver_email = receiver_email
    
    return {"status": "success", "message": "Configuration updated."}

@app.get("/api/config")
async def get_config(user: str = Depends(require_auth)):
    return {
        "targets": live_detector.target_objects,
        "threshold": live_detector.confidence_threshold,
        "email_enabled": notifier.enabled,
        "receiver_email": notifier.receiver_email
    }

class LoginData(BaseModel):
    username: str
    password: str

class ContactData(BaseModel):
    name: str
    email: str
    subject: str
    message: str

@app.post("/api/login")
async def login(data: LoginData, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == data.username).first()
    if not user:
        return JSONResponse({"status": "error", "message": "Invalid credentials"}, status_code=401)
    
    hashed_pw = hashlib.sha256(data.password.encode()).hexdigest()
    if user.password_hash != hashed_pw:
        return JSONResponse({"status": "error", "message": "Invalid credentials"}, status_code=401)
    
    # Generate a real, signed JWT token with 24h expiry
    token = create_jwt_token(data.username)
    return {"status": "success", "token": token, "message": "Login successful"}

@app.post("/api/contact")
async def contact(data: ContactData, db: Session = Depends(get_db)):
    msg = ContactMessage(
        name=data.name,
        email=data.email,
        subject=data.subject,
        message=data.message
    )
    db.add(msg)
    db.commit()
    return {"status": "success", "message": "Message received!"}

@app.get("/api/storage")
async def storage_status(user: str = Depends(require_auth)):
    """Returns alert folder storage stats for the dashboard."""
    alert_files = glob.glob(os.path.join(ALERTS_DIR, "*.jpg"))
    total_bytes = sum(os.path.getsize(f) for f in alert_files)
    total_mb = round(total_bytes / (1024 * 1024), 1)
    return {
        "file_count": len(alert_files),
        "total_size_mb": total_mb,
        "max_files": ALERT_MAX_FILES,
        "retention_days": ALERT_MAX_AGE_DAYS
    }

@app.post("/api/cleanup")
async def manual_cleanup(user: str = Depends(require_auth)):
    """Manually trigger alert folder cleanup."""
    removed = cleanup_alerts()
    return {"status": "success", "removed": removed}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8050))
    print(f"[SERVER] Starting FastAPI Server on port {port}")
    uvicorn.run("backend.api:app", host="0.0.0.0", port=port, reload=False)

