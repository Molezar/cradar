let lastPrice = null;

// Хранение алертов, чтобы не дублировать
const alertsDisplayed = new Set();

function fmtTime(ts) {
    const d = new Date(ts * 1000);
    return d.toLocaleTimeString();
}

async function load() {
    try {
        // whales
        const wr = await fetch("/whales?t=" + Date.now());
        const wj = await wr.json();

        // predictions
        const pr = await fetch("/prediction?t=" + Date.now());
        const pj = await pr.json();

        // price
        const prc = await fetch("/price?t=" + Date.now());
        const pcj = await prc.json();

        let out = "";

        if (wj.whales) {
            for (const x of wj.whales) {
                const t = fmtTime(x.time);
                const isHuge = x.btc >= 1000;

                const cls = isHuge ? "whale huge" : "whale";

                let dir = "";
                if (x.flow === "DEPOSIT") dir = "→ EXCHANGE";
                if (x.flow === "WITHDRAWAL") dir = "← EXCHANGE";
                if (x.flow === "INTERNAL") dir = "↔";

                out += `<div class="${cls}">
                ${t} &nbsp; ${x.btc.toFixed(2)} BTC ${dir} ${x.exchange || ""}
                </div>`;
            }
        }

        let pred = "<br><div class='pred'>=== AI MARKET FORECAST ===</div>";

        for (const horizon in pj) {
            const row = pj[horizon];
            const dir = row.pct > 0 ? "⬆" : "⬇";

            pred += `<div>${horizon/60} min ${dir} ${row.pct.toFixed(2)}% → $${row.target.toFixed(0)}</div>`;
        }

        document.getElementById("list").innerHTML = out + pred;

        document.getElementById("info").innerText =
            pcj.price ? `BTC $${pcj.price.toFixed(0)}` : "BTC price…";

    } catch (e) {
        document.getElementById("info").innerText = "API error";
        console.error(e);
    }
}

// ==========================
// SSE для алертов по ALERT_WHALE_BTC
// ==========================

function startAlerts() {
    const evtSource = new EventSource("/events");

    evtSource.onmessage = (e) => {
        try {
            const tx = JSON.parse(e.data);
            // фильтруем по ALERT_WHALE_BTC
            if (tx.btc >= parseFloat(ALERT_WHALE_BTC || "3000")) {
                const key = tx.txid;
                if (alertsDisplayed.has(key)) return; // уже показано
                alertsDisplayed.add(key);

                const t = fmtTime(tx.time);
                let msg = `${t} &nbsp; ${tx.btc.toFixed(2)} BTC`;

                if (tx.exchange) {
                    let dir = "";
                    if (tx.flow === "DEPOSIT") dir = "→ Exchange";
                    if (tx.flow === "WITHDRAWAL") dir = "← Exchange";
                    if (tx.flow === "INTERNAL") dir = "↔";

                    msg += ` ${dir} ${tx.exchange}`;
                }

                const alertsDiv = document.getElementById("alerts");
                if (alertsDiv) {
                    const div = document.createElement("div");
                    div.className = "alert";
                    div.innerHTML = msg;
                    alertsDiv.prepend(div);
                }
            }
        } catch (err) {
            console.error("Alert parsing error:", err);
        }
    };
}

load();
setInterval(load, 5000);
startAlerts();