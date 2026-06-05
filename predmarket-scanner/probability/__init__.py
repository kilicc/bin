"""probability package — lazy imports.

`from probability.X import ...` pattern'i kullan; bu __init__ boş çünkü bazı
modüller pydantic gerektiren markets.base'i çağırıyor (live path), oysa
backtest path'i bunlardan bağımsız çalışabilmeli.
"""
