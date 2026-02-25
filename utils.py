def calculate_system_stats():
    """
    Рассчитывает общую статистику по системе (без user_id)
    """
    conn = get_db()
    c = conn.cursor()

    # Всего закрытых сделок
    c.execute("SELECT COUNT(*) as total FROM trade_signals WHERE status IN ('TP','SL')")
    total_trades = c.fetchone()["total"] or 0

    # TP / SL
    c.execute("SELECT COUNT(*) as wins FROM trade_signals WHERE status='TP'")
    wins = c.fetchone()["wins"] or 0

    c.execute("SELECT COUNT(*) as losses FROM trade_signals WHERE status='SL'")
    losses = c.fetchone()["losses"] or 0

    # Winrate %
    winrate = (wins / total_trades * 100) if total_trades > 0 else 0

    # Total PnL
    c.execute("SELECT SUM(result) as pnl FROM trade_signals WHERE status IN ('TP','SL')")
    total_pnl = c.fetchone()["pnl"] or 0

    # Текущий баланс
    c.execute("SELECT balance FROM demo_account WHERE id=1")
    balance = c.fetchone()["balance"] or 0

    conn.close()

    return {
        "total_trades": total_trades,
        "wins": wins,
        "losses": losses,
        "winrate": round(winrate, 2),
        "total_pnl": round(total_pnl, 2),
        "balance": round(balance, 2)
    }