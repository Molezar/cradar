let lastPrice = null;
const alertsDisplayed = new Set();

const ALERT_WHALE_BTC = window.ALERT_WHALE_BTC || 3000;

function fmtTime(ts) {
    const d = new Date(ts * 1000);
    return d.toLocaleTimeString();
}

function flowLabel(flow) {
    if (flow === "DEPOSIT")
        return `<span class="flow deposit">DEPOSIT</span>`;
    if (flow === "WITHDRAW")
        return `<span class="flow withdraw">WITHDRAW</span>`;
    if (flow === "INTERNAL")
        return `<span class="flow internal">INTERNAL</span>`;
    return "";
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

                let dirArrow = "";

                if (x.flow_type === "DEPOSIT") dirArrow = "→";
                else if (x.flow_type === "WITHDRAW") dirArrow = "←";
                else if (x.flow_type === "INTERNAL") dirArrow = "↔";

                const flowText = flowLabel(x.flow_type);

                out += `
                    <div class="${cls}">
                        ${t} &nbsp;
                        ${btc.toFixed(2)} BTC
                        ${dirArrow}
                        ${flowText}
                    </div>
                `;
            }
        }

        if (pcj.price) {
            lastPrice = pcj.price;
            document.getElementById("info").innerText =
                `BTC $${Number(pcj.price).toFixed(0)}`;
        } else {
            document.getElementById("info").innerText = "BTC price…";
        }

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

            let arrow = "";
            if (tx.flow === "DEPOSIT") arrow = "→";
            else if (tx.flow === "WITHDRAW") arrow = "←";
            else if (tx.flow === "INTERNAL") arrow = "↔";

            const flowText = flowLabel(tx.flow);

            const msg = `
                ${t} &nbsp;
                ${btc.toFixed(2)} BTC
                ${arrow}
                ${flowText}
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


// INIT
load();
setInterval(load, 5000);
startAlerts();