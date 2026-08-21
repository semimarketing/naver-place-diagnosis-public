/**
 * 네이버 플레이스 30초 정밀 진단 클라이언트 스크립트 (app.js)
 */

let progressInterval = null;
const STORAGE_KEY = "naver_place_last_diagnosis";

document.addEventListener("DOMContentLoaded", () => {
  fetchRateLimitStatus();
  restoreLastDiagnosis();
});

function restoreLastDiagnosis() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved) {
      const parsed = JSON.parse(saved);
      if (parsed && parsed.data) {
        const inputEl = document.getElementById("placeUrlInput");
        if (inputEl && parsed.url) {
          inputEl.value = parsed.url;
        }
        renderDiagnosisResult(parsed.data);
        const resultSection = document.getElementById("resultSection");
        if (resultSection) {
          resultSection.style.display = "flex";
        }
      }
    }
  } catch (err) {
    console.error("Failed to restore last diagnosis", err);
  }
}

// API Base URL (로컬이면 '', 배포 환경이면 Render 백엔드 연결)
const API_BASE = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1' 
  ? '' 
  : 'https://naver-place-diagnosis-public.onrender.com';

async function fetchRateLimitStatus() {
  try {
    const res = await fetch(`${API_BASE}/api/rate-limit-status`);
    if (res.ok) {
      const data = await res.json();
      const countEl = document.getElementById("remainingCount");
      if (countEl) countEl.textContent = data.remaining !== undefined ? data.remaining : 3;
    }
  } catch (err) {
    console.error("Rate limit check failed", err);
  }
}

function showCustomModal(title, message, iconType = "warning") {
  document.getElementById("modalTitle").textContent = title;
  document.getElementById("modalMessage").textContent = message;
  document.getElementById("customModal").style.display = "flex";
}

function closeCustomModal() {
  document.getElementById("customModal").style.display = "none";
}

function startProgressBar() {
  const fill = document.getElementById("progressBarFill");
  let width = 10;
  fill.style.width = "10%";
  
  clearInterval(progressInterval);
  progressInterval = setInterval(() => {
    if (width < 90) {
      width += Math.random() * 12;
      if (width > 90) width = 90;
      fill.style.width = `${width}%`;
    }
  }, 400);
}

function finishProgressBar() {
  clearInterval(progressInterval);
  const fill = document.getElementById("progressBarFill");
  if (fill) fill.style.width = "100%";
}

async function handleDiagnose(e) {
  if (e && e.preventDefault) {
    e.preventDefault();
    e.stopPropagation();
  }
  
  const inputEl = document.getElementById("placeUrlInput");
  const url = inputEl ? inputEl.value.trim() : "";
  
  if (!url) {
    showCustomModal("입력 확인", "네이버 플레이스 URL 또는 매장 번호를 입력해 주세요.");
    return false;
  }

  const submitBtn = document.getElementById("submitBtn");
  const loadingSection = document.getElementById("loadingSection");
  const resultSection = document.getElementById("resultSection");

  if (submitBtn) submitBtn.disabled = true;
  if (loadingSection) loadingSection.style.display = "block";
  if (resultSection) resultSection.style.display = "none";
  startProgressBar();

  try {
    const res = await fetch(`${API_BASE}/api/diagnose`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url })
    });

    let data;
    try {
      data = await res.json();
    } catch (e) {
      data = { error: "응답 파싱에 실패했습니다." };
    }
    
    finishProgressBar();

    if (!res.ok) {
      if (res.status === 429) {
        showCustomModal("조회 한도 초과", data.error || "10분 동안 최대 3회만 조회 가능합니다.", "warning");
      } else {
        showCustomModal("진단 실패", data.error || "매장 정보를 불러오지 못했습니다. 올바른 주소인지 확인해 주세요.", "error");
      }
      if (loadingSection) loadingSection.style.display = "none";
      if (submitBtn) submitBtn.disabled = false;
      fetchRateLimitStatus();
      return false;
    }

    if (data.success && data.data) {
      try {
        renderDiagnosisResult(data.data);
        localStorage.setItem(STORAGE_KEY, JSON.stringify({ url, data: data.data, timestamp: Date.now() }));
      } catch (renderErr) {
        console.error("Render error:", renderErr);
      }
      
      if (data.remaining !== undefined) {
        const remainingEl = document.getElementById("remainingCount");
        if (remainingEl) remainingEl.textContent = data.remaining;
      }
      
            setTimeout(() => {
        if (loadingSection) loadingSection.style.display = "none";
        if (resultSection) {
          resultSection.style.display = "flex";
          // 고정 상단바(sticky header, 약 80px) 높이를 고려한 완벽한 상단 스크롤
          const headerOffset = 90;
          const elementPosition = resultSection.getBoundingClientRect().top;
          const offsetPosition = elementPosition + window.pageYOffset - headerOffset;
          window.scrollTo({
            top: offsetPosition,
            behavior: "smooth"
          });
        }
        if (submitBtn) submitBtn.disabled = false;
      }, 400);
    }
  } catch (err) {
    console.error("Fetch diagnose error:", err);
    finishProgressBar();
    if (loadingSection) loadingSection.style.display = "none";
    if (submitBtn) submitBtn.disabled = false;
    showCustomModal("네트워크 오류", "서버와 통신할 수 없습니다. 잠시 후 다시 시도해 주세요.", "error");
  }
  return false;
}

