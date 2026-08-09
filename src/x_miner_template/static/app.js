const campaignSelect = document.querySelector("#campaign");
const resumeCampaignSelect = document.querySelector("#resume-campaign");
const campaignDetails = document.querySelector("#campaign-details");
const claimResult = document.querySelector("#claim-result");
const resumeClaimResult = document.querySelector("#resume-claim-result");
const submissionResult = document.querySelector("#submission-result");
const verificationRows = document.querySelector("#verification-rows");
let campaigns = [];
let operation = JSON.parse(localStorage.getItem("bitcastMinerOperation") || "null");

async function request(path, options = {}) {
  const response = await fetch(path, { headers: { "content-type": "application/json" }, ...options });
  let body = {};
  try { body = await response.json(); } catch { /* non-JSON error bodies */ }
  if (!response.ok) throw new Error(formatDetail(body.detail) || `Request failed (${response.status})`);
  return body;
}

function show(element, message, ok = true) {
  element.textContent = message;
  element.className = `result ${ok ? "success" : "error"}`;
}

function formatDetail(detail) {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((item) => item.msg || JSON.stringify(item)).join("; ");
  return detail ? JSON.stringify(detail) : "";
}

function claimLabel(claimId, status) {
  if (status === "waiting_for_commitment") {
    return `Claim ${claimId}: waiting for chain commitment… This page will update when it finalizes.`;
  }
  return `Claim ${claimId}: ${status}`;
}

function submissionLabel(submissionId, status) {
  if (status === "tweet_received") {
    return `Submission ${submissionId}: waiting for chain commitment… This page will update when it finalizes.`;
  }
  return `Submission ${submissionId}: ${status}`;
}

function truncateMiddle(value, keep = 6) {
  if (typeof value !== "string" || value.length <= keep * 2 + 1) return value;
  return `${value.slice(0, keep)}…${value.slice(-keep)}`;
}

function statusRow(dl, label, value, { mono = false, title } = {}) {
  if (value === undefined || value === null || value === "") return;
  const dt = document.createElement("dt");
  dt.textContent = label;
  const dd = document.createElement("dd");
  if (mono) dd.className = "mono";
  if (title) dd.title = title;
  if (value instanceof Node) dd.appendChild(value);
  else dd.textContent = value;
  dl.append(dt, dd);
}

function badge(text, ok) {
  const span = document.createElement("span");
  span.className = `badge ${ok ? "yes" : "no"}`;
  span.textContent = text;
  return span;
}

function renderMinerStatus(health, qualification) {
  const dl = document.querySelector("#miner-status");
  dl.replaceChildren();
  statusRow(dl, "Protocol", `v${health.protocol_version} (miner ${health.version})`);
  statusRow(dl, "Qualified", badge(qualification.eligible ? "Yes" : "No", qualification.eligible));
  statusRow(dl, "Reason", qualification.reason);
  if (qualification.conviction_alpha !== undefined) {
    statusRow(
      dl,
      "Conviction",
      `${qualification.conviction_alpha} / ${qualification.required_conviction_alpha} α required`,
    );
  }
  if (qualification.miner_hotkey) {
    statusRow(dl, "Miner hotkey", truncateMiddle(qualification.miner_hotkey), {
      mono: true,
      title: qualification.miner_hotkey,
    });
  }
  if (qualification.configured_owner_hotkey) {
    statusRow(dl, "Owner hotkey", truncateMiddle(qualification.configured_owner_hotkey), {
      mono: true,
      title: qualification.configured_owner_hotkey,
    });
  }
  if (qualification.controlling_coldkey) {
    statusRow(dl, "Controlling coldkey", truncateMiddle(qualification.controlling_coldkey), {
      mono: true,
      title: qualification.controlling_coldkey,
    });
  }
  if (qualification.effective_block !== undefined) {
    statusRow(
      dl,
      "Effective / checked block",
      `${qualification.effective_block} / ${qualification.checked_block ?? "latest"}`,
    );
  }
}

function verificationStatus(status) {
  if (status === "verification_pending") return "Pending validator verification";
  if (status === "provisionally_passed") return "Passed (provisional)";
  if (status === "provisionally_failed") return "Failed (provisional)";
  if (status === "attributed") return "Attributed";
  if (status === "rejected") return "Rejected";
  if (status === "tweet_received") return "Waiting for chain commitment";
  return status;
}

function renderVerifications(submissions) {
  if (!submissions.length) {
    verificationRows.innerHTML = '<tr><td colspan="6">No tweet submissions yet.</td></tr>';
    return;
  }
  verificationRows.replaceChildren(...submissions.map((submission) => {
    const row = document.createElement("tr");
    const tweet = document.createElement("a");
    tweet.href = `https://x.com/i/status/${submission.tweet_id}`;
    tweet.target = "_blank";
    tweet.rel = "noopener noreferrer";
    tweet.textContent = submission.tweet_id;
    const score = submission.score == null ? "—" : Number(submission.score).toFixed(4);
    const metrics = submission.failure_reason ||
      `${Number(submission.views || 0).toLocaleString()} views · ${Number(submission.likes || 0).toLocaleString()} likes · ${Number(submission.retweets || 0).toLocaleString()} reposts`;
    const values = [tweet, submission.campaign_id,
      new Date(Number(submission.created_ns) / 1e6).toLocaleString(),
      verificationStatus(submission.status), score, metrics];
    for (const value of values) {
      const cell = document.createElement("td");
      if (value instanceof Node) cell.appendChild(value);
      else cell.textContent = value;
      row.appendChild(cell);
    }
    row.dataset.status = submission.status;
    return row;
  }));
}

