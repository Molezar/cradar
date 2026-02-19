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


function startAlerts() {
    const evtSource = new EventSource("/events");

    evtSource.onmessage = (e) => {
        try {
            const tx = JSON.parse(e.data);

            if (tx.btc >= ALERT_WHALE_BTC) {

                if (alertsDisplayed.has(tx.txid)) return;
                alertsDisplayed.add(tx.txid);

                const t = fmtTime(tx.time || Math.floor(Date.now()/1000));

                let dir = "";
                if (tx.flow === "DEPOSIT") dir = "→ Exchange";
                if (tx.flow === "WITHDRAWAL") dir = "← Exchange";
                if (tx.flow === "INTERNAL") dir = "↔";

                const msg = `${t} &nbsp; ${tx.btc.toFixed(2)} BTC ${dir} ${tx.exchange || ""}`;

                const alertsDiv = document.getElementById("alerts");
                const div = document.createElement("div");
                div.className = "alert";
                div.innerHTML = msg;
                alertsDiv.prepend(div);
            }

        } catch (err) {
            console.error("Alert parsing error:", err);
        }
    };
}

load();
setInterval(load, 5000);
startAlerts();