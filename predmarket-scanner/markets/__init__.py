"""markets package — lazy imports.

Eager import yapmıyoruz, çünkü markets.base pydantic kullanıyor ve
backtest gibi alt modüllerin onu gerektirmemesi lazım. Kullanıcı kodu
`from markets.polymarket import PolymarketClient` der gibi direkt import etsin.
"""
