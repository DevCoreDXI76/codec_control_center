// app/static/js/theme.js
// 다크모드 토글 (UX_SPEC.md 7절, 선택 사항). 화면 깜빡임 방지를 위해
// <head>에서 defer 없이 동기 실행되어 body 렌더 전에 테마를 적용한다.
(function () {
  function getStoredTheme() {
    try {
      return localStorage.getItem("theme");
    } catch (e) {
      return null;
    }
  }

  function getPreferredTheme() {
    const stored = getStoredTheme();
    if (stored === "light" || stored === "dark") return stored;
    return "dark"; // 최초 설치 시 OS 설정과 무관하게 다크모드로 시작
  }

  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
  }

  applyTheme(getPreferredTheme());

  document.addEventListener("DOMContentLoaded", () => {
    const toggle = document.getElementById("theme-toggle");
    if (!toggle) return;
    const sync = () => {
      toggle.textContent = document.documentElement.getAttribute("data-theme") === "dark" ? "☀" : "🌙";
    };
    sync();
    toggle.addEventListener("click", () => {
      const next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
      try {
        localStorage.setItem("theme", next);
      } catch (e) {
        // localStorage 사용 불가 시에도 현재 세션에서는 토글 동작은 유지
      }
      applyTheme(next);
      sync();
    });
  });
})();
