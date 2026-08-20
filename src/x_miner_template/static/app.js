const $ = (selector) => document.querySelector(selector);

const state = {
  campaigns: [],
  ecosystems: [],
  enabledEcosystems: new Set(),
  selectedCampaign: null,
  claim: JSON.parse(localStorage.getItem("bx-reference-claim") || "null"),
};

async function request(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "content-type": "application/json", ...(options.headers || {}) },
  });
  let body = {};
  try { body = await response.json(); } catch { /* retain empty body */ }
  if (!response.ok) {
    const detail = body.error?.message || body.detail || `Request failed (${response.status})`;
    throw new Error(Array.isArray(detail) ? detail.map((item) => item.msg).join("; ") : detail);
  }
  return body;
}

function idempotencyKey(prefix) {
  return `${prefix}-${crypto.randomUUID()}`;
}

function creatorId() {
  return $("#creator-x-id").value.trim();
}

function requireCreator() {
  const value = creatorId();
  if (!/^\d+$/.test(value)) throw new Error("Enter your numeric X user ID first.");
  localStorage.setItem("bx-reference-creator", value);
  return value;
}

function selectedQuery() {
  const query = new URLSearchParams();
  for (const ecosystem of [...state.enabledEcosystems].sort()) {
    query.append("ecosystem_id", ecosystem);
  }
  return query.toString();
}

function notice(element, text, type = "neutral") {
  element.textContent = text;
  element.className = `notice ${type}`;
}

function money(value) {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(Number(value));
}

function number(value) {
  return new Intl.NumberFormat("en-US").format(Number(value || 0));
}

function short(value, length = 8) {
  if (!value || value.length <= length * 2) return value || "—";
  return `${value.slice(0, length)}…${value.slice(-length)}`;
}

function addDetail(list, label, value) {
  if (value === null || value === undefined || value === "") return;
  const dt = document.createElement("dt");
  const dd = document.createElement("dd");
  dt.textContent = label;
  dd.textContent = value;
  list.append(dt, dd);
}

function renderStatus(status) {
  const qualification = status.qualification || {};
  const badge = $("#node-badge");
  badge.textContent = qualification.eligible || qualification.qualified
    ? "Miner online · qualified"
    : "Miner online · unavailable to claim";
  badge.className = `status-badge ${qualification.eligible || qualification.qualified ? "ready" : "warning"}`;
  const fields = $("#qualification").querySelectorAll("dd");
  fields[0].textContent = short(qualification.miner_hotkey);
  fields[0].title = qualification.miner_hotkey || "";
  fields[1].textContent = qualification.reason || (qualification.eligible ? "Eligible" : "Not qualified");
  fields[2].textContent = qualification.checked_block ?? "—";
}

function renderEcosystems() {
  const target = $("#ecosystem-filters");
  target.replaceChildren();
  for (const ecosystem of state.ecosystems) {
    const label = document.createElement("label");
    label.className = "filter-chip";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = state.enabledEcosystems.has(ecosystem.ecosystem_id);
    input.addEventListener("change", async () => {
      if (input.checked) state.enabledEcosystems.add(ecosystem.ecosystem_id);
      else state.enabledEcosystems.delete(ecosystem.ecosystem_id);
      await loadCampaigns();
    });
    const span = document.createElement("span");
    span.textContent = ecosystem.name;
    label.append(input, span);
    target.append(label);
  }
}

