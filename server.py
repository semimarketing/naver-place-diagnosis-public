# -*- coding: utf-8 -*-
"""
네이버 플레이스 30초 무료 정밀 진단 전용 서버 (FastAPI)
- 관리 위치: server.py
- 특징:
  1. Google API 일체 미사용 ($0원 무부하 운영)
  2. IP 기반 Rate Limiting (10분당 3회 제한)
  3. 24시간 인메모리 진단 결과 캐싱 (중복 조회 즉시 응답)
  4. 외부 공개용 단일 페이지 UI 제공
"""

import os
import sys
import time
import json
import uvicorn
from collections import defaultdict
from typing import Dict, Any, List
from fastapi import FastAPI, Request, HTTPException, status
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
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

app = FastAPI(title="네이버 플레이스 30초 정밀 진단", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------
# 1. IP 기반 Rate Limiting (10분 = 600초 동안 3회 조회 허용)
# ---------------------------------------------------------
RATE_LIMIT_WINDOW = 600  # 10분 (초)
RATE_LIMIT_MAX_REQUESTS = 3  # 3회

# ip -> list of timestamps
ip_request_history: Dict[str, List[float]] = defaultdict(list)

# ---------------------------------------------------------
# 2. 24시간 인메모리 캐싱 (동일 매장 중복 스크래핑 방지)
# ---------------------------------------------------------
CACHE_TTL = 86400  # 24시간 (초)
diagnosis_cache: Dict[str, Dict[str, Any]] = {}


def get_client_ip(request: Request) -> str:
    """프록시/클라우드 환경(X-Forwarded-For) 고려 클라이언트 IP 추출"""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"


def is_local_ip(ip: str) -> bool:
    """로컬호스트 및 개발 환경 IP 판별 (제한 없이 무제한 이용 허용)"""
    return ip in ["127.0.0.1", "localhost", "::1", "testclient"] or ip.startswith("192.168.") or ip.startswith("10.")


def check_rate_limit(ip: str) -> Dict[str, Any]:
    """Rate Limit 검사: 모든 사용자 10분 내 3회 초과 시 엄격 차단"""
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


@app.get("/api/rate-limit-status")
async def get_rate_limit_status(request: Request):
    """현재 접속 IP의 잔여 조회 가능 횟수 확인"""
    ip = get_client_ip(request)
    status_info = check_rate_limit(ip)
    return JSONResponse(status_info)


@app.post("/api/diagnose")
async def run_diagnose(req: DiagnoseRequest, request: Request):
    """플레이스 30초 정밀 진단 API"""
    ip = get_client_ip(request)
    
    # 1. Rate Limit 체크
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
    
    # 2. 캐시 확인
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
    
    # 3. 진단 실행
    res = diagnose_place(url_input)
    if not res.get("success"):
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": res.get("error", "진단 중 오류가 발생했습니다.")}
        )
    
    # 캐시 저장
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
# 정적 웹 파일 서빙
# ---------------------------------------------------------
web_dir = os.path.join(CURRENT_DIR, "web")
if os.path.exists(web_dir):
    app.mount("/static", StaticFiles(directory=web_dir), name="static")

@app.get("/")
async def serve_index():
    index_path = os.path.join(web_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path, media_type="text/html")
    return HTMLResponse("<h1>네이버 플레이스 정밀 진단 시스템</h1>")


@app.get("/robots.txt")
async def serve_robots():
    robots_path = os.path.join(web_dir, "robots.txt")
    if os.path.exists(robots_path):
        return FileResponse(robots_path, media_type="text/plain")
    return HTMLResponse("User-agent: *\nAllow: /\n", media_type="text/plain")


@app.get("/sitemap.xml")
async def serve_sitemap():
    sitemap_path = os.path.join(web_dir, "sitemap.xml")
    if os.path.exists(sitemap_path):
        return FileResponse(sitemap_path, media_type="application/xml")
    return HTMLResponse("<urlset></urlset>", media_type="application/xml")


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=False)