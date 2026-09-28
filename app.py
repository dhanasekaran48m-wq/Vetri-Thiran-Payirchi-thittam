import os
import shutil
import uuid
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

from fastapi import (
    FastAPI, HTTPException, Depends, File, UploadFile, Form, Request, status
)
from fastapi.responses import JSONResponse, RedirectResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from passlib.context import CryptContext
from jose import JWTError, jwt

from gemini_utils import (
    get_home_recommendations, get_party_recommendations, get_jewelry_recommendations
)

app = FastAPI(title="PocketSmart: AI Budget Planner")

SECRET_KEY = os.getenv("SECRET_KEY", "pocket_smart_default_key_2026")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

os.makedirs("static/uploads", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

users_db = {}
active_sessions = {}
blacklisted_tokens = set()
user_recommendations = {}

class RegisterUser(BaseModel):
    username: str
    email: str
    password: str

class HomeBudgetInput(BaseModel):
    total_budget: float
    num_lights: int = 0
    num_fans: int = 0
    num_furniture: int = 0
    num_dining_tables: int = 0
    has_living_room: bool = False
    has_kitchen: bool = False
    has_bedroom: bool = False
    additional_requirements: Optional[str] = None

class PartyBudgetInput(BaseModel):
    total_budget: float
    party_type: str
    num_guests: int
    venue_type: Optional[str] = None
    needs_catering: bool = True
    needs_decoration: bool = True
    needs_entertainment: bool = True
    additional_requirements: Optional[str] = None

class JewelryBudgetInput(BaseModel):
    total_budget: float
    occasion: str
    preferences: Optional[str] = None

class RecommendationHistoryItem(BaseModel):
    id: str
    timestamp: str
    recommendation_type: str
    input_summary: Dict[str, Any]
    result_summary: Dict[str, Any]
    full_result: Dict[str, Any]

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def get_token(request: Request) -> Optional[str]:
    token = request.cookies.get("access_token")
    if token and token in blacklisted_tokens:
        return None
    return token

async def get_current_user(request: Request, token: Optional[str] = Depends(get_token)):
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None or username not in users_db:
            return None
        return users_db[username]
    except JWTError:
        return None

async def get_current_active_user(request: Request, token: Optional[str] = Depends(get_token)):
    user = await get_current_user(request, token)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return user

def save_to_history(username: str, recommendation_type: str, input_data: dict, result: dict):
    if username not in user_recommendations:
        user_recommendations[username] = []
    
    rec_id = str(uuid.uuid4())
    timestamp = datetime.utcnow().strftime("%B %d, %Y %I:%M %p")
    
    item = RecommendationHistoryItem(
        id=rec_id,
        timestamp=timestamp,
        recommendation_type=recommendation_type,
        input_summary=input_data,
        result_summary={
            "total_budget": result.get("total_budget", 0),
            "remaining_budget": result.get("remaining_budget", 0)
        },
        full_result=result
    )
    user_recommendations[username].append(item)

def save_upload_file(upload_file: UploadFile) -> str:
    filename = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{upload_file.filename}"
    file_path = os.path.join("static/uploads", filename)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(upload_file.file, buffer)
    return file_path

@app.get("/", response_class=HTMLResponse)
async def index_page(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    token = await get_token(request)
    if token and await get_current_user(request, token):
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    return templates.TemplateResponse("login.html", {"request": request})

@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})

@app.post("/register")
async def register(user_data: RegisterUser):
    if user_data.username in users_db:
        raise HTTPException(status_code=400, detail="Username already exists")
    users_db[user_data.username] = {
        "username": user_data.username,
        "email": user_data.email,
        "hashed_password": get_password_hash(user_data.password)
    }
    return {"message": "User registered successfully"}

@app.post("/token")
async def login(username: str = Form(...), password: str = Form(...)):
    user = users_db.get(username)
    if not user or not verify_password(password, user["hashed_password"]):
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(data={"sub": username}, expires_delta=access_token_expires)
    
    response = JSONResponse(content={"access_token": access_token, "token_type": "bearer"})
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        samesite="lax"
    )
    
    active_sessions[username] = {
        "username": username,
        "login_time": datetime.utcnow(),
        "last_activity": datetime.utcnow(),
        "user_data": {}
    }
    return response

@app.post("/logout")
async def logout(request: Request):
    token = await get_token(request)
    if token:
        blacklisted_tokens.add(token)
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            username = payload.get("sub")
            if username in active_sessions:
                del active_sessions[username]
        except JWTError:
            pass
    response = RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    response.delete_cookie(key="access_token")
    return response

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, current_user: dict = Depends(get_current_active_user)):
    history = user_recommendations.get(current_user["username"], [])
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "user": current_user,
        "recent_activity": sorted(history, key=lambda x: x.timestamp, reverse=True)[:3]
    })

@app.get("/home-planner", response_class=HTMLResponse)
async def home_planner(request: Request, current_user: dict = Depends(get_current_active_user)):
    return templates.TemplateResponse("home_planner.html", {"request": request, "user": current_user})

@app.post("/home-budget")
async def plan_home_budget(budget_input: HomeBudgetInput, current_user: dict = Depends(get_current_active_user)):
    result = get_home_recommendations(budget_input)
    save_to_history(current_user["username"], "home", budget_input.dict(), result)
    return result

@app.get("/party-planner", response_class=HTMLResponse)
async def party_planner(request: Request, current_user: dict = Depends(get_current_active_user)):
    return templates.TemplateResponse("party_planner.html", {"request": request, "user": current_user})

@app.post("/party-budget")
async def plan_party_budget(budget_input: PartyBudgetInput, current_user: dict = Depends(get_current_active_user)):
    result = get_party_recommendations(budget_input)
    save_to_history(current_user["username"], "party", budget_input.dict(), result)
    return result

@app.get("/jewelry-planner", response_class=HTMLResponse)
async def jewelry_planner(request: Request, current_user: dict = Depends(get_current_active_user)):
    return templates.TemplateResponse("jewelry_planner.html", {"request": request, "user": current_user})

@app.post("/jewelry-budget")
async def plan_jewelry_budget(
    total_budget: float = Form(...),
    occasion: str = Form(...),
    preferences: Optional[str] = Form(None),
    image: Optional[UploadFile] = File(None),
    current_user: dict = Depends(get_current_active_user)
):
    budget_input = JewelryBudgetInput(total_budget=total_budget, occasion=occasion, preferences=preferences)
    image_path = save_upload_file(image) if image else None
    result = get_jewelry_recommendations(budget_input, image_path)
    
    input_data = budget_input.dict()
    if image:
        input_data["image"] = image.filename
        
    save_to_history(current_user["username"], "jewelry", input_data, result)
    return result

@app.get("/history", response_class=HTMLResponse)
async def history_page(request: Request, current_user: dict = Depends(get_current_active_user)):
    return templates.TemplateResponse("history.html", {"request": request, "user": current_user})

@app.get("/recommendation-history")
async def get_recommendation_history(current_user: dict = Depends(get_current_active_user)):
    history = user_recommendations.get(current_user["username"], [])
    sorted_history = sorted(history, key=lambda x: x.timestamp, reverse=True)
    return {"history": [item.dict() for item in sorted_history]}

@app.on_event("startup")
async def setup_session_cleanup():
    async def cleanup_expired_sessions():
        while True:
            current_time = datetime.utcnow()
            expired = [u for u, s in active_sessions.items() if (current_time - s["last_activity"]).total_seconds() > 1800]
            for u in expired:
                del active_sessions[u]
            await asyncio.sleep(300)
    asyncio.create_task(cleanup_expired_sessions())

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)