function campaignCard(campaign) {
  const card = document.createElement("button");
  card.type = "button";
  card.className = `campaign-card ${state.selectedCampaign?.campaign_id === campaign.campaign_id ? "selected" : ""}`;
  const heading = document.createElement("div");
  heading.className = "campaign-card-heading";
  const name = document.createElement("h3");
  name.textContent = campaign.presentation?.name || campaign.campaign_id;
  const status = document.createElement("span");
  status.className = `campaign-status ${campaign.status}`;
  status.textContent = campaign.status.replaceAll("_", " ");
  heading.append(name, status);
  const ecosystems = document.createElement("p");
  ecosystems.className = "campaign-ecosystems";
  ecosystems.textContent = campaign.ecosystem_ids.join(" · ");
  const stats = document.createElement("div");
  stats.className = "campaign-stats";
  stats.innerHTML = `<span><strong>${money(campaign.reward_pool_usd)}</strong> pool</span>`
    + `<span><strong>${number(campaign.stats?.matched_tweets)}</strong> tweets</span>`
    + `<span><strong>${number(campaign.stats?.total_views)}</strong> views</span>`;
  card.append(heading, ecosystems, stats);
  card.addEventListener("click", () => selectCampaign(campaign));
  return card;
}

function renderCampaigns() {
  const grid = $("#campaign-grid");
  grid.replaceChildren(...state.campaigns.map(campaignCard));
  $("#campaign-message").textContent = state.campaigns.length
    ? `${state.campaigns.length} protocol-v2 campaign${state.campaigns.length === 1 ? "" : "s"}`
    : "No campaigns match the selected ecosystems.";
}

async function loadCampaigns() {
  const query = selectedQuery();
  const body = await request(`/api/campaigns${query ? `?${query}` : ""}`);
  state.campaigns = body.items || [];
  renderCampaigns();
}

async function selectCampaign(campaign) {
  const campaignChanged = state.selectedCampaign?.campaign_id !== campaign.campaign_id;
  state.selectedCampaign = await request(`/api/campaigns/${campaign.campaign_id}`);
  renderCampaigns();
  renderSelectedCampaign(campaignChanged);
  await loadLeaderboard();
}

function renderSelectedCampaign(campaignChanged = false) {
  const campaign = state.selectedCampaign;
  $("#campaign-workspace").classList.remove("hidden");
  $("#leaderboard-section").classList.remove("hidden");
  $("#selected-title").textContent = campaign.presentation?.name || campaign.campaign_id;
  $("#campaign-brief").textContent = campaign.brief;
  const metadata = $("#campaign-metadata");
  metadata.replaceChildren();
  addDetail(metadata, "Campaign ID", campaign.campaign_id);
  addDetail(metadata, "Ecosystems", campaign.ecosystem_ids.join(", "));
  addDetail(metadata, "Submission mode", campaign.protocol.submission_mode);
  addDetail(metadata, "Reward pool", money(campaign.reward_pool_usd));
  addDetail(metadata, "Closes", new Date(campaign.closes_at).toLocaleString());
  addDetail(metadata, "Max tweets / creator", campaign.max_tweets_per_creator);
  const direct = !campaign.capabilities.requires_claim;
  $("#claim-form").classList.toggle("hidden", direct);
  $("#operation-title").textContent = direct ? "Submit published tweet" : "Commit draft before posting";
  if (campaignChanged) {
    notice(
      $("#eligibility-result"),
      "Enter your X user ID, then check eligibility.",
    );
    notice($("#submission-result"), "No tweet submitted yet.");
    $("#tweet-id").value = "";
  }
  notice(
    $("#claim-result"),
    direct ? "This exclusive campaign uses direct protocol-v2 submission; no claim is needed." : "No claim created yet.",
  );
  if (state.claim?.campaign_id === campaign.campaign_id) refreshClaim();
}

async function checkEligibility() {
  try {
    const result = await request(
      `/api/campaigns/${state.selectedCampaign.campaign_id}/eligibility/${requireCreator()}`,
    );
    const evidence = (result.eligible_ecosystems || [])
      .map((item) => `${item.ecosystem_id}: ${item.eligible ? `eligible at rank ${item.rank}` : "not eligible"}`)
      .join(" · ");
    notice(
      $("#eligibility-result"),
      `${result.reason.replaceAll("_", " ")}${evidence ? ` · ${evidence}` : ""}`,
      result.eligible_if_published_now ? "success" : "error",
    );
  } catch (error) {
    notice($("#eligibility-result"), error.message, "error");
  }
}

