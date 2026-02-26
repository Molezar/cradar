def calculate_system_stats():
    """
    Рассчитывает общую статистику по системе (без user_id)
    Оптимизированная версия — 1 SQL запрос вместо 5
    """

    conn = None
    try:
        conn = get_db()
        c = conn.cursor()

        c.execute("""
            SELECT
                COUNT(CASE WHEN status IN ('TP','SL') THEN 1 END) AS total_trades,
                COUNT(CASE WHEN status = 'TP' THEN 1 END) AS wins,
                COUNT(CASE WHEN status = 'SL' THEN 1 END) AS losses,
                COALESCE(SUM(CASE WHEN status IN ('TP','SL') THEN result END), 0) AS total_pnl
            FROM trade_signals
        """)

        row = c.fetchone()

        total_trades = row["total_trades"] or 0
        wins = row["wins"] or 0
        losses = row["losses"] or 0
        total_pnl = row["total_pnl"] or 0

        # баланс отдельно (это другая таблица)
        c.execute("SELECT balance FROM demo_account WHERE id=1")
        balance_row = c.fetchone()
        balance = balance_row["balance"] if balance_row else 0

    finally:
        if conn:
            conn.close()

    winrate = (wins / total_trades * 100) if total_trades > 0 else 0

    return {
        "total_trades": total_trades,
        "wins": wins,
        "losses": losses,
        "winrate": round(winrate, 2),
        "total_pnl": round(total_pnl, 2),
        "balance": round(balance, 2)
    }