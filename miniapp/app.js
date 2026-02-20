async function load() {
    try {
        const wr = await fetch("/whales?t=" + Date.now());
        const wj = await wr.json();

        const pr = await fetch("/prediction?t=" + Date.now());
        const pj = await pr.json();

        const prc = await fetch("/price?t=" + Date.now());
        const pcj = await prc.json();

        // =========================
        // PRICE
        // =========================

        if (pcj.price) {
            lastPrice = pcj.price;
            document.getElementById("info").innerText =
                `BTC $${Number(pcj.price).toFixed(0)}`;
        } else {
            document.getElementById("info").innerText = "BTC price…";
        }

        // =========================
        // FORECAST (сразу после цены)
        // =========================

        let forecastHTML = `<div class="pred-title">=== AI MARKET FORECAST ===</div>`;

        for (const horizon in pj) {
            const row = pj[horizon];
            if (!row) continue;

            const pct = Number(row.pct || 0);
            const target = Number(row.target || 0);

            const dir = pct > 0 ? "⬆" : pct < 0 ? "⬇" : "→";

            forecastHTML += `
                <div class="pred-row">
                    ${horizon / 60} min ${dir}
                    ${pct.toFixed(2)}%
                    → $${target.toFixed(0)}
                </div>
            `;
        }

        document.getElementById("forecast").innerHTML = forecastHTML;

        // =========================
        // TRANSACTIONS
        // =========================

        let txHTML = "";

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

                txHTML += `
                    <div class="${cls}">
                        ${t} &nbsp; ${btc.toFixed(2)} BTC ${dir}
                    </div>
                `;
            }
        }

        document.getElementById("list").innerHTML = txHTML;

    } catch (e) {
        document.getElementById("info").innerText = "API error";
        console.error(e);
    }
}