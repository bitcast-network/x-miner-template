const $ = (selector) => document.querySelector(selector);

const state = {
  campaigns: [],
  ecosystems: [],
  enabledEcosystems: new Set(),
  leaderboardEcosystem: null,
  leaderboardLimit: 25,
  leaderboardOffset: 0,
  leaderboardTotalCount: 0,
  leaderboardLoaded: false,
  draftPrecheckEnabled: false,
  selectedCampaign: null,
  selectedSubmissionId: null,
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

function leaderboardQuery() {
  const query = new URLSearchParams({
    limit: String(state.leaderboardLimit),
    offset: String(state.leaderboardOffset),
  });
  const ecosystems = state.leaderboardEcosystem
    ? [state.leaderboardEcosystem]
    : [...state.enabledEcosystems].sort();
  for (const ecosystem of ecosystems) query.append("ecosystem_id", ecosystem);
  return query.toString();
}

function currentPage() {
  return window.location.hash === "#leaderboard" ? "leaderboard" : "campaigns";
}

function showPage(pageName, updateHash = false) {
  const selected = pageName === "leaderboard" ? "leaderboard" : "campaigns";
  $("#campaigns-page").classList.toggle("hidden", selected !== "campaigns");
  $("#leaderboard-page").classList.toggle("hidden", selected !== "leaderboard");
  document.querySelectorAll(".nav-link").forEach((button) => {
    const active = button.dataset.page === selected;
    button.classList.toggle("active", active);
    button.setAttribute("aria-current", active ? "page" : "false");
  });
  if (updateHash) history.pushState(null, "", selected === "leaderboard" ? "#leaderboard" : "#campaigns");
  document.title = selected === "leaderboard"
    ? "Leaderboard · Bitcast X Reference Miner"
    : "Bitcast X · Reference Miner";
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

function dateTime(value) {
  return value ? new Date(value).toLocaleString() : "—";
}

function display(value) {
  if (value === null || value === undefined || value === "") return "—";
  if (Array.isArray(value)) return value.length ? value.join(", ") : "—";
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
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

function renderDraftPrecheckStatus(status) {
  state.draftPrecheckEnabled = Boolean(status.enabled);
  const target = $("#draft-precheck-status");
  if (status.enabled) {
    target.textContent = "Strict tweet precheck enabled · all three OpenRouter reviews must pass.";
    target.className = "precheck-status enabled";
  } else {
    target.textContent = "Tweet precheck is not enabled. Add an OpenRouter key to enable it.";
    target.className = "precheck-status disabled";
  }
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
      if (input.checked) {
        state.enabledEcosystems.add(ecosystem.ecosystem_id);
      } else if (state.enabledEcosystems.size === 1) {
        input.checked = true;
        return;
      } else {
        state.enabledEcosystems.delete(ecosystem.ecosystem_id);
      }
      if (!state.enabledEcosystems.has(state.leaderboardEcosystem)) {
        state.leaderboardEcosystem = null;
      }
      state.leaderboardOffset = 0;
      state.leaderboardLoaded = false;
      renderLeaderboardFilters();
      await loadCampaigns();
      if (currentPage() === "leaderboard") await loadEcosystemLeaderboard();
    });
    const span = document.createElement("span");
    span.textContent = ecosystem.name;
    label.append(input, span);
    target.append(label);
  }
}

function renderLeaderboardFilters() {
  const target = $("#leaderboard-filters");
  target.replaceChildren();
  const options = [
    { ecosystem_id: null, name: "All enabled" },
    ...state.ecosystems.filter((item) => state.enabledEcosystems.has(item.ecosystem_id)),
  ];
  for (const ecosystem of options) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `filter-button ${state.leaderboardEcosystem === ecosystem.ecosystem_id ? "active" : ""}`;
    button.textContent = ecosystem.name;
    button.addEventListener("click", async () => {
      state.leaderboardEcosystem = ecosystem.ecosystem_id;
      state.leaderboardOffset = 0;
      renderLeaderboardFilters();
      await loadEcosystemLeaderboard();
    });
    target.append(button);
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
  if (state.selectedCampaign) {
    const stillVisible = state.campaigns.some(
      (campaign) => campaign.campaign_id === state.selectedCampaign.campaign_id,
    );
    if (stillVisible) await loadCampaignTweets();
    else {
      state.selectedCampaign = null;
      $("#campaign-workspace").classList.add("hidden");
      $("#campaign-tweets-section").classList.add("hidden");
    }
  }
}

