# -*- coding: utf-8 -*-
"""
네이버 지역 자동완성 및 주소 기반 주변 랜드마크(학교/역/아파트) 자동 탐색 모듈 (독립 공개용)
- 관리 위치: core/naver_landmark.py
- 탐색 대상: 인근 초·중·고등학교, 지하철역, 주요 사거리/광장, 대단지 아파트
"""

import os
import sys
import re
import json
import urllib.request
import urllib.parse
from typing import List, Dict, Any, Optional

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def extract_area_keywords(address: str) -> Dict[str, str]:
    clean_addr = address.strip()
    special_region = ""
    for reg in ["동탄", "위례", "송도", "청라", "일산", "분당", "판교", "평촌", "산본", "광교", "미사", "다산"]:
        if reg in clean_addr:
            special_region = reg
            break

    dong_match = re.search(r'([가-힣]+(?:동|읍|면|가))', clean_addr)
    gu_match = re.search(r'([가-힣]+(?:구|군|시))', clean_addr)
    ro_match = re.search(r'([가-힣\d]+(?:로|길))', clean_addr)

    dong = dong_match.group(1) if dong_match else ""
    gu = gu_match.group(1) if gu_match else ""
    ro = ro_match.group(1) if ro_match else ""
    base_ro = re.sub(r'\d+.*', '', ro).strip()

    return {
        "dong": dong,
        "gu": gu,
        "ro": base_ro,
        "special": special_region,
        "full": clean_addr
    }


def clean_place_title(raw_title: str) -> str:
    title = re.sub(r'<[^>]+>', '', raw_title).strip()
    title = re.sub(r'^(지진옥외대피장소|대피소|민방위대피소|임시선별진료소|무인민원발급기)\s*', '', title).strip()
    title = re.split(r'[\(\[\{]', title)[0].strip()
    title = re.sub(r'\s+(체육관|운동장|도서관|급식실|부설.*)$', '', title).strip()
    return title


def search_naver_open_places(query: str, display: int = 5) -> List[Dict[str, str]]:
    headers = {
        'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15',
        'Referer': 'https://m.naver.com'
    }
    found_items = []
    try:
        encoded = urllib.parse.quote(query.strip())
        url = f"https://ac.search.naver.com/nx/ac?q={encoded}&con=1&frm=nv&ans=2&r_format=json&r_enc=UTF-8&r_unicode=0&t_koreng=1&run=2&rev=4&q_enc=UTF-8&st=100"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            for group in data.get("items", []):
                for item in group:
                    name = ""
                    if isinstance(item, list) and item and isinstance(item[0], str):
                        name = item[0]
                    elif isinstance(item, str):
                        name = item
                    if name and len(name) >= 2:
                        found_items.append({"name": clean_place_title(name), "category": "공공/지역"})
    except Exception:
        pass
    return found_items[:display]


def fetch_nearby_landmarks(address: str, category: str = "", store_name: str = "") -> List[str]:
    area_info = extract_area_keywords(address)
    dong = area_info.get("dong")
    gu = area_info.get("gu")
    ro = area_info.get("ro")
    special = area_info.get("special")

    location_prefixes = []
    if special and dong:
        location_prefixes.append(f"{special} {dong}")
    if dong:
        location_prefixes.append(dong)
    elif ro:
        location_prefixes.append(ro)
    elif gu:
        location_prefixes.append(gu)

    if not location_prefixes:
        location_prefixes = [address.split()[0] if address else ""]

    search_queries = []
    for prefix in location_prefixes[:2]:
        search_queries.append(f"{prefix} 고등학교")
        search_queries.append(f"{prefix} 중학교")
        search_queries.append(f"{prefix} 초등학교")
        search_queries.append(f"{prefix} 아파트")
        search_queries.append(f"{prefix} 역")

    landmarks = []
    seen = set()
    for q in search_queries:
        for it in search_naver_open_places(q, display=2):
            name = it["name"]
            if name and name not in seen and name != store_name:
                seen.add(name)
                landmarks.append(name)
        if len(landmarks) >= 10:
            break

    return landmarks[:10]