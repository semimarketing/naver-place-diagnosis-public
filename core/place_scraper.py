# -*- coding: utf-8 -*-
"""
네이버 플레이스 범용 수집 엔진 (Naver Place Universal Scraper)
- 관리 위치: core/place_scraper.py
- 정책 준수: D:/Project Temporary/정책/naver_place_scraping_universal_standard_guide.md
- 지원 항목: 기본 정보, 사장님 소개/스토리, 정제된 요일별 영업시간, 주차/좌석/편의시설, 100% 메뉴판, 실제 방문자 영수증 리뷰, 블로그 찐후기
"""

import os
import sys
import re
import json
import urllib.request
import urllib.parse
from typing import Dict, Any, List

try:
    from core.naver_landmark import fetch_nearby_landmarks
except ImportError:
    from naver_landmark import fetch_nearby_landmarks


if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

def extract_place_id(url_input: str) -> str:
    """다양한 형태의 네이버 플레이스 URL 또는 ID 문자열에서 숫자 Place ID를 추출"""
    if not url_input:
        return ""
    url_str = str(url_input).strip()
    
    # 1. 순수 숫자인 경우
    if url_str.isdigit():
        return url_str

    # 2. naver.me 단축 URL 처리 (302 리다이렉트 추적)
    if 'naver.me' in url_str:
        try:
            req = urllib.request.Request(url_str, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
            with urllib.request.urlopen(req, timeout=5) as resp:
                url_str = resp.geturl()
        except Exception:
            pass

    # 3. 다양한 경로 패턴 정규식 매칭
    patterns = [
        r'/place/(\d+)',
        r'/restaurant/(\d+)',
        r'/hospital/(\d+)',
        r'/hairshop/(\d+)',
        r'/beauty/(\d+)',
        r'/accommodation/(\d+)',
        r'entry=pl[lt].*?place/(\d+)'
    ]
    for pat in patterns:
        m = re.search(pat, url_str)
        if m:
            return m.group(1)
            
    # 4. 쿼리 파라미터 내 id 검출
    m = re.search(r'[?&](?:id|placeId|businessId)=(\d+)', url_str)
    if m:
        return m.group(1)

    return ""

def fetch_apollo_state(url: str) -> Dict[str, Any]:
    """네이버 플레이스 SSR Apollo State JSON 추출"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Referer': 'https://map.naver.com/'
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode('utf-8', errors='ignore')
            match = re.search(r'window\.__APOLLO_STATE__\s*=\s*(\{.+?\});', html)
            if match:
                return json.loads(match.group(1))
    except Exception:
        pass
    return {}

def scrape_naver_place(url_input: str, target_review_count: int = 50) -> Dict[str, Any]:
    """
    네이버 플레이스 종합 정보 수집
    - 기본 매장정보, 영업시간, 편의시설, 메뉴판, 방문자 리뷰 일괄 추출
    """
    place_id = extract_place_id(url_input)
    if not place_id:
        return {"success": False, "error": "올바른 네이버 플레이스 주소 또는 매장 번호를 찾을 수 없습니다."}

    # 1. Apollo State 병합 수집 (PC홈, 상세정보, 메뉴목록, 방문자리뷰, 블로그리뷰)
    pc_home_state = fetch_apollo_state(f'https://pcmap.place.naver.com/restaurant/{place_id}/home')
    info_state = fetch_apollo_state(f'https://pcmap.place.naver.com/restaurant/{place_id}/information')
    menu_state = fetch_apollo_state(f'https://m.place.naver.com/restaurant/{place_id}/menu/list')
    review_state = fetch_apollo_state(f'https://m.place.naver.com/restaurant/{place_id}/review/visitor')
    ugc_review_state = fetch_apollo_state(f'https://m.place.naver.com/restaurant/{place_id}/review/ugc')

    merged_state = {}
    merged_state.update(pc_home_state)
    merged_state.update(info_state)
    merged_state.update(menu_state)
    merged_state.update(review_state)
    merged_state.update(ugc_review_state)

    base_obj = merged_state.get(f"PlaceDetailBase:{place_id}") or {}
    if not base_obj:
        for k, v in merged_state.items():
            if k.startswith("PlaceDetailBase:") or (isinstance(v, dict) and v.get("name") and (v.get("roadAddress") or v.get("address"))):
                base_obj = v
                break

    name = base_obj.get("name", "")
    category = base_obj.get("category", "")
    road_address = base_obj.get("roadAddress", "")
    address = base_obj.get("address", "")
    phone = base_obj.get("phone") or base_obj.get("virtualPhone", "")

    root_query = merged_state.get("ROOT_QUERY", {})
    place_detail_query = None
    for k, v in root_query.items():
        if isinstance(v, dict) and ("houseBanners" in v or "description" in str(k) or "informationTab" in str(k) or "phoneInfo" in v):
            place_detail_query = v
            break

    # 1. 전화번호
    phone = base_obj.get("phone") or base_obj.get("virtualPhone", "")
    if place_detail_query:
        p_info = place_detail_query.get("phoneInfo")
        if isinstance(p_info, dict) and p_info.get("phone"):
            phone = p_info.get("phone")

    # 2. 사장님 스토리텔링 / 소개글
    story_intro = ""
    if place_detail_query:
        for k, v in place_detail_query.items():
            if k.startswith("description(") and isinstance(v, str) and v.strip():
                story_intro = v.strip()
                break
    if not story_intro:
        shop_window = base_obj.get("shopWindow")
        if isinstance(shop_window, dict) and shop_window.get("description"):
            story_intro = shop_window.get("description", "").strip()
        elif base_obj.get("description"):
            story_intro = base_obj.get("description", "").strip()

    # 3. 요일별 영업시간 정제
    cleaned_daily_lines = []
    b_hours_list = []
    if place_detail_query:
        for k, v in place_detail_query.items():
            if (k.startswith("newBusinessHours(") or k.startswith("businessHours(")) and isinstance(v, list) and v:
                for entry in v:
                    if isinstance(entry, dict) and isinstance(entry.get("businessHours"), list):
                        b_hours_list.extend(entry.get("businessHours"))
                    elif isinstance(entry, dict):
                        b_hours_list.append(entry)
                if b_hours_list:
                    break
    if not b_hours_list:
        b_hours_list = base_obj.get("newBusinessHours") or []

    for item in b_hours_list:
        if not isinstance(item, dict): continue
        day_str = item.get("day", "")
        desc = item.get("description", "")
        bh = item.get("businessHours")
        status = item.get("businessStatus")
        last_orders = item.get("lastOrderTimes") or []
        lo_str = ""
        if isinstance(last_orders, list) and last_orders:
            for lo in last_orders:
                if isinstance(lo, dict) and lo.get("time"):
                    lo_str = f" (라스트오더 {lo.get('time')})"
                    break
        elif item.get("lastOrder"):
            lo_str = f" (라스트오더 {item.get('lastOrder')})"

        bt = item.get("breakTime")
        bt_str = f" (브레이크타임 {bt.get('start')}~{bt.get('end')})" if (bt and isinstance(bt, dict) and bt.get('start')) else ""

        if bh and isinstance(bh, dict):
            start = bh.get("start", "")
            end = bh.get("end", "")
            cleaned_daily_lines.append(f"{day_str}: {start} ~ {end}{bt_str}{lo_str}")
        elif desc:
            cleaned_daily_lines.append(f"{day_str}: {desc}")
        elif status:
            cleaned_daily_lines.append(f"{day_str}: {status}")

    regular_closures = base_obj.get("regularClosureList") or []
    if isinstance(regular_closures, list) and regular_closures:
        closures_str = ", ".join([c.get("day", "") for c in regular_closures if isinstance(c, dict) and c.get("day")])
        if closures_str:
            cleaned_daily_lines.append(f"정기휴무: {closures_str}")

    daily_biz_hours = "\n".join(cleaned_daily_lines)

    # 4. 주차, 반려동물, 편의시설 (좌석/결제수단은 사용자 요청으로 제외)
    parking_info_str = ""
    pet_info_str = ""
    
    info_tab_data = None
    if place_detail_query:
        for k, v in place_detail_query.items():
            if k.startswith("informationTab(") and isinstance(v, dict):
                info_tab_data = v
                break

    if info_tab_data:
        # 주차 파싱
        p_data = info_tab_data.get("parkingInfo")
        if isinstance(p_data, dict):
            p_desc = p_data.get("description", "")
            bp = p_data.get("basicParking") or {}
            norm_fee = bp.get("normalFeeDescription", "")
            extra_fee = bp.get("extraFeeDescription", "")
            fee_parts = [f for f in [norm_fee, extra_fee] if f]
            fee_summary = f"({', '.join(fee_parts)})" if fee_parts else ""
            
            p_lines = []
            if fee_summary:
                p_lines.append(f"주차 가능 {fee_summary}")
            if p_desc:
                p_lines.append(p_desc.replace("\n", " / "))
            parking_info_str = " - ".join(p_lines)

        # 반려동물 파싱
        pet_data = info_tab_data.get("pet")
        if isinstance(pet_data, dict):
            is_allowed = pet_data.get("isAllowed")
            pet_desc = pet_data.get("description")
            if is_allowed is False:
                pet_info_str = "반려동물 동반 불가"
            elif is_allowed is True:
                pet_info_str = f"반려동물 동반 가능{f' ({pet_desc})' if pet_desc else ''}"

    if not parking_info_str:
        parking_info = base_obj.get("parking")
        parking_info_str = parking_info if isinstance(parking_info, str) else ("무료 주차 지원" if parking_info else "")

    # 오시는 길 안내
    directions = base_obj.get("road", "") or base_obj.get("directions", "") or ""
    if not directions:
        for k, v in merged_state.items():
            if isinstance(v, dict) and v.get("directions"):
                directions = v.get("directions")
                break

    # 지번 주소
    jibun_address = base_obj.get("address", "")

    # 편의시설 파싱
    facilities = []
    base_conv = base_obj.get("conveniences") or []
    if isinstance(base_conv, list):
        for c in base_conv:
            if isinstance(c, str) and c not in facilities and c not in ["간편결제", "지역화폐", "제로페이"]:
                facilities.append(c)

    for k, v in merged_state.items():
        if k.startswith("InformationFacilities:") and isinstance(v, dict):
            f_name = v.get("name")
            if f_name and f_name not in facilities:
                facilities.append(f_name)

    # 5. 메뉴 파싱 (정책 가이드: 기본 메뉴판 + 실시간 스마트주문/포장 신메뉴 100% 하이브리드 병합)
    menus = []
    seen_menu_names = set()
    
    # 5-1. Apollo State 내 Menu:, NaverOrderItem:, OrderMenu:, MenuDetail: 전체 스캔
    for k, v in merged_state.items():
        if (k.startswith("Menu:") or k.startswith("NaverOrderItem:") or k.startswith("OrderMenu:") or k.startswith("MenuDetail:") or k.startswith("OrderMenuItem:")) and isinstance(v, dict):
            m_name = v.get("name") or v.get("menuName") or v.get("title")
            if m_name and str(m_name).strip():
                clean_name = str(m_name).strip()
                if clean_name not in seen_menu_names:
                    seen_menu_names.add(clean_name)
                    price = v.get("price") or v.get("dealPrice") or v.get("discountPrice") or v.get("basePrice")
                    price_str = f"{int(price):,}원" if (price and str(price).isdigit()) else str(price or "변동")
                    desc = v.get("description") or v.get("desc") or ""
                    is_rec = v.get("isRecommended") or v.get("isSignature") or v.get("isPopular") or v.get("isBest") or False
                    menus.append({
                        "name": clean_name,
                        "price": price_str,
                        "description": desc,
                        "isRecommended": bool(is_rec)
                    })

    # 5-2. placeDetailQuery의 menus(...) 배열 스캔
    if place_detail_query:
        for k, v in place_detail_query.items():
            if k.startswith("menus(") and isinstance(v, list):
                for m_item in v:
                    if isinstance(m_item, dict):
                        m_name = m_item.get("name") or m_item.get("menuName")
                        if m_name and str(m_name).strip():
                            clean_name = str(m_name).strip()
                            if clean_name not in seen_menu_names:
                                seen_menu_names.add(clean_name)
                                price = m_item.get("price")
                                price_str = f"{int(price):,}원" if (price and str(price).isdigit()) else str(price or "변동")
                                menus.append({
                                    "name": clean_name,
                                    "price": price_str,
                                    "description": m_item.get("description", ""),
                                    "isRecommended": bool(m_item.get("isRecommended", False))
                                })

    # 6. 실제 방문자 영수증 리뷰 및 블로그 후기 파싱 (GraphQL API 50개 고품질 우선 수집)
    collected_reviews = []
    seen_bodies = set()
    all_keywords = {}

    # 6-1. GraphQL Direct Session API로 실시간 50개 리뷰 페이지네이션 수집
    try:
        import requests
        s = requests.Session()
        s.headers.update({
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1',
            'Referer': f'https://m.place.naver.com/restaurant/{place_id}/review/visitor'
        })
        s.get(f'https://m.place.naver.com/restaurant/{place_id}/review/visitor', timeout=5)

        for page in range(1, 4):
            if len(collected_reviews) >= target_review_count * 2:
                break
            payload = [{
                'operationName': 'getVisitorReviews',
                'variables': {
                    'input': {
                        'businessId': place_id,
                        'businessType': 'restaurant',
                        'page': page,
                        'size': 50,
                        'isPhotoUsed': False,
                        'includeContent': True
                    }
                },
                'query': 'query getVisitorReviews($input: VisitorReviewsInput) { visitorReviews(input: $input) { items { id rating body author { nickname } visited item { name } votedKeywords { name } media { type } } total } }'
            }]

            r = s.post('https://api.place.naver.com/graphql', json=payload, timeout=8)
            if r.status_code != 200:
                break
            res_data = r.json()
            items = res_data[0].get('data', {}).get('visitorReviews', {}).get('items', [])
            if not items:
                break
            for it in items:
                body = (it.get('body') or '').strip()
                if body and body not in seen_bodies:
                    seen_bodies.add(body)
                    rating = it.get('rating') if it.get('rating') is not None else 5.0
                    v_kws = [vk.get('name') for vk in (it.get('votedKeywords') or []) if isinstance(vk, dict) and vk.get('name')]
                    for vk in v_kws:
                        all_keywords[vk] = all_keywords.get(vk, 0) + 1
                    has_photo = bool(it.get('media'))
                    collected_reviews.append({
                        'id': it.get('id', ''),
                        'type': 'receipt',
                        'rating': rating,
                        'visited': it.get('visited', ''),
                        'author': it.get('author', {}).get('nickname', '방문자') if it.get('author') else '방문자',
                        'orderedItem': it.get('item', {}).get('name') if isinstance(it.get('item'), dict) else None,
                        'body': body,
                        'hasPhoto': has_photo,
                        'keywords': v_kws,
                        'purposes': []
                    })
    except Exception as e:
        print(f"[GraphQL Reviews] API 수집 폴백 전환: {e}")

    # 6-2. Apollo State 보조 병합 (블로그 리뷰 및 추가 영수증)
    for k, v in merged_state.items():
        if k.startswith("VisitorReview:") and isinstance(v, dict):
            body = (v.get("body") or "").strip()
            rating = v.get("rating", 5)
            visited = v.get("visited", "")
            ordered_item = v.get("item", {}).get("name") if isinstance(v.get("item"), dict) else None
            
            # 투표 키워드
            voted_kws = []
            for vk in v.get("votedKeywords") or []:
                if isinstance(vk, dict) and vk.get("name"):
                    kw_name = vk.get("name")
                    voted_kws.append(kw_name)
                    all_keywords[kw_name] = all_keywords.get(kw_name, 0) + 1

            # 방문 카테고리 (데이트, 가족모임 등)
            visit_purposes = []
            for vc in v.get("visitCategories") or []:
                if isinstance(vc, dict):
                    for vck in vc.get("keywords") or []:
                        if isinstance(vck, dict) and vck.get("name"):
                            visit_purposes.append(vck.get("name"))

            if body and body not in seen_bodies:
                seen_bodies.add(body)
                has_photo = bool(v.get("media") or v.get("images") or v.get("imageCount"))
                collected_reviews.append({
                    "id": v.get("id", ""),
                    "type": "receipt",
                    "rating": rating,
                    "visited": visited,
                    "orderedItem": ordered_item,
                    "body": body,
                    "hasPhoto": has_photo,
                    "keywords": voted_kws,
                    "purposes": visit_purposes
                })
        elif k.startswith("FsasReview:") and isinstance(v, dict):
            title = (v.get("title") or "").strip()
            desc = (v.get("contents") or v.get("description") or "").strip()
            combined = f"{title}\n{desc}".strip()
            if combined and combined not in seen_bodies:
                seen_bodies.add(combined)
                collected_reviews.append({
                    "id": v.get("id", ""),
                    "type": "blog",
                    "rating": 5,
                    "visited": v.get("date", ""),
                    "orderedItem": None,
                    "body": combined,
                    "keywords": [],
                    "purposes": []
                })

    # 스마트 정렬 (1순위 별점 높은 순, 2순위 부정 단어 감점 격리, 3순위 본문 길이 순)
    negative_words = ['다신 안', '불친절', '최악', '비추', '기대이하', '돈아깝', '맛없', '실망', '위생 별로']
    def review_sort_key(r):
        body = r.get('body', '')
        penalty = 3.0 if any(w in body for w in negative_words) else 0.0
        base_score = float(r.get('rating') if r.get('rating') is not None else 5.0)
        return (max(0.0, base_score - penalty), len(body))

    collected_reviews.sort(key=review_sort_key, reverse=True)
    final_reviews = collected_reviews[:target_review_count]

    sorted_keywords = sorted(all_keywords.items(), key=lambda x: x[1], reverse=True)
    top_keywords = [k[0] for k in sorted_keywords[:15]]

    # 주변 랜드마크 (학교/역/아파트) 자동 탐색
    addr_for_search = road_address or address
    nearby_landmarks = fetch_nearby_landmarks(addr_for_search, category=category, store_name=name) if addr_for_search else []

    menus_formatted = [f"• {m['name']}: {m['price']}" + (f" ({m['description']})" if m['description'] else "") for m in menus]
    
    sample_reviews_text = []
    for idx, r in enumerate(final_reviews[:20], 1):
        item_text = f" [주문메뉴: {r['orderedItem']}]" if r.get('orderedItem') else ""
        sample_reviews_text.append(f"{idx}. ({r.get('visited', '')}){item_text}\n\"{r['body']}\"")

    # 7. 네이버 공인 빅데이터 통계 및 총 리뷰 수 추출
    visitor_reviews_total = int(base_obj.get("visitorReviewsTotal") or 0)
    blog_reviews_total = int(base_obj.get("cafeBlogReviewsTotal") or 0)

    stats_obj = merged_state.get(f"VisitorReviewStatsResult:{place_id}") or {}
    analysis_obj = stats_obj.get("analysis") or {}

    official_themes = analysis_obj.get("themes") or []
    official_menus = analysis_obj.get("menus") or []
    voted_details = analysis_obj.get("votedKeyword", {}).get("details") or []
    official_voted_kws = [{"name": v.get("displayName"), "count": v.get("count")} for v in voted_details if v.get("displayName")]

    if not visitor_reviews_total and stats_obj.get("visitorReviewsTotal"):
        visitor_reviews_total = int(stats_obj.get("visitorReviewsTotal"))

    return {
        "success": True,
        "data": {
            "placeId": place_id,
            "storeName": name or f"매장_{place_id}",
            "category": category,
            "address": road_address or address,
            "roadAddress": road_address,
            "jibunAddress": jibun_address,
            "directions": directions,
            "phone": phone,
            "dailyBusinessHours": daily_biz_hours,
            "parkingInfo": parking_info_str,
            "petInfo": pet_info_str,
            "facilitiesInfo": ", ".join(facilities),
            "storyIntro": story_intro,
            "menus": menus,
            "menusFormatted": "\n".join(menus_formatted),
            "topKeywords": top_keywords,
            "nearbyLandmarks": nearby_landmarks,
            "reviews": final_reviews,
            "reviewCount": len(final_reviews),
            "visitorReviewsTotal": visitor_reviews_total,
            "blogReviewsTotal": blog_reviews_total,
            "officialThemes": official_themes,
            "officialMenus": official_menus,
            "officialVotedKeywords": official_voted_kws,
            "sampleReviewsFormatted": "\n\n".join(sample_reviews_text)
        }
    }


if __name__ == '__main__':
    test_target = sys.argv[1] if len(sys.argv) > 1 else '18215277'
    res = scrape_naver_place(test_target, 20)
    print(json.dumps(res, ensure_ascii=False, indent=2))
