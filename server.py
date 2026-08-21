# -*- coding: utf-8 -*-
"""
네이버 플레이스 30초 정밀 진단 공개 API & 세미마케팅 간편상담 수신 서버 (FastAPI)
- 실행 위치: server.py
- 특징:
  1. Google API 완전 대체 ($0원 무료 운영)
  2. IP 기반 Rate Limiting (10분당 3회 제한)
  3. 24시간 인메모리 결과 캐싱
  4. 홈페이지 간편상담 접수 API (/api/contact) -> 텔레그램 실시간 푸시(0.1초) + 이메일(SMTP) 자동 발송
"""

import os
import sys
import time
import json
import uvicorn
import smtplib
import urllib.request
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from collections import defaultdict
from typing import Dict, Any, List
from fastapi import FastAPI, Request, HTTPException, status
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, CURRENT_DIR)

from core.place_diagnosis import diagnose_place, extract_place_id

app = FastAPI(title="세미마케팅 통합 백엔드 API", version="1.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------
# 1. IP 기반 Rate Limiting (10분 = 600초 내 3회 조회 허용)
# ---------------------------------------------------------
RATE_LIMIT_WINDOW = 600  # 10분 (초)
RATE_LIMIT_MAX_REQUESTS = 3  # 3회

ip_request_history: Dict[str, List[float]] = defaultdict(list)

# ---------------------------------------------------------
# 2. 24시간 인메모리 캐시
# ---------------------------------------------------------
CACHE_TTL = 86400  # 24시간 (초)
diagnosis_cache: Dict[str, Dict[str, Any]] = {}


def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"


def check_rate_limit(ip: str) -> Dict[str, Any]:
    now = time.time()
    valid_timestamps = [t for t in ip_request_history[ip] if now - t < RATE_LIMIT_WINDOW]
    ip_request_history[ip] = valid_timestamps
    
    remaining = max(0, RATE_LIMIT_MAX_REQUESTS - len(valid_timestamps))
    
    if len(valid_timestamps) >= RATE_LIMIT_MAX_REQUESTS:
        oldest = valid_timestamps[0]
        retry_after = int(RATE_LIMIT_WINDOW - (now - oldest))
        return {
            "allowed": False,
            "remaining": 0,
            "retry_after": max(1, retry_after),
            "is_local": False
        }
    
    return {
        "allowed": True,
        "remaining": remaining,
        "retry_after": 0,
        "is_local": False
    }


def record_request(ip: str):
    ip_request_history[ip].append(time.time())


class DiagnoseRequest(BaseModel):
    url: str


class ContactRequest(BaseModel):
    company: str
    phone: str
    message: str


@app.get("/api/rate-limit-status")
async def get_rate_limit_status(request: Request):
    ip = get_client_ip(request)
    status_info = check_rate_limit(ip)
    return JSONResponse(status_info)


@app.post("/api/diagnose")
async def run_diagnose(req: DiagnoseRequest, request: Request):
    ip = get_client_ip(request)
    
    rate_info = check_rate_limit(ip)
    if not rate_info["allowed"]:
        return JSONResponse(
            status_code=429,
            content={
                "success": False,
                "error": f"조회 한도를 초과했습니다. (10분에 최대 3회 가능)\n약 {rate_info['retry_after'] // 60}분 {rate_info['retry_after'] % 60}초 후에 다시 시도해 주세요.",
                "retry_after": rate_info["retry_after"],
                "remaining": 0
            }
        )
    
    url_input = (req.url or "").strip()
    place_id = extract_place_id(url_input)
    if not place_id:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "올바른 네이버 플레이스 주소 또는 매장 번호를 입력해 주세요."}
        )
    
    now = time.time()
    if place_id in diagnosis_cache:
        cached = diagnosis_cache[place_id]
        if now - cached["timestamp"] < CACHE_TTL:
            record_request(ip)
            new_rate = check_rate_limit(ip)
            return JSONResponse({
                "success": True,
                "cached": True,
                "data": cached["data"],
                "remaining": new_rate["remaining"]
            })
    
    res = diagnose_place(url_input)
    if not res.get("success"):
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": res.get("error", "진단 중 오류가 발생했습니다.")}
        )
    
    diagnosis_cache[place_id] = {
        "timestamp": now,
        "data": res["data"]
    }
    
    record_request(ip)
    new_rate = check_rate_limit(ip)
    
    return JSONResponse({
        "success": True,
        "cached": False,
        "data": res["data"],
        "remaining": new_rate["remaining"]
    })


