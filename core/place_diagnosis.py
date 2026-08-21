# -*- coding: utf-8 -*-
"""
네이버 플레이스 30초 정밀 진단 엔진 (독립 공개용 / Google API 100% 미사용 / 순수 알고리즘 + 네이버 실시간 분석)
- 관리 위치: core/place_diagnosis.py
- 기능: 7대 핵심 노출 지표 산출 (100점 만점), 방문자 반응 키워드 통계, 리뷰 본문 형태소 토픽, 주요 테마 만족도, 보강 추천 키워드 추천
"""

import re
import math
import json
import urllib.request
import urllib.parse
from typing import Dict, Any, List
from collections import Counter

try:
    from core.place_scraper import scrape_naver_place, extract_place_id
except ImportError:
    from place_scraper import scrape_naver_place, extract_place_id

# 1. 업종별 테마 키워드 사전
FOOD_THEMES = {
    "맛": ["맛있", "존맛", "꿀맛", "미쳤", "풍미", "신선", "육즙", "감칠맛", "간이 맞", "간맞", "간간하", "소스", "양념", "식감", "부드럽", "쫄깃", "담백", "고소", "바삭", "얼큰", "달콤", "매콤"],
    "만족도": ["만족", "추천", "최고", "재방문", "대만족", "단골", "강추", "인생", "또갈", "또올", "힐링", "완벽", "기분좋", "인정"],
    "서비스": ["친절", "서비스", "사장님", "직원", "배려", "미소", "설명", "친절하", "센스", "친근", "상냥", "안내", "대응"],
    "분위기": ["분위기", "깔끔", "청결", "쾌적", "인테리어", "예쁘", "감성", "뷰", "조명", "음악", "넓", "조용", "아늑", "고급", "깨끗", "좌석"],
    "가격": ["가성비", "합리적", "저렴", "푸짐", "양많", "넉넉", "착한가격", "혜자", "양도", "배부", "가성비갑", "값어치"],
    "편의/위치": ["주차", "역세권", "근처", "접근성", "화장실", "예약", "단체", "모임", "회식", "데이트", "가족", "포장", "배달", "편리"]
}

STUDY_THEMES = {
    "학습환경/시설": ["쾌적", "깔끔", "청결", "인테리어", "시설", "의자", "책상", "시디즈", "조명", "백색소음", "환기", "온도", "넓", "깨끗"],
    "면학분위기": ["조용", "집중", "면학", "몰입", "순공", "관리형", "열공", "자율", "엄격", "출결", "스파르타", "방해 없는"],
    "서비스/관리": ["친절", "관리", "피드백", "상담", "원장", "선생님", "멘토", "체계적", "질문", "케어", "대응", "안내"],
    "만족도": ["만족", "추천", "최고", "재등록", "합격", "성적", "향상", "효과", "강추", "인정", "대만족", "열심히"],
    "가격/비용": ["가성비", "합리적", "저렴", "패키지", "이벤트", "할인", "값어치", "부담 없는", "착한가격"],
    "편의/위치": ["주차", "역세권", "근처", "접근성", "휴게실", "화장실", "사물함", "프린트", "간식", "음료", "교통", "편리"]
}

GENERAL_THEMES = {
    "전문성/실력": ["실력", "전문", "꼼꼼", "효과", "맞춤", "디테일", "노하우", "손길", "경력", "원장", "선생님", "완벽"],
    "시설/청결": ["청결", "깨끗", "쾌적", "인테리어", "시설", "최신", "기구", "위생", "소독", "룸", "프라이빗", "넓"],
    "친절/서비스": ["친절", "설명", "상냥", "안내", "미소", "배려", "정성", "대응", "서비스", "친근"],
    "만족도": ["만족", "추천", "최고", "재방문", "단골", "인생", "대만족", "힐링", "완벽", "기분좋", "인정"],
    "가격/비용": ["가성비", "합리적", "저렴", "정찰제", "과잉 없는", "투명", "값어치", "혜택", "이벤트"],
    "편의/위치": ["주차", "예약", "역세권", "야간", "접근성", "편리", "위치", "대기", "교통"]
}