function renderDiagnosisResult(data) {
  const p = data.place || {};
  const totalScore = data.seoScore || 0;
  const grade = data.grade || "일반";

  // 1. Gauge Header & Center Info
  const gaugeStore = document.getElementById("gaugeStoreName");
  if (gaugeStore) gaugeStore.textContent = p.storeName || "내 매장";

  const centerGrade = document.getElementById("gaugeCenterGrade");
  if (centerGrade) centerGrade.textContent = grade;

  const centerScore = document.getElementById("gaugeCenterScore");
  if (centerScore) centerScore.textContent = `플레이스 지수 ${Number(totalScore).toFixed(1)}점`;

  // 2. Animate Gauge Needle (0점 = -180도, 100점 = 0도, 피벗: 230, 220)
  const angle = -180 + (Math.min(100, Math.max(0, totalScore)) / 100) * 180;
  const needle = document.getElementById("gaugeNeedleGroup");
  if (needle) {
    needle.setAttribute("transform", `rotate(${angle}, 230, 220)`);
  }

        // 3. Highlight Center Grade Color (Muzli Palette: 딥그린/네온그린 -> 로즈핑크 -> 비비드레드)
  const gradeColors = {
    "최적4": "#29b312",
    "최적3": "#3bff1a",
    "최적2": "#22c55e",
    "최적1": "#10b981",
    "준최4": "#f43f5e",
    "준최3": "#ff6b8b",
    "준최2": "#fb7185",
    "준최1": "#ff1a40",
    "일반": "#b31240"
  };
  if (centerGrade) {
    centerGrade.style.color = gradeColors[grade] || "#ea580c";
  }

  // 4. 7 Axis Grid
  const axisGrid = document.getElementById("axisGrid");
  if (axisGrid) {
    axisGrid.innerHTML = "";
    const axisData = data.seoAxis || {};
    
    Object.keys(axisData).forEach(key => {
      const ax = axisData[key];
      const pct = Math.min(100, Math.round((ax.score / ax.max) * 100));
      const card = document.createElement("div");
      card.className = "axis-item";
      card.innerHTML = `
        <div class="axis-item-header">
          <span>${ax.label}</span>
          <span class="axis-item-score">${ax.score} / ${ax.max}점</span>
        </div>
        <div class="axis-progress-track">
          <div class="axis-progress-bar" style="width: ${pct}%;"></div>
        </div>
      `;
      axisGrid.appendChild(card);
    });
  }

  // 5. Actionable Tips
  const tipsList = document.getElementById("tipsList");
  if (tipsList) {
    tipsList.innerHTML = "";
    const tips = data.tips || [];
    if (tips.length === 0) {
      tipsList.innerHTML = '<div class="tip-item">모든 핵심 지표가 완벽하게 관리되고 있습니다!</div>';
    } else {
      tips.forEach(t => {
        const el = document.createElement("div");
        el.className = "tip-item";
        el.innerHTML = `<span>${t}</span>`;
        tipsList.appendChild(el);
      });
    }
  }

  // 6. Hidden Keywords
  const kwList = document.getElementById("hiddenKeywordsList");
  if (kwList) {
    kwList.innerHTML = "";
    const hiddenKws = data.hiddenKeywords || [];
    hiddenKws.forEach(k => {
      const tag = document.createElement("span");
      tag.className = "kw-tag";
      tag.textContent = `#${k}`;
      kwList.appendChild(tag);
    });
  }
  const prescEl = document.getElementById("prescriptionReason");
  if (prescEl) {
    prescEl.textContent = data.prescriptionReason || "해당 상권에서 고객들이 자주 검색하는 핵심 키워드를 리뷰와 매장 소개에 반영해 보세요.";
  }

  // 7. Sentiment Keywords
  const sentimentList = document.getElementById("sentimentList");
  if (sentimentList) {
    sentimentList.innerHTML = "";
    const sentKws = data.sentimentKeywords || [];
    const maxSentCount = sentKws.length > 0 ? Math.max(...sentKws.map(s => s.count || 1)) : 1;
    
    sentKws.slice(0, 6).forEach(s => {
      const pct = Math.round(((s.count || 1) / maxSentCount) * 100);
      const item = document.createElement("div");
      item.className = "stat-bar-item";
      item.innerHTML = `
        <span class="stat-bar-label">${s.name || s.label}</span>
        <div class="stat-bar-track">
          <div class="stat-bar-fill" style="width: ${pct}%;"></div>
        </div>
        <span class="stat-bar-value">${s.count}</span>
      `;
      sentimentList.appendChild(item);
    });
  }

  // 8. Themes
  const themeList = document.getElementById("themeList");
  if (themeList) {
    themeList.innerHTML = "";
    const themes = data.themes || [];
    themes.forEach(t => {
      const item = document.createElement("div");
      item.className = "stat-bar-item";
      item.innerHTML = `
        <span class="stat-bar-label">${t.label}</span>
        <div class="stat-bar-track">
          <div class="stat-bar-fill" style="width: ${t.percentage || 0}%; background-color: var(--primary-blue);"></div>
        </div>
        <span class="stat-bar-value">${t.percentage}%</span>
      `;
      themeList.appendChild(item);
    });
  }
}

function handleCtaClick() {
  window.open("https://mkt.mainko.net", "_blank");
}