async function refreshVerifications() {
  renderVerifications(await request("/api/submissions"));
}

function showMinerStatusError(message) {
  const dl = document.querySelector("#miner-status");
  dl.replaceChildren();
  statusRow(dl, "Status", message);
}

function selectedCampaign() {
  return campaigns.find((item) => item.access.campaign_id === campaignSelect.value);
}

function renderCampaign() {
  const campaign = selectedCampaign();
  const stats = campaign?.stats;
  campaignDetails.textContent = campaign
    ? `${campaign.display}\nPools: ${campaign.pools.join(", ")}\nReward pool: $${campaign.reward_pool_usd}`
      + (stats
        ? `\nMatched tweets: ${stats.matched_tweets}\nViews: ${stats.total_views.toLocaleString()}`
          + `\nEngagements: ${stats.total_engagements.toLocaleString()} (${stats.engagement_rate}%)`
        : "")
    : "";
}

async function load() {
  try {
    const [health, qualification] = await Promise.all([request("/health"), request("/api/qualification")]);
    renderMinerStatus(health, qualification);
    campaigns = await request("/api/campaigns");
    await refreshVerifications();
    const buildCampaignOptions = () => campaigns.map((item) => {
      const option = document.createElement("option");
      option.value = item.access.campaign_id;
      option.textContent = item.access.campaign_id;
      return option;
    });
    campaignSelect.replaceChildren(...buildCampaignOptions());
    resumeCampaignSelect.replaceChildren(...buildCampaignOptions());
    renderCampaign();
    if (operation) {
      campaignSelect.value = operation.campaignId;
      resumeCampaignSelect.value = operation.campaignId;
      renderCampaign();
      show(claimResult, claimLabel(operation.claimId, operation.claimStatus));
      if (operation.submissionId) {
        show(submissionResult, submissionLabel(operation.submissionId, operation.submissionStatus));
      }
      await refreshOperation();
    }
  } catch (error) {
    showMinerStatusError(error.message);
  }
}

async function refreshOperation() {
  if (!operation) return;
  const claim = await request(`/api/claims/${operation.claimId}`);
  operation.claimStatus = claim.status;
  show(claimResult, claimLabel(operation.claimId, claim.status));
  if (operation.submissionId) {
    const submission = await request(`/api/submissions/${operation.submissionId}`);
    operation.submissionStatus = submission.status;
    show(submissionResult, submissionLabel(operation.submissionId, submission.status));
  }
  localStorage.setItem("bitcastMinerOperation", JSON.stringify(operation));
}

campaignSelect.addEventListener("change", renderCampaign);

document.querySelector("#claim-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  show(claimResult, "Submitting and waiting for finalized chain commitment…");
  try {
    const result = await request("/api/claims", { method: "POST", body: JSON.stringify({
      campaign_id: campaignSelect.value,
      creator_x_id: document.querySelector("#creator-x-id").value,
      draft: document.querySelector("#draft").value,
    }) });
    operation = { campaignId: campaignSelect.value, claimId: result.claim_id, claimStatus: result.status };
    localStorage.setItem("bitcastMinerOperation", JSON.stringify(operation));
    show(claimResult, claimLabel(result.claim_id, result.status));
  } catch (error) { show(claimResult, error.message, false); }
});

document.querySelector("#resume-claim-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const claimId = document.querySelector("#resume-claim-id").value.trim().toLowerCase();
  if (!/^[0-9a-f]{32}$/.test(claimId)) {
    show(resumeClaimResult, "Enter a valid 32-character claim id.", false);
    return;
  }
  show(resumeClaimResult, "Looking up claim…");
  try {
    const claim = await request(`/api/claims/${claimId}`);
    const campaignId = claim.campaign_id || resumeCampaignSelect.value;
    campaignSelect.value = campaignId;
    resumeCampaignSelect.value = campaignId;
    renderCampaign();
    operation = { campaignId, claimId, claimStatus: claim.status };
    localStorage.setItem("bitcastMinerOperation", JSON.stringify(operation));
    show(resumeClaimResult, claimLabel(claimId, claim.status));
    show(claimResult, claimLabel(claimId, claim.status));
  } catch (error) { show(resumeClaimResult, error.message, false); }
});

document.querySelector("#submission-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!operation || operation.claimStatus !== "safe_to_post") {
    show(submissionResult, "Commit the draft and wait for safe_to_post first.", false);
    return;
  }
  const match = document.querySelector("#tweet").value.trim().match(/(?:status\/)?([0-9]+)(?:\?.*)?$/);
  if (!match) { show(submissionResult, "Enter a valid tweet URL or numeric ID.", false); return; }
  show(submissionResult, "Submitting and waiting for finalized chain commitment…");
  try {
    const result = await request("/api/submissions", { method: "POST", body: JSON.stringify({
      campaign_id: operation.campaignId, tweet_id: match[1], claim_id: operation.claimId,
    }) });
    operation.submissionId = result.submission_id;
    operation.submissionStatus = result.status;
    localStorage.setItem("bitcastMinerOperation", JSON.stringify(operation));
    const message = submissionLabel(result.submission_id, result.status);
    show(
      submissionResult,
      result.status === "verification_pending"
        ? `${message}. Validators will now fetch and verify it.`
        : message,
    );
    await refreshVerifications();
  } catch (error) { show(submissionResult, error.message, false); }
});

load();
setInterval(() => refreshOperation().catch(() => {}), 5000);
setInterval(() => refreshVerifications().catch(() => {}), 30000);
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") refreshVerifications().catch(() => {});
});
