// ============================================
// 1. 全局状态
// ============================================
let competitions = [];
let keyword = "";
let filterDifficulty = "全部";
let filterImportance = "全部";

// ============================================
// 2. 获取 DOM 元素
// ============================================
const listEl = document.getElementById("list");
const searchEl = document.getElementById("search");
const countEl = document.getElementById("count");

// ============================================
// 3. 渲染卡片列表
// ============================================
function render(data) {
  if (countEl) countEl.textContent = data.length;

  if (data.length === 0) {
    listEl.innerHTML = '<p class="empty">没有找到匹配的竞赛，试试其他关键词</p>';
    return;
  }

  listEl.innerHTML = data.map(c => `
    <div class="card" onclick="location.href='detail.html?id=${c.id}'">
      <div class="card-head">
        <h2>${c.name}</h2>
        <span class="level">${c.level}</span>
      </div>
      <p class="meta">${c.organizer}</p>
      <p>📅 报名：${c.signUp}</p>
      <p>🏁 比赛：${c.time}</p>
      <p>⚡ 难度：<strong>${c.difficulty}</strong> · 重要：<strong>${c.importance}</strong></p>
      <div class="tags">
        ${c.skills.map(s => `<span>${s}</span>`).join("")}
      </div>
    </div>
  `).join("");
}

// ============================================
// 4. 筛选逻辑
// ============================================
function applyFilter() {
  let result = competitions;

  // 按难度筛选
  if (filterDifficulty !== "全部") {
    result = result.filter(c => c.difficulty === filterDifficulty);
  }

  // 按重要程度筛选
  if (filterImportance !== "全部") {
    result = result.filter(c => c.importance === filterImportance);
  }

  // 按关键词搜索
  if (keyword.trim() !== "") {
    const k = keyword.trim().toLowerCase();
    result = result.filter(c =>
      c.name.toLowerCase().includes(k) ||
      (c.short && c.short.toLowerCase().includes(k)) ||
      c.organizer.toLowerCase().includes(k) ||
      c.skills.join(" ").toLowerCase().includes(k)
    );
  }

  render(result);
}

// ============================================
// 5. 事件绑定
// ============================================

// 搜索框输入
if (searchEl) {
  searchEl.addEventListener("input", (e) => {
    keyword = e.target.value;
    applyFilter();
  });
}

// 筛选按钮（支持 data-type 区分维度）
document.querySelectorAll(".filter-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    const type = btn.dataset.type;
    const val = btn.dataset.val;

    if (!type || !val) return;

    // 同类型按钮互斥高亮
    document.querySelectorAll(`.filter-btn[data-type="${type}"]`).forEach(b => {
      b.classList.toggle("active", b === btn);
    });

    if (type === "difficulty") filterDifficulty = val;
    if (type === "importance") filterImportance = val;

    applyFilter();
  });
});

// ============================================
// 6. 加载数据
// ============================================
async function loadData() {
  try {
    const res = await fetch("data.json");
    if (!res.ok) throw new Error("HTTP " + res.status);
    competitions = await res.json();

    // 初始化：把"全部"按钮设为高亮
    document.querySelectorAll('.filter-btn[data-val="全部"]').forEach(b => {
      b.classList.add("active");
    });

    render(competitions);
  } catch (err) {
    console.error("加载数据失败：", err);
    listEl.innerHTML = '<p class="empty">数据加载失败，请用 Live Server 打开，并确认 data.json 存在且格式正确</p>';
  }
}

loadData();