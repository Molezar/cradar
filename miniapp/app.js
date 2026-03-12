//app.js
let lastPrice = null;
const ALERT_WHALE_BTC = window.ALERT_WHALE_BTC || 1000;

// --- Utility Functions ---
function fmtTime(ts) {
    const d = new Date(ts * 1000);
    return d.toLocaleTimeString("en-US", { hour12: false });
}

function flowArrow(flow) {
    return {
        DEPOSIT: "→",
        WITHDRAW: "←",
        INTERNAL: "↔",
        POSSIBLE_EXCHANGE_WITHDRAW: "←",
        POSSIBLE_EXCHANGE_DEPOSIT: "→",
        CONSOLIDATION: "↦",
        TRANSFER: "•"
    }[flow] || "•";
}

function flowLabel(flow) {
    const labels = {
        DEPOSIT: "DEPOSIT",
        WITHDRAW: "WITHDRAW",
        INTERNAL: "INTERNAL",
        POSSIBLE_EXCHANGE_WITHDRAW: "EXCH. WITHDRAW",
        POSSIBLE_EXCHANGE_DEPOSIT: "EXCH. DEPOSIT",
        CONSOLIDATION: "CONSOLIDATION",
        TRANSFER: "TRANSFER",
        UNKNOWN: "UNKNOWN"
    };

    const cls = flow.toLowerCase();
    return `<span class="flow ${cls}">${labels[flow] || flow}</span>`;
}

// --- Main Load Function ---
async function load() {
    try {

        const [wj, pj, pcj, volj, flowj, rawj] = await Promise.all([
            fetch("/whales?t=" + Date.now()).then(r => r.json()),
            fetch("/prediction?t=" + Date.now()).then(r => r.json()),
            fetch("/price?t=" + Date.now()).then(r => r.json()),
            fetch("/volumes?t=" + Date.now()).then(r => r.json()),
            fetch("/exchange_flow?window=600&t=" + Date.now()).then(r => r.json()),
            fetch("/exchange_flow_raw?limit=50&t=" + Date.now()).then(r => r.json())
        ]);

        // --- Whales List ---
        let out = "";

        if (wj.whales && Array.isArray(wj.whales)) {

            for (const x of wj.whales) {

                const btc = Number(x.btc);
                if (isNaN(btc) || btc <= 0) continue;

                const conf = Number(x.confidence) || 0;

                const cls = btc >= ALERT_WHALE_BTC ? "whale huge" : "whale";

                const confText = conf
                    ? `<span class="confidence">(${(conf*100).toFixed(0)}%)</span>`
                    : "";

                out += `<div class="${cls}">
                    ${fmtTime(x.time)} &nbsp;
                    ${btc.toFixed(2)} BTC
                    ${flowArrow(x.flow_type)}
                    ${flowLabel(x.flow_type)}
                    ${confText}
                </div>`;
            }
        }

        document.getElementById("list").innerHTML = out;

        // --- BTC Price ---
        if (pcj.price) {
            lastPrice = pcj.price;
            document.getElementById("info").innerText = `BTC $${Number(pcj.price).toFixed(0)}`;
        } else {
            document.getElementById("info").innerText = "BTC price…";
        }

        // --- AI Market Forecast ---
        let pred = "<div class='pred'>=== AI MARKET FORECAST ===</div>";

        for (const horizon in pj) {

            const row = pj[horizon];
            if (!row) continue;

            const pct = Number(row.pct) || 0;
            const target = Number(row.target) || 0;

            const dir = pct > 0 ? "⬆" : pct < 0 ? "⬇" : "→";

            const minutes = Number(horizon) / 60;

            pred += `<div>${minutes} min ${dir} ${pct.toFixed(2)}% → $${target.toFixed(0)}</div>`;
        }

        document.getElementById("forecast").innerHTML = pred;

        // --- Volumes ---
        let volHtml = "<div class='volumes'><div class='pred'>=== 1H VOLUMES ===</div>";

        volHtml += `<div>DEPOSIT: <span class='flow deposit'>${volj.deposit.toFixed(2)} BTC</span></div>`;
        volHtml += `<div>WITHDRAW: <span class='flow withdraw'>${volj.withdraw.toFixed(2)} BTC</span></div>`;

        const netColor = volj.net >= 0 ? "positive" : "negative";

        volHtml += `<div>NET (W-D): <span class='net ${netColor}'>${volj.net.toFixed(2)} BTC</span></div>`;
        volHtml += "</div>";

        document.getElementById("volumes").innerHTML = volHtml;

        // --- Exchange Flow Minimap ---
        let flowHtml = "<div class='volumes'><div class='pred'>=== EXCHANGE FLOW (10 min) ===</div>";

        for (const x of flowj.flows || []) {
            const net = Number(x.net_flow) || 0;
            const dir = net > 0 ? "⬆" : net < 0 ? "⬇" : "→";
            const color = net > 0 ? "green" : net < 0 ? "red" : "gray";

            flowHtml += `<div style="color:${color}">
                Cluster ${x.cluster_id}: ${dir} ${net.toFixed(2)} BTC
            </div>`;
        }

        flowHtml += "</div>";

        document.getElementById("exchange_flow").innerHTML = flowHtml;

        // --- RAW Exchange Flow ---
        let rawHtml = "<div class='volumes'><div class='pred'>=== RAW EXCHANGE FLOW ===</div>";

        for (const r of rawj.rows || []) {

            const color = r.flow_type === "DEPOSIT" ? "#00ffaa" : "#ff5c5c";
            const arrow = r.flow_type === "DEPOSIT" ? "←" : "→";    

            rawHtml += `<div style="color:${color}">
                ${fmtTime(r.ts)} &nbsp;
                Cluster ${r.cluster_id} &nbsp;
                ${arrow} ${r.btc.toFixed(2)} BTC
            </div>`;
        }

        rawHtml += "</div>";

        document.getElementById("exchange_flow_raw").innerHTML = rawHtml;

    } catch (e) {

        document.getElementById("info").innerText = "API error";
        console.error(e);

    }
}

// --- INIT ---
load();
setInterval(load, 5000);