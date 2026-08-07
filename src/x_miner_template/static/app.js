const campaignSelect = document.querySelector("#campaign");
const campaignDetails = document.querySelector("#campaign-details");
const claimResult = document.querySelector("#claim-result");
const submissionResult = document.querySelector("#submission-result");
let campaigns = [];
let operation = JSON.parse(localStorage.getItem("bitcastMinerOperation") || "null");

async function request(path, options = {}) {
  const response = await fetch(path, { headers: { "content-type": "application/json" }, ...options });
  const body = await response.json();
  if (!response.ok) throw new Error(body.detail || `Request failed (${response.status})`);
  return body;
}

function show(element, message, ok = true) {
  element.textContent = message;
  element.className = `result ${ok ? "success" : "error"}`;
}

function selectedCampaign() {
  return campaigns.find((item) => item.access.campaign_id === campaignSelect.value);
}

function renderCampaign() {
  const campaign = selectedCampaign();
  campaignDetails.textContent = campaign ? `${campaign.title}\n${campaign.brief}\nReward pool: $${campaign.reward_pool_usd}` : "";
}

async function load() {
  try {
    const [health, qualification] = await Promise.all([request("/health"), request("/api/qualification")]);
    document.querySelector("#miner-status").textContent = `Protocol ${health.protocol_version}; qualification: ${JSON.stringify(qualification)}`;
    campaigns = await request("/api/campaigns");
    campaignSelect.replaceChildren(...campaigns.map((item) => {
      const option = document.createElement("option");
      option.value = item.access.campaign_id;
      option.textContent = item.title;
      return option;
    }));
    renderCampaign();
    if (operation) {
      campaignSelect.value = operation.campaignId;
      renderCampaign();
      show(claimResult, `Restored claim ${operation.claimId}: ${operation.claimStatus}`);
      if (operation.submissionId) show(submissionResult, `Restored submission ${operation.submissionId}: ${operation.submissionStatus}`);
      await refreshOperation();
    }
  } catch (error) {
    document.querySelector("#miner-status").textContent = error.message;
  }
}

async function refreshOperation() {
  if (!operation) return;
  const claim = await request(`/api/claims/${operation.claimId}`);
  operation.claimStatus = claim.status;
  show(claimResult, `Claim ${operation.claimId}: ${claim.status}`);
  if (operation.submissionId) {
    const submission = await request(`/api/submissions/${operation.submissionId}`);
    operation.submissionStatus = submission.status;
    show(submissionResult, `Submission ${operation.submissionId}: ${submission.status}`);
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
    show(claimResult, `Claim ${result.claim_id}: ${result.status}`);
  } catch (error) { show(claimResult, error.message, false); }
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
    show(submissionResult, `Submission ${result.submission_id}: ${result.status}. Validators will now fetch and verify it.`);
  } catch (error) { show(submissionResult, error.message, false); }
});

load();
setInterval(() => refreshOperation().catch(() => {}), 5000);
