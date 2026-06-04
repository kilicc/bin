"""core package — lazy imports.

`from core.X import ...` pattern'i kullan; bu __init__ boş çünkü bazı core
modülleri pydantic'i gerektiren markets.base'i çağırıyor (live path), oysa
backtest path'i bunlardan bağımsız çalışabilmeli.
"""
