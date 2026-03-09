let lastPrice = null;

const ALERT_WHALE_BTC = window.ALERT_WHALE_BTC || 1000;

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

        // ===== НОВЫЙ ЗАПРОС =====
        const vol = await fetch("/volumes?t=" + Date.now());
        const volj = await vol.json();
        // =========================

        let out = "";

        if (wj.whales && Array.isArray(wj.whales)) {
            for (const x of wj.whales) {
                const t = fmtTime(x.time);
                const btc = Number(x.btc || 0);
                const conf = Number(x.confidence || 0);
                const isHuge = btc >= ALERT_WHALE_BTC;
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
                        <span class="confidence">(${(conf*100).toFixed(0)}%)</span>
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

        // ===== ОТРИСОВКА VOLUMES =====
        let volHtml = "<div class='volumes'><div class='pred'>=== 1H VOLUMES ===</div>";
        volHtml += `<div>DEPOSIT: <span class='flow deposit'>${volj.deposit.toFixed(2)} BTC</span></div>`;
        volHtml += `<div>WITHDRAW: <span class='flow withdraw'>${volj.withdraw.toFixed(2)} BTC</span></div>`;
        let netColor = volj.net >= 0 ? "positive" : "negative";
        volHtml += `<div>NET (W-D): <span class='net ${netColor}'>${volj.net.toFixed(2)} BTC</span></div>`;
        volHtml += "</div>";
        document.getElementById("volumes").innerHTML = volHtml;
        // ==============================

        document.getElementById("list").innerHTML = out;

    } catch (e) {
        document.getElementById("info").innerText = "API error";
        console.error(e);
    }
}


// INIT
load();
setInterval(load, 5000);