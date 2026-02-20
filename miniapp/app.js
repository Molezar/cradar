let lastPrice = null;
const alertsDisplayed = new Set();

const ALERT_WHALE_BTC = window.ALERT_WHALE_BTC || 3000;

function fmtTime(ts) {
    const d = new Date(ts * 1000);
    return d.toLocaleTimeString();
}

async function load() {
    try {
        const wr = await fetch("/whales?t=" + Date.now());
        const wj = await wr.json();

        const pr = await fetch("/prediction?t=" + Date.now());
        const pj = await pr.json();

        const prc = await fetch("/price?t=" + Date.now());
        const pcj = await prc.json();

        let out = "";

        if (wj.whales && Array.isArray(wj.whales)) {

            for (const x of wj.whales) {

                const t = fmtTime(x.time);
                const btc = Number(x.btc || 0);
                const isHuge = btc >= 1000;
                const cls = isHuge ? "whale huge" : "whale";

                let dir = "";

                if (x.flow_type === "DEPOSIT") dir = "→ Exchange";
                else if (x.flow_type === "WITHDRAW") dir = "← Exchange";
                else if (x.flow_type === "INTERNAL") dir = "↔ Internal";
                else dir = "";

                out += `
                    <div class="${cls}">
                        ${t} &nbsp; ${btc.toFixed(2)} BTC ${dir}
                    </div>
                `;
            }
        }

        // =========================
        // Price
        // =========================

        if (pcj.price) {
            lastPrice = pcj.price;
            document.getElementById("info").innerText =
                `BTC $${Number(pcj.price).toFixed(0)}`;
        } else {
            document.getElementById("info").innerText = "BTC price…";
        }
        
        // =========================
        // Prediction
        // =========================
        
        let pred = "<br><div class='pred'>=== AI MARKET FORECAST ===</div>";

        for (const horizon in pj) {

            const row = pj[horizon];
            if (!row) continue;

            const pct = Number(row.pct || 0);
            const target = Number(row.target || 0);

            const dir = pct > 0 ? "⬆" : pct < 0 ? "⬇" : "→";

            pred += `
                <div>
                    ${horizon / 60} min ${dir}
                    ${pct.toFixed(2)}%
                    → $${target.toFixed(0)}
                </div>
            `;
        }

        document.getElementById("forecast").innerHTML = pred;
        document.getElementById("list").innerHTML = out;

        // =========================
        // Price
        // =========================

    } catch (e) {
        document.getElementById("info").innerText = "API error";
        console.error(e);
    }
}


// =====================================================
// ALERTS (SSE)
// =====================================================

function startAlerts() {

    const evtSource = new EventSource("/events");

    evtSource.onmessage = (e) => {

        try {

            const tx = JSON.parse(e.data);

            if (!tx || !tx.txid) return;

            const btc = Number(tx.btc || 0);

            if (btc < ALERT_WHALE_BTC) return;

            if (alertsDisplayed.has(tx.txid)) return;
            alertsDisplayed.add(tx.txid);

            const t = fmtTime(tx.time || Math.floor(Date.now() / 1000));

            let dir = "";

            if (tx.flow === "DEPOSIT") dir = "→ Exchange";
            else if (tx.flow === "WITHDRAW") dir = "← Exchange";
            else if (tx.flow === "INTERNAL") dir = "↔ Internal";

            const msg = `
                ${t} &nbsp;
                ${btc.toFixed(2)} BTC
                ${dir}
            `;

            const alertsDiv = document.getElementById("alerts");

            const div = document.createElement("div");
            div.className = "alert";
            div.innerHTML = msg;

            alertsDiv.prepend(div);

        } catch (err) {
            console.error("Alert parsing error:", err);
        }
    };

    evtSource.onerror = () => {
        console.warn("SSE connection lost. Reconnecting...");
    };
}


// =====================================================
// INIT
// =====================================================

load();
setInterval(load, 5000);
startAlerts();