async function selectCampaign(campaign) {
  const campaignChanged = state.selectedCampaign?.campaign_id !== campaign.campaign_id;
  state.selectedCampaign = await request(`/api/campaigns/${campaign.campaign_id}`);
  renderCampaigns();
  renderSelectedCampaign(campaignChanged);
  await loadCampaignTweets();
  $("#campaign-workspace").scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderSelectedCampaign(campaignChanged = false) {
  const campaign = state.selectedCampaign;
  $("#campaign-workspace").classList.remove("hidden");
  $("#campaign-tweets-section").classList.remove("hidden");
  $("#selected-title").textContent = campaign.presentation?.name || campaign.campaign_id;
  $("#campaign-brief").textContent = campaign.brief;
  const metadata = $("#campaign-metadata");
  metadata.replaceChildren();
  addDetail(metadata, "Campaign ID", campaign.campaign_id);
  addDetail(metadata, "Snapshot", campaign.campaign_snapshot_id);
  addDetail(metadata, "Ecosystems", campaign.ecosystem_ids.join(", "));
  addDetail(metadata, "Access", campaign.access?.mode);
  addDetail(metadata, "Submission mode", campaign.protocol.submission_mode);
  addDetail(metadata, "Opens", dateTime(campaign.opens_at));
  addDetail(metadata, "Closes", dateTime(campaign.closes_at));
  addDetail(metadata, "Scoring close block", campaign.scoring_close_block);
  addDetail(metadata, "Reward pool", money(campaign.reward_pool_usd));
  addDetail(metadata, "Max tweets / creator", campaign.max_tweets_per_creator);
  addDetail(metadata, "Required terms", display(campaign.required_terms));
  addDetail(metadata, "Inclusion keywords", display(campaign.inclusion_keywords));
  addDetail(metadata, "Language", campaign.language);
  addDetail(metadata, "Tag", campaign.tag);
  addDetail(metadata, "Quoted tweet", campaign.quoted_tweet_id);
  addDetail(metadata, "Matched tweets", campaign.stats?.matched_tweets);
  addDetail(metadata, "Total views", campaign.stats?.total_views);
  addDetail(metadata, "Total engagements", campaign.stats?.total_engagements);
  addDetail(metadata, "Data updated", dateTime(campaign.stats?.data_updated_at));
  const direct = !campaign.capabilities.requires_claim;
  $("#claim-form").classList.toggle("hidden", direct);
  $("#recover-claim").classList.toggle("hidden", direct);
  $("#operation-title").textContent = direct ? "Submit published tweet" : "Commit draft before posting";
  if (campaignChanged) {
    state.selectedSubmissionId = null;
    $("#submission-detail").classList.add("hidden");
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
  $("#claim-details").classList.add("hidden");
  if (
    state.claim?.campaign_id === campaign.campaign_id
    && state.claim?.creator_x_id === creatorId()
  ) {
    refreshClaim();
  }
}

async function checkEligibility() {
  try {
    const result = await request(
      `/api/campaigns/${state.selectedCampaign.campaign_id}/eligibility/${requireCreator()}`,
    );
    const evidence = (result.eligible_ecosystems || [])
      .map((item) => `${item.ecosystem_id}: ${item.eligible ? `eligible at rank ${item.rank}` : "not eligible"}`)
      .join(" · ");
    const badges = (result.badges || []).map((item) => item.label).join(", ");
    notice(
      $("#eligibility-result"),
      `${result.reason.replaceAll("_", " ")}${evidence ? ` · ${evidence}` : ""}`
        + `${badges ? ` · badges: ${badges}` : ""}`
        + `${result.checked_at ? ` · checked ${dateTime(result.checked_at)}` : ""}`,
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
    notice(
      $("#claim-result"),
      state.draftPrecheckEnabled
        ? "Running strict three-of-three tweet precheck before committing…"
        : "Committing the private draft on chain…",
    );
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
  const details = $("#claim-details");
  details.replaceChildren();
  addDetail(details, "Claim ID", claim.claim_id);
  addDetail(details, "External ID", claim.external_id);
  addDetail(details, "Snapshot", claim.campaign_snapshot_id);
  addDetail(details, "Ecosystems", display(claim.ecosystem_ids));
  addDetail(details, "Commitment", claim.commitment?.status);
  addDetail(details, "Batch sequence", claim.commitment?.batch_sequence);
  addDetail(details, "Batch hash", claim.commitment?.batch_hash);
  addDetail(details, "Finalized block", claim.commitment?.block);
  addDetail(details, "Block hash", claim.commitment?.block_hash);
  addDetail(details, "Extrinsic index", claim.commitment?.extrinsic_index);
  addDetail(details, "Usability", claim.usability?.status);
  addDetail(details, "Created", dateTime(claim.created_at));
  addDetail(details, "Updated", dateTime(claim.updated_at));
  details.classList.remove("hidden");
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

async function recoverClaim() {
  if (!state.selectedCampaign || !state.selectedCampaign.capabilities.requires_claim) return;
  try {
    const creator = requireCreator();
    const query = new URLSearchParams({
      campaign_id: state.selectedCampaign.campaign_id,
      creator_x_id: creator,
    });
    const result = await request(`/api/claims?${query}`);
    const claim = (result.items || [])[0];
    if (!claim) {
      state.claim = null;
      localStorage.removeItem("bx-reference-claim");
      notice($("#claim-result"), "No durable claim was found for this creator and campaign.");
      return;
    }
    state.claim = claim;
    localStorage.setItem("bx-reference-claim", JSON.stringify(claim));
    renderClaim(claim);
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
    await loadSubmissionDetail(submission.submission_id);
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
    const result = document.createElement("div");
    const summary = document.createElement("div");
    summary.textContent = item.failure_reason || item.evaluation?.explanation || item.attribution?.reason || "—";
    const view = document.createElement("button");
    view.type = "button";
    view.className = "button secondary table-action";
    view.textContent = "View complete result";
    view.addEventListener("click", () => loadSubmissionDetail(item.submission_id));
    result.append(summary, view);
    row.append(
      tableCell(link),
      tableCell(item.campaign_id),
      tableCell((item.status || "pending").replaceAll("_", " ")),
      tableCell(item.evaluation?.score ?? item.score),
      tableCell(reward?.status === "recommended" ? money(reward.total) : reward?.status || "Pending"),
      tableCell(result),
    );
    return row;
  }));
}

async function loadSubmissions() {
  try {
    if (!/^\d+$/.test(creatorId())) {
      renderTableMessage("#submission-rows", "Enter your numeric X user ID to load submissions.");
      return;
    }
    const query = new URLSearchParams();
    query.set("creator_x_id", creatorId());
    const result = await request(`/api/submissions${query.size ? `?${query}` : ""}`);
    renderSubmissions(result.items || []);
    if (state.selectedSubmissionId) await loadSubmissionDetail(state.selectedSubmissionId);
  } catch (error) {
    renderTableMessage("#submission-rows", error.message);
  }
}

function resultGroup(title, entries, jsonValue = null) {
  const group = document.createElement("section");
  group.className = `result-group${jsonValue === null ? "" : " full-width"}`;
  const heading = document.createElement("h4");
  heading.textContent = title;
  const list = document.createElement("dl");
  list.className = "detail-list";
  for (const [label, value] of entries) addDetail(list, label, display(value));
  group.append(heading, list);
  if (jsonValue !== null) {
    const pre = document.createElement("pre");
    pre.className = "result-json";
    pre.textContent = JSON.stringify(jsonValue, null, 2);
    group.append(pre);
  }
  return group;
}

function renderSubmissionDetail(item) {
  state.selectedSubmissionId = item.submission_id;
  $("#submission-detail-title").textContent = `Submission ${short(item.submission_id)}`;
  const creator = item.creator || {};
  const claimCommitment = item.claim_commitment || {};
  const submissionCommitment = item.submission_commitment || {};
  const decision = item.decision || {};
  const evaluation = item.evaluation || {};
  const attribution = item.attribution || {};
  const reward = item.reward_recommendation || {};
  const tweet = item.tweet || {};
  const metrics = item.metrics || {};
  $("#submission-detail-content").replaceChildren(
    resultGroup("Receipt", [
      ["Submission ID", item.submission_id], ["External ID", item.external_id],
      ["Campaign", item.campaign_id], ["Snapshot", item.campaign_snapshot_id],
      ["Ecosystems", item.ecosystem_ids], ["Tweet ID", item.tweet_id],
      ["Claim ID", item.claim_id], ["Status", item.status],
      ["Created", dateTime(item.created_at)], ["Updated", dateTime(item.updated_at)],
    ]),
    resultGroup("Creator", [
      ["Submitted X ID", creator.submitted_x_id], ["Verified X ID", creator.verified_x_id],
      ["Username", creator.username ? `@${creator.username}` : null],
    ]),
    resultGroup("Claim commitment", [
      ["Status", claimCommitment.status], ["Batch sequence", claimCommitment.batch_sequence],
      ["Batch hash", claimCommitment.batch_hash], ["Block", claimCommitment.block],
      ["Block hash", claimCommitment.block_hash], ["Extrinsic", claimCommitment.extrinsic_index],
    ]),
    resultGroup("Submission commitment", [
      ["Status", submissionCommitment.status], ["Batch sequence", submissionCommitment.batch_sequence],
      ["Batch hash", submissionCommitment.batch_hash], ["Block", submissionCommitment.block],
      ["Block hash", submissionCommitment.block_hash], ["Extrinsic", submissionCommitment.extrinsic_index],
      ["Failure", submissionCommitment.failure_reason],
    ]),
    resultGroup("Validator decision", [
      ["Authority", decision.authority], ["Validator", decision.source_validator_hotkey],
      ["Status", decision.status], ["Observed", dateTime(decision.observed_at)],
    ]),
    resultGroup("Evaluation", [
      ["Status", evaluation.status], ["Reason", evaluation.reason],
      ["Explanation", evaluation.explanation || item.failure_reason], ["Score", evaluation.score ?? item.score],
      ["Baseline score", evaluation.baseline_score ?? item.baseline_score],
      ["Author influence", evaluation.author_influence ?? item.author_influence],
    ]),
    resultGroup("Attribution", [
      ["Status", attribution.status], ["Reason", attribution.reason],
      ["Winner match", attribution.winner_match_score], ["Runner-up match", attribution.runner_up_match_score],
    ]),
    resultGroup("Reward recommendation", [
      ["Status", reward.status], ["Reason", reward.reason], ["Currency", reward.currency],
      ["Total", reward.total === null || reward.total === undefined ? null : money(reward.total)],
      ["Finality", reward.finality],
    ]),
    resultGroup("Tweet and metrics", [
      ["URL", tweet.url], ["Content", tweet.content], ["Published", dateTime(tweet.published_at)],
      ["Observed", dateTime(tweet.observed_at)], ["Views", metrics.views ?? item.views],
      ["Likes", metrics.likes ?? item.likes], ["Retweets", metrics.retweets ?? item.retweets],
      ["Replies", metrics.replies ?? item.replies], ["Quotes", metrics.quotes ?? item.quotes],
      ["Bookmarks", metrics.bookmarks ?? item.bookmarks], ["Captured", dateTime(metrics.captured_at)],
    ]),
    resultGroup("Score breakdown", [], evaluation.score_breakdown || item.score_breakdown || []),
  );
  $("#submission-detail").classList.remove("hidden");
  $("#submission-detail").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

async function loadSubmissionDetail(submissionId) {
  try {
    renderSubmissionDetail(await request(`/api/submissions/${submissionId}`));
  } catch (error) {
    notice($("#submission-result"), error.message, "error");
  }
}

async function loadCampaignTweets() {
  try {
    const query = selectedQuery();
    const result = await request(
      `/api/campaigns/${state.selectedCampaign.campaign_id}/tweets${query ? `?${query}` : ""}`,
    );
    const items = result.tweets || result.items || [];
    const rows = $("#campaign-tweet-rows");
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
        tableCell(item.author_username
          ? `@${item.author_username}${item.belongs_to_requesting_miner ? " · yours" : ""}`
          : (item.belongs_to_requesting_miner ? "Yours" : "—")),
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
    renderTableMessage("#campaign-tweet-rows", error.message);
  }
}

async function loadEcosystemLeaderboard() {
  renderTableMessage("#leaderboard-rows", "Loading leaderboard…");
  $("#leaderboard-previous").disabled = true;
  $("#leaderboard-next").disabled = true;
  try {
    const result = await request(`/api/leaderboard?${leaderboardQuery()}`);
    const items = result.accounts || [];
    state.leaderboardTotalCount = Number(result.total_count || 0);
    state.leaderboardLoaded = true;
    $("#leaderboard-updated").textContent = result.data_updated_at
      ? `Scores updated ${dateTime(result.data_updated_at)} · ${number(result.total_count)} creators`
      : `${number(result.total_count)} creators`;
    if (!items.length) {
      renderTableMessage("#leaderboard-rows", "No scored creators in the selected ecosystems.");
      renderLeaderboardPagination();
      return;
    }
    $("#leaderboard-rows").replaceChildren(...items.map((item) => {
      const row = document.createElement("tr");
      const creator = document.createElement("a");
      creator.href = `https://x.com/${encodeURIComponent(item.username)}`;
      creator.target = "_blank";
      creator.rel = "noopener noreferrer";
      creator.textContent = item.display_name
        ? `${item.display_name} · @${item.username}`
        : `@${item.username}`;
      const scores = Object.entries(item.scores || {})
        .sort((left, right) => Number(right[1]) - Number(left[1]))
        .map(([ecosystem, score]) => `${ecosystem}: ${Number(score).toFixed(3)}`)
        .join(" · ");
      row.append(
        tableCell(`#${item.rank}`),
        tableCell(creator),
        tableCell(scores),
        tableCell(Number(item.score).toFixed(3)),
        tableCell(item.followers === null || item.followers === undefined ? "—" : number(item.followers)),
        tableCell(item.connected ? "Yes" : "No"),
      );
      return row;
    }));
    renderLeaderboardPagination();
  } catch (error) {
    $("#leaderboard-updated").textContent = "Leaderboard unavailable";
    renderTableMessage("#leaderboard-rows", error.message);
    $("#leaderboard-page-status").textContent = "Unable to load page";
  }
}

function renderLeaderboardPagination() {
  const total = state.leaderboardTotalCount;
  const pageCount = Math.max(1, Math.ceil(total / state.leaderboardLimit));
  const page = Math.floor(state.leaderboardOffset / state.leaderboardLimit) + 1;
  const first = total ? state.leaderboardOffset + 1 : 0;
  const last = Math.min(state.leaderboardOffset + state.leaderboardLimit, total);
  $("#leaderboard-page-status").textContent = total
    ? `Showing ${number(first)}–${number(last)} of ${number(total)} · Page ${number(page)} of ${number(pageCount)}`
    : "No ranked creators";
  $("#leaderboard-previous").disabled = state.leaderboardOffset === 0;
  $("#leaderboard-next").disabled = state.leaderboardOffset + state.leaderboardLimit >= total;
}

async function boot() {
  showPage(currentPage());
  $("#creator-x-id").value = localStorage.getItem("bx-reference-creator") || "";
  try {
    const [status, ecosystems, draftPrecheck] = await Promise.all([
      request("/api/status"),
      request("/api/ecosystems"),
      request("/api/draft-precheck/status"),
    ]);
    renderStatus(status);
    renderDraftPrecheckStatus(draftPrecheck);
    state.ecosystems = ecosystems.items || [];
    state.enabledEcosystems = new Set(state.ecosystems.map((item) => item.ecosystem_id));
    renderEcosystems();
    renderLeaderboardFilters();
    const loads = [loadCampaigns(), loadSubmissions()];
    if (currentPage() === "leaderboard") loads.push(loadEcosystemLeaderboard());
    await Promise.all(loads);
  } catch (error) {
    $("#node-badge").textContent = error.message;
    $("#node-badge").className = "status-badge error";
    $("#campaign-message").textContent = error.message;
  }
}

$("#creator-x-id").addEventListener("change", () => {
  if (/^\d+$/.test(creatorId())) {
    localStorage.setItem("bx-reference-creator", creatorId());
    if (state.claim?.creator_x_id !== creatorId()) {
      state.claim = null;
      localStorage.removeItem("bx-reference-claim");
    }
    recoverClaim();
  }
  loadSubmissions();
});
$("#check-eligibility").addEventListener("click", checkEligibility);
$("#claim-form").addEventListener("submit", createClaim);
$("#recover-claim").addEventListener("click", recoverClaim);
$("#submission-form").addEventListener("submit", createSubmission);
$("#refresh-campaign").addEventListener("click", async () => {
  await selectCampaign(state.selectedCampaign);
  await refreshClaim();
});
$("#refresh-submissions").addEventListener("click", loadSubmissions);
document.querySelectorAll(".nav-link").forEach((button) => {
  button.addEventListener("click", async () => {
    showPage(button.dataset.page, true);
    if (button.dataset.page === "leaderboard" && !state.leaderboardLoaded) {
      await loadEcosystemLeaderboard();
    }
    window.scrollTo({ top: 0, behavior: "smooth" });
  });
});
window.addEventListener("popstate", async () => {
  showPage(currentPage());
  if (currentPage() === "leaderboard" && !state.leaderboardLoaded) {
    await loadEcosystemLeaderboard();
  }
});
$("#leaderboard-page-size").addEventListener("change", async (event) => {
  state.leaderboardLimit = Number(event.target.value);
  state.leaderboardOffset = 0;
  await loadEcosystemLeaderboard();
});
$("#leaderboard-previous").addEventListener("click", async () => {
  state.leaderboardOffset = Math.max(0, state.leaderboardOffset - state.leaderboardLimit);
  await loadEcosystemLeaderboard();
  $("#leaderboard-page").scrollIntoView({ behavior: "smooth", block: "start" });
});
$("#leaderboard-next").addEventListener("click", async () => {
  if (state.leaderboardOffset + state.leaderboardLimit >= state.leaderboardTotalCount) return;
  state.leaderboardOffset += state.leaderboardLimit;
  await loadEcosystemLeaderboard();
  $("#leaderboard-page").scrollIntoView({ behavior: "smooth", block: "start" });
});
$("#close-submission-detail").addEventListener("click", () => {
  state.selectedSubmissionId = null;
  $("#submission-detail").classList.add("hidden");
});
setInterval(async () => {
  await refreshClaim();
  await loadSubmissions();
}, 15000);

boot();