async function createClaim(event) {
  event.preventDefault();
  try {
    const key = idempotencyKey("claim");
    notice($("#claim-result"), "Committing the private draft on chain…");
    const claim = await request("/api/claims", {
      method: "POST",
      headers: { "Idempotency-Key": key },
      body: JSON.stringify({
        campaign_id: state.selectedCampaign.campaign_id,
        creator_x_id: requireCreator(),
        draft: $("#draft").value,
        external_id: key,
      }),
    });
    state.claim = claim;
    localStorage.setItem("bx-reference-claim", JSON.stringify(claim));
    renderClaim(claim);
  } catch (error) {
    notice($("#claim-result"), error.message, "error");
  }
}

function renderClaim(claim) {
  const status = claim.usability?.status;
  if (claim.usability?.safe_to_post) {
    notice(
      $("#claim-result"),
      `Safe to post. Claim ${claim.claim_id} is finalized and active.`,
      "success",
    );
    return;
  }
  if (status === "consumed") {
    notice(
      $("#claim-result"),
      `Claim ${claim.claim_id} was consumed by submission ${claim.usability.consumed_by_submission_id}.`,
      "success",
    );
    return;
  }
  if (status === "evicted") {
    notice(
      $("#claim-result"),
      `Claim ${claim.claim_id} was evicted when claim ${claim.usability.evicted_by_claim_id} became active. Create a new claim before posting.`,
      "error",
    );
    return;
  }
  notice(
    $("#claim-result"),
    `Claim ${claim.claim_id}: ${status || claim.commitment?.status || "pending"}. Waiting before you post.`,
    status === "expired" ? "error" : "neutral",
  );
}

async function refreshClaim() {
  if (!state.claim?.claim_id) return;
  try {
    state.claim = await request(`/api/claims/${state.claim.claim_id}`);
    localStorage.setItem("bx-reference-claim", JSON.stringify(state.claim));
    renderClaim(state.claim);
  } catch (error) {
    notice($("#claim-result"), error.message, "error");
  }
}

function normalizeTweetId(value) {
  const match = value.trim().match(/(?:status\/)?(\d{5,})/);
  if (!match) throw new Error("Enter a valid tweet URL or numeric tweet ID.");
  return match[1];
}

async function createSubmission(event) {
  event.preventDefault();
  try {
    const direct = !state.selectedCampaign.capabilities.requires_claim;
    if (!direct && !state.claim?.usability?.safe_to_post) {
      throw new Error("Wait for a safe-to-post claim before submitting your tweet.");
    }
    const key = idempotencyKey("submission");
    notice($("#submission-result"), "Saving the tweet for chain commitment…");
    const submission = await request("/api/submissions", {
      method: "POST",
      headers: { "Idempotency-Key": key },
      body: JSON.stringify({
        campaign_id: state.selectedCampaign.campaign_id,
        tweet_id: normalizeTweetId($("#tweet-id").value),
        claim_id: direct ? null : state.claim.claim_id,
        creator_x_id: requireCreator(),
        external_id: key,
      }),
    });
    notice(
      $("#submission-result"),
      `Submission ${submission.submission_id}: ${submission.status.replaceAll("_", " ")}.`,
      "success",
    );
    await loadSubmissions();
  } catch (error) {
    notice($("#submission-result"), error.message, "error");
  }
}

function tableCell(value) {
  const cell = document.createElement("td");
  if (value instanceof Node) cell.append(value);
  else cell.textContent = value ?? "—";
  return cell;
}

function renderTableMessage(selector, message) {
  const row = document.createElement("tr");
  const cell = tableCell(message);
  cell.colSpan = 6;
  row.append(cell);
  $(selector).replaceChildren(row);
}