# 2. 불용어
STOPWORDS = {
    "너무", "정말", "진짜", "있고", "가서", "ㅎㅎ", "ㅠㅠ", "조금", "많이", "그냥", "다시",
    "곳이", "매장", "가게", "방문", "여기", "먹고", "좋고", "좋은", "하고", "해서", "저는",
    "오늘", "어제", "이번", "처음", "같이", "하나", "두개", "우리", "모두", "완전", "직접",
    "바로", "항상", "계속", "제일", "가장", "정도", "이런", "저런", "보고", "다른", "생각"
}

# 3. 업종별 추천 키워드 풀
CATEGORY_INTENT_KEYWORDS = {
    "고기": ["부평 회식", "구워주는 고기집", "단체 모임", "가성비 맛집", "육즙 가득", "데이트 코스", "점심 특선", "구이 전문점"],
    "한식": ["정갈한 한상", "점심 밥집", "가족 외식", "집밥 느낌", "모임 장소", "가성비 한식", "건강한 식사", "단체 회식"],
    "일식": ["신선한 오마카세", "데이트 맛집", "혼밥 추천", "초밥 맛집", "이자카야", "사케 모임", "숙성회 전문"],
    "양식": ["분위기 좋은 레스토랑", "파스타 맛집", "기념일 데이트", "와인 모임", "소개팅 장소", "스테이크 전문"],
    "카페": ["디저트 맛집", "감성 카페", "주차 편한 카페", "포토존", "원두 맛있는", "카공하기 좋은", "루프탑 카페"],
    "술집": ["안주 맛있는", "분위기 좋은 술집", "단체 회식", "가성비 포차", "하이볼 맛집", "데이트 2차", "프라이빗 룸"],
    "독서실": ["관리형 독서실", "집중 잘되는 스터디카페", "순공 시간 확보", "조용한 면학분위기", "독학재수 추천", "쾌적한 좌석", "성인 수험생"],
    "스터디": ["조용한 스터디카페", "집중 잘되는 좌석", "쾌적한 시설", "순공 시간", "스터디룸 예약", "가성비 정기권", "면학분위기"],
    "학원": ["맞춤 입시 지도", "성적 향상", "소수 정예 수업", "꼼꼼한 피드백", "체계적인 커리큘럼", "친절한 강사진", "내신 대비"],
    "병원": ["과잉진료 없는", "친절하고 꼼꼼한 진료", "야간 진료 가능", "통증 없는 치료", "대기시간 적은", "친절한 원장님", "정확한 진단"],
    "미용": ["손질 편한 헤어", "인생 머리 추천", "친절한 1:1 맞춤 시술", "트렌디한 스타일링", "손상 없는 펌/염색", "두피 케어"],
    "헬스": ["기구 좋은 헬스장", "친절하고 체계적인 PT", "청결한 샤워시설", "체형 교정 전문", "쾌적한 운동공간", "다이어트 성공"]
}