# ---------------------------------------------------------
# 3. 📧 세미마케팅 홈페이지 간편상담 접수 API (/api/contact)
#    (텔레그램 실시간 0.1초 알림 + Gmail/Naver SMTP 이메일 발송)
# ---------------------------------------------------------
@app.post("/api/contact")
async def handle_contact_submit(req: ContactRequest):
    company = (req.company or "").strip()
    phone = (req.phone or "").strip()
    msg = (req.message or "").strip()

    if not company or not phone or not msg:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "업체명, 연락처, 문의 내용을 모두 입력해 주세요."}
        )

    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # [1] 텔레그램 실시간 알림 발송 (0.1초)
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "8159691058:AAHPfJjHU6O8jR7o703Mt-CjlWGJB5hBf1E")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "-5222649599")
    
    tg_text = (
        f"🔔 [세미마케팅] 홈페이지 신규 간편상담 접수\n\n"
        f"🏢 업체명: {company}\n"
        f"📞 연락처: {phone}\n"
        f"⏰ 접수일시: {now_str}\n\n"
        f"📝 문의 내용:\n{msg}"
    )

    telegram_sent = False
    try:
        tg_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        tg_payload = json.dumps({
            "chat_id": chat_id,
            "text": tg_text
        }).encode('utf-8')
        
        tg_req = urllib.request.Request(
            tg_url,
            data=tg_payload,
            headers={'Content-Type': 'application/json'}
        )
        with urllib.request.urlopen(tg_req, timeout=5) as response:
            if response.status == 200:
                telegram_sent = True
    except Exception as e:
        print(f"[Telegram Alert Error] {e}")

    # [2] 이메일 SMTP 발송 (STARTTLS 587 -> SSL 465)
    email_sent = False
    smtp_user = os.getenv("SMTP_USER", "mainkoapp@gmail.com")
    smtp_pass = os.getenv("SMTP_PASS", "srbhopjjnqeeyaah").replace(" ", "")
    to_email = os.getenv("RECEIVE_EMAIL", "semimkt.cs@gmail.com")

    try:
        mail = MIMEMultipart()
        mail['Subject'] = f"[세미마케팅] {company}님의 간편상담 신청이 접수되었습니다."
        mail['From'] = f"세미마케팅 알리미 <{smtp_user}>"
        mail['To'] = to_email

        body_html = f"""
        <div style="font-family: 'Apple SD Gothic Neo', 'Malgun Gothic', sans-serif; max-width: 600px; margin: 0 auto; padding: 25px; border: 1px solid #E2E8F0; border-radius: 10px; background: #FFFFFF;">
          <h2 style="color: #0066FF; margin-top: 0; border-bottom: 2px solid #0066FF; padding-bottom: 12px;">[세미마케팅] 홈페이지 간편상담 접수</h2>
          <table style="width: 100%; border-collapse: collapse; margin-top: 20px; font-size: 15px;">
            <tr style="border-bottom: 1px solid #F1F5F9;">
              <td style="padding: 10px 0; font-weight: bold; color: #475569; width: 100px;">• 업체명</td>
              <td style="padding: 10px 0; color: #0F172A; font-weight: 800;">{company}</td>
            </tr>
            <tr style="border-bottom: 1px solid #F1F5F9;">
              <td style="padding: 10px 0; font-weight: bold; color: #475569;">• 연락처</td>
              <td style="padding: 10px 0; color: #0066FF; font-weight: 800;">{phone}</td>
            </tr>
            <tr style="border-bottom: 1px solid #F1F5F9;">
              <td style="padding: 10px 0; font-weight: bold; color: #475569;">• 접수일시</td>
              <td style="padding: 10px 0; color: #64748B;">{now_str}</td>
            </tr>
          </table>
          <div style="margin-top: 20px;">
            <p style="font-weight: bold; color: #475569; margin-bottom: 8px;">• 문의 내용:</p>
            <div style="background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 6px; padding: 15px; font-size: 14px; line-height: 1.6; color: #1E293B; white-space: pre-wrap;">{msg}</div>
          </div>
          <div style="margin-top: 30px; font-size: 12px; color: #94A3B8; text-align: center; border-top: 1px solid #F1F5F9; padding-top: 15px;">
            본 메일은 세미마케팅 공식 웹사이트(mkt.mainko.net)에서 고객이 직접 전송한 간편상담 알림 메일입니다.
          </div>
        </div>
        """
        mail.attach(MIMEText(body_html, 'html', 'utf-8'))

        try:
            with smtplib.SMTP("smtp.gmail.com", 587, timeout=8) as server:
                server.starttls()
                server.login(smtp_user, smtp_pass)
                server.send_message(mail)
                email_sent = True
        except Exception:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=8) as server:
                server.login(smtp_user, smtp_pass)
                server.send_message(mail)
                email_sent = True
    except Exception as e:
        print(f"[Email SMTP Error] {e}")

    return JSONResponse({
        "success": True,
        "message": "상담 신청이 성공적으로 접수되었습니다.",
        "telegram_sent": telegram_sent,
        "email_sent": email_sent
    })


@app.get("/")
async def serve_index():
    return RedirectResponse(url="https://naver-place-diagnosis.pages.dev", status_code=301)


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "SEMI MARKETING Backend & Notification Engine"}


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=False)