function renderSubmissions(items) {
  const rows = $("#submission-rows");
  if (!items.length) {
    rows.innerHTML = '<tr><td colspan="6">No submissions yet.</td></tr>';
    return;
  }
  rows.replaceChildren(...items.map((item) => {
    const row = document.createElement("tr");
    const link = document.createElement("a");
    link.href = `https://x.com/i/status/${item.tweet_id}`;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = item.tweet_id;
    const reward = item.reward_recommendation;
    row.append(
      tableCell(link),
      tableCell(item.campaign_id),
      tableCell((item.status || "pending").replaceAll("_", " ")),
      tableCell(item.evaluation?.score ?? item.score),
      tableCell(reward?.status === "recommended" ? money(reward.total) : reward?.status || "Pending"),
      tableCell(item.failure_reason || item.evaluation?.explanation || item.attribution?.reason || "—"),
    );
    return row;
  }));
}

async function loadSubmissions() {
  try {
    const query = new URLSearchParams();
    if (/^\d+$/.test(creatorId())) query.set("creator_x_id", creatorId());
    const result = await request(`/api/submissions${query.size ? `?${query}` : ""}`);
    renderSubmissions(result.items || []);
  } catch (error) {
    renderTableMessage("#submission-rows", error.message);
  }
}

async function loadLeaderboard() {
  try {
    const query = selectedQuery();
    const result = await request(
      `/api/campaigns/${state.selectedCampaign.campaign_id}/tweets${query ? `?${query}` : ""}`,
    );
    const items = result.tweets || result.items || [];
    const rows = $("#leaderboard-rows");
    if (!items.length) {
      rows.innerHTML = '<tr><td colspan="6">No evaluated tweets yet.</td></tr>';
      return;
    }
    rows.replaceChildren(...items.map((item) => {
      const row = document.createElement("tr");
      const link = document.createElement("a");
      link.href = item.tweet_url || `https://x.com/i/status/${item.tweet_id}`;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = short(item.tweet_id, 6);
      row.append(
        tableCell(item.author_username ? `@${item.author_username}` : "—"),
        tableCell(link),
        tableCell(item.score ?? "—"),
        tableCell(number(item.views)),
        tableCell(number(item.engagements || (
          Number(item.likes || 0)
          + Number(item.retweets || 0)
          + Number(item.replies || 0)
          + Number(item.quotes || 0)
        ))),
        tableCell(item.reward_recommendation?.status === "recommended"
          ? money(item.reward_recommendation.total) : "—"),
      );
      return row;
    }));
  } catch (error) {
    renderTableMessage("#leaderboard-rows", error.message);
  }
}

async function boot() {
  $("#creator-x-id").value = localStorage.getItem("bx-reference-creator") || "";
  try {
    const [status, ecosystems] = await Promise.all([
      request("/api/status"),
      request("/api/ecosystems"),
    ]);
    renderStatus(status);
    state.ecosystems = ecosystems.items || [];
    state.enabledEcosystems = new Set(state.ecosystems.map((item) => item.ecosystem_id));
    renderEcosystems();
    await Promise.all([loadCampaigns(), loadSubmissions()]);
  } catch (error) {
    $("#node-badge").textContent = error.message;
    $("#node-badge").className = "status-badge error";
    $("#campaign-message").textContent = error.message;
  }
}

$("#creator-x-id").addEventListener("change", () => {
  if (/^\d+$/.test(creatorId())) localStorage.setItem("bx-reference-creator", creatorId());
});
$("#check-eligibility").addEventListener("click", checkEligibility);
$("#claim-form").addEventListener("submit", createClaim);
$("#submission-form").addEventListener("submit", createSubmission);
$("#refresh-campaign").addEventListener("click", async () => {
  await selectCampaign(state.selectedCampaign);
  await refreshClaim();
});
$("#refresh-submissions").addEventListener("click", loadSubmissions);
setInterval(async () => {
  await refreshClaim();
  await loadSubmissions();
}, 15000);

boot();