def fetch_naver_live_keywords(queries: List[str]) -> List[str]:
    """네이버 실시간 연관 및 자동완성 검색어 조회"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15',
        'Referer': 'https://m.naver.com'
    }
    keywords = []
    for q in queries:
        if not q or len(q.strip()) < 2:
            continue
        try:
            encoded = urllib.parse.quote(q.strip())
            url = f"https://ac.search.naver.com/nx/ac?q={encoded}&con=1&frm=nv&ans=2&r_format=json&r_enc=UTF-8&r_unicode=0&t_koreng=1&run=2&rev=4&q_enc=UTF-8&st=100"
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                for group in data.get("items", []):
                    for item in group:
                        if isinstance(item, list) and item and isinstance(item[0], str):
                            keywords.append(item[0])
                        elif isinstance(item, str):
                            keywords.append(item)
        except Exception:
            pass
    return list(dict.fromkeys(keywords))


def _generate_hidden_keywords_rule_based(category: str, address: str, store_data: Dict[str, Any], reviews: List[Dict[str, Any]]) -> Dict[str, Any]:
    """네이버 실시간 검색 및 상권 분석 기반 보강 추천 키워드 추출"""
    store_name = store_data.get("storeName", "")
    menus = store_data.get("menus", [])
    menu_names = [m.get("name") for m in menus if m.get("name")][:4]

    region_match = re.search(r'([가-힣]+[구동시군])', address)
    region = region_match.group(1) if region_match else ""

    is_food = any(f in category for f in ["음식점", "식당", "카페", "고기", "한식", "일식", "중식", "양식", "술집", "베이커리", "치킨", "피자", "분식", "주점", "이자카야"])

    search_queries = [f"{region} {category}".strip()]
    if is_food:
        search_queries.extend([f"{region} 맛집".strip(), f"{region} 회식".strip()])
        for m_name in menu_names[:2]:
            search_queries.append(f"{region} {m_name}".strip())
    else:
        search_queries.extend([f"{region} {category} 추천".strip(), f"{region} {category} 후기".strip(), f"{region} {category} 전문".strip()])

    search_queries = list(dict.fromkeys([q for q in search_queries if q]))
    naver_live_kws = fetch_naver_live_keywords(search_queries)

    all_text = store_data.get("storyIntro", "") + " " + " ".join([r.get("body", "") for r in reviews])
    matched_pool = []
    for cat_key, pool in CATEGORY_INTENT_KEYWORDS.items():
        if cat_key in category or cat_key in store_name:
            matched_pool = pool
            break
    if not matched_pool:
        matched_pool = ["가성비 맛집", "단체 모임", "친절한 매장", "주차 편한 곳", "데이트 추천"] if is_food else ["친절한 상담", "전문적인 관리", "쾌적한 시설", "맞춤 추천", "주차 편한 곳"]

    hidden_list = []
    for kw in matched_pool:
        clean_kw = kw.replace("부평 ", f"{region} " if region else "")
        if clean_kw not in all_text:
            hidden_list.append(clean_kw)
        if len(hidden_list) >= 5:
            break

    for n_kw in naver_live_kws:
        if len(hidden_list) >= 5:
            break
        if n_kw not in hidden_list and len(n_kw) >= 3 and n_kw not in store_name:
            hidden_list.append(n_kw)

    if not hidden_list:
        hidden_list = [f"{region} 핫플", "가성비 최고", "친절한 사장님", "재방문 맛집"] if is_food else [f"{region} 추천", "친절한 상담", "쾌적한 시설", "전문 관리"]

    prescription_reason = f"해당 상권({category})에서 자주 검색되는 핵심 키워드를 리뷰와 매장 소개에 자연스럽게 활용해 보세요."

    return {
        "hiddenKeywords": hidden_list[:5],
        "prescriptionReason": prescription_reason,
        "naverLiveKeywords": naver_live_kws[:10]
    }


def _extract_menu_keywords(reviews: List[Dict[str, Any]], menus: List[Dict[str, Any]], category: str = "", store_name: str = "") -> List[Dict[str, Any]]:
    """리뷰 본문에서 매장의 실제 메뉴 및 관련 단어 빈도 분석"""
    menu_names = [m.get("name", "").strip() for m in menus if m.get("name")]
    all_text = " ".join([r.get("body", "") for r in reviews])
    keyword_counter = Counter()

    for m_name in menu_names:
        clean_m = re.sub(r'[\(\)\[\]\d+,\.원g개/]', '', m_name).strip()
        if len(clean_m) >= 2:
            count = len(re.findall(re.escape(clean_m), all_text))
            keyword_counter[clean_m] += (count * 3) if count > 0 else 1

    FOOD_IRRELEVANT_WORDS = {
        "삼겹살", "목살", "갈비", "오겹살", "소고기", "한우", "곱창", "막창",
        "초밥", "스시", "오마카세", "사시미", "참치", "대게", "킹크랩",
        "파스타", "피자", "스테이크", "리조또", "버거", "타코",
        "마라탕", "양꼬치", "훠궈", "짜장면", "짬뽕", "탕수육",
        "치킨", "닭발", "호프", "맥주", "소주", "하이볼", "와인"
    }

    store_profile_text = (store_name + " " + category + " " + " ".join(menu_names)).lower()
    words = re.findall(r'[가-힣]{2,5}', all_text)
    for w in words:
        if w in STOPWORDS or len(w) < 2:
            continue
        if w in FOOD_IRRELEVANT_WORDS and w not in store_profile_text:
            continue
        if any(w in m_name for m_name in menu_names) or w in store_profile_text:
            keyword_counter[w] += 1

    sorted_kws = keyword_counter.most_common(20)
    return [{"label": kw, "count": cnt} for kw, cnt in sorted_kws if cnt >= 1]


def _analyze_themes(reviews: List[Dict[str, Any]], category: str = "") -> List[Dict[str, Any]]:
    """테마별 언급 빈도 분석"""
    cat_lower = str(category).lower()
    if any(k in cat_lower for k in ["독서실", "스터디", "학원", "교육", "교습", "과외"]):
        theme_dict = STUDY_THEMES
    elif any(k in cat_lower for k in ["음식점", "식당", "카페", "고기", "한식", "일식", "중식", "양식", "술집", "베이커리", "치킨", "피자", "분식", "주점", "이자카야"]):
        theme_dict = FOOD_THEMES
    else:
        theme_dict = GENERAL_THEMES

    theme_counts = {t: 0 for t in theme_dict}
    all_text = " ".join([r.get("body", "") for r in reviews])

    if not all_text.strip():
        return [{"label": t, "count": 0, "percentage": 0.0} for t in theme_dict]

    for theme, kw_list in theme_dict.items():
        for kw in kw_list:
            theme_counts[theme] += len(re.findall(re.escape(kw), all_text))

    total = sum(theme_counts.values())
    result = []
    for theme, cnt in sorted(theme_counts.items(), key=lambda x: x[1], reverse=True):
        pct = round((cnt / total) * 100, 1) if total > 0 else 0.0
        result.append({
            "label": theme,
            "count": cnt,
            "percentage": pct
        })
    return result


def _calculate_seo_scores(store_data: Dict[str, Any], reviews: List[Dict[str, Any]], sentiment_kws: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    네이버 플레이스 7대 핵심 노출 지표 산출 (100점 만점)
    - 1. 매장 기본 정보 및 소개글 (15점)
    - 2. 메뉴판 및 사진 등록 (15점)
    - 3. 영수증 리뷰 수 (20점)
    - 4. 사진 리뷰 비율 (15점)
    - 5. 블로그 리뷰 현황 (10점)
    - 6. 네이버 예약 및 스마트콜 (10점)
    - 7. 고객 반응 키워드 태그 (15점)
    """
        # =========================================================================
    # 7대 핵심 축 점수 산출 (100점 만점, 2026 상권 상위 경쟁 기준 초정밀 세분화)
    # =========================================================================

    # 1. 매장 기본 정보 및 소개글 (15점 만점)
    # 기본 필수 정보 (최대 6점)
    f1 = 0
    if store_data.get("storeName"): f1 += 1
    if store_data.get("category"): f1 += 1
    if store_data.get("roadAddress") or store_data.get("jibunAddress"): f1 += 1
    if store_data.get("phone"): f1 += 1
    if store_data.get("dailyBusinessHours"): f1 += 2
    # 사장님 소개글 / 스토리텔링 길이 (최대 9점, 키워드 연관성 및 충실도)
    story = str(store_data.get("storyIntro") or "").strip()
    story_len = len(story)
    if story_len >= 300: f1 += 9
    elif story_len >= 200: f1 += 7
    elif story_len >= 120: f1 += 5
    elif story_len >= 60: f1 += 3
    elif story_len >= 20: f1 += 1
    f1_score = min(15, f1)

    # 2. 메뉴판 및 사진 등록 (15점 만점)
    f2 = 0
    menus = store_data.get("menus") or []
    menu_len = len(menus)
    # 메뉴 개수 (최대 4점)
    if menu_len >= 20: f2 += 4
    elif menu_len >= 12: f2 += 3
    elif menu_len >= 6: f2 += 2
    elif menu_len >= 1: f2 += 1

    # 대표/추천 메뉴 등록 (최대 3점)
    rec_cnt = sum(1 for m in menus if m.get("isRecommended"))
    if rec_cnt >= 3: f2 += 3
    elif rec_cnt >= 1: f2 += 2

    # 메뉴 가격 정상 등록 (최대 3점)
    price_cnt = sum(1 for m in menus if m.get("price") and str(m.get("price")).strip() not in ["", "변동", "0", "0원"])
    if price_cnt >= 10: f2 += 3
    elif price_cnt >= 4: f2 += 2
    elif price_cnt >= 1: f2 += 1

    # 메뉴별 상세 설명 (최대 5점)
    desc_cnt = sum(1 for m in menus if m.get("description") and len(str(m.get("description")).strip()) >= 5)
    if desc_cnt >= 5: f2 += 5
    elif desc_cnt >= 3: f2 += 3
    elif desc_cnt >= 1: f2 += 1
    f2_score = min(15, f2)

            # 3. 영수증 리뷰 수 (25점 만점, 1점 단위 초정밀 세분화)
    # 상권 상위 경쟁 기준: 2000건+(25점), 1000건+(18점), 500건+(12점), 200건+(5점), 50건 미만(0~1점)
    f3 = 0
    raw_rev = store_data.get("visitorReviewsTotal")
    if raw_rev is None:
        raw_rev = store_data.get("reviewCount")
    rev_cnt = int(raw_rev) if raw_rev is not None else len(reviews)

    if rev_cnt >= 2000: f3 = 25
    elif rev_cnt >= 1800: f3 = 24
    elif rev_cnt >= 1600: f3 = 23
    elif rev_cnt >= 1400: f3 = 22
    elif rev_cnt >= 1200: f3 = 20
    elif rev_cnt >= 1000: f3 = 18
    elif rev_cnt >= 900: f3 = 17
    elif rev_cnt >= 800: f3 = 16
    elif rev_cnt >= 700: f3 = 15
    elif rev_cnt >= 600: f3 = 13
    elif rev_cnt >= 500: f3 = 12
    elif rev_cnt >= 450: f3 = 10
    elif rev_cnt >= 400: f3 = 9
    elif rev_cnt >= 350: f3 = 8
    elif rev_cnt >= 300: f3 = 7
    elif rev_cnt >= 250: f3 = 6
    elif rev_cnt >= 200: f3 = 5
    elif rev_cnt >= 150: f3 = 4
    elif rev_cnt >= 100: f3 = 3
    elif rev_cnt >= 50: f3 = 1
    else: f3 = 0
    f3_score = min(25, f3)

    # 4. 사진 리뷰 비율 (10점 만점)
    # 포토 리뷰 백분율 비중
    f4 = 0
    receipt_reviews = [r for r in reviews if r.get("type") != "blog"]
    sample_cnt = len(receipt_reviews)
    photo_cnt = sum(1 for r in receipt_reviews if r.get("hasPhoto"))
    photo_ratio = round((photo_cnt / sample_cnt) * 100) if sample_cnt > 0 else 0

    if rev_cnt >= 30 and sample_cnt >= 5:
        if photo_ratio >= 80: f4 = 10
        elif photo_ratio >= 70: f4 = 9
        elif photo_ratio >= 60: f4 = 8
        elif photo_ratio >= 50: f4 = 6
        elif photo_ratio >= 40: f4 = 5
        elif photo_ratio >= 30: f4 = 3
        elif photo_ratio >= 20: f4 = 2
        elif photo_ratio >= 10: f4 = 1
        else: f4 = 0
    elif rev_cnt >= 10:
        f4 = min(4, photo_ratio // 20)
    else:
        f4 = 0
    f4_score = min(10, f4)

    # 5. 블로그 리뷰 현황 (15점 만점, 1점 단위 초정밀 세분화)
    # 상위 바이럴 경쟁 기준: 500건+(15점), 300건+(12점), 150건+(8점), 50건+(3점), 20건 미만(0~1점)
    f5 = 0
    blog_cnt = int(store_data.get("blogReviewsTotal") or store_data.get("blogReviewCount") or 0)
    if blog_cnt >= 500: f5 = 15
    elif blog_cnt >= 400: f5 = 14
    elif blog_cnt >= 300: f5 = 12
    elif blog_cnt >= 250: f5 = 11
    elif blog_cnt >= 200: f5 = 10
    elif blog_cnt >= 150: f5 = 8
    elif blog_cnt >= 100: f5 = 6
    elif blog_cnt >= 70: f5 = 5
    elif blog_cnt >= 40: f5 = 3
    elif blog_cnt >= 20: f5 = 2
    elif blog_cnt >= 5: f5 = 1
    else: f5 = 0
    f5_score = min(15, f5)

    # 6. 네이버 예약 및 스마트콜 연동 (5점 만점)
    f6 = 0
    phone_str = str(store_data.get("phone") or "")
    if phone_str.startswith("0507"): f6 += 2  # 스마트콜 (2점)
    facilities_str = str(store_data.get("facilitiesInfo") or "")
    if any(b in facilities_str for b in ["예약", "네이버예약", "스마트주문", "포장", "배달"]):
        f6 += 2  # 예약/주문 (2점)
    if any(t in facilities_str for t in ["톡톡", "네이버페이", "무선인터넷", "간편결제", "주차"]):
        f6 += 1  # 편의 인프라 (1점)
    f6_score = min(5, f6)

    # 7. 고객 반응 키워드 태그 (15점 만점)
    f7 = 0
    tag_cnt = len(sentiment_kws)
    total_tag_votes = sum(k.get("count", 0) for k in sentiment_kws)
    # 태그 종류 다양성 (최대 5점)
    if tag_cnt >= 14: f7 += 5
    elif tag_cnt >= 10: f7 += 4
    elif tag_cnt >= 7: f7 += 3
    elif tag_cnt >= 4: f7 += 2
    elif tag_cnt >= 1: f7 += 1

    # 태그 총 투표 수 (최대 6점)
    if total_tag_votes >= 1000: f7 += 6
    elif total_tag_votes >= 600: f7 += 5
    elif total_tag_votes >= 300: f7 += 4
    elif total_tag_votes >= 150: f7 += 3
    elif total_tag_votes >= 50: f7 += 2
    elif total_tag_votes >= 10: f7 += 1

    # 주차 및 랜드마크 연계성 (최대 4점)
    if store_data.get("parkingInfo"): f7 += 2
    if store_data.get("nearbyLandmarks"): f7 += 2
    f7_score = min(15, f7)

    total_score = f1_score + f2_score + f3_score + f4_score + f5_score + f6_score + f7_score

        # 등급 체계 (업계 표준 9단계 게이지 등급 체계)
    # 일반(<20) -> 준최1(20~29) -> 준최2(30~39) -> 준최3(40~49) -> 준최4(50~59) -> 최적1(60~69) -> 최적2(70~79) -> 최적3(80~89) -> 최적4(90~100)
    if total_score >= 90:
        grade = "최적4"
        grade_type = "opt4"
        grade_desc = "상위 1% 최상위 플레이스 노출 최적화 상태입니다."
    elif total_score >= 80:
        grade = "최적3"
        grade_type = "opt3"
        grade_desc = "상위 노출 및 유입이 매우 강력한 최적화 매장입니다."
    elif total_score >= 70:
        grade = "최적2"
        grade_type = "opt2"
        grade_desc = "우수한 관리 상태이며, 세부 키워드 보강 시 최상위 랭킹 선점이 가능합니다."
    elif total_score >= 60:
        grade = "최적1"
        grade_type = "opt1"
        grade_desc = "최적화 진입 단계이며, 리뷰 사진과 소개글 보강을 권장합니다."
    elif total_score >= 50:
        grade = "준최4"
        grade_type = "semi4"
        grade_desc = "기본기가 탄탄하며 최적화 등급 도약이 가능한 상태입니다."
    elif total_score >= 40:
        grade = "준최3"
        grade_type = "semi3"
        grade_desc = "영수증 리뷰와 반응 키워드 보강이 필요한 상태입니다."
    elif total_score >= 30:
        grade = "준최2"
        grade_type = "semi2"
        grade_desc = "기본 정보와 메뉴판 사진 관리가 필요한 상태입니다."
    elif total_score >= 20:
        grade = "준최1"
        grade_type = "semi1"
        grade_desc = "플레이스 기본 설정 보강이 필요한 상태입니다."
    else:
        grade = "일반"
        grade_type = "normal"
        grade_desc = "플레이스 등록 및 리뷰 관리가 시급한 초기 상태입니다."

    # 실용적인 개선 팁
    tips = []
    if f1_score < 12:
        if len(story) < 40: tips.append("매장 소개글을 150자 이상으로 상세하게 작성해 보세요.")
    if f2_score < 10:
        if menu_len < 5: tips.append("대표 메뉴를 포함해 주요 메뉴 사진과 설명을 보강해 보세요.")
        if rec_cnt < 1: tips.append("대표/추천 메뉴를 최소 1개 이상 지정해 보세요.")
    if f3_score < 12:
        if rev_cnt < 50: tips.append(f"방문자 영수증 리뷰(현재 {rev_cnt}건)를 50건 이상으로 꾸준히 늘려보세요.")
        elif rev_cnt < 300: tips.append(f"지속적인 상위 유지를 위해 매월 일정한 영수증 리뷰를 확보해 보세요.")
    if f4_score < 10:
        tips.append("방문 고객들이 사진이 포함된 포토 리뷰를 작성하도록 안내해 보세요.")
    if f5_score < 6:
        if blog_cnt < 10: tips.append(f"블로그 리뷰(현재 {blog_cnt}건)를 늘려 매장 인지도를 높여보세요.")
    if f6_score < 7:
        if not phone_str.startswith("0507"): tips.append("네이버 무료 스마트콜(0507 가상번호)을 연결해 보세요.")
        if "예약" not in facilities_str: tips.append("네이버 플레이스 공식 예약 기능을 활용해 보세요.")
    if f7_score < 10:
        if total_tag_votes < 100: tips.append("방문 고객들이 맛, 친절 등 키워드 태그에 참여하도록 유도해 보세요.")

    return {
        "totalScore": total_score,
        "grade": grade,
        "gradeType": grade_type,
        "gradeDesc": grade_desc,
        "tips": tips,
        "axis": {
            "basicInfo": {"score": f1_score, "max": 15, "label": "매장 기본 정보 및 소개글"},
            "menuPhoto": {"score": f2_score, "max": 15, "label": "메뉴판 및 사진 등록"},
            "reviewVolume": {"score": f3_score, "max": 25, "label": f"영수증 리뷰 수 ({rev_cnt}건)"},
            "photoRatio": {"score": f4_score, "max": 10, "label": f"사진 리뷰 비율 ({photo_ratio}%)"},
            "blogBalance": {"score": f5_score, "max": 15, "label": f"블로그 리뷰 현황 ({blog_cnt}건)"},
            "naverInteraction": {"score": f6_score, "max": 5, "label": "네이버 예약 및 스마트콜 연동"},
            "customerReaction": {"score": f7_score, "max": 15, "label": "고객 반응 키워드 태그"}
        }
    }


def diagnose_place_from_scraped_data(store_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    수집된 플레이스 원본 데이터로부터 7대 핵심 지표 점수 및 고객 반응 분석
    """
    reviews = store_data.get("reviews", [])
    menus = store_data.get("menus", [])
    visitor_total = int(store_data.get("visitorReviewsTotal") if store_data.get("visitorReviewsTotal") is not None else len(reviews))
    blog_total = int(store_data.get("blogReviewsTotal") or 0)

    official_voted_kws = store_data.get("officialVotedKeywords") or []
    if official_voted_kws:
        sentiment_keywords = official_voted_kws[:16]
    else:
        tag_counter = Counter()
        for r in reviews:
            for tag in r.get("keywords", []):
                tag_counter[tag] += 1
        sentiment_keywords = [{"name": tag, "count": cnt} for tag, cnt in tag_counter.most_common(12)]
        if not sentiment_keywords and store_data.get("topKeywords"):
            sentiment_keywords = [{"name": kw, "count": 10 - i} for i, kw in enumerate(store_data.get("topKeywords")[:8])]

    official_menus = store_data.get("officialMenus") or []
    if official_menus:
        menu_keywords = [{"label": m.get("label"), "count": m.get("count")} for m in official_menus[:20]]
    else:
        menu_keywords = _extract_menu_keywords(reviews, menus, store_data.get("category", ""), store_data.get("storeName", ""))

    official_themes = store_data.get("officialThemes") or []
    if official_themes:
        total_theme_count = sum(t.get("count", 0) for t in official_themes) or 1
        themes = [{
            "label": t.get("label"),
            "count": t.get("count", 0),
            "percentage": round((t.get("count", 0) / total_theme_count) * 100, 1)
        } for t in official_themes[:6]]
    else:
        themes = _analyze_themes(reviews, store_data.get("category", ""))

    seo_diagnosis = _calculate_seo_scores(store_data, reviews, sentiment_keywords)

    ai_prescription = _generate_hidden_keywords_rule_based(
        store_data.get("category", ""),
        store_data.get("address", "") or store_data.get("roadAddress", "") or store_data.get("jibunAddress", ""),
        store_data,
        reviews
    )
    hidden_kws = ai_prescription.get("hiddenKeywords", [])
    prescription_reason = ai_prescription.get("prescriptionReason", "")
    naver_live_kws = ai_prescription.get("naverLiveKeywords", [])

    recommend_menus = [m for m in menus if m.get("isRecommended")]
    if not recommend_menus and menus:
        recommend_menus = menus[:3]

    return {
        "place": {
            "placeId": store_data.get("placeId"),
            "storeName": store_data.get("storeName"),
            "category": store_data.get("category"),
            "roadAddress": store_data.get("roadAddress"),
            "jibunAddress": store_data.get("jibunAddress"),
            "phone": store_data.get("phone"),
            "dailyBusinessHours": store_data.get("dailyBusinessHours"),
            "parkingInfo": store_data.get("parkingInfo"),
            "petInfo": store_data.get("petInfo"),
            "facilitiesInfo": store_data.get("facilitiesInfo"),
            "storyIntro": store_data.get("storyIntro"),
            "reviewCount": visitor_total,
            "blogReviewCount": blog_total,
            "menuCount": len(menus)
        },
        "seoScore": seo_diagnosis["totalScore"],
        "grade": seo_diagnosis["grade"],
        "gradeType": seo_diagnosis["gradeType"],
        "gradeDesc": seo_diagnosis["gradeDesc"],
        "tips": seo_diagnosis["tips"],
        "seoAxis": seo_diagnosis["axis"],
        "sentimentKeywords": sentiment_keywords,
        "menuKeywords": menu_keywords,
        "themes": themes,
        "recommendMenus": recommend_menus,
        "hiddenKeywords": hidden_kws,
        "prescriptionReason": prescription_reason,
        "naverLiveKeywords": naver_live_kws,
        "recentReviews": reviews[:10]
    }


def diagnose_place(url_input: str) -> Dict[str, Any]:
    """
    네이버 플레이스 30초 정밀 진단 실행
    """
    place_id = extract_place_id(url_input)
    if not place_id:
        return {"success": False, "error": "올바른 네이버 플레이스 주소 또는 매장 번호를 입력해 주세요."}

    scrape_res = scrape_naver_place(url_input, target_review_count=50)
    if not scrape_res.get("success"):
        return scrape_res

    store_data = scrape_res.get("data", {})
    diagnosis_data = diagnose_place_from_scraped_data(store_data)

    return {
        "success": True,
        "data": diagnosis_data
    }