def build_cluster():
    """
    Заглушка для теста, чтобы сервер точно запускался.
    Возвращает фиктивные адреса с BTC, без запросов к Blockstream.
    """
    fake_cluster = [
        {"address": "1FakeAddress11111111111111111111111", "btc": 123.45},
        {"address": "1FakeAddress22222222222222222222222", "btc": 67.89},
        {"address": "1FakeAddress33333333333333333333333", "btc": 10.0},
        {"address": "1FakeAddress44444444444444444444444", "btc": 500.5},
        {"address": "1FakeAddress55555555555555555555555", "btc": 250.25},
    ]
    return fake_cluster