// ============================================
// 1. 从 URL 里读取 id
//    detail.html?id=3  →  id = 3
// ============================================
const params = new URLSearchParams(window.location.search);
const id = parseInt(params.get("id"));

const detailEl = document.getElementById("detail");
const titleEl = document.getElementById("page-title");

// ============================================
// 2. 加载数据并渲染
// ============================================
async function loadDetail() {
  // 没带 id，提示错误
  if (!id) {
    detailEl.innerHTML = '<p class="empty">缺少竞赛 ID，请从列表页进入</p>';
    return;
  }

  try {
    const res = await fetch("data.json");
    const competitions = await res.json();

    // 根据 id 找到对应的竞赛
    const c = competitions.find(x => x.id === id);

    if (!c) {
      detailEl.innerHTML = '<p class="empty">没有找到该竞赛</p>';
      return;
    }

    // 更新页面标题
    titleEl.textContent = c.short || c.name;
    document.title = c.name + " - 竞赛详情";

    // 渲染详情内容
    detailEl.innerHTML = `
      <h2>${c.name}</h2>

      <div class="detail-row">
        <span class="detail-label">主办方</span>
        <span class="detail-value">${c.organizer}</span>
      </div>

      <div class="detail-row">
        <span class="detail-label">级别</span>
        <span class="detail-value">${c.level}</span>
      </div>

      <div class="detail-row">
        <span class="detail-label">报名时间</span>
        <span class="detail-value">${c.signUp}</span>
      </div>

      <div class="detail-row">
        <span class="detail-label">比赛时间</span>
        <span class="detail-value">${c.time}</span>
      </div>

      <div class="detail-row">
        <span class="detail-label">赛制</span>
        <span class="detail-value">${c.format}</span>
      </div>

      <div class="detail-row">
        <span class="detail-label">难度</span>
        <span class="detail-value">${c.difficulty}</span>
      </div>

      <div class="detail-row">
        <span class="detail-label">组队</span>
        <span class="detail-value">${c.team}</span>
      </div>

      <div class="detail-row">
        <span class="detail-label">技能要求</span>
        <span class="detail-value">${c.skills.join("、")}</span>
      </div>

      <div class="detail-row">
        <span class="detail-label">加分参考</span>
        <span class="detail-value">${c.bonus}</span>
      </div>

      <div class="detail-row">
        <span class="detail-label">备赛建议</span>
        <span class="detail-value">${c.prep}</span>
      </div>

      <div class="detail-row">
        <span class="detail-label">官网</span>
        <span class="detail-value">
          <a href="${c.link}" target="_blank">${c.link}</a>
        </span>
      </div>
    `;
  } catch (err) {
    console.error("加载失败：", err);
    detailEl.innerHTML = '<p class="empty">数据加载失败，请检查 data.json</p>';
  }
}

loadDetail();